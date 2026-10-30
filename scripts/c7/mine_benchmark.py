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
REPOS = ROOT / "data/c7-repos"
OUT = ROOT / "data/c7-benchmark"

PROJECTS = {
    "kafka": {
        "key_prefix": "KAFKA",
        "git_dir": REPOS / "kafka.git",
        "src_ext": (".java", ".scala"),
    },
    "mariadb": {
        "key_prefix": "MDEV",
        "git_dir": REPOS / "mariadb-server.git",
        "src_ext": (".c", ".cc", ".cpp", ".h", ".hpp", ".ic", ".inl", ".yy"),
    },
}

TEST_PATH = re.compile(r"(^|/)(test|tests|testing|mysql-test|unittest|jtest)(/|$)"
                       r"|Test\.(java|scala)$|(^|/)Test[A-Z]\w*\.(java|scala)$", re.I)
# stack-trace shapes: JVM frames, C/C++ file:line refs, gdb/mysqld frames, signal dumps
TRACE_PATTERNS = (
    re.compile(r"^\s+at [\w.$<>]+\(", re.M),
    re.compile(r"\.(?:c|cc|cpp|h|hpp|ic)\s*:\s*\d+"),
    re.compile(r"^#\d+\s+0x[0-9a-f]+", re.M),
    re.compile(r"mysqld got signal|stack_bottom", re.I),
)
GIT_SHOW_BATCH = 100
MAX_FIX_COMMITS = 3


def run_git(git_dir: Path, *args: str) -> str:
    r = subprocess.run(["git", "--git-dir", str(git_dir), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}...: {r.stderr[:300]}")
    return r.stdout


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


def link_commits(git_dir: Path, key_prefix: str) -> tuple[dict[str, list[dict]], Counter]:
    """key -> [{sha, ts, subject, parents}] from the default branch, with
    revert/merge commits dropped (counted in the returned Counter)."""
    key_re = re.compile(rf"\b({key_prefix}-\d+)\b")
    dropped = Counter()
    linked: dict[str, list[dict]] = defaultdict(list)
    out = run_git(git_dir, "log", "--format=%H%x01%ct%x01%P%x01%s")
    for line in out.splitlines():
        try:
            sha, ts, parents, subj = line.split("\x01", 3)
        except ValueError:
            continue
        keys = set(key_re.findall(subj))
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
                              "parent": parents.strip(), "subject": subj})
    return linked, dropped


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
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        log.info("  %d/%d (%.0fs)", min(i + GIT_SHOW_BATCH, len(todo)), len(todo),
                 time.time() - t0)
    return cache


def mine_project(name: str) -> dict:
    cfg = PROJECTS[name]
    OUT.mkdir(parents=True, exist_ok=True)
    funnel = Counter()

    issues = load_wol_issues(cfg["key_prefix"])
    funnel["wol_ticket_worthy_issues"] = len(issues)
    linked, dropped_commits = link_commits(cfg["git_dir"], cfg["key_prefix"])

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
        candidates[key] = commits
    funnel["linked_1_to_3_commits"] = len(candidates)

    all_shas = [c["sha"] for commits in candidates.values() for c in commits]
    file_cache = fetch_file_lists(cfg["git_dir"], all_shas, REPOS / f"cache-{name}.json")

    rows, strata = [], Counter()
    for key, commits in sorted(candidates.items()):
        gold, all_changed = set(), set()
        for c in commits:
            for status, path in file_cache.get(c["sha"], []):
                all_changed.add(path)
                if (status == "M" and path.endswith(cfg["src_ext"])
                        and not TEST_PATH.search(path)):
                    gold.add(path)
        if not gold:
            funnel["no_source_gold"] += 1
            continue

        rec = issues[key]
        ev = rec["evidence_text"]
        has_trace = any(p.search(ev) for p in TRACE_PATTERNS)
        named = any(Path(f).stem in ev for f in gold)
        first = commits[0]
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
            "n_fix_commits": len(commits),
            "fix_sha": first["sha"],
            "fix_shas": [c["sha"] for c in commits],
            "fix_time": first["ts"],
            "fix_subject": first["subject"],
            "snapshot_sha": first["parent"],
            "gold_files": sorted(gold),
            "gold_modules": sorted({f.split("/")[0] for f in gold}),
            "n_all_changed_files": len(all_changed),
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
    summary = {
        "project": name,
        "git_dir": str(cfg["git_dir"]),
        "git_head": run_git(cfg["git_dir"], "rev-parse", "HEAD").strip(),
        "branch_scanned": "default branch only (first-parent history not enforced)",
        "funnel": dict(funnel),
        "dropped_commit_level": dict(dropped_commits),
        "strata": dict(strata),
        "gold_files_median": gold_sizes[len(gold_sizes) // 2] if gold_sizes else 0,
        "gold_files_mean": round(sum(gold_sizes) / len(gold_sizes), 2) if gold_sizes else 0,
        "output": str(out_path),
    }
    log.info("%s: %d instances -> %s", name, len(rows), out_path)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, choices=[*PROJECTS, "all"])
    args = ap.parse_args()

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
