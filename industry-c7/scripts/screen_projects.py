"""Screen candidate projects for the expanded C7 benchmark.

For each candidate: clone the repo treeless, then measure what it would
actually contribute, rather than assuming it behaves like the four we
already mined.

Reported per candidate:
  eligible    log-bearing fixed Bugs in WoL v2 (the miner's own condition)
  linked      issues whose key appears in a commit subject (or Fixes: trailer)
  le_cap      ... and within MAX_FIX_COMMITS
  src_rate    of a sampled set of fix commits, the share that modify at least
              one non-test source file of the declared extensions
  projected   eligible * linked_rate * src_rate

A candidate is a KEEP if linkage and source rate are both in the band our
mined projects sit in. Everything else is reported with the reason, so the
paper can say why a project was excluded instead of leaving it unexplained.

Usage:
    python industry-c7/scripts/screen_projects.py --wave 1
    python industry-c7/scripts/screen_projects.py --only hive,hbase
    python industry-c7/scripts/screen_projects.py --report
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOS = ROOT / "data/c7-repos"
OUT = ROOT / "industry-c7/data/benchmark/screening.json"
MONGO = "mongodb://localhost:27017"

MAX_FIX_COMMITS = 10
SAMPLE_COMMITS = 120          # per candidate, for the source-gold estimate

JVM = (".java",)
TEST_PATH = re.compile(r"(^|/)(test|tests|testing|mysql-test|unittest|jtest|"
                       r"src/test|jstests)(/|$)"
                       r"|Test\.(java|scala|kt)$|(^|/)Test[A-Z]\w*\.(java|scala)$"
                       r"|_test\.(cc|cpp|py|go)$|Tests?\.cs$", re.I)

# name -> (keys, github repo, src extensions, link convention)
CANDIDATES: dict[str, dict] = {
    # ---- wave 1: largest Apache, "KEY-123" commit subject (Kafka's rule) ----
    "hive":      dict(keys=["HIVE"], repo="apache/hive", ext=JVM, wave=1),
    "hbase":     dict(keys=["HBASE"], repo="apache/hbase", ext=JVM, wave=1),
    "hadoop":    dict(keys=["HADOOP", "HDFS", "YARN", "MAPREDUCE"],
                      repo="apache/hadoop", ext=JVM, wave=1),
    "spark":     dict(keys=["SPARK"], repo="apache/spark",
                      ext=(".scala", ".java"), wave=1),
    "cassandra": dict(keys=["CASSANDRA"], repo="apache/cassandra", ext=JVM, wave=1),
    "flink":     dict(keys=["FLINK"], repo="apache/flink",
                      ext=(".java", ".scala"), wave=1),
    "ambari":    dict(keys=["AMBARI"], repo="apache/ambari",
                      ext=(".java", ".py"), wave=1),
    "impala":    dict(keys=["IMPALA"], repo="apache/impala",
                      ext=(".cc", ".h", ".java"), wave=1),
    "geode":     dict(keys=["GEODE"], repo="apache/geode", ext=JVM, wave=1),
    "ignite":    dict(keys=["IGNITE"], repo="apache/ignite", ext=JVM, wave=1),
    # ---- wave 2: mid-size Apache, same convention ----
    "camel":     dict(keys=["CAMEL"], repo="apache/camel", ext=JVM, wave=2),
    "derby":     dict(keys=["DERBY"], repo="apache/derby", ext=JVM, wave=2),
    "solr":      dict(keys=["SOLR"], repo="apache/solr", ext=JVM, wave=2),
    "drill":     dict(keys=["DRILL"], repo="apache/drill", ext=JVM, wave=2),
    "phoenix":   dict(keys=["PHOENIX"], repo="apache/phoenix", ext=JVM, wave=2),
    "beam":      dict(keys=["BEAM"], repo="apache/beam",
                      ext=(".java", ".go", ".py"), wave=2),
    "pdfbox":    dict(keys=["PDFBOX"], repo="apache/pdfbox", ext=JVM, wave=2),
    "pig":       dict(keys=["PIG"], repo="apache/pig", ext=JVM, wave=2),
    "groovy":    dict(keys=["GROOVY"], repo="apache/groovy",
                      ext=(".java", ".groovy"), wave=2),
    # ---- wave 3: non-Apache public repos, and more Qt modules ----
    "sakai":      dict(keys=["SAK"], repo="sakaiproject/sakai", ext=JVM, wave=3),
    "wildfly":    dict(keys=["WFLY"], repo="wildfly/wildfly", ext=JVM, wave=3),
    "infinispan": dict(keys=["ISPN"], repo="infinispan/infinispan", ext=JVM, wave=3),
    "keycloak":   dict(keys=["KEYCLOAK"], repo="keycloak/keycloak", ext=JVM, wave=3),
    # Qt: QTBUG spans ~40 repos and we currently mine only qtbase. These are
    # the biggest remaining modules; convention is the "Fixes:" trailer.
    "qtdeclarative": dict(keys=["QTBUG"], repo="qt/qtdeclarative",
                          ext=(".cpp", ".h", ".qml"), link="fixes_trailer", wave=3),
    "qttools":       dict(keys=["QTBUG"], repo="qt/qttools",
                          ext=(".cpp", ".h"), link="fixes_trailer", wave=3),
    "qtmultimedia":  dict(keys=["QTBUG"], repo="qt/qtmultimedia",
                          ext=(".cpp", ".h", ".mm"), link="fixes_trailer", wave=3),
    "qtwebengine":   dict(keys=["QTBUG"], repo="qt/qtwebengine",
                          ext=(".cpp", ".h"), link="fixes_trailer", wave=3),
    "qtquickcontrols2": dict(keys=["QTBUG"], repo="qt/qtquickcontrols2",
                             ext=(".cpp", ".h", ".qml"),
                             link="fixes_trailer", wave=3),
    "qtbase_extra":  dict(keys=["QTCREATORBUG"], repo="qt-creator/qt-creator",
                          ext=(".cpp", ".h"), link="fixes_trailer", wave=3),
}


def sh(*args: str, cwd: Path | None = None, timeout: int = 3600) -> str:
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(cwd) if cwd else None,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} {' '.join(args[1:4])}: {r.stderr[:400]}")
    return r.stdout


def git(gd: Path, *args: str, timeout: int = 3600) -> str:
    return sh("git", "--git-dir", str(gd), *args, timeout=timeout)


def clone(name: str, repo: str) -> Path:
    gd = REPOS / f"{name}-full.git"
    if gd.exists():
        return gd
    print(f"  cloning {repo} -> {gd.name} ...", flush=True)
    t0 = time.time()
    # --template= skips git's hook/description template copy, which fails
    # intermittently on Windows and killed 3 of 9 clones in wave 2.
    sh("git", "clone", "--bare", "--filter=blob:none", "--template=",
       f"https://github.com/{repo}.git", str(gd), timeout=5400)
    print(f"    done in {time.time() - t0:.0f}s", flush=True)
    return gd


def eligible_keys(prefixes: list[str]) -> set[str]:
    """The miner's own condition, so the screen and the mine agree."""
    from pymongo import MongoClient
    jira = MongoClient(MONGO)["WoL_v2_gh_so"]["JIRA"]
    out: set[str] = set()
    for p in prefixes:
        cur = jira.find(
            {"key": {"$regex": f"^{p}-"},
             "fields.issuetype.name": "Bug",
             "fields.resolution.name": {"$in": ["Fixed", "Done"]}},
            {"key": 1, "has_log_msg": 1, "log_msg_count": 1,
             "pred_uncertainty": 1})
        for d in cur:
            if not (d.get("has_log_msg") or (d.get("log_msg_count") or 0) > 0):
                continue
            if (d.get("pred_uncertainty") or 1) > 0.05:
                continue
            out.add(d["key"])
    return out


def key_to_commits(gd: Path, prefixes: list[str], link: str) -> dict[str, int]:
    """key -> number of non-merge, non-revert commits naming it."""
    fmt = "%H%x01%s%x01%b%x02"
    log = git(gd, "log", "--no-merges", f"--format={fmt}", "--all"
              if False else "HEAD")
    pat = re.compile(r"\b(" + "|".join(prefixes) + r")-(\d+)\b", re.I)
    trailer = re.compile(r"^\s*Fixes:\s*(.+)$", re.I | re.M)
    n = Counter()
    for rec in log.split("\x02"):
        if not rec.strip():
            continue
        parts = rec.split("\x01")
        if len(parts) < 2:
            continue
        subj = parts[1]
        body = parts[2] if len(parts) > 2 else ""
        if "revert" in subj.lower():
            continue
        hay = subj if link == "subject" else " ".join(trailer.findall(body))
        for m in pat.finditer(hay or ""):
            n[f"{m.group(1).upper()}-{m.group(2)}"] += 1
    return n


def src_rate(gd: Path, shas: list[str], ext: tuple[str, ...]) -> tuple[float, int]:
    """Share of sampled fix commits that modify a non-test source file."""
    if not shas:
        return 0.0, 0
    ok = 0
    for sha in shas:
        try:
            out = git(gd, "show", "--name-status", "--format=", "-m",
                      "--first-parent", sha, timeout=300)
        except Exception:
            continue
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) < 2 or not p[0].startswith("M"):
                continue
            f = p[-1]
            if f.lower().endswith(ext) and not TEST_PATH.search(f):
                ok += 1
                break
    return ok / len(shas), len(shas)


def screen(name: str, cfg: dict) -> dict:
    print(f"[{name}] {cfg['repo']}", flush=True)
    rec: dict = {"name": name, "repo": cfg["repo"], "keys": cfg["keys"],
                 "wave": cfg["wave"], "ext": list(cfg["ext"])}
    try:
        gd = clone(name, cfg["repo"])
    except Exception as e:  # noqa: BLE001
        rec.update(status="CLONE_FAILED", error=str(e)[:300])
        print(f"  CLONE FAILED: {str(e)[:200]}", flush=True)
        return rec
    rec["repo_mb"] = round(sum(f.stat().st_size for f in gd.rglob("*")
                               if f.is_file()) / 1e6)
    el = eligible_keys(cfg["keys"])
    link = cfg.get("link", "subject")
    counts = key_to_commits(gd, cfg["keys"], link)
    linked = {k: counts[k] for k in el if k in counts}
    le_cap = {k: v for k, v in linked.items() if v <= MAX_FIX_COMMITS}

    rng = random.Random(42)
    sample = rng.sample(sorted(le_cap), min(SAMPLE_COMMITS, len(le_cap))) \
        if le_cap else []
    shas = []
    for k in sample:
        try:
            s = git(gd, "log", "-1", "--format=%H", "--grep", f"\\b{k}\\b",
                    "-E", "-i", timeout=120).strip().splitlines()
            if s:
                shas.append(s[0])
        except Exception:
            pass
    rate, n_sampled = src_rate(gd, shas, tuple(cfg["ext"]))

    rec.update(
        eligible=len(el), linked=len(linked), le_cap=len(le_cap),
        link_rate=round(len(le_cap) / len(el), 3) if el else 0.0,
        over_cap=len(linked) - len(le_cap),
        src_rate=round(rate, 3), src_sampled=n_sampled,
        projected=int(len(le_cap) * rate),
        link=link,
    )
    # band observed on the four mined projects (Qt excluded: single repo)
    rec["status"] = ("KEEP" if rec["link_rate"] >= 0.35 and rec["src_rate"] >= 0.50
                     else "REVIEW")
    print(f"  eligible {rec['eligible']:5d}  linked<=cap {rec['le_cap']:5d} "
          f"({rec['link_rate']:.1%})  src {rec['src_rate']:.1%} "
          f"-> projected {rec['projected']:5d}  [{rec['status']}]", flush=True)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    done = {}
    if OUT.exists():
        done = {r["name"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}

    if a.report:
        rows = sorted(done.values(), key=lambda r: -r.get("projected", 0))
        print(f"{'project':16s} {'elig':>6s} {'linked':>7s} {'rate':>6s} "
              f"{'src':>6s} {'proj':>6s} {'MB':>6s}  status")
        tot = 0
        for r in rows:
            if r.get("status") == "CLONE_FAILED":
                print(f"{r['name']:16s} {'':>6s} {'':>7s} {'':>6s} {'':>6s} "
                      f"{'':>6s} {'':>6s}  CLONE_FAILED")
                continue
            tot += r.get("projected", 0)
            print(f"{r['name']:16s} {r['eligible']:6d} {r['le_cap']:7d} "
                  f"{r['link_rate']:5.1%} {r['src_rate']:5.1%} "
                  f"{r['projected']:6d} {r.get('repo_mb',0):6d}  {r['status']}")
        print(f"\nprojected NEW instances (KEEP only): "
              f"{sum(r.get('projected',0) for r in rows if r.get('status')=='KEEP')}")
        print(f"projected all screened: {tot}  (current benchmark: 6,437)")
        return 0

    todo = [n for n, c in CANDIDATES.items()
            if (a.only and n in a.only.split(","))
            or (not a.only and a.wave and c["wave"] == a.wave)]
    if not todo:
        print("nothing selected; use --wave N or --only a,b")
        return 2
    for n in todo:
        if n in done and done[n].get("status") != "CLONE_FAILED":
            print(f"[{n}] already screened, skipping")
            continue
        done[n] = screen(n, CANDIDATES[n])
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(list(done.values()), indent=1),
                       encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
