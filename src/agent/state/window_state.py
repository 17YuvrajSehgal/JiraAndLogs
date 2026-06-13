"""WindowState — one decision's snapshot, the unit the ring buffer holds.

Built from an `AgentDecision` + the corresponding `InputBundle` (which
carries `service_name`, `scenario_family`, `window_type`).

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §7.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..types import AgentDecision, InputBundle, TriageDecision


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class WindowState:
    """Snapshot of one window's decision, recorded in a service's ring buffer.

    Fields beyond the §7.1 schema:
      - `window_id`/`service_name` — needed for re-association on reload.
      - `scenario_family` — required by the page-suppression rule.
      - `window_type` — required to detect intervening recovery_window.
    """

    window_id: str
    service_name: str
    timestamp: str                                # ISO-8601 UTC, ms precision
    triage_decision: TriageDecision
    top1_match: str | None = None
    is_novel: bool = False
    incident_id: str | None = None
    scenario_family: str | None = None
    window_type: str | None = None

    # ------------------------------------------------------------------ factory

    @classmethod
    def from_decision(
        cls,
        decision: AgentDecision,
        bundle: InputBundle,
        *,
        incident_id: str | None = None,
        timestamp: str | None = None,
    ) -> "WindowState":
        """Build a WindowState from an AgentDecision + InputBundle.

        `service_name` comes from the bundle, NOT the decision (the
        decision is service-agnostic). When no incident_id is supplied,
        the field stays None; the StateLayer fills it during `record`."""
        top1 = decision.matched_issue_ids[0] if decision.matched_issue_ids else None
        return cls(
            window_id=decision.bundle_id,
            service_name=bundle.service_name or "",
            timestamp=timestamp or _now_iso(),
            triage_decision=decision.triage_decision,
            top1_match=top1,
            is_novel=decision.is_novel,
            incident_id=incident_id,
            scenario_family=bundle.scenario_family,
            window_type=bundle.window_type,
        )

    # ------------------------------------------------------------------ helpers

    def is_recovery(self) -> bool:
        """The page-suppression rule needs to detect intervening recoveries."""
        return self.window_type == "recovery_window"

    def matches_for_suppression(
        self,
        *,
        top1: str | None,
        scenario_family: str | None,
    ) -> bool:
        """Same-incident criterion: same top1_match + same scenario_family.

        Both sides being None counts as a mismatch — if a window had no
        top1_match, it can't suppress anything."""
        if top1 is None or self.top1_match is None:
            return False
        if top1 != self.top1_match:
            return False
        if scenario_family != self.scenario_family:
            return False
        return True

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "service_name": self.service_name,
            "timestamp": self.timestamp,
            "triage_decision": self.triage_decision,
            "top1_match": self.top1_match,
            "is_novel": self.is_novel,
            "incident_id": self.incident_id,
            "scenario_family": self.scenario_family,
            "window_type": self.window_type,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WindowState":
        return cls(
            window_id=str(d["window_id"]),
            service_name=str(d.get("service_name", "")),
            timestamp=str(d.get("timestamp", "")),
            triage_decision=d["triage_decision"],
            top1_match=d.get("top1_match"),
            is_novel=bool(d.get("is_novel", False)),
            incident_id=d.get("incident_id"),
            scenario_family=d.get("scenario_family"),
            window_type=d.get("window_type"),
        )
