"""ReAct tool-calling protocol — Phase 2 of the smarter-agent plan.

Defines the data types an `EvidenceRequestSkill` produces (ToolRequest)
and consumes (ToolResult), plus the in-bundle slot
(`bundle.extra["tool_results"]`) where fulfilled tool results live so
downstream skills can read them.

Design (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5):

A tool is a *skill that fetches evidence the agent didn't have at
window-decoration time* — pod events, an extended trace window, a
peer-incident retrieval, etc. The skill itself queries the data lake
(no LLM in v1 — that's the v2 step). The result is stored in the
bundle's `extra` dict under a well-known key, so subsequent skills
(compose_l2, compose_triage, retrieve_*) can read it.

Why this design (vs the §15.1 sketch in AGENTIC-SYSTEM.md):
- Keeps the runner unchanged. No "re-observe capabilities then
  re-invoke skill" loop. The runner just executes a Plan; tools are
  Skills like any other.
- Bundle augmentation happens *in-skill* via `ctx.replace_bundle(...)`,
  so the next skill in the same Plan automatically sees the new
  evidence.
- Future LLM-emitted tool requests can be layered on top: a future
  `decide_next_tool` skill emits a ToolRequest in its SkillOutput,
  and the controller's plan adds the corresponding EvidenceRequestSkill.
  v1 just hardcodes "always run RequestPodEvents in the evidence
  branch" — close enough to ReAct for evaluation purposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Well-known keys on `bundle.extra` where tool results land.
TOOL_RESULTS_KEY = "tool_results"

# Tool-call history (one entry per (tool_name, args_hash) call in the
# current window). Used for the loop-detection failure mode.
TOOL_CALL_HISTORY_KEY = "tool_call_history"


# -----------------------------------------------------------------------------
# Failure-mode taxonomy — closes RQ-D6
# -----------------------------------------------------------------------------
#
# Five categories per IMPLEMENTATION-PLAN §5.4. Recorded as a string on
# `ToolResult.failure_mode`. None = the tool succeeded with a useful
# payload.
#
# The names are intentionally lowercase snake_case so they read cleanly
# in JSON catalog files and trace events.

#: Tool name not in registry (controller asked for a tool that doesn't
#: exist). For v1's deterministic controller this can only fire if a
#: schema-validation defensive check trips; v2's LLM-emitted ToolRequest
#: makes this a real risk.
FAILURE_HALLUCINATED = "hallucinated_tool_name"

#: Tool returned a valid-schema result but no usable signal — e.g. the
#: pod_events list is empty, or all events are `Normal` type. The
#: reranker can't extract any tokens. ToolResult.error is None in this
#: case (the fetch succeeded; the data is just sparse).
FAILURE_EMPTY = "tool_returned_empty"

#: The same (tool_name, args_hash) was called >= FAILURE_LOOPING_THRESHOLD
#: times in this window. The skill refuses to invoke again and emits
#: this mode instead.
FAILURE_LOOPING = "looping_repeated_call"

#: Budget exhausted (spent_tool_calls >= max_tool_calls cap). The skill
#: refuses to invoke and emits this mode.
FAILURE_BUDGET_EXHAUSTED = "budget_exhausted"

#: Data lake API raised an exception, or the underlying file is missing.
#: ToolResult.error carries the exception message; failure_mode = this.
FAILURE_TOOL_ERROR = "tool_threw_or_missing"

# All known failure modes; the catalog script enumerates this.
FAILURE_MODES: tuple[str, ...] = (
    FAILURE_HALLUCINATED,
    FAILURE_EMPTY,
    FAILURE_LOOPING,
    FAILURE_BUDGET_EXHAUSTED,
    FAILURE_TOOL_ERROR,
)

#: Looping threshold — repeat the same (tool_name, args_hash) this many
#: times before refusing further calls. Conservative default of 3 so a
#: single retry doesn't trip the gate (in case a tool fails transiently
#: and the controller retries once).
FAILURE_LOOPING_THRESHOLD = 3

#: Default per-window max_tool_calls cap. Skills check this against
#: `len(ctx.extra["tool_call_history"])` before invoking. Overridable
#: via the Budget caps in agent-config.yaml.
DEFAULT_MAX_TOOL_CALLS = 6


@dataclass(frozen=True)
class ToolRequest:
    """What a skill asks for. Emitted as `SkillOutput.extra["requested_tool"]`
    or built directly by the EvidenceRequestSkill itself.

    In v1, ToolRequest is mostly informational — the EvidenceRequestSkill
    fetches data DIRECTLY rather than emitting a request the runner
    fulfills. Kept as a first-class type so future LLM-emitted ReAct
    skills have a clear contract.
    """

    tool_name: str                          # e.g. "request_pod_events"
    args: dict[str, Any] = field(default_factory=dict)
    requested_by_skill: str = ""
    cost_estimate_ms: float = 0.0           # for Budget pre-flight

    def cache_key(self) -> str:
        """Content-addressed key for caching tool results."""
        import hashlib
        import json
        canon = json.dumps(
            {"name": self.tool_name, "args": self.args},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ToolResult:
    """What the tool returned. Carried in `bundle.extra[TOOL_RESULTS_KEY]`.

    `failure_mode` is None on success; otherwise it's one of the
    constants in `FAILURE_MODES`. The catalog script aggregates these
    per-tool to populate RQ-D6's distribution.
    """

    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]                  # tool-specific payload
    cost_actual_ms: float = 0.0
    bytes_returned: int = 0
    cache_hit: bool = False
    error: str | None = None                # populated on failure
    failure_mode: str | None = None         # None on success; one of FAILURE_MODES

    @property
    def is_empty(self) -> bool:
        """True when the tool returned nothing usable."""
        if self.error is not None:
            return True
        r = self.result
        if not r:
            return True
        # The "no useful signal" check is tool-specific. Default: an
        # empty list/dict counts as empty.
        for v in r.values():
            if v:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "args": dict(self.args),
            "result": dict(self.result),
            "cost_actual_ms": self.cost_actual_ms,
            "bytes_returned": self.bytes_returned,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "failure_mode": self.failure_mode,
        }


def add_tool_result(extra: dict[str, Any], result: ToolResult) -> dict[str, Any]:
    """Return a new `extra` dict with `result` appended to the tool_results
    list. Doesn't mutate the input."""
    new_extra = dict(extra) if extra else {}
    existing = list(new_extra.get(TOOL_RESULTS_KEY, []))
    existing.append(result.to_dict())
    new_extra[TOOL_RESULTS_KEY] = existing
    return new_extra


def get_tool_results(bundle_extra: dict[str, Any]) -> list[ToolResult]:
    """Pull the tool_results list out of a bundle.extra and rehydrate
    each entry as a ToolResult. Returns [] if none."""
    raw = (bundle_extra or {}).get(TOOL_RESULTS_KEY, [])
    out: list[ToolResult] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        out.append(ToolResult(
            tool_name=str(d.get("tool_name", "")),
            args=dict(d.get("args") or {}),
            result=dict(d.get("result") or {}),
            cost_actual_ms=float(d.get("cost_actual_ms") or 0.0),
            bytes_returned=int(d.get("bytes_returned") or 0),
            cache_hit=bool(d.get("cache_hit", False)),
            error=d.get("error"),
            failure_mode=d.get("failure_mode"),
        ))
    return out


# -----------------------------------------------------------------------------
# Loop-detection helpers
# -----------------------------------------------------------------------------


def args_hash(args: dict[str, Any]) -> str:
    """Stable hash of a tool's args dict — used to detect repeat calls
    in the same window. Independent of dict ordering."""
    import hashlib
    import json
    canon = json.dumps(args or {}, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def record_tool_call(extra: dict[str, Any], tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Append a (tool_name, args_hash) pair to ctx.extra[TOOL_CALL_HISTORY_KEY].

    Returns a NEW extra dict (does not mutate the input). The hash is
    used for loop-detection on subsequent calls.
    """
    new_extra = dict(extra) if extra else {}
    history = list(new_extra.get(TOOL_CALL_HISTORY_KEY, []))
    history.append({"tool_name": tool_name, "args_hash": args_hash(args)})
    new_extra[TOOL_CALL_HISTORY_KEY] = history
    return new_extra


def count_tool_call_repeats(
    extra: dict[str, Any],
    tool_name: str,
    args: dict[str, Any],
) -> int:
    """How many times has the exact (tool_name, args_hash) been called
    in this window already? Used by the looping-detection failure mode."""
    history = (extra or {}).get(TOOL_CALL_HISTORY_KEY) or []
    h = args_hash(args)
    return sum(
        1 for entry in history
        if isinstance(entry, dict)
        and entry.get("tool_name") == tool_name
        and entry.get("args_hash") == h
    )


# -----------------------------------------------------------------------------
# Hallucination guard
# -----------------------------------------------------------------------------


def validate_tool_request(
    request: "ToolRequest",
    known_tool_names: set[str] | frozenset[str],
) -> ToolResult | None:
    """Return None if `request.tool_name` is in the known set;
    otherwise return a refusal ToolResult tagged with
    `FAILURE_HALLUCINATED`.

    In v1 the controller emits tool names from a hardcoded constant
    so this defensive check is only triggered by tests. In v2 — when
    an LLM-emitted `decide_next_tool` skill produces tool names —
    this becomes the gate that catches "decide_next_tool asked for
    `request_thread_dump` which doesn't exist."
    """
    if request.tool_name in known_tool_names:
        return None
    return ToolResult(
        tool_name=request.tool_name,
        args=dict(request.args),
        result={},
        cost_actual_ms=0.0,
        bytes_returned=0,
        cache_hit=False,
        error=(
            f"hallucinated tool name {request.tool_name!r}; "
            f"known tools: {sorted(known_tool_names)}"
        ),
        failure_mode=FAILURE_HALLUCINATED,
    )
