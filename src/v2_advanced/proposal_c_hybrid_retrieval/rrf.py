"""Reciprocal Rank Fusion.

Given multiple ranked lists of document IDs from different retrievers,
fuse them into one ranked list using:

    RRF_score(doc) = Σ_retriever  1 / (k + rank_of_doc_in_retriever)

Documents that don't appear in a retriever's list contribute 0 (i.e.,
that retriever stays silent for them).

References:
  - Cormack et al. (2009): "Reciprocal Rank Fusion outperforms Condorcet
    and individual Rank Learning Methods", SIGIR 2009.

The k=60 default is the value the original paper recommends. We expose
it for ablation studies.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def rrf_fuse(
    ranked_lists: dict[str, list[str]],
    *,
    k: float = 60.0,
    weights: dict[str, float] | None = None,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists.

    Args:
        ranked_lists: dict {retriever_name: [doc_id_1, doc_id_2, ...]}.
            Each list is in ranked order (best first).
        k: RRF smoothing constant. Larger k = each rank contributes less.
        weights: optional dict {retriever_name: weight}. Multiplies each
            retriever's RRF contribution. Default 1.0 per retriever.
        top_k: if set, return only the top-K fused documents.

    Returns:
        list of (doc_id, fused_score), sorted by score descending.
    """
    weights = weights or {}
    scores: dict[str, float] = defaultdict(float)
    for name, ranked in ranked_lists.items():
        w = weights.get(name, 1.0)
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] += w * (1.0 / (k + rank))
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    if top_k is not None:
        ordered = ordered[:top_k]
    return ordered


def rrf_fuse_ids(
    ranked_lists: dict[str, list[str]],
    *,
    k: float = 60.0,
    weights: dict[str, float] | None = None,
    top_k: int | None = None,
) -> list[str]:
    """Convenience wrapper that returns only the doc IDs (not the scores)."""
    return [d for d, _ in rrf_fuse(ranked_lists, k=k, weights=weights, top_k=top_k)]
