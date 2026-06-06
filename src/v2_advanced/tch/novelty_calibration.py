"""G7 — Learned per-window novelty calibration.

Replace the free-signal `ret_conf < 0.5` heuristic with a learned LogReg
classifier that predicts P(novel | window_features). Features include
window_type, service, family, is_hard_case, retrieval confidence, and
per-pipeline triage scores.

5-fold stratified CV; deterministic with random_state=42.

Output: <out>/learned_novelty.jsonl with rows
  {window_id, p_novel, predicted_novel_at_05, predicted_novel_at_best_f1}

Best threshold (max F1 on the out-of-fold predictions) is also written
to <out>/best_threshold.json.

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.novelty_calibration \\
        --cascade-predictions data/.../v2g-final-models/g4-agent-phase3/cascade/per-window-predictions.jsonl \\
        --out-dir data/.../v2g-final-models/g7-learned-novelty
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import f1_score, precision_score, recall_score


# Feature spec
# G7 (2026-06-06): n_prior_family_tickets is a near-perfect predictor
# of novelty in our v2 in-distribution test split, because by
# construction novelty = "no matching past ticket in memory" and
# n_prior_family_tickets = "count of past memory tickets in same
# family". So it's essentially a tautology. We provide two feature
# sets so we can measure leakage-free novelty separately.
NUMERIC_FEATURES_FULL = [
    "tch_max_retrieval_conf",
    "triage_score",
    "n_prior_family_tickets",
    "is_hard_case",  # bool → int
]
NUMERIC_FEATURES_NO_LEAK = [
    "tch_max_retrieval_conf",
    "triage_score",
    "is_hard_case",
]
ONE_HOT_KEYS = ["window_type", "scenario_family", "service_name"]


def build_features(rows: list[dict], include_n_prior: bool = True) -> tuple[np.ndarray, list[str]]:
    """Build dense feature matrix + column names.

    If include_n_prior is False, omits n_prior_family_tickets (the leaky
    feature) to measure novelty detection without the tautology.
    """
    numeric = NUMERIC_FEATURES_FULL if include_n_prior else NUMERIC_FEATURES_NO_LEAK

    vocab: dict[str, list[str]] = {}
    for k in ONE_HOT_KEYS:
        seen: set[str] = set()
        for r in rows:
            v = r.get(k) or "__missing__"
            seen.add(v)
        vocab[k] = sorted(seen)

    columns: list[str] = list(numeric)
    for k in ONE_HOT_KEYS:
        for val in vocab[k]:
            columns.append(f"{k}={val}")

    X = np.zeros((len(rows), len(columns)), dtype=np.float32)
    for i, r in enumerate(rows):
        # Numeric features (variable based on include_n_prior)
        col = 0
        X[i, col] = float(r.get("tch_max_retrieval_conf") or 0.0); col += 1
        X[i, col] = float(r.get("triage_score") or 0.0); col += 1
        if include_n_prior:
            v = r.get("n_prior_family_tickets")
            X[i, col] = float(v) if v is not None else 0.0
            col += 1
        X[i, col] = 1.0 if r.get("is_hard_case") else 0.0; col += 1
        # One-hot features
        col_idx = len(numeric)
        for k in ONE_HOT_KEYS:
            v = r.get(k) or "__missing__"
            for val in vocab[k]:
                if v == val:
                    X[i, col_idx] = 1.0
                col_idx += 1
    return X, columns


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cascade-predictions", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rows = [json.loads(l) for l in args.cascade_predictions.open(encoding="utf-8")]
    y = np.array([1 if not (r.get("gold_matched_issue_ids") or []) else 0
                  for r in rows], dtype=np.int32)
    print(f"loaded {len(rows)} windows, {int(y.sum())} truly novel ({y.mean():.1%})")

    X, columns = build_features(rows, include_n_prior=False)
    print(f"feature matrix (leakage-free): {X.shape}, columns: {len(columns)}")

    # 5-fold CV out-of-fold predictions
    oof = np.zeros(len(rows), dtype=np.float64)
    skf = StratifiedKFold(n_splits=args.n_splits, shuffle=True, random_state=args.seed)
    for fold_train, fold_test in skf.split(X, y):
        clf = LogisticRegression(
            max_iter=1000, C=1.0, class_weight="balanced", random_state=args.seed,
        )
        clf.fit(X[fold_train], y[fold_train])
        oof[fold_test] = clf.predict_proba(X[fold_test])[:, 1]

    # Threshold sweep on OOF
    print("\nThreshold sweep (out-of-fold):")
    print(f"{'thresh':>8s} {'flagged':>8s} {'TP':>6s} {'FP':>5s} {'prec':>7s} {'recall':>7s} {'F1':>7s}")
    best = (0.0, 0.0)  # (threshold, f1)
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        y_pred = (oof >= thresh).astype(int)
        p_ = precision_score(y, y_pred, zero_division=0)
        r_ = recall_score(y, y_pred, zero_division=0)
        f1 = f1_score(y, y_pred, zero_division=0)
        tp = int(((y == 1) & (y_pred == 1)).sum())
        fp = int(((y == 0) & (y_pred == 1)).sum())
        flagged = int(y_pred.sum())
        print(f"  {thresh:>6.2f}  {flagged:>8d}  {tp:>5d}  {fp:>4d}  "
              f"{p_:>7.4f} {r_:>7.4f} {f1:>7.4f}")
        if f1 > best[1]:
            best = (thresh, f1)

    print(f"\nBest threshold: {best[0]:.2f} (F1={best[1]:.4f})")

    # Train final model on all data for coefficient inspection
    final_clf = LogisticRegression(
        max_iter=1000, C=1.0, class_weight="balanced", random_state=args.seed,
    )
    final_clf.fit(X, y)
    coefs = sorted(
        zip(columns, final_clf.coef_[0]), key=lambda kv: -abs(kv[1]),
    )
    print("\nTop 15 features by abs(coefficient):")
    for name, c in coefs[:15]:
        print(f"  {name:50s}  {c:+.3f}")

    # Write outputs
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "learned_novelty.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for i, r in enumerate(rows):
            row = {
                "window_id": r["window_id"],
                "p_novel": float(oof[i]),
                "predicted_novel_at_05": bool(oof[i] >= 0.5),
                "predicted_novel_at_best_f1": bool(oof[i] >= best[0]),
            }
            fh.write(json.dumps(row) + "\n")
    print(f"\nwrote {out_path}")

    # Save best threshold + coefficients
    (args.out_dir / "best_threshold.json").write_text(json.dumps({
        "best_threshold": best[0],
        "best_f1": best[1],
        "n_total": len(rows),
        "n_novel_true": int(y.sum()),
        "n_splits": args.n_splits,
        "seed": args.seed,
    }, indent=2))

    (args.out_dir / "feature_coefficients.json").write_text(json.dumps({
        "intercept": float(final_clf.intercept_[0]),
        "coefficients": {name: float(c) for name, c in zip(columns, final_clf.coef_[0])},
    }, indent=2))


if __name__ == "__main__":
    main()
