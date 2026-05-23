"""Memory retrieval + novelty metrics."""

from __future__ import annotations


def recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """recall@k for a single window. Gold is the matched_memory_issue_ids set."""
    if not gold_ids:
        return 0.0  # undefined; novelty windows are handled separately
    top = set(retrieved_ids[:k])
    hits = sum(1 for g in gold_ids if g in top)
    return hits / len(gold_ids)


def mean_reciprocal_rank(retrieved_ids: list[str], gold_ids: list[str]) -> float:
    if not gold_ids:
        return 0.0
    gold = set(gold_ids)
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in gold:
            return 1.0 / i
    return 0.0


def novelty_f1(predicted_novel: list[bool], gold_novel: list[bool]) -> dict[str, float]:
    """F1 for the binary novelty flag.

    Only computed over windows where the triage decision was ticket_worthy in
    BOTH the prediction and gold standard; the caller filters before calling.
    """
    tp = fp = fn = tn = 0
    for p, g in zip(predicted_novel, gold_novel):
        if p and g:
            tp += 1
        elif p and not g:
            fp += 1
        elif not p and g:
            fn += 1
        else:
            tn += 1
    if tp + fp + fn == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "n": 0}
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "n": tp + fp + fn + tn}
