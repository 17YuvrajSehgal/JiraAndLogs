"""G8 — OOD novelty evaluation via leave-one-family-out.

Tests whether G7's learned novelty classifier generalizes to families
NOT present in training. Each scenario_family is held out in turn; the
classifier is trained on the remaining ~21 families and predicts
P(novel) on the held-out family.

This is the canonical OOD test for family-distribution shift: if the
classifier learned a generic "what does a novel window look like"
function it should generalize; if it memorized family-specific patterns
it will collapse.

Comparison points:
- G7 in-distribution (5-fold CV, all families present in each fold):
    threshold 0.50 -> precision 0.969, recall 0.776, F1 0.861

OOD success criterion: F1 within ~10% rel of in-distribution at any
single threshold. Anything beyond that is a strong generalization
result.

Output:
- <out>/ood_per_family.json    per-family precision/recall/F1 at thresh 0.50
- <out>/ood_aggregate.json     overall pooled metrics across all families
- <out>/ood_threshold_sweep.json sweep across {0.3..0.7}

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.novelty_ood \\
        --cascade-predictions data/.../v2g-final-models/g4-agent-phase3/cascade/per-window-predictions.jsonl \\
        --out-dir data/.../v2g-final-models/g8-ood-eval
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score

from v2_advanced.tch.novelty_calibration import build_features


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cascade-predictions", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rows = [json.loads(l) for l in args.cascade_predictions.open(encoding="utf-8")]
    y = np.array([1 if not (r.get("gold_matched_issue_ids") or []) else 0
                  for r in rows], dtype=np.int32)
    families = np.array([r.get("scenario_family") or "__missing__" for r in rows])
    unique_families = sorted(set(families.tolist()))
    print(f"loaded {len(rows)} windows, {int(y.sum())} truly novel ({y.mean():.1%})")
    print(f"unique families: {len(unique_families)}")

    X, columns = build_features(rows, include_n_prior=False)
    print(f"feature matrix: {X.shape} ({len(columns)} cols)")

    # Track per-window OOD probability + which fold it came from
    oof_p = np.full(len(rows), np.nan, dtype=np.float64)
    fold_family = ["" for _ in rows]

    print("\nLeave-one-family-out:")
    print(f"{'family':30s} {'n_test':>6s} {'n_novel':>7s} {'n_train':>7s}")
    for fam in unique_families:
        test_mask = families == fam
        train_mask = ~test_mask
        n_test = int(test_mask.sum())
        n_novel = int(y[test_mask].sum())
        n_train = int(train_mask.sum())

        # If the family has no novel windows OR all novel windows, we can
        # still train (the classifier just has to predict that family
        # never appears as a feature). But if training has only one
        # class, sklearn errors.
        if len(set(y[train_mask].tolist())) < 2:
            print(f"  {fam:30s} {n_test:>6d} {n_novel:>7d} {n_train:>7d}  SKIP (single-class train)")
            continue

        clf = LogisticRegression(
            max_iter=1000, C=1.0, class_weight="balanced", random_state=args.seed,
        )
        clf.fit(X[train_mask], y[train_mask])
        probs = clf.predict_proba(X[test_mask])[:, 1]
        for idx, prob in zip(np.where(test_mask)[0], probs):
            oof_p[idx] = float(prob)
            fold_family[idx] = fam
        print(f"  {fam:30s} {n_test:>6d} {n_novel:>7d} {n_train:>7d}")

    # Filter out windows whose family had a single-class train set
    valid = ~np.isnan(oof_p)
    print(f"\nvalid OOD predictions: {int(valid.sum())} / {len(rows)}")

    # Aggregate threshold sweep
    print("\nAggregate threshold sweep (OOD):")
    print(f"{'thresh':>8s} {'flagged':>8s} {'TP':>6s} {'FP':>5s} {'prec':>7s} {'recall':>7s} {'F1':>7s}")
    sweep = {}
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        y_pred = (oof_p[valid] >= thresh).astype(int)
        y_true_v = y[valid]
        prec = precision_score(y_true_v, y_pred, zero_division=0)
        rec = recall_score(y_true_v, y_pred, zero_division=0)
        f1 = f1_score(y_true_v, y_pred, zero_division=0)
        tp = int(((y_true_v == 1) & (y_pred == 1)).sum())
        fp = int(((y_true_v == 0) & (y_pred == 1)).sum())
        flagged = int(y_pred.sum())
        print(f"  {thresh:>6.2f}  {flagged:>8d}  {tp:>5d}  {fp:>4d}  "
              f"{prec:>7.4f} {rec:>7.4f} {f1:>7.4f}")
        sweep[f"{thresh:.2f}"] = {
            "flagged": flagged, "TP": tp, "FP": fp,
            "precision": float(prec), "recall": float(rec), "F1": float(f1),
        }

    # Per-family at threshold 0.50
    print("\nPer-family at threshold 0.50:")
    print(f"{'family':30s} {'n':>5s} {'novel':>5s} {'pred':>5s} {'TP':>4s} {'prec':>7s} {'recall':>7s} {'F1':>7s}")
    per_family = {}
    for fam in unique_families:
        mask = (families == fam) & valid
        if not mask.any():
            continue
        y_true_f = y[mask]
        y_pred_f = (oof_p[mask] >= 0.5).astype(int)
        n = int(mask.sum())
        n_novel_f = int(y_true_f.sum())
        n_pred_f = int(y_pred_f.sum())
        tp_f = int(((y_true_f == 1) & (y_pred_f == 1)).sum())
        prec_f = precision_score(y_true_f, y_pred_f, zero_division=0)
        rec_f = recall_score(y_true_f, y_pred_f, zero_division=0)
        f1_f = f1_score(y_true_f, y_pred_f, zero_division=0)
        print(f"  {fam:30s} {n:>5d} {n_novel_f:>5d} {n_pred_f:>5d} {tp_f:>4d}  "
              f"{prec_f:>7.4f} {rec_f:>7.4f} {f1_f:>7.4f}")
        per_family[fam] = {
            "n_test": n, "n_novel_true": n_novel_f, "n_predicted_novel": n_pred_f,
            "TP": tp_f, "precision": float(prec_f),
            "recall": float(rec_f), "F1": float(f1_f),
        }

    # Compare to in-distribution baseline (from G7)
    in_dist = {
        "0.30": {"precision": 0.898, "recall": 0.882, "F1": 0.890},
        "0.40": {"precision": 0.936, "recall": 0.821, "F1": 0.875},
        "0.50": {"precision": 0.969, "recall": 0.776, "F1": 0.861},
        "0.60": {"precision": 0.991, "recall": 0.770, "F1": 0.866},
        "0.70": {"precision": 1.000, "recall": 0.762, "F1": 0.865},
    }
    print("\nOOD vs In-Distribution (F1):")
    print(f"{'thresh':>8s} {'OOD F1':>8s} {'ID F1':>8s} {'rel delta':>10s}")
    for thresh in ["0.30", "0.40", "0.50", "0.60", "0.70"]:
        ood_f1 = sweep[thresh]["F1"]
        id_f1 = in_dist[thresh]["F1"]
        rel = (ood_f1 - id_f1) / id_f1 * 100 if id_f1 else 0.0
        print(f"  {thresh}  {ood_f1:>8.4f} {id_f1:>8.4f} {rel:>+9.1f}%")

    # Write outputs
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ood_per_family.json").write_text(json.dumps({
        "per_family": per_family,
        "threshold": 0.5,
        "n_families": len(per_family),
    }, indent=2))

    (args.out_dir / "ood_threshold_sweep.json").write_text(json.dumps({
        "sweep": sweep,
        "in_distribution_g7": in_dist,
        "n_valid": int(valid.sum()),
        "n_total": len(rows),
        "n_novel_total": int(y.sum()),
    }, indent=2))

    # Per-window probabilities for cascade-use if desired
    with (args.out_dir / "ood_learned_novelty.jsonl").open("w", encoding="utf-8") as fh:
        for i, r in enumerate(rows):
            if not np.isnan(oof_p[i]):
                fh.write(json.dumps({
                    "window_id": r["window_id"],
                    "p_novel": float(oof_p[i]),
                    "ood_fold_family": fold_family[i],
                }) + "\n")
    print(f"\nwrote {args.out_dir}/")


if __name__ == "__main__":
    main()
