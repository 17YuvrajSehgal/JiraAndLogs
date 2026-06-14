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
    """What the tool returned. Carried in `bundle.extra[TOOL_RESULTS_KEY]`."""

    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]                  # tool-specific payload
    cost_actual_ms: float = 0.0
    bytes_returned: int = 0
    cache_hit: bool = False
    error: str | None = None                # populated on failure

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
        ))
    return out
