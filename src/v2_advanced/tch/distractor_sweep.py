"""G6 — Distractor robustness sweep for the TCH cascade.

For each distractor ratio R% ∈ {0, 10, 25, 50}, simulate the effect on
the cascade's headline metrics. Approach: take the locked G1+G4 cascade
top-5 outputs, and at each position INJECT a synthetic distractor ID with
probability p = N_distractor / (N_distractor + N_memory). This models the
expected displacement of gold candidates by similar-looking distractors.

Caveats (documented in the output):
  - This simulates UNIFORM distractor displacement. In practice, distractors
    that LOOK like the window evidence are more likely to outrank gold;
    unrelated distractors rarely appear in top-K. The simulation gives a
    "lower bound" on cascade degradation under the assumption distractors
    are evenly likely to appear in top-K positions.
  - A rigorous distractor sweep would re-fit BiEncoder + re-index SPLADE
    + re-extract KG with the augmented corpus. That takes ~1 hr GPU per
    ratio, deferred for future work.

Output: <out>/distractor_curve.json with per-ratio metrics.

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.distractor_sweep \\
        --cascade-predictions data/.../v2g-final-models/g4-agent-phase3/cascade/per-window-predictions.jsonl \\
        --out data/.../v2g-final-models/g6-distractor-sweep/distractor_curve.json \\
        --memory-size 347 \\
        --distractor-pool-size 110 \\
        --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def compute_metrics(predictions: list[dict]) -> dict:
    """Hit@K binary + MRR for a list of predictions."""
    h1 = h5 = n = 0
    mrr_sum = 0.0
    for p in predictions:
        gold = set(p.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        n += 1
        top = p.get("matched_issue_ids") or []
        for i, t in enumerate(top, 1):
            if t in gold:
                if i == 1:
                    h1 += 1
                if i <= 5:
                    h5 += 1
                mrr_sum += 1.0 / i
                break
    return {
        "n_with_gold": n,
        "hit_at_1": h1 / n if n else 0.0,
        "hit_at_5": h5 / n if n else 0.0,
        "mrr": mrr_sum / n if n else 0.0,
    }


def inject_distractors(
    cascade: list[dict],
    n_distractors: int,
    n_memory: int,
    seed: int = 42,
) -> list[dict]:
    """For each window, inject distractors into top-5 with per-slot probability p."""
    rng = random.Random(seed)
    if n_distractors == 0:
        return cascade
    p = n_distractors / (n_distractors + n_memory)
    distractor_ids = [f"DISTRACTOR-{i:03d}" for i in range(n_distractors)]

    out = []
    for window_pred in cascade:
        new_top = list(window_pred.get("matched_issue_ids") or [])
        for i in range(len(new_top)):
            if rng.random() < p:
                new_top[i] = rng.choice(distractor_ids)
        out.append({**window_pred, "matched_issue_ids": new_top})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cascade-predictions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--memory-size", type=int, default=347,
                    help="Size of the real memory corpus")
    ap.add_argument("--distractor-pool-size", type=int, default=110,
                    help="Max distractor pool size (100% ratio)")
    ap.add_argument("--ratios", type=str, default="0,10,25,50",
                    help="Comma-separated percentages")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cascade = [json.loads(l) for l in args.cascade_predictions.open(encoding="utf-8")]
    print(f"loaded {len(cascade)} cascade predictions")

    ratios = [int(r) for r in args.ratios.split(",")]
    results = {}

    for ratio_pct in ratios:
        n_distractors = int(args.distractor_pool_size * ratio_pct / 100)
        # Apply seed deterministically per-ratio so they're independent
        injected = inject_distractors(
            cascade, n_distractors, args.memory_size,
            seed=args.seed + ratio_pct,
        )
        m = compute_metrics(injected)
        m["n_distractors"] = n_distractors
        m["p_per_slot"] = n_distractors / (n_distractors + args.memory_size) if n_distractors else 0.0
        results[f"{ratio_pct}pct"] = m

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "cascade_source": str(args.cascade_predictions),
        "memory_size": args.memory_size,
        "distractor_pool_size": args.distractor_pool_size,
        "seed": args.seed,
        "method": (
            "Probabilistic per-slot distractor injection. For each ratio R%, "
            "compute p = N_distractor / (N_distractor + N_memory); each top-5 "
            "slot is replaced by a synthetic distractor ID with probability p. "
            "Models the lower-bound effect of distractors evenly displacing "
            "real candidates in cascade output."
        ),
        "caveats": (
            "Uniform displacement; in practice, similar-looking distractors are "
            "more likely to outrank gold. A rigorous sweep would re-fit BiEncoder "
            "+ re-index SPLADE + re-extract KG with augmented corpus (~1 hr GPU "
            "per ratio, deferred)."
        ),
        "results": results,
    }
    args.out.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {args.out}\n")

    # Print pretty table
    print(f"{'ratio':>8s}  {'n_distr':>7s}  {'p/slot':>7s}  "
          f"{'Hit@1':>7s}  {'Hit@5':>7s}  {'MRR':>7s}")
    for ratio_pct in ratios:
        r = results[f"{ratio_pct}pct"]
        print(f"  {ratio_pct:>4d}%   {r['n_distractors']:>7d}  "
              f"{r['p_per_slot']:>6.3f}  "
              f"{r['hit_at_1']:>7.4f}  {r['hit_at_5']:>7.4f}  {r['mrr']:>7.4f}")


if __name__ == "__main__":
    main()
