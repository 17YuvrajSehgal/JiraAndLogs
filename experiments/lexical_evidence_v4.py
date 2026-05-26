#!/usr/bin/env python3
"""Lexical-only and hybrid lexical+numeric baselines over triage_evidence_text.

Two pipelines:

  1. tfidf_text_only          — TF-IDF over triage_evidence_text + logistic
  2. tfidf_text_plus_numeric  — concat[TF-IDF, scaled numeric features] + logistic

The point of this experiment is to measure how much signal the evidence text
carries on its OWN (the v4 dataset has fairly thin evidence text — mostly
trace/log aggregates), and whether mixing text with the numeric features
beats either alone.

Why this matters for v5: v5's M0–M5 telemetry adds L1 per-RPC logs, L2
dep-error logs, and L3 business events. The evidence text from those windows
will be dramatically richer (more error classes, more peer-service tokens,
more business-event vocabulary). Whatever lift TF-IDF gives on v4 evidence
text should grow substantially on v5.

Compare these numbers against the numeric-only leaderboard from baseline_v4.py.

Usage:

    python experiments/lexical_evidence_v4.py
    python experiments/lexical_evidence_v4.py --binarize inclusive
    python experiments/lexical_evidence_v4.py --global-id <other-corpus>

Expected runtime: ~10 seconds.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parent.parent
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
    return list(contract["feature_columns"])


def _binarize(rows: list[dict[str, Any]], mode: str) -> np.ndarray:
    if mode == "strict":
        return np.asarray(
            [1 if r["triage_label"] == "ticket_worthy" else 0 for r in rows],
            dtype=np.int64,
        )
    return np.asarray(
        [1 if r["triage_label"] in {"ticket_worthy", "borderline"} else 0 for r in rows],
        dtype=np.int64,
    )


def _numeric(rows: list[dict[str, Any]], cols: list[str]) -> np.ndarray:
    return np.asarray(
        [[float(r.get(c, 0.0) or 0.0) for c in cols] for r in rows],
        dtype=np.float64,
    )


# The build pipeline currently embeds lab-only identifiers in
# triage_evidence_text — both as individual tokens (active_fault,
# pre_fault_baseline, ...) AND as substrings of the WINDOW header line
# (`WINDOW window_id=<full-dataset-run-id>-<scenario>-<timestamp>-<window_type>-<service> ...`).
# A real production deployment would NOT know any of these at inference
# time — the dataset name, scenario id, window_type, and per-run timestamp
# are lab-only constructs. Leaving them in gives TF-IDF the answer for free.
#
# We strip in two layers:
#   1. Drop the entire "WINDOW window_id=..." header line.
#   2. Replace remaining lab-only token substrings with WTYPE.
#
# This is also a v4/v5 data-builder bug — `triage_evidence_text` should not
# include any of these fields. Flagged for the v5.1 dataset rebuild.
_LEAKAGE_TOKENS = (
    "active_fault",
    "pre_fault_baseline",
    "recovery_window",
    "observation_window",
)


def _redact_leakage(text: str) -> str:
    # Drop the WINDOW header line entirely — it carries window_id + service +
    # start/end timestamps, all lab-only metadata.
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith("WINDOW ")
    ]
    out = "\n".join(lines)
    for tok in _LEAKAGE_TOKENS:
        out = out.replace(tok, "WTYPE")
    return out


def _text(rows: list[dict[str, Any]], redact: bool = True) -> list[str]:
    raw = [r.get("triage_evidence_text", "") or "" for r in rows]
    if redact:
        return [_redact_leakage(t) for t in raw]
    return raw


def _threshold_at_fpr(
    scores: np.ndarray, labels: np.ndarray, target_fpr: float
) -> float:
    order = np.argsort(-scores)
    s = scores[order]
    y = labels[order]
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float(s[0]) + 1e-9
    tp = fp = 0
    best = float(s[0]) + 1e-9
    feasible = False
    for score, label in zip(s, y):
        if label == 1:
            tp += 1
        else:
            fp += 1
        if fp / n_neg <= target_fpr:
            best = float(score)
            feasible = True
        else:
            if not feasible:
                best = float(score) + 1e-9
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
        total += (k / n) * abs(scores[mask].mean() - labels[mask].mean())
    return total


@dataclass
class Result:
    name: str
    pr_auc_test: float
    roc_auc_test: float
    precision_at_fpr_01: float
    recall_at_fpr_01: float
    precision_at_fpr_05: float
    recall_at_fpr_05: float
    ece_test: float
    brier_test: float
    n_features: int


def _evaluate(
    name: str,
    test_scores: np.ndarray,
    test_labels: np.ndarray,
    val_scores: np.ndarray,
    val_labels: np.ndarray,
    n_features: int,
) -> Result:
    t_01 = _threshold_at_fpr(val_scores, val_labels, 0.01)
    t_05 = _threshold_at_fpr(val_scores, val_labels, 0.05)
    pred_01 = (test_scores >= t_01).astype(np.int64)
    pred_05 = (test_scores >= t_05).astype(np.int64)

    def _pr(pred: np.ndarray) -> tuple[float, float]:
        tp = int(((pred == 1) & (test_labels == 1)).sum())
        fp = int(((pred == 1) & (test_labels == 0)).sum())
        fn = int(((pred == 0) & (test_labels == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        return prec, rec

    p01, r01 = _pr(pred_01)
    p05, r05 = _pr(pred_05)
    return Result(
        name=name,
        pr_auc_test=float(average_precision_score(test_labels, test_scores))
        if test_labels.sum() > 0
        else 0.0,
        roc_auc_test=float(roc_auc_score(test_labels, test_scores))
        if 0 < test_labels.sum() < len(test_labels)
        else 0.0,
        precision_at_fpr_01=p01,
        recall_at_fpr_01=r01,
        precision_at_fpr_05=p05,
        recall_at_fpr_05=r05,
        ece_test=_expected_calibration_error(test_scores, test_labels),
        brier_test=float(brier_score_loss(test_labels, test_scores))
        if 0 < test_labels.sum() < len(test_labels)
        else 0.0,
        n_features=n_features,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-id", default=DEFAULT_GLOBAL_ID)
    parser.add_argument("--derived-root", default=str(REPO_ROOT / "data" / "derived"))
    parser.add_argument(
        "--binarize", choices=("strict", "inclusive"), default="strict"
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=20000,
        help="TfidfVectorizer max_features cap",
    )
    parser.add_argument(
        "--ngram-max",
        type=int,
        default=2,
        help="Use 1..ngram-max word ngrams",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help=(
            "Disable redaction of lab-only window_type tokens "
            "(active_fault, pre_fault_baseline, recovery_window, "
            "observation_window). Use ONLY to demonstrate the leak; "
            "production-realistic measurement requires redaction."
        ),
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

    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_split[r.get("split", "train")].append(r)
    train_rows = by_split["train"]
    val_rows = by_split["validation"]
    test_rows = by_split["test"]
    print(
        f"Splits: train={len(train_rows)}, val={len(val_rows)}, test={len(test_rows)}",
        file=sys.stderr,
    )

    y_train = _binarize(train_rows, args.binarize)
    y_val = _binarize(val_rows, args.binarize)
    y_test = _binarize(test_rows, args.binarize)

    redact = not args.no_redact
    train_text = _text(train_rows, redact=redact)
    val_text = _text(val_rows, redact=redact)
    test_text = _text(test_rows, redact=redact)
    print(
        f"Evidence-text redaction: "
        f"{'ON (lab-only window_type tokens stripped)' if redact else 'OFF (LEAKY — for demonstration only)'}",
        file=sys.stderr,
    )

    print(
        f"Avg evidence_text length: train={np.mean([len(t) for t in train_text]):.0f}, "
        f"val={np.mean([len(t) for t in val_text]):.0f}, "
        f"test={np.mean([len(t) for t in test_text]):.0f}",
        file=sys.stderr,
    )

    print(
        f"Fitting TF-IDF (max_features={args.max_features}, ngrams=1..{args.ngram_max}) ...",
        file=sys.stderr,
    )
    vec = TfidfVectorizer(
        max_features=args.max_features,
        ngram_range=(1, args.ngram_max),
        sublinear_tf=True,
        min_df=2,
        max_df=0.95,
    ).fit(train_text)
    Xt_train = vec.transform(train_text)
    Xt_val = vec.transform(val_text)
    Xt_test = vec.transform(test_text)
    print(
        f"  vocab size: {len(vec.vocabulary_)}; train shape: {Xt_train.shape}",
        file=sys.stderr,
    )

    # Pipeline 1: text-only logistic
    print("Fitting tfidf_text_only logistic ...", file=sys.stderr)
    m_text = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=2000,
        solver="liblinear",
    ).fit(Xt_train, y_train)
    val_scores_text = m_text.predict_proba(Xt_val)[:, 1]
    test_scores_text = m_text.predict_proba(Xt_test)[:, 1]
    r_text = _evaluate(
        "tfidf_text_only",
        test_scores_text,
        y_test,
        val_scores_text,
        y_val,
        n_features=Xt_train.shape[1],
    )

    # Pipeline 2: text + numeric concatenated
    print("Fitting tfidf_text_plus_numeric logistic ...", file=sys.stderr)
    Xn_train = _numeric(train_rows, feature_cols)
    Xn_val = _numeric(val_rows, feature_cols)
    Xn_test = _numeric(test_rows, feature_cols)
    scaler = StandardScaler().fit(Xn_train)
    Xn_train_s = csr_matrix(scaler.transform(Xn_train))
    Xn_val_s = csr_matrix(scaler.transform(Xn_val))
    Xn_test_s = csr_matrix(scaler.transform(Xn_test))
    X_combo_train = hstack([Xt_train, Xn_train_s]).tocsr()
    X_combo_val = hstack([Xt_val, Xn_val_s]).tocsr()
    X_combo_test = hstack([Xt_test, Xn_test_s]).tocsr()
    m_combo = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=2000,
        solver="liblinear",
    ).fit(X_combo_train, y_train)
    val_scores_combo = m_combo.predict_proba(X_combo_val)[:, 1]
    test_scores_combo = m_combo.predict_proba(X_combo_test)[:, 1]
    r_combo = _evaluate(
        "tfidf_text_plus_numeric",
        test_scores_combo,
        y_test,
        val_scores_combo,
        y_val,
        n_features=X_combo_train.shape[1],
    )

    results = sorted([r_text, r_combo], key=lambda r: -r.pr_auc_test)

    print()
    print(f"=== Lexical leaderboard ({args.binarize} borderline) ===")
    print(
        f"v4-large baseline: HGB numeric-only PR-AUC ~0.72 / ROC-AUC ~0.95 (see baseline_v4.py)"
    )
    print()
    print(
        f"{'pipeline':<28} {'features':>9} {'PR-AUC':>7} {'ROC-AUC':>8} "
        f"{'P@1%':>6} {'R@1%':>6} {'P@5%':>6} {'R@5%':>6} {'ECE':>6} {'Brier':>6}"
    )
    print("-" * 105)
    for r in results:
        print(
            f"{r.name:<28} {r.n_features:>9} "
            f"{r.pr_auc_test:>7.4f} {r.roc_auc_test:>8.4f} "
            f"{r.precision_at_fpr_01:>6.3f} {r.recall_at_fpr_01:>6.3f} "
            f"{r.precision_at_fpr_05:>6.3f} {r.recall_at_fpr_05:>6.3f} "
            f"{r.ece_test:>6.3f} {r.brier_test:>6.3f}"
        )

    # Show top text features that the text-only model learned (high positive
    # log-odds = "ticket_worthy"). Helps sanity-check that the model is
    # picking up real fault terms, not labels.
    coef = m_text.coef_.ravel()
    vocab = vec.get_feature_names_out()
    top_positive = np.argsort(coef)[-15:][::-1]
    top_negative = np.argsort(coef)[:15]
    print()
    print("=== top tfidf_text_only features (positive = ticket_worthy) ===")
    for idx in top_positive:
        print(f"  +{coef[idx]:+.3f}  {vocab[idx]!r}")
    print("=== top tfidf_text_only features (negative = noise) ===")
    for idx in top_negative:
        print(f"  {coef[idx]:+.3f}  {vocab[idx]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
