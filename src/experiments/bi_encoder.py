#!/usr/bin/env python3
"""Neural bi-encoder pipeline — Phase 4 of the ML dev plan.

Embeds each window's `triage_evidence_text` via sentence-transformers
(`all-MiniLM-L6-v2`, 384-dim, small + fast) and trains a logistic regression
over the embedding alone, then over (embedding + numeric) concatenation.

Why this matters:
  TF-IDF over evidence text plateaued at PR-AUC ~0.30 on v5-quick (after
  redaction). The text has new L2 `dep_error` content but TF-IDF can't tell
  that "dep_error during cart-redis" semantically resembles "Redis Connection
  Timeout" — they share no surface tokens. A bi-encoder embedding captures
  that semantic similarity in vector space, so the same model architecture
  should pick up signal TF-IDF cannot.

Production-realism: the WINDOW header line is DROPPED before embedding —
that's where the lab-only `window_id`/`scenario_id`/`window_type` substring
leaks live. See `experiments/lexical_evidence_v4.py` and §7 of
`docs/results-v5-quick.md`.

Usage:
    python experiments/bi_encoder_v5.py
    python experiments/bi_encoder_v5.py --global-id 2026-05-25-dataset-v5-quick-m05v2
    python experiments/bi_encoder_v5.py --model intfloat/e5-small-v2 --binarize inclusive

Expected runtime: ~1-3 min for embedding 1,020 windows on CPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # src/experiments/X.py -> repo root
DEFAULT_GLOBAL_ID = "2026-05-25-dataset-v5-quick-m05v2"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Make `from util.device import ...` work no matter where this script is invoked
# from. We're already living under src/, so this just resolves to it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from util.device import resolve_device, safe_batch_size  # noqa: E402


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


def _strip_window_header(text: str) -> str:
    """Drop the leaky WINDOW header line — see lexical_evidence_v4.py."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("WINDOW "))


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


def _ece(scores: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
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
    n_features: int
    pr_auc_test: float
    roc_auc_test: float
    precision_at_fpr_01: float
    recall_at_fpr_01: float
    precision_at_fpr_05: float
    recall_at_fpr_05: float
    ece_test: float
    brier_test: float


def _evaluate(
    name: str,
    n_features: int,
    test_scores: np.ndarray,
    test_labels: np.ndarray,
    val_scores: np.ndarray,
    val_labels: np.ndarray,
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
        n_features=n_features,
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
        ece_test=_ece(test_scores, test_labels),
        brier_test=float(brier_score_loss(test_labels, test_scores))
        if 0 < test_labels.sum() < len(test_labels)
        else 0.0,
    )


def _stratified_pr_auc(
    rows: list[dict[str, Any]],
    scores: np.ndarray,
    labels: np.ndarray,
    key: str,
) -> dict[str, tuple[int, int, float]]:
    groups: dict[Any, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r.get(key)].append(i)
    out: dict[str, tuple[int, int, float]] = {}
    for g, idxs in groups.items():
        gl = labels[idxs]
        gs = scores[idxs]
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-id", default=DEFAULT_GLOBAL_ID)
    parser.add_argument("--derived-root", default=str(REPO_ROOT / "data" / "derived"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--binarize", choices=("strict", "inclusive"), default="strict"
    )
    parser.add_argument(
        "--max-len",
        type=int,
        default=512,
        help="Max input chars before sentence-transformers truncates",
    )
    parser.add_argument(
        "--cache-embeddings",
        action="store_true",
        help="Save / reuse a .npz cache of the embeddings (lets you swap models without recompute)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Where to run the encoder. 'auto' (default) picks GPU when usable.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Override the auto-picked encoder batch size. 0 = auto from device.",
    )
    args = parser.parse_args()

    device = resolve_device(prefer=None if args.device == "auto" else args.device)
    # MiniLM-512tok ~ 150KB activations/item; cross-encoders ~ 1MB. Pick conservatively.
    batch_size = args.batch_size or safe_batch_size(
        bytes_per_item=200_000, default_cpu=64, default_gpu=256
    )
    print(f"[bi_encoder] device={device} batch_size={batch_size}", file=sys.stderr)

    global_dir = Path(args.derived_root) / "global" / args.global_id
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        print(f"ERROR: {examples_path} not found", file=sys.stderr)
        return 2

    print(f"Loading {examples_path}", file=sys.stderr)
    rows = _read_jsonl(examples_path)
    feature_cols = _load_feature_columns(global_dir)
    print(
        f"Loaded {len(rows)} rows; {len(feature_cols)} numeric features",
        file=sys.stderr,
    )

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

    texts = [
        _strip_window_header(r.get("triage_evidence_text") or "")[: args.max_len]
        for r in rows
    ]
    avg_len = sum(len(t) for t in texts) / max(len(texts), 1)
    print(f"Avg evidence text length (post-redaction): {avg_len:.0f} chars", file=sys.stderr)

    cache_path = global_dir / f"_bi_encoder_cache_{args.model.replace('/', '_')}.npz"
    embeddings: np.ndarray | None = None
    if args.cache_embeddings and cache_path.exists():
        cache = np.load(str(cache_path))
        if cache["n"] == len(rows) and cache["max_len"] == args.max_len:
            embeddings = cache["emb"]
            print(f"Loaded {embeddings.shape} embeddings from cache", file=sys.stderr)

    if embeddings is None:
        print(f"Loading model {args.model}", file=sys.stderr)
        t0 = time.time()
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(args.model, device=device)
        print(f"  loaded in {time.time() - t0:.1f}s on {device}", file=sys.stderr)
        t0 = time.time()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            device=device,
        )
        print(
            f"Embedded {len(texts)} windows -> shape {embeddings.shape} in {time.time() - t0:.1f}s on {device}",
            file=sys.stderr,
        )
        if args.cache_embeddings:
            np.savez(str(cache_path), emb=embeddings, n=len(rows), max_len=args.max_len)
            print(f"Cached embeddings at {cache_path}", file=sys.stderr)

    # Slice embeddings by split (positional — same order as rows iter)
    n_train = len(train_rows)
    n_val = len(val_rows)
    n_test = len(test_rows)
    # rows order: train + val + test? NO — we read all 1020 from the global
    # file in whatever order they were written, then split via by_split. So
    # the embeddings array is in the original row order, not grouped by
    # split. Build index lists.
    indices_by_split: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        indices_by_split[r.get("split", "train")].append(i)
    train_idx = indices_by_split["train"]
    val_idx = indices_by_split["validation"]
    test_idx = indices_by_split["test"]
    E_train = embeddings[train_idx]
    E_val = embeddings[val_idx]
    E_test = embeddings[test_idx]
    print(
        f"Embedding slices: train={E_train.shape}, val={E_val.shape}, test={E_test.shape}",
        file=sys.stderr,
    )

    y_train = _binarize(train_rows, args.binarize)
    y_val = _binarize(val_rows, args.binarize)
    y_test = _binarize(test_rows, args.binarize)

    results: list[Result] = []

    # Pipeline 1: embedding-only logistic
    print("Fitting embedding-only logistic", file=sys.stderr)
    m_emb = LogisticRegression(
        C=1.0, class_weight="balanced", max_iter=2000, solver="lbfgs"
    ).fit(E_train, y_train)
    val_emb_scores = m_emb.predict_proba(E_val)[:, 1]
    test_emb_scores = m_emb.predict_proba(E_test)[:, 1]
    results.append(
        _evaluate(
            "bi_encoder_text_only",
            E_train.shape[1],
            test_emb_scores,
            y_test,
            val_emb_scores,
            y_val,
        )
    )

    # Pipeline 2: embedding + numeric concat
    print("Fitting embedding + numeric logistic", file=sys.stderr)
    Xn_train = _numeric(train_rows, feature_cols)
    Xn_val = _numeric(val_rows, feature_cols)
    Xn_test = _numeric(test_rows, feature_cols)
    scaler = StandardScaler().fit(Xn_train)
    Xn_train_s = scaler.transform(Xn_train)
    Xn_val_s = scaler.transform(Xn_val)
    Xn_test_s = scaler.transform(Xn_test)
    X_combo_train = np.hstack([E_train, Xn_train_s])
    X_combo_val = np.hstack([E_val, Xn_val_s])
    X_combo_test = np.hstack([E_test, Xn_test_s])
    m_combo = LogisticRegression(
        C=1.0, class_weight="balanced", max_iter=2000, solver="lbfgs"
    ).fit(X_combo_train, y_train)
    val_combo_scores = m_combo.predict_proba(X_combo_val)[:, 1]
    test_combo_scores = m_combo.predict_proba(X_combo_test)[:, 1]
    results.append(
        _evaluate(
            "bi_encoder_plus_numeric",
            X_combo_train.shape[1],
            test_combo_scores,
            y_test,
            val_combo_scores,
            y_val,
        )
    )

    # Pipeline 3: numeric-only baseline (HGB) for comparison
    print("Fitting numeric-only HGB baseline", file=sys.stderr)
    from sklearn.ensemble import HistGradientBoostingClassifier

    m_hgb = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        max_depth=8,
        l2_regularization=0.1,
        class_weight="balanced",
        random_state=42,
    ).fit(Xn_train, y_train)
    val_hgb_scores = m_hgb.predict_proba(Xn_val)[:, 1]
    test_hgb_scores = m_hgb.predict_proba(Xn_test)[:, 1]
    results.append(
        _evaluate(
            "hgb_numeric_only",
            Xn_train.shape[1],
            test_hgb_scores,
            y_test,
            val_hgb_scores,
            y_val,
        )
    )

    results.sort(key=lambda r: -r.pr_auc_test)

    print()
    print(f"=== Bi-encoder leaderboard on {args.global_id} ({args.binarize}) ===")
    print(f"Model: {args.model}")
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

    # Stratified by family for the leading pipeline
    leader = results[0]
    print()
    print(f"=== {leader.name} PR-AUC by scenario_family ===")
    if leader.name == "bi_encoder_text_only":
        leader_scores = test_emb_scores
    elif leader.name == "bi_encoder_plus_numeric":
        leader_scores = test_combo_scores
    else:
        leader_scores = test_hgb_scores
    strata = _stratified_pr_auc(test_rows, leader_scores, y_test, "scenario_family")
    print(f"{'family':<48} {'windows':>8} {'positives':>10} {'PR-AUC':>8}")
    print("-" * 78)
    for g in sorted(strata.keys()):
        n, pos, pr = strata[g]
        pr_str = f"{pr:.4f}" if pr == pr else "  n/a "
        print(f"{g:<48} {n:>8} {pos:>10} {pr_str:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
