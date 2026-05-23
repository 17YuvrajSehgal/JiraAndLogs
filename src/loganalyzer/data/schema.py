"""Strongly-typed views over the v4 global dataset rows.

The on-disk format is JSONL with all the fields documented in
docs/dataset-v4-plan.md. These dataclasses are thin wrappers that let
downstream layers type-check what they touch instead of stringly-typed dicts.

We never copy the raw row's numeric features into the dataclass; we keep the
underlying dict in `raw` so the feature extractor can read whatever the
schema decides is "production-safe" at build time. That keeps this layer
stable across feature-column changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriageWindow:
    """One row from global-triage-examples.jsonl.

    Holds the eval-only labels plus a pointer to the original feature dict.
    The Jira-as-memory ground truth (`matched_memory_issue_ids`, `is_novel`)
    is joined in from window-memory-matchings.jsonl when present.
    """

    window_id: str
    dataset_run_id: str
    incident_episode_id: str
    scenario_id: str
    scenario_family: str
    service_name: str
    window_type: str
    start_time: str
    end_time: str
    triage_label: str  # ticket_worthy | borderline | noise
    triage_severity: str | None
    triage_components: list[str] | None
    triage_reason_class: str | None
    is_hard_case: bool
    source: str  # scenario_authored | derived | human_adjudicated
    evidence_text: str
    raw: dict[str, Any]
    matched_memory_issue_ids: list[str] = field(default_factory=list)
    is_novel: bool | None = None
    fault_compatibility_class: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TriageWindow":
        return cls(
            window_id=row["window_id"],
            dataset_run_id=row["dataset_run_id"],
            incident_episode_id=row["incident_episode_id"],
            scenario_id=row["scenario_id"],
            scenario_family=row["scenario_family"],
            service_name=row["service_name"],
            window_type=row["window_type"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            triage_label=row["triage_label"],
            triage_severity=row.get("triage_severity"),
            triage_components=row.get("triage_components"),
            triage_reason_class=row.get("triage_reason_class"),
            is_hard_case=bool(row.get("is_hard_case", False)),
            source=row.get("source", "derived"),
            evidence_text=row.get("triage_evidence_text", "") or "",
            raw=row,
        )


@dataclass
class JiraMemoryIssue:
    """One row from jira-memory-corpus.jsonl.

    `available_as_memory_from` is the issue's created_at. The corpus enforces
    time-ordering at query time by filtering on this field, so we keep it
    here as the canonical visibility key rather than re-deriving it.
    """

    jira_shadow_issue_id: str
    jira_issue_key: str
    dataset_run_id: str
    incident_episode_id: str
    available_as_memory_from: str
    scenario_id: str
    scenario_family: str
    affected_service: str
    fault_type: str
    fault_compatibility_class: str
    severity: str
    memory_text: str
    resolution_notes: str
    linked_window_ids: list[str]
    linked_trace_ids: list[str]
    linked_alert_fingerprints: list[str]
    raw: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "JiraMemoryIssue":
        return cls(
            jira_shadow_issue_id=row["jira_shadow_issue_id"],
            jira_issue_key=row.get("jira_issue_key", ""),
            dataset_run_id=row["dataset_run_id"],
            incident_episode_id=row["incident_episode_id"],
            available_as_memory_from=row["available_as_memory_from"],
            scenario_id=row.get("scenario_id", ""),
            scenario_family=row.get("scenario_family", ""),
            affected_service=row.get("affected_service", ""),
            fault_type=row.get("fault_type", ""),
            fault_compatibility_class=row.get("fault_compatibility_class", ""),
            severity=row.get("severity", ""),
            memory_text=row.get("memory_text", "") or "",
            resolution_notes=row.get("resolution_notes", "") or "",
            linked_window_ids=list(row.get("linked_window_ids", []) or []),
            linked_trace_ids=list(row.get("linked_trace_ids", []) or []),
            linked_alert_fingerprints=list(row.get("linked_alert_fingerprints", []) or []),
            raw=row,
        )


@dataclass
class MemoryMatch:
    """One row from window-memory-matchings.jsonl - the retrieval ground truth."""

    window_id: str
    dataset_run_id: str
    scenario_family: str
    affected_service: str
    fault_compatibility_class: str
    triage_label: str
    is_novel: bool
    matched_memory_issue_ids: list[str]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MemoryMatch":
        return cls(
            window_id=row["window_id"],
            dataset_run_id=row.get("dataset_run_id", ""),
            scenario_family=row.get("scenario_family", ""),
            affected_service=row.get("affected_service", ""),
            fault_compatibility_class=row.get("fault_compatibility_class", "none"),
            triage_label=row.get("triage_label", ""),
            is_novel=bool(row.get("is_novel", False)),
            matched_memory_issue_ids=list(row.get("matched_memory_issue_ids", []) or []),
        )


@dataclass
class SplitManifest:
    """Family-to-split assignment + leave-one-family-out fold list."""

    family_assignment: dict[str, str]  # family -> train|validation|test
    leave_one_family_out_folds: list[str]
    global_dataset_id: str
    split_by: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SplitManifest":
        folds = [f["held_out_family"] for f in row.get("leave_one_family_out_folds", [])]
        return cls(
            family_assignment=row["family_assignment"],
            leave_one_family_out_folds=folds,
            global_dataset_id=row.get("global_dataset_id", ""),
            split_by=row.get("split_by", "scenario_family"),
        )

    def split_of(self, family: str) -> str:
        return self.family_assignment.get(family, "train")
