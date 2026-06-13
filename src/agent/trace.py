"""Trace + TraceEvent — the audit log of a single agent decision.

The Runner appends a TraceEvent to the Trace for every notable step
(plan_start, skill_start, skill_end, cache_hit, budget_check, fallback,
plan_end). The final Trace is serialised to
`data/agent_traces/<experiment>/<bundle_id>.json`.

Traces are the **substrate for** debugging, ablation analysis, and the
v2 LearnedController's training data.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §4.7.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .budget import BudgetSnapshot
from .types import AgentDecision, SkillOutput


TraceEventKind = Literal[
    "plan_start",
    "skill_start",
    "skill_end",
    "skill_skipped_by_gate",
    "cache_hit",
    "budget_check_passed",
    "budget_exceeded",
    "skill_failed",
    "fallback_triggered",
    "plan_end",
]


@dataclass(frozen=True)
class TraceEvent:
    """One notable event during plan execution.

    Most fields are optional — different event kinds populate different
    subsets. The `kind` field is the discriminator.
    """

    ts: str                                      # ISO-8601 UTC, ms precision
    kind: TraceEventKind
    skill: str | None = None
    skill_version: str | None = None
    duration_ms: float | None = None
    output: SkillOutput | None = None
    error: str | None = None
    budget_snapshot: BudgetSnapshot | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "skill": self.skill,
            "skill_version": self.skill_version,
            "duration_ms": self.duration_ms,
            "output": self.output.to_dict() if self.output else None,
            "error": self.error,
            "budget_snapshot": (
                self.budget_snapshot.to_dict() if self.budget_snapshot else None
            ),
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TraceEvent":
        output = d.get("output")
        bs = d.get("budget_snapshot")
        return cls(
            ts=str(d["ts"]),
            kind=d["kind"],
            skill=d.get("skill"),
            skill_version=d.get("skill_version"),
            duration_ms=d.get("duration_ms"),
            output=SkillOutput.from_dict(output) if output else None,
            error=d.get("error"),
            budget_snapshot=BudgetSnapshot.from_dict(bs) if bs else None,
            notes=dict(d.get("notes") or {}),
        )


@dataclass
class Trace:
    """Mutable container of TraceEvents for one bundle.

    The Runner is the only writer; downstream consumers (ablation
    analysis, learned-controller training data builder) read-only.

    Persisted as a single JSON file per bundle, not per event — keeps
    file count manageable on large test splits.
    """

    bundle_id: str
    plan_id: str
    events: list[TraceEvent] = field(default_factory=list)
    final_decision: AgentDecision | None = None
    started_at: str = field(default_factory=TraceEvent.now)
    finished_at: str | None = None

    # ------------------------------------------------------------------ writes

    def add(self, event: TraceEvent) -> None:
        self.events.append(event)

    def close(self, decision: AgentDecision) -> None:
        self.final_decision = decision
        self.finished_at = TraceEvent.now()

    # ------------------------------------------------------------------ queries

    def latest_output(self, skill: str) -> SkillOutput | None:
        """Most recent SkillOutput from `skill`, if any.

        Used by skill gates (e.g. "if `triage_numeric.score > 0.9` then
        skip the verifier") to read intermediate results."""
        for event in reversed(self.events):
            if event.kind == "skill_end" and event.skill == skill and event.output:
                return event.output
        return None

    def all_outputs(self) -> list[SkillOutput]:
        return [e.output for e in self.events if e.kind == "skill_end" and e.output]

    def skill_names_invoked(self) -> tuple[str, ...]:
        return tuple(
            e.skill for e in self.events
            if e.kind == "skill_start" and e.skill is not None
        )

    def n_skill_calls(self) -> int:
        return sum(1 for e in self.events if e.kind == "skill_start")

    def had_error(self) -> bool:
        return any(e.kind == "skill_failed" for e in self.events)

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "plan_id": self.plan_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "n_events": len(self.events),
            "events": [e.to_dict() for e in self.events],
            "final_decision": (
                self.final_decision.to_dict() if self.final_decision else None
            ),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), default=str, indent=indent)

    def write_to(self, output_root: Path | str, *, experiment: str = "") -> Path:
        """Persist as `<output_root>/<experiment>/<bundle_id>.json`.

        Returns the path written."""
        root = Path(output_root)
        if experiment:
            root = root / experiment
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.bundle_id}.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trace":
        events = [TraceEvent.from_dict(e) for e in (d.get("events") or ())]
        final_decision = d.get("final_decision")
        return cls(
            bundle_id=str(d["bundle_id"]),
            plan_id=str(d.get("plan_id", "")),
            events=events,
            final_decision=(
                AgentDecision.from_dict(final_decision) if final_decision else None
            ),
            started_at=str(d.get("started_at", "")),
            finished_at=d.get("finished_at"),
        )

    @classmethod
    def load(cls, path: Path | str) -> "Trace":
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ debug

    def __repr__(self) -> str:
        return (
            f"Trace(bundle={self.bundle_id!r}, plan={self.plan_id!r}, "
            f"n_events={len(self.events)}, "
            f"decision={self.final_decision.triage_decision if self.final_decision else None})"
        )
