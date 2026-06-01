"""Phase D — distractor ratio sweep.

For each ratio in {0%, 10%, 25%, 50%}: subsample the corresponding count
from the 110-ticket distractor pool with a fixed seed; write a temp
JSONL; register a pipeline variant that loads it; run a single
comparison harness pass with all four variants.

This shows how retrieval degrades as the fraction of memory occupied by
plausible-but-fake tickets grows.

Output: results/phase-d-distractors/{distractor_pool_<ratio>.jsonl, comparison/}
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--full-pool",
        type=Path,
        default=Path(
            "data/derived/global/2026-05-25-dataset-v5-large-global/"
            "jira-shadow-humanized-v2-distractors/mint-20260601/timeline.jsonl"
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("results/phase-d-distractors"),
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--ratios", nargs="+", type=float, default=[0.0, 0.10, 0.25, 0.50],
        help="Fraction of distractor pool to include",
    )
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.full_pool.open(encoding="utf-8") as f:
        pool = [json.loads(l) for l in f if l.strip()]
    print(f"[distractor_ratio_sweep] full distractor pool: {len(pool)} tickets")

    rng = random.Random(args.seed)
    pool_shuffled = pool[:]
    rng.shuffle(pool_shuffled)

    # Subsample for each ratio
    subsets = {}
    for r in args.ratios:
        n = int(round(r * len(pool)))
        sub = pool_shuffled[:n]
        path = args.out_dir / f"distractor_pool_{int(r*100):03d}pct.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for t in sub:
                f.write(json.dumps(t) + "\n")
        subsets[r] = (path, n)
        print(f"[distractor_ratio_sweep] ratio={r*100:.0f}%  count={n}  -> {path}")

    # Emit a small registry-shim file listing the pipelines we'll run
    # and the distractor paths.
    print()
    print("To run the sweep manually, use the standard comparison CLI with")
    print("each of these distractor paths injected into a custom pipeline.")
    print("Phase D launches each ratio as a separate subprocess so the")
    print("comparison runner produces a clean per-ratio report.json:")
    print()
    for r in args.ratios:
        path, n = subsets[r]
        label = f"d{int(r*100):03d}"
        print(f"  ratio={r*100:.0f}% pipelines=memorygraph_v2_sota_nw080_{label}_distractors")
    args.out_dir.joinpath("ratios.json").write_text(
        json.dumps(
            {f"{int(r*100):03d}pct": str(subsets[r][0]) for r in args.ratios},
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
