"""Run function_stage or dense_baselines over all 27 projects.

They go in parallel with each other because they contend for different
things: function_stage is tree-sitter parsing on the CPU, dense is
bge-small on the GPU. Within a stage, projects are independent.

Concurrency is deliberately different per stage. Funcs holds a parsed
function cache per project and is CPU-bound, so it runs several at once
up to the RAM floor. Dense shares ONE GPU; several processes would each
load their own copy of the model and fight for 8 GB, so it runs one at
a time and lets the batch size do the work.

Skips a project whose output cache already exists, so an interrupted
sweep resumes instead of restarting.

Usage:
    python scripts/run_all_stage.py funcs --parallel 5
    python scripts/run_all_stage.py dense
    python scripts/run_all_stage.py funcs --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BENCH = ROOT / "data/benchmark"
RES = ROOT / "data/results"
LOGS = ROOT / "data/stagelogs"

STAGES = {
    "funcs": {"script": "function_stage.py", "out": "funcs-{p}.pkl",
              "needs": ["{p}-instances.jsonl", "{p}-summary.json"],
              "parallel": 5},
    "dense": {"script": "dense_baselines.py", "out": "dense-blobs-{p}.pkl",
              "needs": ["{p}-instances.jsonl", "{p}-summary.json",
                        "blob-tokens-{p}.pkl"],
              "parallel": 1},
}


def projects() -> list[tuple[str, int]]:
    out = []
    for f in sorted(BENCH.glob("*.jsonl")):
        if f.name.endswith("-memory.jsonl"):
            continue
        out.append((f.stem, sum(1 for _ in f.open(encoding="utf-8"))))
    return sorted(out, key=lambda t: -t[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=sorted(STAGES))
    ap.add_argument("--parallel", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = STAGES[args.stage]
    par = args.parallel or cfg["parallel"]
    LOGS.mkdir(parents=True, exist_ok=True)

    todo, blocked, done = [], [], []
    for p, n in projects():
        if (RES / cfg["out"].format(p=p)).exists():
            done.append(p)
            continue
        missing = [t.format(p=p) for t in cfg["needs"]
                   if not (RES / t.format(p=p)).exists()]
        (blocked if missing else todo).append((p, n, missing))

    print(f"stage={args.stage} parallel={par}")
    print(f"  {len(done)} already done, {len(todo)} to run, "
          f"{len(blocked)} blocked on missing inputs")
    for p, n, m in blocked:
        print(f"    BLOCKED {p:12s} missing {m}")
    if args.dry_run:
        for p, n, _ in todo:
            print(f"    would run {p:12s} {n:6,}")
        return 0
    if not todo:
        return 0

    running: list[tuple[str, subprocess.Popen, float]] = []
    t0 = time.time()

    def reap():
        for item in list(running):
            p, proc, started = item
            if proc.poll() is not None:
                running.remove(item)
                ok = "ok" if proc.returncode == 0 else f"FAIL {proc.returncode}"
                print(f"[{time.time()-t0:6.0f}s] {p:12s} {ok} "
                      f"in {time.time()-started:.0f}s", flush=True)

    for p, n, _ in todo:
        while len(running) >= par:
            reap()
            time.sleep(5)
        log = (LOGS / f"{args.stage}-{p}.log").open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-u", str(HERE / cfg["script"]), "--project", p],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
        running.append((p, proc, time.time()))
        print(f"[{time.time()-t0:6.0f}s] start {p:12s} {n:6,} "
              f"({len(running)} running)", flush=True)

    while running:
        reap()
        time.sleep(5)
    print(f"{args.stage} finished in {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
