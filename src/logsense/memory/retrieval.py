"""BM25 retrieval where the query is the window's anomalous-template list
and the documents are Jira memory_text fields tokenized the same way.

We deliberately reuse loganalyzer.memory.corpus.MemoryCorpus for the time-
ordered visibility logic - that's the contract from
docs/dataset-v4-plan.md and it has nothing to do with whether the signal
came from logs or traces.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from loganalyzer.data.schema import JiraMemoryIssue, TriageWindow
from loganalyzer.memory.corpus import MemoryCorpus

from ..data.schema import WindowLogs
from ..templates.fingerprint import AnomalousTemplate
from ..templates.miner import mask_line


def _tokenize(text: str) -> list[str]:
    """Same dumb tokenizer as loganalyzer.features.text; lowercase
    alphanumeric, drop <2 char tokens. Operates on template strings, so
    masks like <UUID> survive as 'uuid'."""
    if not text:
        return []
    out: list[str] = []
    buf: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            buf.append(ch)
        else:
            if len(buf) >= 2:
                out.append("".join(buf))
            buf.clear()
    if len(buf) >= 2:
        out.append("".join(buf))
    return out


@dataclass
class LogRetrievalHit:
    issue_id: str
    issue: JiraMemoryIssue
    score: float
    rank: int


class LogTemplateBM25Retriever:
    """Okapi BM25 over Jira memory_text + the window's anomalous templates."""

    name = "log_template_bm25"

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tokens: dict[str, Counter[str]] = {}
        self.doc_lengths: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.avg_doc_length: float = 0.0

    def fit(self, corpus: MemoryCorpus) -> None:
        df: Counter[str] = Counter()
        total_len = 0
        for issue in corpus.issues:
            tokens = _tokenize(issue.memory_text)
            self.doc_tokens[issue.jira_shadow_issue_id] = Counter(tokens)
            self.doc_lengths[issue.jira_shadow_issue_id] = len(tokens)
            total_len += len(tokens)
            for t in set(tokens):
                df[t] += 1
        n_docs = max(len(corpus.issues), 1)
        self.avg_doc_length = total_len / n_docs if n_docs else 0.0
        self.idf = {
            t: math.log(1 + (n_docs - f + 0.5) / (f + 0.5))
            for t, f in df.items()
        }

    def _query_tokens(
        self,
        window: WindowLogs,
        anomalies: list[AnomalousTemplate],
    ) -> list[str]:
        # Anomalous templates first - those carry the rare, discriminating
        # tokens. Then a small budget of the highest-frequency in-window
        # templates as additional anchors.
        seen: list[str] = []
        for a in anomalies:
            seen.extend(_tokenize(a.template))
            seen.extend(_tokenize(a.example_body))
        # Pull a few extra in-window templates (top 10 by count)
        counts: Counter[str] = Counter()
        for ln in window.lines:
            tmpl = mask_line(ln.body)
            if tmpl:
                counts[tmpl] += 1
        for tmpl, _ in counts.most_common(10):
            seen.extend(_tokenize(tmpl))
        # Sprinkle service / window_type so service-specific Jira issues rank
        seen.append(window.service_name.lower())
        return seen

    def retrieve(
        self,
        window: WindowLogs,
        corpus: MemoryCorpus,
        anomalies: list[AnomalousTemplate],
        *,
        top_k: int = 5,
        as_triage_window: TriageWindow | None = None,
    ) -> list[LogRetrievalHit]:
        if as_triage_window is None:
            visible = list(corpus.issues)
        else:
            visible = corpus.visible_to(as_triage_window)
        visible_ids = {iss.jira_shadow_issue_id for iss in visible}
        if not visible_ids:
            return []
        q_tokens = self._query_tokens(window, anomalies)
        if not q_tokens:
            return []
        scores: dict[str, float] = {}
        for issue_id, counts in self.doc_tokens.items():
            if issue_id not in visible_ids:
                continue
            doc_len = self.doc_lengths[issue_id]
            denom_norm = 1 - self.b + self.b * (doc_len / max(self.avg_doc_length, 1.0))
            s = 0.0
            for term in q_tokens:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                s += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / (tf + self.k1 * denom_norm)
            scores[issue_id] = s
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        by_id = corpus.by_id()
        return [
            LogRetrievalHit(issue_id=issue_id, issue=by_id[issue_id], score=score, rank=rank)
            for rank, (issue_id, score) in enumerate(ranked[:top_k], start=1)
        ]
