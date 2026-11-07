"""Can every project's gold files actually be READ, offline?

check_benchmark_integrity.py asks whether each gold file exists in its
snapshot's tree. That passed on 38,001 instances while 23 of 27 repos
were --filter=blob:none partial clones holding no file contents at all,
because a tree entry is metadata: `git ls-tree` serves it from the
commit graph without ever needing the blob.

The gap cost six hours. Retrieval reads contents with `git cat-file`,
and on a blobless clone that lazily fetches from GitHub per blob. On the
laptop it merely looked slow (4.57 s/instance, almost all of it network
round-trips). On a compute node with no internet, 22 of 27 projects hung
at zero instances for 33 minutes using one second of CPU.

So this asserts the thing that actually matters: read real bytes for
real gold files, with the network refused. GIT_ALLOW_PROTOCOL blocks the
lazy fetch, so a partial clone fails here instead of silently phoning
home.

Usage:
    python industry-c7/scripts/check_blobs_readable.py
    python industry-c7/scripts/check_blobs_readable.py --per-project 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize import BENCH, FULL_REPOS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-project", type=int, default=5,
                    help="gold files to read per project")
    ap.add_argument("--seed", type=int, default=20261107)
    args = ap.parse_args()

    # Refuse every transport git could use to fetch a missing blob. A
    # blobless clone then errors instead of quietly reaching the network,
    # which is the whole point: we are testing local completeness.
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": "none",
           "GIT_TERMINAL_PROMPT": "0"}

    rng = random.Random(args.seed)
    bad: list[str] = []
    print(f"{'project':12s} {'checked':>8s} {'ok':>5s} {'bytes read':>12s}")
    print("-" * 42)
    total_ok = total_n = 0
    for f in sorted(BENCH.glob("*.jsonl")):
        if f.name.endswith("-memory.jsonl"):
            continue
        p = f.stem
        if p not in FULL_REPOS:
            bad.append(f"{p}: no repo configured")
            continue
        rows = [json.loads(line) for line in f.open(encoding="utf-8")
                if line.strip()]
        picks = rng.sample(rows, min(args.per_project, len(rows)))
        ok = nbytes = 0
        for r in picks:
            gold = r["gold_files"][0]
            cp = subprocess.run(
                ["git", "--git-dir", str(FULL_REPOS[p]), "cat-file", "-p",
                 f"{r['snapshot_sha']}:{gold}"],
                capture_output=True, timeout=120, env=env)
            if cp.returncode == 0 and cp.stdout:
                ok += 1
                nbytes += len(cp.stdout)
            else:
                err = cp.stderr.decode("utf-8", "replace").strip()[:90]
                bad.append(f"{p} {r['issue_key']} {gold[:40]}: {err}")
        total_ok += ok
        total_n += len(picks)
        print(f"{p:12s} {len(picks):8d} {ok:5d} {nbytes:12,}")
    print("-" * 42)
    print(f"{'TOTAL':12s} {total_n:8d} {total_ok:5d}")

    # A partial clone is not just slow, it is unpublishable: anyone who
    # reproduces the benchmark gets a repo that needs the network or hangs.
    partial = []
    for p, g in sorted(FULL_REPOS.items()):
        cp = subprocess.run(["git", "--git-dir", str(g), "config", "--get",
                             "remote.origin.partialclonefilter"],
                            capture_output=True, text=True)
        if cp.stdout.strip():
            partial.append(f"{p}: still {cp.stdout.strip()}")

    if bad or partial:
        print("\nFAILURES:")
        for b in (bad + partial)[:30]:
            print("  " + b)
        return 1
    print("\nall gold files readable offline; no partial clones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
