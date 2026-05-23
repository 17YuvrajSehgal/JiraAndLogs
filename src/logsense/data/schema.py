"""Dataclasses for log-only analysis.

LogLine and WindowLogs are independent of the global triage label - they
just describe what Loki returned. LabeledWindowLogs glues a WindowLogs onto
the TriageWindow row from loganalyzer so we keep one source of truth for
labels and split assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loganalyzer.data.schema import TriageWindow


@dataclass
class LogLine:
    timestamp_ns: int
    body: str
    severity: str  # error | warning | info | debug | unknown
    service: str
    container: str | None
    pod: str | None
    detected_level: str | None

    @property
    def is_error(self) -> bool:
        return self.severity in {"error", "critical", "fatal"}

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"


@dataclass
class WindowLogs:
    """All log lines Loki returned for one telemetry window's labeled service."""

    window_id: str
    dataset_run_id: str
    incident_episode_id: str
    service_name: str
    window_type: str
    start_time: str
    end_time: str
    lines: list[LogLine] = field(default_factory=list)
    namespace_lines: list[LogLine] = field(default_factory=list)
    fetched_at: str = ""

    @property
    def n_lines(self) -> int:
        return len(self.lines)

    @property
    def error_count(self) -> int:
        return sum(1 for l in self.lines if l.is_error)

    @property
    def warning_count(self) -> int:
        return sum(1 for l in self.lines if l.is_warning)

    @property
    def duration_seconds(self) -> float:
        # Best-effort: caller may have already parsed start/end. We compute
        # from the timestamps of the first and last LogLine instead, which
        # is correct for what the model actually saw.
        if len(self.lines) < 2:
            return 0.0
        ts = sorted(l.timestamp_ns for l in self.lines)
        return (ts[-1] - ts[0]) / 1e9


@dataclass
class LabeledWindowLogs:
    """WindowLogs + its triage label, the unit the triage model trains on."""

    logs: WindowLogs
    label: TriageWindow  # we keep the whole TriageWindow so gold matchings ride along

    @property
    def triage_label(self) -> str:
        return self.label.triage_label

    @property
    def scenario_family(self) -> str:
        return self.label.scenario_family

    @property
    def window_id(self) -> str:
        return self.logs.window_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "triage_label": self.triage_label,
            "scenario_family": self.scenario_family,
            "service_name": self.logs.service_name,
            "n_lines": self.logs.n_lines,
            "error_count": self.logs.error_count,
        }
