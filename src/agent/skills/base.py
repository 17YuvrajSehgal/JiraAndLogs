"""Skill ABC — the uniform interface every diagnostic primitive obeys.

A Skill wraps one diagnostic capability (a retriever, a verifier, an
LLM extractor, etc.) behind a uniform contract:

    skill.can_invoke(capabilities)  →  bool
    skill.invoke(bundle, memory, ctx) →  SkillOutput

The runner never imports a concrete Skill class — it pulls instances
from the SkillRegistry by name. Adding a new diagnostic primitive is
one file under `src/agent/skills/` + one `register_skill(...)` call.

Subclasses MUST be thread-safe — the runner may invoke several skills
concurrently when the controller permits it.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §4.3, §5.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from ..budget import Budget
from ..capabilities import Capabilities
from ..types import InputBundle, SkillCallCost, SkillOutput


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cost class — used by the controller to pick cheap-first paths
# ---------------------------------------------------------------------------


CostClass = Literal["cheap", "medium", "expensive_llm"]


# ---------------------------------------------------------------------------
# Failure modes — documented, citable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureMode:
    """A known failure mode for a skill.

    Every skill declares its known failure modes so the controller can
    consult them (e.g. WoL-LogSeq2Vec underperformance per Mode 3 §3.5).
    Each mode carries a citation pointing back to the evidence.

    Example::

        FailureMode(
            kind="ood_underperformance",
            description="LogSeq2Vec needs ordered log streams; "
                        "WoL log_quotes are unordered fragments.",
            citation="DOCS/docs7/MODE3-TCH-LITE-WoL-RESULTS.md §3.5",
            triggered_when={"UNORDERED_LOGS"},      # capability flag set
            severity="warning",
        )
    """
    kind: str
    description: str
    citation: str = ""
    triggered_when: frozenset[str] = field(default_factory=frozenset)
    severity: Literal["info", "warning", "error"] = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "citation": self.citation,
            "triggered_when": sorted(self.triggered_when),
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# MemoryView — the time-ordered, same-run-excluded view of memory
# ---------------------------------------------------------------------------


class MemoryView:
    """Iterable view of the memory tickets visible to a bundle.

    The agent doesn't reach into the global memory corpus — it gets a
    pre-filtered MemoryView that's already constrained to
    time-ordered + same-run-excluded subset for this bundle. The
    Skill receives this view and can iterate over it.

    The `signature()` method is a stable hash of (the view's contents).
    Used as part of SkillCache keys so the cache stays correct when the
    memory composition changes (distractor injection, additions, etc.).

    The current implementation is a thin wrapper around a list of memory
    issues; a streaming reader could replace it for very large corpora
    without changing the Skill ABC.
    """

    def __init__(
        self,
        issues: Iterable[Any],
        *,
        signature_override: str | None = None,
    ) -> None:
        self._issues = list(issues)
        # Pre-compute signature once at construction. Signature inputs
        # are the issue IDs in iteration order — assumes the upstream
        # filter (MemoryCorpus.visible_to) is deterministic.
        if signature_override is not None:
            self._signature = signature_override
        else:
            joined = "|".join(
                getattr(iss, "jira_shadow_issue_id", None)
                or getattr(iss, "issue_id", None)
                or str(id(iss))
                for iss in self._issues
            )
            self._signature = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]

    def __iter__(self):
        return iter(self._issues)

    def __len__(self) -> int:
        return len(self._issues)

    def issues(self) -> list[Any]:
        """Materialised list — useful for downstream code that needs
        random access. Returns a copy so callers can't mutate the view."""
        return list(self._issues)

    def signature(self) -> str:
        """Stable hash of this view's contents. Part of SkillCache key."""
        return self._signature

    def __repr__(self) -> str:
        return f"MemoryView(n={len(self._issues)}, sig={self._signature})"


# ---------------------------------------------------------------------------
# AgentContext — per-bundle execution context passed to every skill
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """Per-bundle execution context handed to `Skill.invoke()`.

    Carries the dependencies a skill might need:
        - `llm`: an LLMProvider (when the skill is LLM-backed)
        - `neo4j`: a Neo4j client (when the skill queries the KG)
        - `budget`: the current bundle's mutable Budget
        - `cache`: the SkillCache (skills can consult/populate it)
        - `experiment`: name (threaded into LLM telemetry)
        - `ablation`: ablation tag (similarly threaded)
        - `seed`: deterministic random seed
        - `extra`: forward-compatible slot

    Skills should treat AgentContext as a read-mostly handle — only the
    `budget` is intended to be mutated (via `budget.deduct()`).
    """

    bundle_id: str
    experiment: str = ""
    ablation: str = ""
    llm: Any | None = None                       # LLMProvider; circular-import-safe via Any
    neo4j: Any | None = None
    budget: Budget = field(default_factory=Budget)
    cache: Any | None = None                     # SkillCache; Any for cyclic-import safety
    seed: int = 42
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Skill ABC
# ---------------------------------------------------------------------------


class Skill(ABC):
    """Uniform interface every diagnostic primitive obeys.

    Concrete skills:
        - Override `name` (class attr) — registry key.
        - Override `version` — bumping invalidates SkillCache entries.
        - Override `required_flags` — capability flags needed to invoke.
        - Override `cost_class` — controller uses this to pick cheap-first.
        - Optionally override `failure_modes` — documented OOD warnings.
        - Implement `invoke()` — the actual work.

    The runner consults `can_invoke()` before `invoke()` — if False,
    the skill is silently skipped and the trace records why.

    Skills must be **stateless and thread-safe**. State across
    bundles lives in the agent's StateLayer (`state/state_layer.py`),
    not in skill instances.
    """

    #: Registry key. Must be unique across all registered skills.
    name: str = ""

    #: Semver. Bumping invalidates SkillCache for this skill.
    version: str = "0.0.0"

    #: Capability flags this skill needs. Empty = always invokable.
    required_flags: frozenset[str] = frozenset()

    #: Hint for the controller; cost-aware policies route accordingly.
    cost_class: CostClass = "medium"

    #: Documented failure modes. Surface them to the trace/eval.
    failure_modes: tuple[FailureMode, ...] = ()

    # ------------------------------------------------------------------ identity

    #: Set to True on intermediate base classes (e.g. PredictionsBackedSkill)
    #: that aren't directly instantiated and don't need a `name`. Concrete
    #: subclasses set this back to False (default) and must declare a `name`.
    __intermediate_base__: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip the check for intermediate bases (they're not instantiated
        # directly; their concrete subclasses get checked instead). Also
        # skip for any class that's still abstract by Python's ABC rules.
        if cls.__intermediate_base__:
            return
        if getattr(cls, "__abstractmethods__", None):
            return
        if not cls.name:
            raise TypeError(
                f"Skill subclass {cls.__name__} must set a non-empty `name` "
                "(or set __intermediate_base__ = True if not directly "
                "instantiated).",
            )

    # ------------------------------------------------------------------ gating

    def can_invoke(self, capabilities: Capabilities) -> bool:
        """Default: all required_flags must be present."""
        return capabilities.has_all(self.required_flags)

    # ------------------------------------------------------------------ main

    @abstractmethod
    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        """Do the work; return a SkillOutput.

        Must NOT raise for *expected* failure paths (e.g. LLM timeout
        when retries are exhausted, no candidates found). Return a
        SkillOutput with empty matched_issue_ids + low confidence
        instead — the runner records this as a skill-end event and the
        controller's fallback policy takes over.

        DO raise for *programmer* errors (wrong types, missing required
        config). The runner catches all exceptions and treats them as
        skill failures, but exceptions cost a Trace event and an
        on_failure-policy invocation, which is overkill for normal
        retrieval misses.
        """

    # ------------------------------------------------------------------ cache key

    def cache_key(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        *,
        extra_inputs: dict[str, Any] | None = None,
    ) -> str:
        """Content-addressed key for SkillCache.

        Default: SHA-256 over
            (name, version, bundle.cache_key(), memory.signature(),
             stable-repr(extra_inputs)).

        Subclasses can override to include additional state — e.g.
        `reformulate_query` mixes in the retry_count, EvidenceRequest
        skills mix in the evidence_kind hash.
        """
        parts = [
            self.name,
            self.version,
            bundle.cache_key(),
            memory.signature(),
        ]
        if extra_inputs:
            # Sort for stability across Python dict-ordering quirks
            joined = "&".join(f"{k}={extra_inputs[k]!r}" for k in sorted(extra_inputs))
            parts.append(joined)
        composite = "|".join(parts)
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()[:24]

    # ------------------------------------------------------------------ debug

    def describe(self) -> dict[str, Any]:
        """Public debug shape — used by `agent --dry-run` and the trace
        when recording skill_start events."""
        return {
            "name": self.name,
            "version": self.version,
            "cost_class": self.cost_class,
            "required_flags": sorted(self.required_flags),
            "failure_modes": [fm.to_dict() for fm in self.failure_modes],
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}@{self.version}>"


# ---------------------------------------------------------------------------
# Helpers for skills that consume the cache
# ---------------------------------------------------------------------------


def make_cost(
    *,
    llm_tokens: int = 0,
    wall_seconds: float = 0.0,
    usd: float = 0.0,
    n_calls: int = 1,
) -> SkillCallCost:
    """Convenience constructor used inside `Skill.invoke` implementations."""
    return SkillCallCost(
        llm_tokens=llm_tokens,
        wall_seconds=wall_seconds,
        usd=usd,
        n_calls=n_calls,
    )
