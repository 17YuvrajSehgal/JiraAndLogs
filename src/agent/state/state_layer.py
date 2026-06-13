"""StateLayer — per-service ring buffers + page-suppression rule.

Three responsibilities:
  1. Maintain the per-`service_name` recent-windows ring buffer
     (size N=12 default; AGENTIC-SYSTEM §7.1).
  2. Apply the conservative page-suppression rule
     (same top1_match in last 3 contiguous windows + same
     scenario_family + no recovery_window intervened) to a candidate
     decision, returning an existing incident_id when suppression
     fires (§7.2).
  3. Expose a read-only `ServiceStateView` to the Controller so
     stateful policy hints (§7.3) can be derived without mutating the
     buffer.

The StateLayer is mutable but thread-safe (a single lock guards every
write/read — buffers are small, contention is minimal). Disk
persistence is opt-in: pass `persistence_path` to `__init__` to
auto-load existing state; call `save()` to checkpoint.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §7.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .window_state import WindowState


log = logging.getLogger(__name__)


#: Per-service buffer size. §7.1 default; configurable via constructor /
#: agent-config.yaml > state.buffer_size.
DEFAULT_BUFFER_SIZE = 12

#: Page-suppression looks back at most this many windows. Conservative
#: per IMPROVEMENTS — hiding a real second incident is worse than a
#: missed suppression.
DEFAULT_SUPPRESSION_LOOKBACK = 3


# ---------------------------------------------------------------------------
# ServiceStateView — read-only handle the Controller sees
# ---------------------------------------------------------------------------


class ServiceStateView:
    """Read-only snapshot of one service's recent windows.

    The Controller receives this via `Controller.plan(state=...)` and
    derives stateful hints (e.g. "skip log_sequence — same incident
    matched 3+ windows in a row"). Returning a view rather than the
    raw deque guarantees the Controller can't mutate the buffer.
    """

    def __init__(self, service_name: str, recent: list[WindowState]) -> None:
        self.service_name = service_name
        # Defensive copy + freeze order. Newest is at the end.
        self._states: tuple[WindowState, ...] = tuple(recent)

    # ------------------------------------------------------------------ iteration

    def __iter__(self) -> Iterator[WindowState]:
        return iter(self._states)

    def __len__(self) -> int:
        return len(self._states)

    def __bool__(self) -> bool:
        return bool(self._states)

    def __repr__(self) -> str:
        return f"ServiceStateView(service={self.service_name!r}, n={len(self._states)})"

    # ------------------------------------------------------------------ queries

    @property
    def latest(self) -> WindowState | None:
        return self._states[-1] if self._states else None

    def last_n(self, n: int) -> list[WindowState]:
        """Most recent N windows, oldest first (chronological)."""
        if n <= 0:
            return []
        return list(self._states[-n:])

    def n_consecutive_with_top1(self, top1: str) -> int:
        """How many of the most-recent contiguous windows share `top1`?

        Counts back from the newest window. Stops at the first mismatch.
        Used for the "same incident N+ windows in a row" heuristic from
        §7.3 (skip log_sequence when answer isn't changing).
        """
        if not top1:
            return 0
        count = 0
        for w in reversed(self._states):
            if w.top1_match == top1:
                count += 1
            else:
                break
        return count

    def n_consecutive_recovery(self) -> int:
        """Count of consecutive recovery_window windows at the end.

        ≥ 3 → §4.3 incident-closure rule fires (handled by the caller)."""
        count = 0
        for w in reversed(self._states):
            if w.is_recovery():
                count += 1
            else:
                break
        return count

    def saw_recovery_within(self, n_back: int) -> bool:
        """Was there a recovery_window in the last `n_back` windows?"""
        if n_back <= 0:
            return False
        return any(w.is_recovery() for w in self._states[-n_back:])

    def has_seen_scenario(self, scenario_family: str | None) -> bool:
        """True iff any window in the buffer shares `scenario_family`.

        Used for §7.3 "force expensive path on never-seen scenarios"."""
        if scenario_family is None:
            return False
        return any(w.scenario_family == scenario_family for w in self._states)

    def to_list(self) -> list[WindowState]:
        return list(self._states)


# ---------------------------------------------------------------------------
# PageSuppressionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageSuppressionResult:
    """Outcome of `StateLayer.check_page_suppression`.

    `suppress=True` ⇒ caller should downgrade `ticket_worthy` →
    `borderline` and attach `incident_id` from this result. The
    `matched_windows` count is informational (audit + telemetry).
    """

    suppress: bool
    incident_id: str | None = None
    matched_windows: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "suppress": self.suppress,
            "incident_id": self.incident_id,
            "matched_windows": self.matched_windows,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# StateLayer
# ---------------------------------------------------------------------------


class StateLayer:
    """Mutable per-service ring buffer + page-suppression rule.

    Construction options:
        buffer_size: ring-buffer capacity per service (default 12).
        suppression_lookback: page-suppression window (default 3).
        persistence_path: if given, attempt to load existing state from
            disk at construction and use as the default `save()` target.

    Thread-safety: a single lock guards every write/read. Buffers are
    small (≤12 entries) so contention is negligible.
    """

    def __init__(
        self,
        *,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        suppression_lookback: int = DEFAULT_SUPPRESSION_LOOKBACK,
        persistence_path: Path | str | None = None,
    ) -> None:
        if buffer_size <= 0:
            raise ValueError(f"buffer_size must be positive, got {buffer_size}")
        if suppression_lookback <= 0:
            raise ValueError(
                f"suppression_lookback must be positive, got {suppression_lookback}",
            )
        if suppression_lookback > buffer_size:
            raise ValueError(
                f"suppression_lookback ({suppression_lookback}) cannot exceed "
                f"buffer_size ({buffer_size}) — the rule would peek past the buffer.",
            )

        self.buffer_size = buffer_size
        self.suppression_lookback = suppression_lookback
        self.persistence_path = Path(persistence_path) if persistence_path else None

        self._buffers: dict[str, deque[WindowState]] = {}
        # The ring buffer rolls off old windows (the page-suppression
        # rule only needs the last 3 anyway), but the eval harness needs
        # the full count of unique incidents over an entire run for the
        # pages-per-incident metric. Track them separately here.
        self._seen_incident_ids: set[str] = set()
        self._lock = threading.RLock()

        if self.persistence_path is not None and self.persistence_path.exists():
            self._load_from_disk(self.persistence_path)

    # ------------------------------------------------------------------ view

    def get_view(self, service_name: str) -> ServiceStateView:
        """Read-only view of `service_name`'s recent windows.

        Empty service ⇒ empty view (the controller treats this as
        "no prior state for this service")."""
        with self._lock:
            buf = self._buffers.get(service_name)
            if buf is None:
                return ServiceStateView(service_name, [])
            return ServiceStateView(service_name, list(buf))

    # ------------------------------------------------------------------ record

    def record(self, state: WindowState) -> WindowState:
        """Append `state` to its service's buffer.

        If `state.incident_id` is None AND the window is `ticket_worthy`,
        a fresh incident_id is generated and returned as part of the
        stored state. The caller gets the (possibly mutated) state back
        so it can be threaded into downstream artifacts.

        Windows with empty `service_name` are stored under the empty
        string key — useful for datasets where service isn't a meaningful
        partition (WoL). Down-stream queries against
        `get_view(service_name="")` still work.
        """
        with self._lock:
            stored = state
            if (
                stored.incident_id is None
                and stored.triage_decision == "ticket_worthy"
            ):
                stored = self._with_incident_id(stored, self.generate_incident_id())
            buf = self._buffers.setdefault(state.service_name, deque(maxlen=self.buffer_size))
            buf.append(stored)
            if stored.incident_id:
                self._seen_incident_ids.add(stored.incident_id)
            return stored

    # ------------------------------------------------------------------ page suppression

    def check_page_suppression(
        self,
        *,
        service_name: str,
        candidate_top1: str | None,
        scenario_family: str | None,
        window_type: str | None = None,
    ) -> PageSuppressionResult:
        """Apply §7.2 page-suppression rule against the candidate decision.

        Returns `suppress=True` iff ALL hold:
          - Some window in the last `suppression_lookback` shares
            (candidate_top1, scenario_family).
          - That matching window is not followed by any
            `recovery_window` (which would indicate the prior fault
            resolved before the current window).

        Caller's responsibility: when `suppress=True`, downgrade
        triage_decision ticket_worthy → borderline and attach
        `result.incident_id` to the AgentDecision/WindowState before
        calling `record()`.
        """
        # If we can't compare top1, the rule can't fire.
        if candidate_top1 is None:
            return PageSuppressionResult(
                suppress=False, reason="candidate_top1 is None",
            )

        with self._lock:
            buf = self._buffers.get(service_name)
            if not buf:
                return PageSuppressionResult(
                    suppress=False, reason="no prior windows for service",
                )

            lookback = list(buf)[-self.suppression_lookback :]

        # Walk newest-to-oldest looking for a (top1, family)-matching
        # window. Bail on intervening recovery_window — that means the
        # incident resolved before us.
        for prior in reversed(lookback):
            if prior.is_recovery():
                return PageSuppressionResult(
                    suppress=False,
                    reason="recovery_window intervened",
                )
            if prior.matches_for_suppression(
                top1=candidate_top1,
                scenario_family=scenario_family,
            ):
                return PageSuppressionResult(
                    suppress=True,
                    incident_id=prior.incident_id,
                    matched_windows=1,
                    reason="same top1_match + scenario_family within lookback",
                )

        return PageSuppressionResult(
            suppress=False,
            reason="no matching prior window within lookback",
        )

    # ------------------------------------------------------------------ misc

    @staticmethod
    def generate_incident_id() -> str:
        """Fresh opaque incident ID — used when a ticket_worthy window
        creates a new incident."""
        return f"inc-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _with_incident_id(state: WindowState, incident_id: str) -> WindowState:
        """Return a copy of `state` with the given incident_id."""
        return WindowState(
            window_id=state.window_id,
            service_name=state.service_name,
            timestamp=state.timestamp,
            triage_decision=state.triage_decision,
            top1_match=state.top1_match,
            is_novel=state.is_novel,
            incident_id=incident_id,
            scenario_family=state.scenario_family,
            window_type=state.window_type,
        )

    def services(self) -> list[str]:
        with self._lock:
            return sorted(self._buffers)

    def n_services(self) -> int:
        with self._lock:
            return len(self._buffers)

    def n_windows_for(self, service_name: str) -> int:
        with self._lock:
            buf = self._buffers.get(service_name)
            return len(buf) if buf is not None else 0

    def clear(self, service_name: str | None = None) -> None:
        """Drop one service's buffer (or all if `service_name` is None).

        Useful between experiments to avoid leakage when reusing the
        same StateLayer instance. Clearing all services also resets
        the all-time `seen_incident_ids` set."""
        with self._lock:
            if service_name is None:
                self._buffers.clear()
                self._seen_incident_ids.clear()
            else:
                self._buffers.pop(service_name, None)

    def seen_incident_ids(self) -> frozenset[str]:
        """All unique incident_ids generated (or attached via suppression)
        since construction or the last full `clear()`.

        Survives ring-buffer rollover — used by the eval harness to
        report accurate pages-per-incident over long runs."""
        with self._lock:
            return frozenset(self._seen_incident_ids)

    def n_unique_incidents_seen(self) -> int:
        with self._lock:
            return len(self._seen_incident_ids)

    # ------------------------------------------------------------------ persistence

    def save(self, path: Path | str | None = None) -> Path:
        """Persist the full state to JSONL.

        Format: one line per WindowState, with `service_name` embedded.
        Order matches the in-memory buffer order so reload restores
        chronology."""
        target = Path(path) if path else self.persistence_path
        if target is None:
            raise ValueError(
                "StateLayer.save: no path supplied and no persistence_path set.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with target.open("w", encoding="utf-8") as fh:
                for service in sorted(self._buffers):
                    for state in self._buffers[service]:
                        fh.write(json.dumps(state.to_dict()) + "\n")
        return target

    def _load_from_disk(self, path: Path) -> None:
        """Hydrate from a JSONL produced by `save()`."""
        with self._lock:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("StateLayer: skipping malformed line in %s", path)
                        continue
                    try:
                        state = WindowState.from_dict(d)
                    except (KeyError, TypeError) as e:
                        log.warning(
                            "StateLayer: skipping unparseable record (%s) in %s",
                            e, path,
                        )
                        continue
                    buf = self._buffers.setdefault(
                        state.service_name,
                        deque(maxlen=self.buffer_size),
                    )
                    buf.append(state)

    # ------------------------------------------------------------------ debug

    def __repr__(self) -> str:
        return (
            f"StateLayer(buffer_size={self.buffer_size}, "
            f"n_services={self.n_services()}, "
            f"path={self.persistence_path})"
        )
