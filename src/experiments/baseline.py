#!/usr/bin/env python3
"""Fast iteration script for triage model development.

Loads a global triage dataset (defaults to the committed v4-large global),
trains a small leaderboard of sklearn models against the family-stratified
split, and prints PR-AUC / ROC-AUC / Precision@FPR=1% per pipeline.

Design rules (per docs/ml-ai-pipeline-development-plan.md §5):

  * Feature list is read from triage-feature-columns.json at runtime — never
    hardcoded. v5's new RED / business / runtime columns flow through with
    zero code changes once the build pipeline emits them.

  * Production-realism: only triage_feature_* columns are model inputs.
    triage_label, triage_severity, triage_components, triage_reason_class,
    is_hard_case, scenario_id, scenario_family are eval-only.

  * Split discipline: train on split=train, threshold-tune on split=validation,
    score on split=test. Never random-split rows.

  * Borderline handling: STRICT (borderline counted as negative) is the
    headline. INCLUSIVE (borderline counted as positive) is reported too.

Iteration loop:

    python experiments/baseline_v4.py                       # v4-large baseline
    python experiments/baseline_v4.py --global-id <id>      # any other corpus
    python experiments/baseline_v4.py --models hgb,rf       # subset of pipelines

Expected runtime on v4-large: <30 seconds end-to-end.

To add a new model: append an entry to MODELS at the bottom. The function
must take (X_train, y_train) and return a fitted estimator that exposes
.predict_proba(X)[:, 1]. Everything else (split loading, scaling, metrics)
is shared.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # src/experiments/X.py -> repo root
DEFAULT_GLOBAL_ID = "2026-05-22-dataset-v4-large-global"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_feature_columns(global_dir: Path) -> list[str]:
    contract = json.loads(
        (global_dir / "triage-feature-columns.json").read_text(encoding="utf-8-sig")
    )
    cols = contract.get("feature_columns") or []
    if not cols:
        raise RuntimeError(
            f"triage-feature-columns.json at {global_dir} declares no feature_columns"
        )
    return list(cols)


def _matrix(rows: list[dict[str, Any]], cols: list[str]) -> np.ndarray:
    return np.asarray(
        [[float(r.get(c, 0.0) or 0.0) for c in cols] for r in rows],
        dtype=np.float64,
    )


def _binarize(rows: list[dict[str, Any]], mode: str) -> np.ndarray:
    if mode == "strict":
        return np.asarray(
            [1 if r["triage_label"] == "ticket_worthy" else 0 for r in rows],
            dtype=np.int64,
        )
    if mode == "inclusive":
        return np.asarray(
            [1 if r["triage_label"] in {"ticket_worthy", "borderline"} else 0 for r in rows],
            dtype=np.int64,
        )
    raise ValueError(f"unknown binarize mode {mode!r}")


def _threshold_at_fpr(
    scores: np.ndarray, labels: np.ndarray, target_fpr: float
) -> tuple[float, float, float]:
    """Return (threshold, achieved_fpr, achieved_tpr) where threshold is the
    smallest value such that FPR <= target_fpr."""
    order = np.argsort(-scores)
    s = scores[order]
    y = labels[order]
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return (1.0, 0.0, 0.0)
    tp = fp = 0
    best = (float(s[0]) + 1e-9, 0.0, 0.0)
    feasible = False
    for score, label in zip(s, y):
        if label == 1:
            tp += 1
        else:
            fp += 1
        fpr = fp / n_neg
        tpr = tp / n_pos
        if fpr <= target_fpr:
            best = (float(score), fpr, tpr)
            feasible = True
        else:
            if not feasible:
                best = (float(score) + 1e-9, fpr, tpr)
            break
    return best


def _expected_calibration_error(
    scores: np.ndarray, labels: np.ndarray, bins: int = 10
) -> float:
    if len(scores) == 0:
        return 0.0
    idx = np.clip((scores * bins).astype(np.int64), 0, bins - 1)
    total = 0.0
    n = len(scores)
    for b in range(bins):
        mask = idx == b
        k = int(mask.sum())
        if k == 0:
            continue
        bucket_scores = scores[mask]
        bucket_labels = labels[mask]
        total += (k / n) * abs(bucket_scores.mean() - bucket_labels.mean())
    return total


@dataclass
class PipelineResult:
    name: str
    pr_auc_test: float
    roc_auc_test: float
    precision_at_fpr_01: float
    recall_at_fpr_01: float
    precision_at_fpr_05: float
    recall_at_fpr_05: float
    ece_test: float
    brier_test: float
    threshold_at_fpr_01: float


def _evaluate(
    name: str,
    test_scores: np.ndarray,
    test_labels: np.ndarray,
    val_scores: np.ndarray,
    val_labels: np.ndarray,
) -> PipelineResult:
    threshold_01, _, _ = _threshold_at_fpr(val_scores, val_labels, 0.01)
    threshold_05, _, _ = _threshold_at_fpr(val_scores, val_labels, 0.05)
    pred_01 = (test_scores >= threshold_01).astype(np.int64)
    pred_05 = (test_scores >= threshold_05).astype(np.int64)

    def _prec_rec(pred: np.ndarray) -> tuple[float, float]:
        tp = int(((pred == 1) & (test_labels == 1)).sum())
        fp = int(((pred == 1) & (test_labels == 0)).sum())
        fn = int(((pred == 0) & (test_labels == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        return prec, rec

    prec_01, rec_01 = _prec_rec(pred_01)
    prec_05, rec_05 = _prec_rec(pred_05)

    return PipelineResult(
        name=name,
        pr_auc_test=float(average_precision_score(test_labels, test_scores))
        if test_labels.sum() > 0
        else 0.0,
        roc_auc_test=float(roc_auc_score(test_labels, test_scores))
        if test_labels.sum() > 0 and test_labels.sum() < len(test_labels)
        else 0.0,
        precision_at_fpr_01=prec_01,
        recall_at_fpr_01=rec_01,
        precision_at_fpr_05=prec_05,
        recall_at_fpr_05=rec_05,
        ece_test=_expected_calibration_error(test_scores, test_labels),
        brier_test=float(brier_score_loss(test_labels, test_scores))
        if 0 < test_labels.sum() < len(test_labels)
        else 0.0,
        threshold_at_fpr_01=threshold_01,
    )


# ---------------------------------------------------------------------------
# Pipelines — add new ones here
# ---------------------------------------------------------------------------


def _fit_logistic(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    # class_weight='balanced' is the apples-to-apples vs the existing
    # run_triage_benchmark.py logistic, which uses inverse-frequency weights.
    return LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=2000,
        solver="lbfgs",
    ).fit(X_train, y_train)


def _fit_hgb(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    # HistGradientBoosting is the strongest fast-to-train classical baseline
    # for tabular data. No standardization needed; tree models are
    # scale-invariant. class_weight='balanced' handles the 22% positive rate.
    return HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        max_depth=8,
        l2_regularization=0.1,
        class_weight="balanced",
        random_state=42,
    ).fit(X_train, y_train)


def _fit_rf(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    # Wrap RF in calibrated classifier so the FPR-thresholding produces
    # well-calibrated probabilities. cv=3 keeps it fast.
    base = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    return CalibratedClassifierCV(base, method="isotonic", cv=3).fit(
        X_train, y_train
    )


MODELS: dict[str, tuple[str, Callable[[np.ndarray, np.ndarray], Any], bool]] = {
    # name -> (display_name, fit_fn, needs_scaling)
    "logistic": ("logistic_l2_balanced", _fit_logistic, True),
    "hgb": ("hist_gradient_boosting", _fit_hgb, False),
    "rf": ("calibrated_random_forest", _fit_rf, False),
}


# ---------------------------------------------------------------------------
# Stratified breakdown helper
# ---------------------------------------------------------------------------


def _stratified_pr_auc(
    test_rows: list[dict[str, Any]],
    test_scores: np.ndarray,
    test_labels: np.ndarray,
    key: str,
) -> dict[str, tuple[int, int, float]]:
    """Return {group_value: (n_windows, n_positive, pr_auc)}."""
    groups: dict[Any, list[int]] = defaultdict(list)
    for i, r in enumerate(test_rows):
        groups[r.get(key)].append(i)
    out: dict[str, tuple[int, int, float]] = {}
    for g, idxs in groups.items():
        gl = test_labels[idxs]
        gs = test_scores[idxs]
        n_pos = int(gl.sum())
        if n_pos == 0 or n_pos == len(gl):
            out[str(g)] = (len(gl), n_pos, float("nan"))
        else:
            out[str(g)] = (
                len(gl),
                n_pos,
                float(average_precision_score(gl, gs)),
            )
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--global-id",
        default=DEFAULT_GLOBAL_ID,
        help=f"Global dataset id (default: {DEFAULT_GLOBAL_ID})",
    )
    parser.add_argument(
        "--derived-root",
        default=str(REPO_ROOT / "data" / "derived"),
        help="Path to data/derived (default: repo root)",
    )
    parser.add_argument(
        "--models",
        default=",".join(MODELS.keys()),
        help=f"Comma-separated subset of: {','.join(MODELS.keys())}",
    )
    parser.add_argument(
        "--binarize",
        choices=("strict", "inclusive"),
        default="strict",
        help="Borderline handling: strict (default, headline) or inclusive",
    )
    parser.add_argument(
        "--stratify",
        choices=("scenario_family", "is_hard_case", "window_type", "none"),
        default="scenario_family",
        help="Print per-group PR-AUC breakdown",
    )
    args = parser.parse_args()

    global_dir = Path(args.derived_root) / "global" / args.global_id
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        print(f"ERROR: {examples_path} not found", file=sys.stderr)
        return 2

    print(f"Loading {examples_path} ...", file=sys.stderr)
    rows = _read_jsonl(examples_path)
    feature_cols = _load_feature_columns(global_dir)
    print(
        f"Loaded {len(rows)} rows; {len(feature_cols)} feature columns from "
        f"triage-feature-columns.json",
        file=sys.stderr,
    )

    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_split[r.get("split", "train")].append(r)
    train_rows = by_split["train"]
    val_rows = by_split["validation"]
    test_rows = by_split["test"]
    print(
        f"Splits: train={len(train_rows)}, validation={len(val_rows)}, test={len(test_rows)}",
        file=sys.stderr,
    )

    X_train = _matrix(train_rows, feature_cols)
    X_val = _matrix(val_rows, feature_cols)
    X_test = _matrix(test_rows, feature_cols)
    y_train = _binarize(train_rows, args.binarize)
    y_val = _binarize(val_rows, args.binarize)
    y_test = _binarize(test_rows, args.binarize)

    label_counts = Counter(r["triage_label"] for r in rows)
    print(
        f"Label distribution (overall): {dict(label_counts)}",
        file=sys.stderr,
    )
    print(
        f"Positive rate ({args.binarize}): train={y_train.mean():.3f}, "
        f"val={y_val.mean():.3f}, test={y_test.mean():.3f}",
        file=sys.stderr,
    )

    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)

    requested = [m.strip() for m in args.models.split(",") if m.strip()]
    results: list[PipelineResult] = []
    for key in requested:
        if key not in MODELS:
            print(f"WARN: unknown model {key!r}, skipping", file=sys.stderr)
            continue
        display, fit_fn, needs_scaling = MODELS[key]
        Xtr, Xva, Xte = (
            (X_train_s, X_val_s, X_test_s)
            if needs_scaling
            else (X_train, X_val, X_test)
        )
        print(f"Fitting {display} ...", file=sys.stderr)
        model = fit_fn(Xtr, y_train)
        val_scores = model.predict_proba(Xva)[:, 1]
        test_scores = model.predict_proba(Xte)[:, 1]
        result = _evaluate(display, test_scores, y_test, val_scores, y_val)
        results.append(result)

    results.sort(key=lambda r: -r.pr_auc_test)

    print()
    print(f"=== Triage leaderboard ({args.binarize} borderline) ===")
    print()
    print(
        f"{'pipeline':<32} {'PR-AUC':>7} {'ROC-AUC':>8} "
        f"{'P@1%':>6} {'R@1%':>6} {'P@5%':>6} {'R@5%':>6} {'ECE':>6} {'Brier':>6}"
    )
    print("-" * 100)
    for r in results:
        print(
            f"{r.name:<32} "
            f"{r.pr_auc_test:>7.4f} {r.roc_auc_test:>8.4f} "
            f"{r.precision_at_fpr_01:>6.3f} {r.recall_at_fpr_01:>6.3f} "
            f"{r.precision_at_fpr_05:>6.3f} {r.recall_at_fpr_05:>6.3f} "
            f"{r.ece_test:>6.3f} {r.brier_test:>6.3f}"
        )

    if args.stratify != "none" and results:
        # Stratified PR-AUC for the leading pipeline only — keeps output
        # short. Re-run with --models <one> for per-pipeline breakdowns.
        leader = results[0]
        print()
        print(f"=== {leader.name} PR-AUC stratified by {args.stratify} ===")
        print()
        display_model_name, fit_fn, needs_scaling = MODELS[
            next(k for k in MODELS if MODELS[k][0] == leader.name)
        ]
        Xtr, _, Xte = (
            (X_train_s, X_val_s, X_test_s)
            if needs_scaling
            else (X_train, X_val, X_test)
        )
        model = fit_fn(Xtr, y_train)
        test_scores = model.predict_proba(Xte)[:, 1]
        strata = _stratified_pr_auc(test_rows, test_scores, y_test, args.stratify)
        print(f"{'group':<48} {'windows':>8} {'positives':>10} {'PR-AUC':>8}")
        print("-" * 78)
        for g in sorted(strata.keys()):
            n, pos, pr = strata[g]
            pr_str = f"{pr:.4f}" if pr == pr else "  n/a "  # nan check
            print(f"{g:<48} {n:>8} {pos:>10} {pr_str:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
