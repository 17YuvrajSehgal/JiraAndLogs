"""Window-aware BM25 retriever over the Jira memory corpus.

Wraps the raw scorer in `comparison.retrievers.BM25Retriever` so callers
can fit once against the full corpus and retrieve per-window with the
visibility filter (`MemoryCorpus.visible_to`) applied at query time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.schema import JiraMemoryIssue, TriageWindow
from .corpus import MemoryCorpus


@dataclass
class Hit:
    issue_id: str
    issue: JiraMemoryIssue
    score: float


class BM25Retriever:
    """Window-aware BM25 over `MemoryCorpus`.

    Usage:
        bm25 = BM25Retriever()
        bm25.fit(corpus)
        hits = bm25.retrieve(window, corpus, top_k=20)
        for h in hits: ...  # h.issue_id, h.issue, h.score
    """

    def __init__(self) -> None:
        self._fitted = False
        self._issues: list[JiraMemoryIssue] = []
        self._scorer = None

    def fit(self, corpus: MemoryCorpus) -> "BM25Retriever":
        from comparison.retrievers import BM25Retriever as _RawBM25, tokenize

        self._issues = list(corpus.issues)
        docs = [tokenize(iss.memory_text or "") for iss in self._issues]
        self._scorer = _RawBM25(docs)
        self._fitted = True
        return self

    def retrieve(
        self,
        window: TriageWindow,
        corpus: MemoryCorpus,
        *,
        top_k: int = 20,
    ) -> list[Hit]:
        if not self._fitted:
            raise RuntimeError("BM25Retriever.retrieve called before fit()")
        from comparison.retrievers import tokenize

        query = tokenize(window.evidence_text or "")
        visible_ids = {
            iss.jira_shadow_issue_id for iss in corpus.visible_to(window)
        }
        # Score all docs then filter by visibility. Memory corpus is small
        # (a few hundred docs) so this is cheap.
        candidates = self._scorer.topk(query, k=len(self._issues))
        hits: list[Hit] = []
        for idx, score in candidates:
            iss = self._issues[idx]
            if iss.jira_shadow_issue_id not in visible_ids:
                continue
            hits.append(
                Hit(
                    issue_id=iss.jira_shadow_issue_id,
                    issue=iss,
                    score=float(score),
                )
            )
            if len(hits) >= top_k:
                break
        return hits
