"""Phase 3.4 — similarity-weighted distractor sweep (RQ-A4 closure).

Runs the locked cascade's distractor sweep TWICE side-by-side:

  1. Uniform model (reproduces Mode 1 baseline — identity-agnostic).
  2. Similarity-weighted model (TF-IDF cosine to window text; windows
     whose top-similar distractor LOOKS like their evidence get hit
     harder).

Both runs use the same TOTAL expected displacement count per ratio,
so the side-by-side delta isolates identity-aware displacement from
pool-size effects.

Per-ratio output: Hit@1 / Hit@5 / MRR + the Δ(weighted − uniform).
A negative delta on Hit@5 means real-language distractors degrade
the cascade more than equal-count random distractors — that's the
paper claim.

Usage:
    PYTHONPATH=src python scripts/agent/run_distractor_sweep.py \\
        --cascade-predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \\
        --triage-examples data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl \\
        --distractors data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl \\
        --memory-size 347 \\
        --distractor-pool-size 300 \\
        --ratios 0,10,25,50 \\
        --output data/agent_runs/wol-distractor-sweep.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    compute_max_similarity_per_window,
    compute_window_weights,
    load_distractor_texts,
    load_window_texts_for_cascade,
    run_similarity_weighted_sweep,
    run_uniform_sweep,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cascade-predictions", type=Path, required=True,
                   help="locked cascade per-window-predictions.jsonl")
    p.add_argument("--triage-examples", type=Path, required=True,
                   help="global-triage-examples.jsonl (for window text)")
    p.add_argument("--distractors", type=Path, required=True,
                   help="WoL distractors/timeline.jsonl")
    p.add_argument("--memory-size", type=int, default=347)
    p.add_argument("--distractor-pool-size", type=int, default=300)
    p.add_argument("--ratios", type=str, default="0,10,25,50",
                   help="comma-separated percentages")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ratios = tuple(int(r) for r in args.ratios.split(","))

    # ------------------------------------------------------------------ load
    print(f"[distractor_sweep] loading cascade predictions from {args.cascade_predictions}")
    cascade = [
        json.loads(l) for l in args.cascade_predictions.open(encoding="utf-8")
        if l.strip()
    ]
    print(f"[distractor_sweep]   {len(cascade)} windows in cascade")

    print(f"[distractor_sweep] loading window texts from {args.triage_examples}")
    window_texts = load_window_texts_for_cascade(cascade, args.triage_examples)

    print(f"[distractor_sweep] loading distractor texts from {args.distractors}")
    distractor_texts = load_distractor_texts(
        args.distractors, limit=args.distractor_pool_size,
    )
    print(f"[distractor_sweep]   {len(distractor_texts)} distractor texts loaded")

    # ------------------------------------------------------------------ compute weights
    print("[distractor_sweep] computing TF-IDF similarity matrix...")
    sim_max, sim_summary = compute_max_similarity_per_window(
        window_texts, distractor_texts,
    )
    print(f"[distractor_sweep]   sim_max mean={sim_summary['sim_max_mean']:.4f} "
          f"min={sim_summary['sim_max_min']:.4f} max={sim_summary['sim_max_max']:.4f}")
    weights = compute_window_weights(sim_max)

    # ------------------------------------------------------------------ runs
    print("[distractor_sweep] running UNIFORM sweep...")
    uniform = run_uniform_sweep(
        cascade,
        distractor_pool_size=args.distractor_pool_size,
        memory_size=args.memory_size,
        ratios_pct=ratios, seed=args.seed,
    )

    print("[distractor_sweep] running SIMILARITY-WEIGHTED sweep...")
    weighted = run_similarity_weighted_sweep(
        cascade, window_weights=weights,
        distractor_pool_size=args.distractor_pool_size,
        memory_size=args.memory_size,
        ratios_pct=ratios, seed=args.seed,
        sim_summary=sim_summary,
    )

    # ------------------------------------------------------------------ print table
    by_ratio_u = {r.ratio_pct: r for r in uniform.ratios}
    by_ratio_w = {r.ratio_pct: r for r in weighted.ratios}

    print()
    print("=" * 102)
    print(f"  Distractor Sweep — RQ-A4 ({args.cascade_predictions.parent.name})")
    print("=" * 102)
    print(f"  pool_size={args.distractor_pool_size} memory_size={args.memory_size} "
          f"seed={args.seed}")
    print(f"  TF-IDF sim_max:  mean={sim_summary['sim_max_mean']:.4f}  "
          f"max={sim_summary['sim_max_max']:.4f}")
    print()
    print(f"  {'ratio':>6} {'p':>7} "
          f"{'Hit@5_unif':>11} {'Hit@5_simw':>11} {'dHit@5':>8} "
          f"{'Hit@1_unif':>11} {'Hit@1_simw':>11} {'dHit@1':>8} "
          f"{'MRR_unif':>9} {'MRR_simw':>9} {'dMRR':>8}")
    print("  " + "-" * 100)
    for r in ratios:
        u = by_ratio_u[r]
        w = by_ratio_w[r]
        dh5 = w.hit_at_5 - u.hit_at_5
        dh1 = w.hit_at_1 - u.hit_at_1
        dmrr = w.mrr - u.mrr
        sgn5 = "+" if dh5 >= 0 else ""
        sgn1 = "+" if dh1 >= 0 else ""
        sgnm = "+" if dmrr >= 0 else ""
        print(
            f"  {r:>5}% {u.p_per_slot_baseline:>7.3f} "
            f"{u.hit_at_5:>11.4f} {w.hit_at_5:>11.4f} {sgn5}{dh5:>7.4f} "
            f"{u.hit_at_1:>11.4f} {w.hit_at_1:>11.4f} {sgn1}{dh1:>7.4f} "
            f"{u.mrr:>9.4f} {w.mrr:>9.4f} {sgnm}{dmrr:>7.4f}"
        )
    print("=" * 102)

    # RQ-A4 paper claim check: does similarity weighting degrade Hit@5
    # at 50% ratio MORE than uniform? Expected sign: negative delta.
    if 50 in by_ratio_u and 50 in by_ratio_w:
        delta = by_ratio_w[50].hit_at_5 - by_ratio_u[50].hit_at_5
        rel = (delta / by_ratio_u[50].hit_at_5 * 100) if by_ratio_u[50].hit_at_5 else 0
        print()
        if delta <= 0:
            print(f"  RQ-A4 closure: similarity-weighted Hit@5 drop at 50% ratio is "
                  f"{abs(delta):.4f} absolute ({abs(rel):.1f}% relative)")
            print(f"  WORSE than uniform — confirms identity-aware displacement "
                  f"hurts more than random.")
        else:
            print(f"  Unexpected: similarity-weighted Hit@5 ({by_ratio_w[50].hit_at_5:.4f}) "
                  f"is BETTER than uniform ({by_ratio_u[50].hit_at_5:.4f}) at 50%.")
            print(f"  Possible cause: low TF-IDF coverage between WoL distractors and OB windows.")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({
                "uniform": uniform.to_dict(),
                "similarity_weighted": weighted.to_dict(),
            }, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n[distractor_sweep] wrote report -> {args.output}")


if __name__ == "__main__":
    main()
