"""Triage classification metrics.

These match the contract in docs/triage-task-contract.md so the new ML
system's headline numbers compare apples-to-apples with the existing
scripts/research-lab/run_triage_benchmark.py output.
"""

from __future__ import annotations


def _pairs(scores: list[float], labels: list[int]) -> list[tuple[float, int]]:
    return sorted(zip(scores, labels), key=lambda x: -x[0])


def pr_auc(scores: list[float], labels: list[int]) -> float:
    """Average precision (area under the precision/recall curve)."""
    n_pos = sum(labels)
    if n_pos == 0 or len(scores) != len(labels):
        return 0.0
    tp = 0
    fp = 0
    last_recall = 0.0
    ap = 0.0
    pairs = _pairs(scores, labels)
    n = len(pairs)
    i = 0
    while i < n:
        # Consume the whole tied-score group together so within-group label
        # order can't inflate precision (a constant classifier must score AP =
        # base rate, not 1.0).
        j = i
        while j < n and pairs[j][0] == pairs[i][0]:
            if pairs[j][1] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        precision = tp / (tp + fp)
        recall = tp / n_pos
        ap += precision * (recall - last_recall)
        last_recall = recall
        i = j
    return ap


def roc_auc(scores: list[float], labels: list[int]) -> float:
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.0
    pos_ranks = 0.0
    items = sorted(zip(scores, labels), key=lambda x: x[0])
    cumulative_rank = 0.0
    i = 0
    n = len(items)
    while i < n:
        j = i
        while j < n and items[j][0] == items[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            cumulative_rank += 1
            if items[k][1] == 1:
                pos_ranks += avg_rank
        i = j
    return (pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def precision_at_fpr(scores: list[float], labels: list[int], target_fpr: float) -> tuple[float, float, float]:
    """Returns (precision, recall, threshold) at the largest threshold whose FPR <= target_fpr."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.0, 0.0, 1.0
    items = _pairs(scores, labels)
    tp = 0
    fp = 0
    best = (0.0, 0.0, 1.0)
    for score, lab in items:
        if lab == 1:
            tp += 1
        else:
            fp += 1
        fpr = fp / n_neg
        if fpr <= target_fpr:
            precision = tp / max(tp + fp, 1)
            recall = tp / n_pos
            best = (precision, recall, score)
    return best


def expected_calibration_error(scores: list[float], labels: list[int], n_bins: int = 10) -> float:
    if not scores:
        return 0.0
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for score, lab in zip(scores, labels):
        idx = min(int(score * n_bins), n_bins - 1)
        bins[idx].append((score, lab))
    ece = 0.0
    n = len(scores)
    for bucket in bins:
        if not bucket:
            continue
        avg_conf = sum(s for s, _ in bucket) / len(bucket)
        avg_acc = sum(l for _, l in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_conf - avg_acc)
    return ece


def f_beta(precision: float, recall: float, beta: float = 2.0) -> float:
    if precision + recall == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall)
