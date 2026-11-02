"""Integrity check: every gold file must exist in its own snapshot.

Gold is defined as files the fix commit MODIFIED (status M), so each gold
file must already be present in the snapshot (the fix commit's parent). A
gold file missing from its snapshot means the gold came from the wrong
commit, and the instance is unusable.

This caught a real corruption: concurrent miner processes sharing
data/c7-repos/cache-<project>.json produced file lists keyed to the wrong
SHAs, so instances were given gold files that postdate their snapshot by
years. Run this after any mine, and never run two miners on one project.

Usage:
    python industry-c7/scripts/check_benchmark_integrity.py --out benchmark-v2
    python industry-c7/scripts/check_benchmark_integrity.py --out benchmark-v2 --fix
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOS = ROOT / "data/c7-repos"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_benchmark import PROJECTS  # noqa: E402  the authoritative git_dir map


def snapshot_files(gd: Path, sha: str) -> set[str]:
    r = subprocess.run(["git", "--git-dir", str(gd), "ls-tree", "-r",
                        "--name-only", sha], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    return set(r.stdout.splitlines()) if r.returncode == 0 else set()


def check_project(path: Path) -> tuple[str, int, int, list]:
    name = path.stem
    # use the miner's own map: mongodb -> mongo-full.git, qt -> qtbase-full.git
    gd = PROJECTS[name]["git_dir"] if name in PROJECTS else REPOS / f"{name}-full.git"
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    shas = list({r["snapshot_sha"] for r in rows if r.get("snapshot_sha")})
    with ThreadPoolExecutor(max_workers=12) as ex:
        trees = dict(zip(shas, ex.map(lambda s: snapshot_files(gd, s), shas)))
    bad = []
    for r in rows:
        tree = trees.get(r["snapshot_sha"], set())
        if not tree:
            bad.append((r["issue_key"], "snapshot unreadable"))
            continue
        missing = [f for f in r["gold_files"] if f not in tree]
        if missing:
            bad.append((r["issue_key"],
                        f"{len(missing)}/{len(r['gold_files'])} gold files "
                        f"absent from snapshot, e.g. {missing[0]}"))
    return name, len(rows), len(bad), bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmark-v2")
    ap.add_argument("--fix", action="store_true",
                    help="delete the file-list cache of any corrupt project "
                         "so a re-mine rebuilds it from git")
    a = ap.parse_args()
    base = ROOT / "industry-c7/data" / a.out

    tot = totbad = 0
    corrupt = []
    for f in sorted(glob.glob(str(base / "*.jsonl"))):
        name, n, nbad, bad = check_project(Path(f))
        tot += n
        totbad += nbad
        flag = ""
        if nbad:
            corrupt.append(name)
            flag = f"   <-- {nbad} bad"
        print(f"  {name:12s} {n:6,d} instances{flag}")
        for k, why in bad[:3]:
            print(f"       {k}: {why}")
    print(f"\n{tot:,} instances checked, {totbad} with gold absent from their "
          f"snapshot")
    if corrupt:
        print(f"corrupt projects ({len(corrupt)}): {' '.join(corrupt)}")
        if a.fix:
            for c in corrupt:
                cp = REPOS / f"cache-{c}.json"  # rebuilt from git on re-mine
                jp = base / f"{c}.jsonl"
                for p in (cp, jp):
                    if p.exists():
                        p.unlink()
                        print(f"   removed {p.name}")
            print("re-mine those projects; caches will rebuild from git")
        else:
            print("re-run with --fix to drop their caches and outputs")
        return 1
    print("all gold files present in their snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
