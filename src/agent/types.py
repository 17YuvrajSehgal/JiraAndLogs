"""Core data types for the agent.

Most of these are frozen dataclasses representing pure data flowing
between agent layers. Concepts that own logic (Budget, Plan, Trace)
live in their own modules.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §4 (Core abstractions).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Triage decision enum
# ---------------------------------------------------------------------------
# Three-class enum reserved from day 1. v1 controller only emits the
# first two; the third (`needs_review`) is wired up for the deferred
# self-critique extension (XX_AGENTIC_IDEA.md §4.4).

TriageDecision = Literal["noise", "ticket_worthy", "needs_review", "borderline"]
EvaluationMode = Literal["telemetry_diagnosis", "text_retrieval_generalisation"]


# ---------------------------------------------------------------------------
# Sub-records for input bundles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogLine:
    """One row of log output."""
    ts_ns: int = 0
    service: str = ""
    severity: str = "info"
    line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LogLine":
        return cls(
            ts_ns=int(d.get("ts_ns", 0)),
            service=str(d.get("service", "")),
            severity=str(d.get("severity", "info")),
            line=str(d.get("line", "")),
        )


@dataclass(frozen=True)
class TraceSummary:
    """Anomaly-summary blob extracted from distributed traces."""
    n_spans: int = 0
    error_spans: int = 0
    p99_latency_ms: float = 0.0
    affected_services: tuple[str, ...] = ()
    summary_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["affected_services"] = list(self.affected_services)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TraceSummary":
        return cls(
            n_spans=int(d.get("n_spans", 0)),
            error_spans=int(d.get("error_spans", 0)),
            p99_latency_ms=float(d.get("p99_latency_ms", 0.0)),
            affected_services=tuple(d.get("affected_services") or ()),
            summary_text=str(d.get("summary_text", "")),
        )


@dataclass(frozen=True)
class K8sEvent:
    """One Kubernetes event."""
    ts_ns: int = 0
    kind: str = ""           # e.g. "Pod", "Deployment"
    reason: str = ""         # e.g. "Killing", "OOMKilling"
    message: str = ""
    object_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "K8sEvent":
        return cls(
            ts_ns=int(d.get("ts_ns", 0)),
            kind=str(d.get("kind", "")),
            reason=str(d.get("reason", "")),
            message=str(d.get("message", "")),
            object_name=str(d.get("object_name", "")),
        )


# ---------------------------------------------------------------------------
# InputBundle — the per-window evidence packet
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputBundle:
    """All evidence the agent has for one incident window.

    Every field except `window_id` and `dataset` is optional. The
    Capabilities Observer (Phase 1.5) inspects which fields are
    non-empty and produces a Capabilities set; the controller then
    selects skills based on those flags.

    `extra` is a forward-compatible slot for evidence types we haven't
    designed yet (e.g. ReAct request_more_evidence outputs in v3).
    """

    window_id: str
    dataset: str                                          # "online_boutique" | "otel_demo" | "wol"

    text_evidence: str | None = None
    numeric_features: dict[str, float] | None = None
    log_lines: tuple[LogLine, ...] | None = None
    log_lines_ordered: bool = False                      # WoL has lines but unordered
    trace_summary: TraceSummary | None = None
    k8s_events: tuple[K8sEvent, ...] | None = None
    metric_snapshots: dict[str, tuple[float, ...]] | None = None

    scenario_family: str | None = None                   # used for state binding, never retrieval
    service_name: str | None = None
    window_type: str | None = None                       # pre_fault / active_fault / recovery_window

    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers

    def cache_key(self) -> str:
        """Stable signature for SkillCache. Composed of the dataset +
        window_id, which together uniquely identify a bundle within the
        research pipeline. Extra evidence (e.g. ReAct augmentation)
        does not affect the key — those skills override `cache_key` in
        SkillOutput to mix in the augmented evidence hash."""
        return f"{self.dataset}/{self.window_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "dataset": self.dataset,
            "text_evidence": self.text_evidence,
            "numeric_features": dict(self.numeric_features) if self.numeric_features else None,
            "log_lines": [l.to_dict() for l in (self.log_lines or ())] if self.log_lines else None,
            "log_lines_ordered": self.log_lines_ordered,
            "trace_summary": self.trace_summary.to_dict() if self.trace_summary else None,
            "k8s_events": [e.to_dict() for e in (self.k8s_events or ())] if self.k8s_events else None,
            "metric_snapshots": (
                {k: list(v) for k, v in self.metric_snapshots.items()}
                if self.metric_snapshots else None
            ),
            "scenario_family": self.scenario_family,
            "service_name": self.service_name,
            "window_type": self.window_type,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InputBundle":
        log_lines = d.get("log_lines")
        k8s_events = d.get("k8s_events")
        metric_snapshots = d.get("metric_snapshots")
        trace_summary = d.get("trace_summary")
        return cls(
            window_id=str(d["window_id"]),
            dataset=str(d.get("dataset", "")),
            text_evidence=d.get("text_evidence"),
            numeric_features=dict(d.get("numeric_features") or {}) or None,
            log_lines=(
                tuple(LogLine.from_dict(l) for l in log_lines)
                if log_lines else None
            ),
            log_lines_ordered=bool(d.get("log_lines_ordered", False)),
            trace_summary=TraceSummary.from_dict(trace_summary) if trace_summary else None,
            k8s_events=(
                tuple(K8sEvent.from_dict(e) for e in k8s_events)
                if k8s_events else None
            ),
            metric_snapshots=(
                {k: tuple(v) for k, v in metric_snapshots.items()}
                if metric_snapshots else None
            ),
            scenario_family=d.get("scenario_family"),
            service_name=d.get("service_name"),
            window_type=d.get("window_type"),
            extra=dict(d.get("extra") or {}),
        )

    def replace_extra(self, **kwargs: Any) -> "InputBundle":
        """Return a copy with the `extra` dict updated. Used by
        EvidenceRequestSkill subclasses (the v3 ReAct hook) to attach
        newly-fetched evidence without mutating the original bundle."""
        new_extra = {**self.extra, **kwargs}
        return dataclasses.replace(self, extra=new_extra)


# ---------------------------------------------------------------------------
# Skill outputs + cost tracking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillCallCost:
    """How much one skill invocation cost the budget."""
    llm_tokens: int = 0
    wall_seconds: float = 0.0
    usd: float = 0.0
    n_calls: int = 1                                     # provider sub-calls (retries etc.)

    @classmethod
    def zero(cls) -> "SkillCallCost":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillCallCost":
        return cls(
            llm_tokens=int(d.get("llm_tokens", 0)),
            wall_seconds=float(d.get("wall_seconds", 0.0)),
            usd=float(d.get("usd", 0.0)),
            n_calls=int(d.get("n_calls", 1)),
        )

    def __add__(self, other: "SkillCallCost") -> "SkillCallCost":
        return SkillCallCost(
            llm_tokens=self.llm_tokens + other.llm_tokens,
            wall_seconds=self.wall_seconds + other.wall_seconds,
            usd=self.usd + other.usd,
            n_calls=self.n_calls + other.n_calls,
        )


@dataclass(frozen=True)
class SkillOutput:
    """Uniform output of every skill.

    `triage_decision` is None when the skill doesn't make a triage call
    (e.g. a pure retriever). `triage_decision="needs_review"` is
    reserved for the deferred self-critique extension; v1 emits only
    `noise` and `ticket_worthy`.

    `evidence_used` lists which Capability flags the skill actually
    consumed — useful for the §9 ablation analysis ("did `verify` rely
    on the trace summary?").
    """

    skill: str
    skill_version: str = "0.0.0"

    triage_score: float | None = None
    triage_decision: TriageDecision | None = None
    matched_issue_ids: tuple[str, ...] = ()
    is_novel: bool | None = None
    confidence: float = 0.0

    evidence_used: tuple[str, ...] = ()
    cost: SkillCallCost = field(default_factory=SkillCallCost.zero)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "skill_version": self.skill_version,
            "triage_score": self.triage_score,
            "triage_decision": self.triage_decision,
            "matched_issue_ids": list(self.matched_issue_ids),
            "is_novel": self.is_novel,
            "confidence": self.confidence,
            "evidence_used": list(self.evidence_used),
            "cost": self.cost.to_dict(),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillOutput":
        return cls(
            skill=str(d["skill"]),
            skill_version=str(d.get("skill_version", "0.0.0")),
            triage_score=d.get("triage_score"),
            triage_decision=d.get("triage_decision"),
            matched_issue_ids=tuple(d.get("matched_issue_ids") or ()),
            is_novel=d.get("is_novel"),
            confidence=float(d.get("confidence", 0.0)),
            evidence_used=tuple(d.get("evidence_used") or ()),
            cost=SkillCallCost.from_dict(d.get("cost") or {}),
            extra=dict(d.get("extra") or {}),
        )


# ---------------------------------------------------------------------------
# Final agent output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentDecision:
    """The agent's verdict for one bundle.

    Always carries `evaluation_mode` — set to "telemetry_diagnosis"
    for OB / OTel Demo, "text_retrieval_generalisation" for WoL.
    The eval harness uses this to refuse illegal cross-mode comparison
    rows (per IMPROVEMENTS §4 — WoL is text-only retrieval).
    """

    bundle_id: str
    triage_decision: TriageDecision
    triage_score: float
    matched_issue_ids: tuple[str, ...] = ()
    is_novel: bool = False
    confidence: float = 0.0
    evaluation_mode: EvaluationMode = "telemetry_diagnosis"
    plan_id: str = ""
    skills_invoked: tuple[str, ...] = ()
    cost: SkillCallCost = field(default_factory=SkillCallCost.zero)
    trace_path: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "triage_decision": self.triage_decision,
            "triage_score": self.triage_score,
            "matched_issue_ids": list(self.matched_issue_ids),
            "is_novel": self.is_novel,
            "confidence": self.confidence,
            "evaluation_mode": self.evaluation_mode,
            "plan_id": self.plan_id,
            "skills_invoked": list(self.skills_invoked),
            "cost": self.cost.to_dict(),
            "trace_path": self.trace_path,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentDecision":
        return cls(
            bundle_id=str(d["bundle_id"]),
            triage_decision=d["triage_decision"],
            triage_score=float(d["triage_score"]),
            matched_issue_ids=tuple(d.get("matched_issue_ids") or ()),
            is_novel=bool(d.get("is_novel", False)),
            confidence=float(d.get("confidence", 0.0)),
            evaluation_mode=d.get("evaluation_mode", "telemetry_diagnosis"),
            plan_id=str(d.get("plan_id", "")),
            skills_invoked=tuple(d.get("skills_invoked") or ()),
            cost=SkillCallCost.from_dict(d.get("cost") or {}),
            trace_path=str(d.get("trace_path", "")),
            ts=str(d.get("ts", "")),
        )
