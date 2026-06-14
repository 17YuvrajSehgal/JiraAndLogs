"""EvidenceRequestSkill — the v1 ReAct hook (per AGENTIC-SYSTEM.md §15.1).

These skills are "tools" — they fetch evidence the agent didn't have
at window-decoration time and inject it into the in-flight execution
context so subsequent skills in the same Plan can read it.

v1 design (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5):
  - Skill's `invoke()` calls `_fetch_evidence(bundle, ctx)` (concrete
    subclasses implement) to ask the DataLake for something.
  - Result is recorded as a `ToolResult` and appended to
    `ctx.extra[TOOL_RESULTS_KEY]`. Downstream skills read it from there.
  - SkillOutput.extra["tool_result"] also carries the result so the
    Trace captures it permanently.

Concrete v1 subclass shipped:
  - `RequestPodEventsSkill` — fetches the k8s event list for the
    bundle's `window_id` from `data/runs/<run_id>/raw/kubernetes/`.

Future tools (Phase 2 follow-ups, same ABC):
  - RequestExtendedTraceWindow, RequestPodMetrics,
    RequestSimilarIncidentWindow.

ReAct loop status:
  v1 = controller decides when to invoke the tool (deterministic gate)
  v2 = LLM decides via a separate "decide_next_tool" skill (deferred)
"""

from __future__ import annotations

import re
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any

from ..capabilities import (
    K8S_EVENTS,
    METRIC_SNAPSHOTS,
    TRACE_SUMMARY,
)
from ..tool_protocol import (
    TOOL_RESULTS_KEY,
    ToolResult,
    add_tool_result,
)
from ..types import InputBundle, SkillCallCost, SkillOutput
from .base import AgentContext, MemoryView, Skill


class EvidenceRequestSkill(Skill):
    """Base for ReAct evidence-gathering skills.

    Subclasses override:
      - `tool_name` (class attr) — registered with the data lake
      - `_fetch_evidence(bundle, ctx) -> dict` — the actual fetch

    The base `invoke()` handles:
      - calling `_fetch_evidence`
      - wrapping the result as a ToolResult
      - appending to `ctx.extra[TOOL_RESULTS_KEY]` so downstream skills see it
      - building a neutral SkillOutput (no triage_score / matched_ids
        change — that's downstream skills' job once they read the
        augmented evidence)
    """

    __intermediate_base__ = True

    #: The tool name routed to the DataLake (e.g. "request_pod_events").
    tool_name: str = ""

    cost_class = "medium"

    @abstractmethod
    def _fetch_evidence(
        self,
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        """Concrete subclasses query the DataLake here. Return the
        tool's raw result dict — the base wraps it into a ToolResult."""

    def _build_args(self, bundle: InputBundle) -> dict[str, Any]:
        """Args recorded in ToolRequest + cache key. Override for
        non-default args. Default: just window_id."""
        return {"window_id": bundle.window_id}

    def _is_evidence_useful(self, result: dict[str, Any]) -> bool:
        """Did the tool return something worth recording? Subclasses
        override for tool-specific semantics. Default: no error + at
        least one non-empty value."""
        if result.get("error"):
            return False
        for v in result.values():
            if v not in (None, "", [], {}, 0):
                return True
        return False

    # ------------------------------------------------------------------ invoke

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        args = self._build_args(bundle)
        start_ms = time.monotonic()
        try:
            raw_result = self._fetch_evidence(bundle, ctx)
            error: str | None = None
        except Exception as e:                                          # noqa: BLE001
            raw_result = {}
            error = f"{type(e).__name__}: {e}"[:140]
        duration_ms = (time.monotonic() - start_ms) * 1000.0

        # Cache-hit flag comes from the data lake's payload; default False.
        cache_hit = bool(raw_result.pop("cache_hit", False)) if isinstance(raw_result, dict) else False

        tool_result = ToolResult(
            tool_name=self.tool_name,
            args=args,
            result=raw_result if isinstance(raw_result, dict) else {},
            cost_actual_ms=duration_ms,
            bytes_returned=len(str(raw_result)) if raw_result else 0,
            cache_hit=cache_hit,
            error=error,
        )

        # Propagate to subsequent skills in the same Plan via ctx.extra.
        ctx.extra = add_tool_result(ctx.extra or {}, tool_result)

        # Cost — the runner deducts this from the per-window Budget.
        cost = SkillCallCost(
            wall_seconds=duration_ms / 1000.0,
            n_calls=1,
            llm_tokens=0,
            usd=0.0,
        )

        is_useful = (error is None) and self._is_evidence_useful(raw_result)
        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=None,            # evidence tool doesn't triage
            triage_decision=None,
            matched_issue_ids=[],
            is_novel=None,
            confidence=1.0 if is_useful else 0.0,
            evidence_used=[self.tool_name],
            cost=cost,
            extra={
                "tool_result": tool_result.to_dict(),
                "is_useful": is_useful,
            },
        )

    def cache_key(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        *,
        extra_inputs: dict[str, Any] | None = None,
    ) -> str:
        """Evidence-request skills are deterministic in (window_id, args),
        so cache on those — independent of memory."""
        args = self._build_args(bundle)
        composite_extra = dict(args)
        if extra_inputs:
            composite_extra.update(extra_inputs)
        # Reuse the base cache_key shape but stuff args into extra_inputs
        # so re-runs with the same window hit cache.
        return super().cache_key(bundle, memory, extra_inputs=composite_extra)


# -----------------------------------------------------------------------------
# RequestPodEventsSkill — the v1 concrete tool
# -----------------------------------------------------------------------------


class RequestPodEventsSkill(EvidenceRequestSkill):
    """Fetch k8s pod events for the bundle's window from the data lake.

    Useful when retrieval consensus failed because the textual evidence
    is ambiguous but the k8s events (OOMKilled, CrashLoopBackOff,
    FailedScheduling, ImagePullBackOff) are dispositive about which
    Jira ticket family matches.

    Required flags: `K8S_EVENTS` — the bundle must carry k8s event data
    (which OB and OTel Demo do; WoL does not).
    """

    name = "request_pod_events"
    version = "1.0.0"
    tool_name = "request_pod_events"
    required_flags = frozenset({K8S_EVENTS})
    cost_class = "medium"

    def __init__(self, data_lake: Any) -> None:
        """`data_lake` is a `RawRunDataLake` instance — passed in at
        registration time so the skill stays testable with mocks."""
        self.data_lake = data_lake

    def _fetch_evidence(
        self,
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        # The data lake handles missing-file gracefully and returns
        # {events: [], error: "missing"} — we just pass that through.
        return self.data_lake.get_pod_events(bundle.window_id, max_events=50)

    def _is_evidence_useful(self, result: dict[str, Any]) -> bool:
        """For pod events, "useful" means at least one warning event.
        Normal events (Pulled, Created, Scheduled) don't disambiguate
        — they happen on every healthy pod restart."""
        if result.get("error"):
            return False
        return int(result.get("warning_count", 0)) > 0


# -----------------------------------------------------------------------------
# RequestExtendedTraceWindowSkill — Tempo evidence tool
# -----------------------------------------------------------------------------


class RequestExtendedTraceWindowSkill(EvidenceRequestSkill):
    """Fetch a summarized Tempo trace dump for the window from the data lake.

    Useful when retrieval is ambiguous because text-evidence already names
    the right service but the same service appears in multiple ticket
    families (cart-redis vs cart-restart vs cart-saturation). The set
    of `services_seen` plus any `error_span_names` adds a coarse but
    independent disambiguation signal.

    Required flags: `TRACE_SUMMARY` — set by the OB loader when a Tempo
    capture exists on disk for the window.
    """

    name = "request_extended_trace_window"
    version = "1.0.0"
    tool_name = "request_extended_trace_window"
    required_flags = frozenset({TRACE_SUMMARY})
    cost_class = "medium"

    def __init__(self, data_lake: Any) -> None:
        self.data_lake = data_lake

    def _fetch_evidence(
        self,
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        return self.data_lake.get_extended_trace_window(bundle.window_id)

    def _is_evidence_useful(self, result: dict[str, Any]) -> bool:
        """Useful when at least one trace was captured. Even with zero
        error_span_names, services_seen is still a usable rerank signal."""
        if result.get("error"):
            return False
        return int(result.get("n_traces", 0)) > 0


# -----------------------------------------------------------------------------
# RequestPodMetricsSkill — Prometheus evidence tool
# -----------------------------------------------------------------------------


class RequestPodMetricsSkill(EvidenceRequestSkill):
    """Fetch Prometheus snapshot summary (restarts/CPU/memory/alerts).

    Useful for disambiguating between scenarios that share the same
    service surface but differ in resource profile (e.g. "restart
    storm" vs "slow memory leak" vs "alert flood without restarts").

    Required flags: `METRIC_SNAPSHOTS` — set by the OB loader when a
    Prometheus capture exists on disk for the window.
    """

    name = "request_pod_metrics"
    version = "1.0.0"
    tool_name = "request_pod_metrics"
    required_flags = frozenset({METRIC_SNAPSHOTS})
    cost_class = "medium"

    def __init__(self, data_lake: Any) -> None:
        self.data_lake = data_lake

    def _fetch_evidence(
        self,
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        return self.data_lake.get_pod_metrics(bundle.window_id)

    def _is_evidence_useful(self, result: dict[str, Any]) -> bool:
        """Useful if at least one of (restarts changed, alerts firing,
        cpu/mem readings exist)."""
        if result.get("error"):
            return False
        if (result.get("restart_delta") or 0) > 0:
            return True
        if (result.get("n_alerts_firing") or 0) > 0:
            return True
        # Any non-null metric reading counts as usable
        return any(
            result.get(k) is not None
            for k in ("cpu_max", "cpu_mean", "mem_max", "mem_mean")
        )


# -----------------------------------------------------------------------------
# RequestSimilarIncidentWindowSkill — peer-incident lookup tool
# -----------------------------------------------------------------------------


class RequestSimilarIncidentWindowSkill(EvidenceRequestSkill):
    """Fetch peer Jira tickets that share scenario_family.

    Useful because peers in the same family typically share canonical
    components and resolution language; their `memory_text` heads
    provide a high-precision token bag that helps the reranker
    disambiguate when the L2 top-K is mixed across families.

    Unlike the other three tools, this skill is *always* applicable —
    every OB window has a `scenario_family` and the corpus always has
    peers. We still register it with no required_flags so the
    controller can include/exclude it via plan rules.
    """

    name = "request_similar_incident_window"
    version = "1.0.0"
    tool_name = "request_similar_incident_window"
    required_flags = frozenset()
    cost_class = "low"

    def __init__(self, data_lake: Any, global_dir: Path | str, *, top_k: int = 3) -> None:
        self.data_lake = data_lake
        self.global_dir = str(Path(global_dir))
        self.top_k = top_k

    def _build_args(self, bundle: InputBundle) -> dict[str, Any]:
        return {
            "scenario_family": bundle.scenario_family or "",
            "exclude_episode_id": _episode_from_window(bundle.window_id),
            "global_dir": self.global_dir,
            "top_k": self.top_k,
        }

    def _fetch_evidence(
        self,
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        family = bundle.scenario_family
        if not family:
            return {"peers": [], "n_peers": 0, "error": "no_scenario_family"}
        return self.data_lake.get_similar_incidents(
            scenario_family=family,
            global_dir=self.global_dir,
            exclude_episode_id=_episode_from_window(bundle.window_id),
            top_k=self.top_k,
        )

    def _is_evidence_useful(self, result: dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        return int(result.get("n_peers", 0)) > 0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


# window_id format: <run_id>-<window_type>-<service> where <run_id> is
# the prefix up to and including "-rNN". `_episode_from_window` peels
# the trailing `-<window_type>-<service>` so the same fault gets
# exclude-deduplicated against the corpus episode_id.
_RUN_ID_PATTERN = "^(.*?-r\\d+)-"


def _episode_from_window(window_id: str) -> str:
    """Return the episode_id slice of a window_id (everything up to
    `-<window_type>-<service>`)."""
    m = re.match(_RUN_ID_PATTERN, window_id)
    if not m:
        return window_id
    run_prefix = m.group(1)
    # Episode = run_prefix + the scenario-id segment.
    # e.g. window_id=
    #   2026-...-r01-cart-redis-degradation-critical-20260525T134155Z-active_fault-cartservice
    # episode_id should be:
    #   2026-...-r01-cart-redis-degradation-critical-20260525T134155Z
    # i.e. strip the trailing "-<window_type>-<service>".
    remainder = window_id[len(run_prefix):]
    parts = remainder.rsplit("-", 2)
    if len(parts) < 3:
        return window_id
    return run_prefix + parts[0]
