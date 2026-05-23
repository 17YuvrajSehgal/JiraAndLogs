"""SmartLogAnalyzer - the company-facing entrypoint.

For a given telemetry window it answers all three product questions in one
call:

    1. is this worth a Jira ticket?       -> triage_score / triage_decision
    2. which past issues does it match?   -> matched_issues
    3. is this a novel incident?          -> is_novel

The class is intentionally model-agnostic: pass any TriageModel + any
retriever conforming to the .retrieve(window, corpus, top_k=...) contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..data.schema import JiraMemoryIssue, TriageWindow
from ..memory.corpus import MemoryCorpus
from ..memory.retrieval import RetrievalHit
from ..triage.base import TriageModel


class Retriever(Protocol):
    def fit(self, corpus: MemoryCorpus) -> None: ...
    def retrieve(self, window: TriageWindow, corpus: MemoryCorpus, *, top_k: int = 5) -> list[RetrievalHit]: ...


@dataclass
class AnalysisResult:
    window_id: str
    triage_score: float
    triage_decision: str  # ticket_worthy | noise
    is_novel: bool
    matched_issues: list[RetrievalHit] = field(default_factory=list)
    citation_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "triage_score": self.triage_score,
            "triage_decision": self.triage_decision,
            "is_novel": self.is_novel,
            "matched_issues": [
                {
                    "rank": hit.rank,
                    "issue_id": hit.issue_id,
                    "jira_issue_key": hit.issue.jira_issue_key,
                    "score": hit.score,
                    "scenario_family": hit.issue.scenario_family,
                    "affected_service": hit.issue.affected_service,
                    "memory_text_preview": hit.issue.memory_text[:240],
                    "resolution_notes": hit.issue.resolution_notes,
                }
                for hit in self.matched_issues
            ],
            "citation_summary": self.citation_summary,
        }


class SmartLogAnalyzer:
    """Triage + retrieval pipeline, ready to .fit on a training set and
    .analyze a window in production."""

    def __init__(
        self,
        triage_model: TriageModel,
        retriever: Retriever,
        memory_corpus: MemoryCorpus,
        *,
        triage_threshold: float = 0.5,
        retrieval_top_k: int = 5,
        novelty_min_score: float = 0.15,
    ) -> None:
        self.triage_model = triage_model
        self.retriever = retriever
        self.memory_corpus = memory_corpus
        self.triage_threshold = triage_threshold
        self.retrieval_top_k = retrieval_top_k
        self.novelty_min_score = novelty_min_score
        self._fit_done = False

    def fit(self, training_windows: list[TriageWindow]) -> None:
        """Fit the triage model on training windows and index the corpus."""
        self.triage_model.fit(training_windows)
        self.retriever.fit(self.memory_corpus)
        self._fit_done = True

    def analyze(self, window: TriageWindow) -> AnalysisResult:
        if not self._fit_done:
            raise RuntimeError("SmartLogAnalyzer.fit must be called before analyze")

        score = self.triage_model.predict_score(window)
        decision = "ticket_worthy" if score >= self.triage_threshold else "noise"

        hits: list[RetrievalHit] = []
        if decision == "ticket_worthy":
            hits = self.retriever.retrieve(window, self.memory_corpus, top_k=self.retrieval_top_k)

        is_novel = decision == "ticket_worthy" and (
            not hits or hits[0].score < self.novelty_min_score
        )

        citation = _short_citation(hits, is_novel=is_novel, decision=decision)
        return AnalysisResult(
            window_id=window.window_id,
            triage_score=score,
            triage_decision=decision,
            is_novel=is_novel,
            matched_issues=hits,
            citation_summary=citation,
        )

    def analyze_batch(self, windows: list[TriageWindow]) -> list[AnalysisResult]:
        return [self.analyze(w) for w in windows]


def _short_citation(hits: list[RetrievalHit], *, is_novel: bool, decision: str) -> str:
    if decision == "noise":
        return "No ticket suggested - window scored below triage threshold."
    if is_novel:
        return "Likely novel incident. No close match in Jira memory."
    top = hits[0]
    return (
        f"Likely matches {top.issue.jira_issue_key} "
        f"({top.issue.scenario_family} / {top.issue.affected_service}). "
        f"Resolution notes: {top.issue.resolution_notes[:140]}"
    )
