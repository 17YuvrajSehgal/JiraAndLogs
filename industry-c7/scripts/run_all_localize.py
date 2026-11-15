"""Run the retrieval pipeline over every project, within the RAM we have.

Each localize run holds that project's blob-token cache in memory, and
the caches are not small: mongodb's is 702 MB on disk and several times
that as live Counters. One run uses about 8% of 24 cores, so cores are
not the limit here -- memory is. Launching 27 at once would thrash or
die partway, losing hours of warmed cache.

So: small projects run a few at a time, large ones run alone, and the
scheduler waits when free memory drops below a floor. Order is smallest
first, which gets results on the board early and keeps the memory high
water mark down until the caches have been written once.

Restartable: a project whose blob cache and results already exist is
skipped, so an interrupted sweep continues instead of starting over.

Usage:
    python scripts/run_all_localize.py            # all 27
    python scripts/run_all_localize.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BENCH = ROOT / "data/benchmark"
RES = ROOT / "data/results"
LOGS = ROOT / "data/loclogs"

BIG = 1500          # instances above which a project runs on its own
SMALL_PAR = 3       # concurrent small projects
MEM_FLOOR_MB = 2500  # pause launching below this


def available_mb() -> int:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Counter '\\Memory\\Available MBytes')"
             ".CounterSamples[0].CookedValue"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return int(float(out))
    except Exception:
        return 10**6        # never block on a failed probe


def sizes() -> list[tuple[str, int]]:
    out = []
    for f in sorted(BENCH.glob("*.jsonl")):
        if f.name.endswith("-memory.jsonl"):
            continue
        p = f.stem
        out.append((p, sum(1 for _ in f.open(encoding="utf-8"))))
    return sorted(out, key=lambda t: t[1])


def done(p: str) -> bool:
    """A project is done when its results file exists and parses."""
    f = RES / f"{p}-instances.jsonl"
    if not f.exists() or f.stat().st_size == 0:
        return False
    try:
        with f.open(encoding="utf-8") as fh:
            json.loads(fh.readline())
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--parallel", type=int, default=SMALL_PAR)
    args = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)

    todo = [(p, n) for p, n in sizes() if not done(p)]
    skip = [p for p, _ in sizes() if done(p)]
    print(f"{len(todo)} to run, {len(skip)} already done {skip}")
    for p, n in todo:
        print(f"   {p:12s} {n:6,} instances{'   [runs alone]' if n >= BIG else ''}")
    if args.dry_run:
        return 0

    running: list[tuple[str, subprocess.Popen, float]] = []
    t0 = time.time()

    def reap():
        for item in list(running):
            p, proc, started = item
            if proc.poll() is not None:
                running.remove(item)
                mark = "ok" if proc.returncode == 0 else f"FAIL {proc.returncode}"
                print(f"[{time.time()-t0:7.0f}s] {p:12s} {mark} "
                      f"in {time.time()-started:.0f}s", flush=True)

    for p, n in todo:
        alone = n >= BIG
        while True:
            reap()
            cap = 1 if alone else args.parallel
            if len(running) >= cap or (alone and running):
                time.sleep(20)
                continue
            if available_mb() < MEM_FLOOR_MB and running:
                time.sleep(30)
                continue
            break
        log = (LOGS / f"{p}.log").open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-u", str(HERE / "localize.py"), "--project", p],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
        running.append((p, proc, time.time()))
        print(f"[{time.time()-t0:7.0f}s] start {p:12s} {n:6,} "
              f"({len(running)} running, {available_mb()} MB free)", flush=True)

    while running:
        reap()
        time.sleep(20)
    print(f"all done in {(time.time()-t0)/3600:.1f} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
