"""Retrieval backends.

BM25Retriever     - Okapi BM25 over tokenized memory text. Fast, no deps.
EmbeddingHashingRetriever - hashing-trick dense embeddings + cosine. Stand-in
                    for a real sentence-transformer; deterministic and stdlib.
HybridRetriever  - blends BM25 + embedding scores per docs/dataset-v4-plan.md.

All retrievers respect MemoryCorpus visibility: the visible set is recomputed
per window so time-ordering and own-run exclusion are never bypassed.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ..data.schema import JiraMemoryIssue, TriageWindow
from ..features.text import build_memory_doc_text, build_window_query_text, tokenize
from .corpus import MemoryCorpus


@dataclass
class RetrievalHit:
    issue_id: str
    issue: JiraMemoryIssue
    score: float
    rank: int


class _Retriever:
    """Shared logic: index-once on the full corpus, filter at query time."""

    def fit(self, corpus: MemoryCorpus) -> None:
        raise NotImplementedError

    def _all_scores(self, query_text: str) -> dict[str, float]:
        raise NotImplementedError

    def retrieve(
        self,
        window: TriageWindow,
        corpus: MemoryCorpus,
        *,
        top_k: int = 5,
    ) -> list[RetrievalHit]:
        visible_ids = {iss.jira_shadow_issue_id for iss in corpus.visible_to(window)}
        if not visible_ids:
            return []
        query = build_window_query_text(window)
        scores = self._all_scores(query)
        scored = [
            (issue_id, score)
            for issue_id, score in scores.items()
            if issue_id in visible_ids
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        by_id = corpus.by_id()
        hits: list[RetrievalHit] = []
        for rank, (issue_id, score) in enumerate(scored[:top_k], start=1):
            hits.append(RetrievalHit(issue_id=issue_id, issue=by_id[issue_id], score=score, rank=rank))
        return hits


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


class BM25Retriever(_Retriever):
    name = "bm25"

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.idf: dict[str, float] = {}
        self.doc_lengths: dict[str, int] = {}
        self.doc_term_counts: dict[str, Counter[str]] = {}
        self.avg_doc_length: float = 0.0

    def fit(self, corpus: MemoryCorpus) -> None:
        df: Counter[str] = Counter()
        total_len = 0
        for issue in corpus.issues:
            toks = tokenize(build_memory_doc_text(issue))
            self.doc_term_counts[issue.jira_shadow_issue_id] = Counter(toks)
            self.doc_lengths[issue.jira_shadow_issue_id] = len(toks)
            total_len += len(toks)
            for term in set(toks):
                df[term] += 1
        n_docs = max(len(corpus.issues), 1)
        self.avg_doc_length = total_len / n_docs if n_docs else 0.0
        self.idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def _all_scores(self, query_text: str) -> dict[str, float]:
        q_terms = tokenize(query_text)
        scores: dict[str, float] = {}
        for issue_id, counts in self.doc_term_counts.items():
            doc_len = self.doc_lengths[issue_id]
            denom_norm = 1 - self.b + self.b * (doc_len / max(self.avg_doc_length, 1.0))
            score = 0.0
            for term in q_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self.idf.get(term, 0.0)
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * denom_norm)
            scores[issue_id] = score
        return scores


# ---------------------------------------------------------------------------
# Hashing-trick dense embedding
# ---------------------------------------------------------------------------


def _hash_token(token: str, dim: int) -> tuple[int, int]:
    """Token -> (index, sign) using sha1; deterministic across processes."""
    h = hashlib.sha1(token.encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "little") % dim
    sign = 1 if (h[4] & 1) == 0 else -1
    return idx, sign


def _embed(tokens: Iterable[str], dim: int) -> list[float]:
    vec = [0.0] * dim
    for tok in tokens:
        idx, sign = _hash_token(tok, dim)
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class EmbeddingHashingRetriever(_Retriever):
    name = "embedding_hashing"

    def __init__(self, *, dim: int = 512) -> None:
        self.dim = dim
        self.doc_vectors: dict[str, list[float]] = {}

    def fit(self, corpus: MemoryCorpus) -> None:
        for issue in corpus.issues:
            toks = tokenize(build_memory_doc_text(issue))
            self.doc_vectors[issue.jira_shadow_issue_id] = _embed(toks, self.dim)

    def _all_scores(self, query_text: str) -> dict[str, float]:
        q = _embed(tokenize(query_text), self.dim)
        scores: dict[str, float] = {}
        for issue_id, dv in self.doc_vectors.items():
            scores[issue_id] = sum(qa * da for qa, da in zip(q, dv))
        return scores


# ---------------------------------------------------------------------------
# Hybrid
# ---------------------------------------------------------------------------


class HybridRetriever(_Retriever):
    name = "hybrid_bm25_embedding"

    def __init__(self, *, bm25_weight: float = 0.6, embedding_weight: float = 0.4, dim: int = 512) -> None:
        self.bm25 = BM25Retriever()
        self.embedding = EmbeddingHashingRetriever(dim=dim)
        self.bm25_weight = bm25_weight
        self.embedding_weight = embedding_weight

    def fit(self, corpus: MemoryCorpus) -> None:
        self.bm25.fit(corpus)
        self.embedding.fit(corpus)

    def _all_scores(self, query_text: str) -> dict[str, float]:
        b = self.bm25._all_scores(query_text)
        e = self.embedding._all_scores(query_text)
        # min-max normalize each, then blend
        def normalize(d: dict[str, float]) -> dict[str, float]:
            if not d:
                return {}
            lo = min(d.values())
            hi = max(d.values())
            span = max(hi - lo, 1e-9)
            return {k: (v - lo) / span for k, v in d.items()}

        b_n = normalize(b)
        e_n = normalize(e)
        keys = set(b_n) | set(e_n)
        return {k: self.bm25_weight * b_n.get(k, 0.0) + self.embedding_weight * e_n.get(k, 0.0) for k in keys}
