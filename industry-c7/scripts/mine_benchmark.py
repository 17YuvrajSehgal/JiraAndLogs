"""Challenge #7 benchmark miner: WoL issues x git history -> fault-localization gold.

For every WoL ticket_worthy issue of a configured project, find the commit(s)
that fixed it (Jira key in the commit subject on the default branch), take the
files that commit modified as ground truth, and the commit's PARENT as the
code snapshot (the code as it was while still broken). Pre-registered filters
and strata per icse-review-results/09-challenge7-plan.md:

  - drop commits whose subject contains "revert"
  - drop merge commits (ambiguous diffs)
  - core = issues with exactly one fixing commit; 2-3 commits kept but
    flagged (gold = union); >3 dropped (long-running epics, noisy linkage)
  - gold = modified (status M) non-test source files; issues whose fixes
    touch no such file are dropped ("no_source_gold": test-only, docs, build)
  - strata recorded per instance: has_stack_trace, gold_named_in_text (easy)

Yield is reported at every filter stage (datasheet.json). git file lists are
cached per project (cache-<project>.json) because the clones are treeless and
each `git show` lazy-fetches trees over the network -- the run is resumable.

Usage:
    python scripts/c7/mine_benchmark.py --project kafka
    python scripts/c7/mine_benchmark.py --project mariadb
    python scripts/c7/mine_benchmark.py --project all
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-mine")

ROOT = Path(__file__).resolve().parents[2]
WOL_GLOBAL = ROOT / "data/derived/global/2026-06-17-wol-real-v3-global/global-triage-examples.jsonl"
# shared, regenerable infra (bare git clones; see industry-c7/README.md)
REPOS = ROOT / "data/c7-repos"
OUT = ROOT / "industry-c7/data/benchmark"   # overridden by --out

PROJECTS = {
    # ALL projects use source "wolv2" (decision 2026-10-30): one population
    # definition, fully reproducible from the public WoL v2 + PJD artifacts.
    # The earlier "wol-slice" source (internal v3 triage labels) is retired;
    # its loader remains below for provenance.
    "kafka": {
        "key_prefix": "KAFKA",
        "git_dir": REPOS / "kafka-full.git",
        "src_ext": (".java", ".scala"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "mariadb": {
        "key_prefix": "MDEV",
        "git_dir": REPOS / "mariadb-full.git",
        "src_ext": (".c", ".cc", ".cpp", ".h", ".hpp", ".ic", ".inl", ".yy"),
        "source": "wolv2",
        "link_via": "subject",
    },
    # source "wolv2": queries from the WoL v2 mongo restore (log-bearing,
    # fixed Bug, pred_uncertainty <= 0.05 per the WoL paper's guidance)
    "mongodb": {
        "key_prefix": "SERVER",
        "git_dir": REPOS / "mongo-full.git",
        "src_ext": (".c", ".cpp", ".h", ".hpp", ".idl"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "qt": {
        "key_prefix": "QTBUG",
        "git_dir": REPOS / "qtbase-full.git",
        "src_ext": (".cpp", ".h", ".c", ".hpp", ".mm", ".qml"),
        "source": "wolv2",
        "link_via": "fixes_trailer",  # Qt convention: "Fixes: QTBUG-nnn" trailer
    },

# ---- expanded set (screened 2026-11-02; see paper/screening-results.json)
# 23 projects that passed linkage and non-test-source screening.
    "hive": {
        "key_prefix": "HIVE",
        "git_dir": REPOS / "hive-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "hadoop": {
        "key_prefix": ["HADOOP", "HDFS", "YARN", "MAPREDUCE"],
        "git_dir": REPOS / "hadoop-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "hbase": {
        "key_prefix": "HBASE",
        "git_dir": REPOS / "hbase-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "ambari": {
        "key_prefix": "AMBARI",
        "git_dir": REPOS / "ambari-full.git",
        "src_ext": (".java", ".py"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "cassandra": {
        "key_prefix": "CASSANDRA",
        "git_dir": REPOS / "cassandra-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject_or_body",
    },
    "sakai": {
        "key_prefix": "SAK",
        "git_dir": REPOS / "sakai-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "spark": {
        "key_prefix": "SPARK",
        "git_dir": REPOS / "spark-full.git",
        "src_ext": (".scala", ".java"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "flink": {
        "key_prefix": "FLINK",
        "git_dir": REPOS / "flink-full.git",
        "src_ext": (".java", ".scala"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "groovy": {
        "key_prefix": "GROOVY",
        "git_dir": REPOS / "groovy-full.git",
        "src_ext": (".java", ".groovy"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "camel": {
        "key_prefix": "CAMEL",
        "git_dir": REPOS / "camel-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "phoenix": {
        "key_prefix": "PHOENIX",
        "git_dir": REPOS / "phoenix-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "impala": {
        "key_prefix": "IMPALA",
        "git_dir": REPOS / "impala-full.git",
        "src_ext": (".cc", ".h", ".java"),
        "source": "wolv2",
        "link_via": "subject",
    },
    "infinispan": {
        "key_prefix": "ISPN",
        "git_dir": REPOS / "infinispan-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "ignite": {
        "key_prefix": "IGNITE",
        "git_dir": REPOS / "ignite-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "wildfly": {
        "key_prefix": "WFLY",
        "git_dir": REPOS / "wildfly-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "pdfbox": {
        "key_prefix": "PDFBOX",
        "git_dir": REPOS / "pdfbox-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "derby": {
        "key_prefix": "DERBY",
        "git_dir": REPOS / "derby-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "solr": {
        "key_prefix": "SOLR",
        "git_dir": REPOS / "solr-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "pig": {
        "key_prefix": "PIG",
        "git_dir": REPOS / "pig-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "geode": {
        "key_prefix": "GEODE",
        "git_dir": REPOS / "geode-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "drill": {
        "key_prefix": "DRILL",
        "git_dir": REPOS / "drill-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "keycloak": {
        "key_prefix": "KEYCLOAK",
        "git_dir": REPOS / "keycloak-full.git",
        "src_ext": (".java",),
        "source": "wolv2",
        "link_via": "subject",
    },
    "beam": {
        "key_prefix": "BEAM",
        "git_dir": REPOS / "beam-full.git",
        "src_ext": (".java", ".go", ".py"),
        "source": "wolv2",
        "link_via": "subject",
    },
}
WOLV2_MONGO = "mongodb://localhost:27017"
MAX_QUERY_CHARS = 0        # 0 = no truncation (was 20_000; it clipped 0.3% of
                           # instances, so the cap bought nothing and invited
                           # the question). TRUNC_REPORT_AT only *reports*.
TRUNC_REPORT_AT = 20_000   # recorded in the datasheet so the old cap's cost
                           # stays visible without being applied
UNCERTAINTY_MAX = 0.05  # WoL paper: treat pred_uncertainty > 0.05 with caution

# Gold must be a file a localizer could sensibly be asked to rank. The first
# version of this pattern only knew Java and Scala conventions, so C++, Python
# and Go test files, and whole alternative test source sets, survived into the
# gold set: 1,717 such files over 1,166 instances, and 200 instances whose
# ENTIRE ground truth was test code. MongoDB alone contributed 1,155, mostly
# "*_test.cpp", which matters because it is one of the four study projects.
#
# Deliberately NOT excluded: shipped test-support libraries that are real
# product APIs with their own defects, such as Kafka's streams/test-utils
# (TopologyTestDriver), Flink's flink-test-utils, Qt's src/testlib (QTestLib)
# and MariaDB's client/mysqltest.cc. Those are published artifacts, so asking
# a localizer to rank them is fair.
# NOTE: case-SENSITIVE on purpose. The previous pattern used re.I, so
# "Test\.(java|scala)$" also matched Latest.java, Protest.java, Contest.java
# and Greatest.java, quietly dropping ordinary source files from gold. The
# camelCase suffix convention is capital-T by definition, so matching it
# exactly is both correct and more precise.
TEST_PATH = re.compile(
    # test source sets and directories (lowercase by convention)
    r"(^|/)(test|tests|Test|Tests|testing|mysql-test|unittest|jtest"
    r"|itest|itests|dbtest|dbtests|testsuite|testutil|testutils)(/|$)"
    # gradle/maven alternative source sets: src/distributedTest/java, ...
    r"|(^|/)(?:unit|integration|distributed|acceptance|functional|system"
    r"|upgrade|performance|benchmark)Test(/|$)"
    # camelCase file suffix: FooTest.java, QueryTest.cpp
    r"|Test\.(java|scala|cpp|cc|py|go)$"
    r"|(^|/)Test[A-Z]\w*\.(java|scala)$"
    # separator conventions: query_planner_test.cpp, admission-controller-test.cc
    r"|[_-][Tt]est\.(cpp|cc|c|py|go|js|ts)$"
    r"|(^|/)test_\w+\.(py|cpp|cc|go)$")
# stack-trace shapes: JVM frames, C/C++ file:line refs, gdb/mysqld frames, signal dumps
TRACE_PATTERNS = (
    re.compile(r"^\s+at [\w.$<>]+\(", re.M),
    re.compile(r"\.(?:c|cc|cpp|h|hpp|ic)\s*:\s*\d+"),
    re.compile(r"^#\d+\s+0x[0-9a-f]+", re.M),
    re.compile(r"mysqld got signal|stack_bottom", re.I),
)
# For via="subject_or_body": only body text AFTER a fix cue counts as a link.
# Validated on Cassandra, whose convention is "patch by X; reviewed by Y for
# CASSANDRA-123". A bare mention is rejected because those are usually
# cross-references ("extends the feature from CASSANDRA-18112").
BODY_FIX_CUE = re.compile(
    r"(?:\bpatch\s+by\b[^\n]*?\bfor\b"
    r"|^[ \t]*(?:fixes|fix|closes|close|resolves|resolve)\b[:\s]+)"
    r"\s*((?:[A-Za-z]+-\d+[\s,]*(?:and\s+)?)+)", re.I | re.M)

# A fix modifying more than this many non-test source files is a bulk edit
# (license headers, log4j->slf4j, interface annotations), not a targeted fix.
# Acc@K counts a hit if ANY gold file is retrieved, so such instances are
# trivially solvable: HIVE-17952 touches 3,493 of 4,819 files, where random
# top-5 guessing hits 99.8% of the time. Keeping them inflates every system
# equally and measures nothing. Set to 0 to disable.
# Linked commits more than this far after the earliest are not part of the
# same fix. Measured span across multi-commit instances: median 2 days, p90
# 105, max 5,919 (16 years). A commit years later merely mentions the key.
MAX_COMMIT_SPAN_DAYS = 180

GOLD_MAX_FILES = 50

GIT_SHOW_BATCH = 100
GIT_WORKERS = 16           # ls-tree is spawn-bound, not CPU-bound, so this
                           # sits above the core count on purpose
MAX_FIX_COMMITS = 10       # was 3; cost 1.2% here but 8.3% on PDFBOX, and
                           # a multi-commit fix is a harder instance, not a
                           # worse one. Full distribution is recorded.


def run_git(git_dir: Path, *args: str, tries: int = 3) -> str:
    """git, retried. Under concurrency on Windows a spawn fails now and then
    (process pressure, virus scanner holding a pack file). A caller that
    swallows that failure writes a plausible wrong number instead of
    crashing: the first threaded universe pass returned 0 for 99 of PDFBOX's
    713 snapshots, which read as 'this repo has no source files'. Retry, and
    let a persistent failure raise so it is counted rather than guessed."""
    for attempt in range(tries):
        r = subprocess.run(["git", "--git-dir", str(git_dir), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode == 0:
            return r.stdout
        if attempt + 1 < tries:
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"git {' '.join(args[:3])}...: {r.stderr[:300]}")


def load_wol_issues(key_prefix: str) -> dict[str, dict]:
    """issue_key -> canonical query window (longest evidence text wins)."""
    issues: dict[str, dict] = {}
    n_windows = Counter()
    for line in WOL_GLOBAL.open(encoding="utf-8"):
        d = json.loads(line)
        key = d.get("wol_issue_key") or ""
        if d.get("triage_label") != "ticket_worthy" or not key.startswith(key_prefix + "-"):
            continue
        n_windows[key] += 1
        ev = d.get("triage_evidence_text") or ""
        cur = issues.get(key)
        if cur is None or len(ev) > len(cur["evidence_text"]):
            issues[key] = {
                "window_id": d["window_id"],
                "evidence_text": ev,
                "split": d.get("split"),
                "service_name": d.get("service_name"),
                "triage_severity": d.get("triage_severity"),
                "triage_components": d.get("triage_components"),
                "wol_source_id": d.get("wol_source_id"),
            }
    for key, rec in issues.items():
        rec["n_windows"] = n_windows[key]
    return issues


def link_commits(git_dir: Path, key_prefix: str | list[str],
                 via: str = "subject") -> tuple[dict[str, list[dict]], Counter]:
    """key -> [{sha, ts, subject, parents}] from the default branch, with
    revert/merge commits dropped (counted in the returned Counter).

    via="subject"         scan commit subjects (the Apache convention)
    via="fixes_trailer"   scan the Fixes: trailer (the Qt convention)
    via="subject_or_body" subject, plus body text that follows a FIX cue
                          ("patch by X; reviewed by Y for KEY-1", or
                          Fixes/Closes/Resolves). A bare body mention is
                          NOT matched: in Cassandra's history those are
                          cross-references to other issues, and matching
                          them would manufacture false ground truth.

    key_prefix may be a list: one repo can serve several trackers (the
    Hadoop repo carries HADOOP, HDFS, YARN and MAPREDUCE).
    """
    prefixes = [key_prefix] if isinstance(key_prefix, str) else list(key_prefix)
    key_re = re.compile(r"\b((?:" + "|".join(prefixes) + r")-\d+)\b")
    dropped = Counter()
    linked: dict[str, list[dict]] = defaultdict(list)
    # %x02 separates records so a multi-line body cannot break parsing
    out = run_git(git_dir, "log",
                  "--format=%H%x01%ct%x01%P%x01%s%x01"
                  "%(trailers:key=Fixes,valueonly,separator=;)%x01%b%x02")
    for rec in out.split("\x02"):
        if not rec.strip():
            continue
        try:
            sha, ts, parents, subj, trailers, body = rec.strip("\n").split("\x01", 5)
        except ValueError:
            continue
        if via == "subject":
            keysrc = subj
        elif via == "fixes_trailer":
            keysrc = trailers
        else:  # subject_or_body
            keysrc = subj + " " + " ".join(BODY_FIX_CUE.findall(body))
        keys = set(key_re.findall(keysrc))
        if not keys:
            continue
        if "revert" in subj.lower():
            dropped["revert_commits"] += 1
            continue
        if len(parents.split()) > 1:
            dropped["merge_commits"] += 1
            continue
        for k in keys:
            linked[k].append({"sha": sha, "ts": int(ts),
                              "parent": parents.split()[0] if parents.strip() else "",
                              "subject": subj})
    return linked, dropped


def load_wolv2_issues(cfg: dict) -> dict[str, dict]:
    """issue_key -> query record from the WoL v2 mongo restore: log-bearing,
    fixed Bug, low-uncertainty. query_text = summary + description (the
    description carries the reporter-pasted logs)."""
    from pymongo import MongoClient
    jira = MongoClient(WOLV2_MONGO)["WoL_v2_gh_so"]["JIRA"]
    issues: dict[str, dict] = {}
    kp = cfg["key_prefix"]
    prefixes = [kp] if isinstance(kp, str) else list(kp)
    cur = jira.find(
        {"key": {"$regex": "^(?:" + "|".join(prefixes) + ")-"},
         "fields.issuetype.name": "Bug",
         "fields.resolution.name": {"$in": ["Fixed", "Done"]}},
        {"key": 1, "has_log_msg": 1, "log_msg_count": 1, "pred_uncertainty": 1,
         "fields.summary": 1, "fields.description": 1, "fields.created": 1,
         "fields.resolutiondate": 1, "fields.components.name": 1,
         "fields.priority.name": 1})
    for d in cur:
        if not (d.get("has_log_msg") or (d.get("log_msg_count") or 0) > 0):
            continue
        if (d.get("pred_uncertainty") or 1) > UNCERTAINTY_MAX:
            continue
        f = d.get("fields") or {}
        text = f"{f.get('summary') or ''}\n\n{f.get('description') or ''}"
        issues[d["key"]] = {
            "window_id": f"pjd-{d['key']}",
            "evidence_text": (text[:MAX_QUERY_CHARS] if MAX_QUERY_CHARS
                              else text),
            "split": "test",
            "service_name": None,
            "triage_severity": (f.get("priority") or {}).get("name"),
            "triage_components": [c.get("name") for c in (f.get("components") or [])],
            "wol_source_id": None,
            "created": f.get("created"),
            "resolutiondate": f.get("resolutiondate"),
            "n_windows": 1,
        }
    return issues


def topo_first(git_dir: Path, shas: list[str]) -> str | None:
    """The fix commit no other fix commit precedes.

    The snapshot is the parent of the "first" fix commit, and first was taken
    to mean earliest commit timestamp. Timestamps disagree with apply order
    after a rebase, a cherry-pick or a cross-branch merge, and when they do
    the snapshot already contains part of the fix: measured, 539 commits over
    380 instances were ancestors of their own snapshot. That is leakage, and
    it makes those instances easier than they look.

    Returns the sha that has no other given sha as an ancestor. If every
    candidate is preceded by another, the commits sit on divergent branches
    and no single snapshot predates them all, so return None and let the
    caller drop the instance.
    """
    if len(shas) == 1:
        return shas[0]
    for c in shas:
        if not any(o != c and subprocess.run(
                ["git", "--git-dir", str(git_dir), "merge-base",
                 "--is-ancestor", o, c],
                capture_output=True).returncode == 0 for o in shas):
            return c
    return None


def topo_first_many(git_dir: Path, groups: list[list[str]]) -> list:
    """topo_first for many instances at once; one thread per instance."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=GIT_WORKERS) as ex:
        return list(ex.map(lambda g: topo_first(git_dir, g), groups))


def scan_snapshots(git_dir: Path, tasks: list[tuple[str, frozenset]],
                   src_ext: tuple[str, ...]) -> dict:
    """One `ls-tree` per snapshot, answering both questions we ask of it.

    Two things are read off a snapshot, and they used to cost two identical
    `ls-tree -r` calls on the same sha:

      universe_size   non-test source files in the snapshot: the pool a
                      localizer must rank, and the denominator for 'how hard
                      is this instance'. Without it, gold-set size cannot be
                      read: 46 gold files is most of early Kafka (213 source
                      files) but a needle in modern MongoDB (11,095).
      gold presence   gold means 'files to find in THIS snapshot', so a gold
                      file absent from it is an impossible target: every
                      system misses it, which depresses all scores equally
                      and measures nothing. Arises when an issue links to
                      commits spread over time and the later ones touch
                      files that did not exist yet.

    The second call also ran serially inside the row loop, which made it the
    bottleneck of a mine. Reading the tree once and returning both answers
    halves the git calls and leaves none of them serial.

    Returns {(sha, gold): (universe_count, absent_gold)}. Only the count and
    the few absent paths are kept, never the tree, so memory stays flat on
    repos with 50k+ files. Each call is ~35 ms, almost all of it process
    spawn, and the calls are independent and local (blob:none clones keep
    trees).
    """
    from concurrent.futures import ThreadPoolExecutor
    failed: list[str] = []  # list.append is atomic; a Counter here is not

    def one(task: tuple[str, frozenset]) -> tuple[int, frozenset]:
        sha, gold = task
        if not sha:
            return 0, frozenset()
        try:
            paths = run_git(git_dir, "ls-tree", "-r", "--name-only",
                            sha).splitlines()
        except Exception:  # noqa: BLE001
            failed.append(sha)
            return 0, frozenset()  # unreadable: keep gold rather than guess
        if not paths:
            failed.append(sha)
            return 0, frozenset()
        n = sum(1 for p in paths
                if p.lower().endswith(src_ext) and not TEST_PATH.search(p))
        return n, frozenset(gold - set(paths))

    uniq = list(dict.fromkeys(tasks))
    with ThreadPoolExecutor(max_workers=GIT_WORKERS) as ex:
        out = dict(zip(uniq, ex.map(one, uniq)))
    if failed:
        log.warning("snapshot scan failed for %d of %d snapshots after "
                    "retries, e.g. %s", len(failed), len(uniq), failed[0])
    return out, len(failed)


def fetch_file_lists(git_dir: Path, shas: list[str], cache_path: Path) -> dict[str, list]:
    """sha -> [[status, path], ...] via batched `git show`, cached on disk."""
    cache: dict[str, list] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    todo = [s for s in shas if s not in cache]
    log.info("file lists: %d cached, %d to fetch", len(shas) - len(todo), len(todo))
    t0 = time.time()
    for i in range(0, len(todo), GIT_SHOW_BATCH):
        batch = todo[i:i + GIT_SHOW_BATCH]
        out = run_git(git_dir, "show", "--name-status", "--no-renames",
                      "--format=%x02%H", *batch)
        for section in out.split("\x02"):
            if not section.strip():
                continue
            lines = section.strip().splitlines()
            sha = lines[0].strip()
            files = []
            for fl in lines[1:]:
                if "\t" in fl:
                    status, path = fl.split("\t", 1)
                    files.append([status.strip(), path.strip()])
            cache[sha] = files
        # rewriting a multi-MB cache every batch dominated runtime at 60k+ shas
        if (i // GIT_SHOW_BATCH) % 20 == 0 or i + GIT_SHOW_BATCH >= len(todo):
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            log.info("  %d/%d (%.0fs)", min(i + GIT_SHOW_BATCH, len(todo)),
                     len(todo), time.time() - t0)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def mine_project(name: str) -> dict:
    cfg = PROJECTS[name]
    OUT.mkdir(parents=True, exist_ok=True)
    funnel = Counter()

    if cfg.get("source") == "wolv2":
        issues = load_wolv2_issues(cfg)
        funnel["wolv2_log_fixed_lowuncert_issues"] = len(issues)
    else:
        issues = load_wol_issues(cfg["key_prefix"])
        funnel["wol_ticket_worthy_issues"] = len(issues)
    linked, dropped_commits = link_commits(cfg["git_dir"], cfg["key_prefix"],
                                           cfg.get("link_via", "subject"))

    candidates = {}
    for key, rec in issues.items():
        commits = sorted(linked.get(key, []), key=lambda c: c["ts"])
        if not commits:
            funnel["no_fix_commit"] += 1
            continue
        if len(commits) > MAX_FIX_COMMITS:
            funnel[f"gt{MAX_FIX_COMMITS}_fix_commits"] += 1
            continue
        if not commits[0]["parent"]:
            funnel["root_commit_fix"] += 1
            continue
        # drop commits far after the first: same-fix commits land together
        span = MAX_COMMIT_SPAN_DAYS * 86400
        kept = [c for c in commits if c["ts"] - commits[0]["ts"] <= span]
        if len(kept) != len(commits):
            funnel["commits_dropped_span"] += len(commits) - len(kept)
        candidates[key] = kept
    funnel[f"linked_1_to_{MAX_FIX_COMMITS}_commits"] = len(candidates)

    all_shas = [c["sha"] for commits in candidates.values() for c in commits]
    file_cache = fetch_file_lists(cfg["git_dir"], all_shas, REPOS / f"cache-{name}.json")
    # Gold comes from the cached file lists, so it costs no git. Computing it
    # first lets the snapshot scan below answer both of its questions in one
    # `ls-tree` per row instead of two.
    prepared = []
    for key, commits in sorted(candidates.items()):
        gold, all_changed = set(), set()
        for c in commits:
            for status, path in file_cache.get(c["sha"], []):
                all_changed.add(path)
                if (status == "M" and path.endswith(cfg["src_ext"])
                        and not TEST_PATH.search(path)):
                    gold.add(path)
        prepared.append((key, commits, frozenset(gold), len(all_changed)))

    # The snapshot is the parent of commits[0], so commits[0] must be the one
    # no other fix commit precedes. Sorting by timestamp does not guarantee
    # that; see topo_first. Only multi-commit instances need the git calls.
    multi = [i for i, p in enumerate(prepared) if len(p[1]) > 1]
    if multi:
        firsts = topo_first_many(
            cfg["git_dir"], [[c["sha"] for c in prepared[i][1]] for i in multi])
        for i, sha in zip(multi, firsts):
            key, commits, gold, n_ch = prepared[i]
            if sha is None:
                # divergent branches: no snapshot predates every fix commit
                prepared[i] = None
                continue
            if commits[0]["sha"] != sha:
                head = next(c for c in commits if c["sha"] == sha)
                prepared[i] = (key, [head] + [c for c in commits if c is not head],
                               gold, n_ch)
                funnel["snapshot_reordered_topologically"] += 1
        dropped = sum(1 for i in multi if prepared[i] is None)
        if dropped:
            funnel["fix_commits_on_divergent_branches"] = dropped
        prepared = [p for p in prepared if p is not None]

    scans, n_scan_failed = scan_snapshots(
        cfg["git_dir"],
        [(c[0]["parent"], g) for _, c, g, _ in prepared],
        cfg["src_ext"])
    # must stay 0: a failed scan writes n_universe=0, which reads as a repo
    # with no source files and quietly corrupts the hardness strata
    funnel["snapshot_scan_failed"] = n_scan_failed

    rows, strata = [], Counter()
    for key, commits, gold_all, n_all_changed in prepared:
        first = commits[0]
        n_universe, absent = scans.get((first["parent"], gold_all),
                                       (0, frozenset()))
        if absent:
            funnel["gold_files_absent_from_snapshot"] += len(absent)
        gold = set(gold_all) - absent
        if not gold:
            funnel["no_source_gold"] += 1
            continue
        if GOLD_MAX_FILES and len(gold) > GOLD_MAX_FILES:
            # bulk edit, not a targeted fix: see GOLD_MAX_FILES
            funnel[f"gold_over_{GOLD_MAX_FILES}_files"] += 1
            continue

        rec = issues[key]
        ev = rec["evidence_text"]
        has_trace = any(p.search(ev) for p in TRACE_PATTERNS)
        named = any(Path(f).stem in ev for f in gold)
        rows.append({
            "project": name,
            "issue_key": key,
            "window_id": rec["window_id"],
            "n_windows": rec["n_windows"],
            "split": rec["split"],
            "query_text": ev,
            "service_name": rec["service_name"],
            "triage_severity": rec["triage_severity"],
            "triage_components": rec["triage_components"],
            "created": rec.get("created"),
            "resolutiondate": rec.get("resolutiondate"),
            "n_fix_commits": len(commits),
            "fix_sha": first["sha"],
            "fix_shas": [c["sha"] for c in commits],
            # min, not first["ts"]: commits[0] is now the topologically first
            # commit, which need not be the earliest by timestamp. fix_time
            # drives the chronological dev/eval split and is a firewall
            # fallback, so keep the earliest, which is the conservative end.
            "fix_time": min(c["ts"] for c in commits),
            "fix_subject": first["subject"],
            "snapshot_sha": first["parent"],
            "gold_files": sorted(gold),
            "gold_modules": sorted({f.split("/")[0] for f in gold}),
            "n_all_changed_files": n_all_changed,
            "n_universe": n_universe,
            "has_stack_trace": has_trace,
            "gold_named_in_text": named,
        })
        strata["single_commit" if len(commits) == 1 else "multi_commit"] += 1
        strata["trace_present" if has_trace else "trace_absent"] += 1
        strata["easy_gold_named" if named else "hard_gold_not_named"] += 1
    funnel["final_instances"] = len(rows)

    out_path = OUT / f"{name}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    gold_sizes = sorted(len(r["gold_files"]) for r in rows)

    def dist(vals: list[int]) -> dict:
        """Distribution we report instead of silently capping."""
        if not vals:
            return {}
        v = sorted(vals)
        return {"n": len(v), "min": v[0], "median": v[len(v) // 2],
                "p95": v[int(0.95 * len(v))], "max": v[-1],
                "mean": round(sum(v) / len(v), 2)}

    q_chars = [len(r["query_text"]) for r in rows]
    n_commits = [r["n_fix_commits"] for r in rows]
    n_files = [r["n_all_changed_files"] for r in rows]
    summary = {
        "project": name,
        "git_dir": str(cfg["git_dir"]),
        "git_head": run_git(cfg["git_dir"], "rev-parse", "HEAD").strip(),
        "branch_scanned": "default branch only (first-parent history not enforced)",
        "funnel": dict(funnel),
        "dropped_commit_level": dict(dropped_commits),
        "strata": dict(strata),
        "gold_files_median": gold_sizes[len(gold_sizes) // 2] if gold_sizes else 0,
        # recorded, not capped: the two limits a reviewer would ask about
        "query_chars": dict(dist(q_chars),
                            over_20k=sum(1 for x in q_chars if x > TRUNC_REPORT_AT),
                            truncated_at=MAX_QUERY_CHARS or None),
        "fix_commits_per_issue": dict(dist(n_commits), cap=MAX_FIX_COMMITS,
                                      hist={str(k): sum(1 for x in n_commits if x == k)
                                            for k in range(1, MAX_FIX_COMMITS + 1)}),
        "files_changed_by_fix": dict(dist(n_files),
                                     over_3=sum(1 for x in n_files if x > 3),
                                     over_10=sum(1 for x in n_files if x > 10),
                                     over_50=sum(1 for x in n_files if x > 50)),
        "gold_files_mean": round(sum(gold_sizes) / len(gold_sizes), 2) if gold_sizes else 0,
        "output": str(out_path),
    }
    log.info("%s: %d instances -> %s", name, len(rows), out_path)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, choices=[*PROJECTS, "all"])
    ap.add_argument("--out", default="", help="output dir under industry-c7/data/ "
                    "(default: benchmark). Use benchmark-v2 to build the expanded "
                    "set without touching the frozen one.")
    args = ap.parse_args()
    if args.out:
        global OUT
        OUT = ROOT / "industry-c7/data" / args.out

    names = list(PROJECTS) if args.project == "all" else [args.project]
    datasheet_path = OUT / "datasheet.json"
    datasheet = (json.loads(datasheet_path.read_text(encoding="utf-8"))
                 if datasheet_path.exists() else {})
    for name in names:
        datasheet[name] = mine_project(name)
    OUT.mkdir(parents=True, exist_ok=True)
    datasheet_path.write_text(json.dumps(datasheet, indent=2), encoding="utf-8")

    for name in names:
        s = datasheet[name]
        print(f"\n=== {name} ===")
        for k, v in s["funnel"].items():
            print(f"  {k:<28}{v}")
        print(f"  strata: {s['strata']}")
        print(f"  gold files/instance: median {s['gold_files_median']}, "
              f"mean {s['gold_files_mean']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
