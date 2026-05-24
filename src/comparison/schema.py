"""Unified per-window prediction row.

Every PipelineRunner emits a list of PipelinePrediction. Downstream code
(stratified metrics, ensemble blending, significance tests) only ever
touches this dataclass - it never imports loganalyzer / logsense
internals. That isolation is what lets Phase 2+ swap in LLM pipelines
without touching the report code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelinePrediction:
    window_id: str
    pipeline_name: str
    # Predicted
    triage_score: float
    triage_decision: str  # ticket_worthy | noise
    is_novel: bool | None  # None when no retrieval was attempted
    matched_issue_ids: list[str] = field(default_factory=list)
    # Gold (joined from labels at predict time)
    gold_label: str = ""
    gold_is_novel: bool | None = None
    gold_matched_issue_ids: list[str] = field(default_factory=list)
    # D12.3 orphan-fault gold: True/False/None — see loganalyzer schema.
    gold_expected_in_memory: bool | None = None
    # Stratification keys
    scenario_family: str = ""
    service_name: str = ""
    window_type: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "pipeline_name": self.pipeline_name,
            "triage_score": self.triage_score,
            "triage_decision": self.triage_decision,
            "is_novel": self.is_novel,
            "matched_issue_ids": self.matched_issue_ids,
            "gold_label": self.gold_label,
            "gold_is_novel": self.gold_is_novel,
            "gold_matched_issue_ids": self.gold_matched_issue_ids,
            "gold_expected_in_memory": self.gold_expected_in_memory,
            "scenario_family": self.scenario_family,
            "service_name": self.service_name,
            "window_type": self.window_type,
        }


@dataclass
class PipelineResult:
    """All test-set predictions from one pipeline run."""

    pipeline_name: str
    predictions: list[PipelinePrediction]
    triage_threshold: float
    fit_seconds: float = 0.0
    predict_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def by_window(self) -> dict[str, PipelinePrediction]:
        return {p.window_id: p for p in self.predictions}
