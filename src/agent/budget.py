"""Budget — per-window cost tracking with hard ceilings.

Tracks LLM tokens, wall seconds, USD cost, and skill-call count.
The Runner enforces hard ceilings: when a Budget is exhausted, the
next skill invocation fails fast with `BudgetExhausted`.

This is the only mutable dataclass in the agent's "data type" layer.
The Plan stores a *prototype* Budget; the Runner calls `clone()` to
get a fresh tracker per bundle.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §4.5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .types import SkillCallCost


class BudgetExhausted(Exception):
    """Raised when a skill invocation would push the Budget past a hard cap.

    The skill is NOT invoked; the runner records `budget_exceeded` in
    the Trace and the bundle's `on_failure` policy decides whether to
    fall through to a cheaper skill or abort.
    """

    def __init__(self, message: str, *, kind: str, would_be: float, cap: float) -> None:
        super().__init__(message)
        self.kind = kind            # "tokens" | "wall_seconds" | "usd" | "calls"
        self.would_be = would_be
        self.cap = cap


@dataclass
class Budget:
    """Per-window cost ceiling + counters.

    Construction sets the *caps* (max_*). The `spent_*` counters start
    at zero and are bumped by `deduct()` after each skill invocation.

    Typical lifecycle::

        prototype = Budget(max_llm_tokens=100_000, max_usd_equivalent=0.50)
        # ... stored on the Plan ...
        tracker = prototype.clone()                          # fresh counters
        while planning skills:
            cost = SkillCallCost(llm_tokens=..., usd=...)
            if not tracker.can_afford(cost):
                raise BudgetExhausted(...)
            tracker.deduct(cost)
    """

    max_llm_tokens: int = 100_000
    max_wall_seconds: float = 90.0
    max_usd_equivalent: float = 0.50
    max_skill_calls: int = 12

    spent_tokens: int = 0
    spent_seconds: float = 0.0
    spent_usd: float = 0.0
    spent_calls: int = 0

    # ------------------------------------------------------------------ queries

    def can_afford(self, cost: SkillCallCost) -> bool:
        """True iff `cost` fits under every cap. Use BEFORE invoking a skill."""
        return (
            self.spent_tokens + cost.llm_tokens <= self.max_llm_tokens
            and self.spent_seconds + cost.wall_seconds <= self.max_wall_seconds
            and self.spent_usd + cost.usd <= self.max_usd_equivalent
            and self.spent_calls + cost.n_calls <= self.max_skill_calls
        )

    def remaining(self) -> dict[str, Any]:
        return {
            "llm_tokens": self.max_llm_tokens - self.spent_tokens,
            "wall_seconds": round(self.max_wall_seconds - self.spent_seconds, 3),
            "usd": round(self.max_usd_equivalent - self.spent_usd, 6),
            "skill_calls": self.max_skill_calls - self.spent_calls,
        }

    def is_exhausted(self) -> bool:
        return (
            self.spent_tokens >= self.max_llm_tokens
            or self.spent_seconds >= self.max_wall_seconds
            or self.spent_usd >= self.max_usd_equivalent
            or self.spent_calls >= self.max_skill_calls
        )

    # ------------------------------------------------------------------ mutation

    def deduct(self, cost: SkillCallCost) -> None:
        """Charge `cost` against the budget. Raises BudgetExhausted if any
        cap would be breached AFTER deduction.

        The check + deduct are atomic from the caller's perspective; we
        compute the projected state first, decide which cap would fail,
        and either commit or raise."""
        new_tokens = self.spent_tokens + cost.llm_tokens
        new_seconds = self.spent_seconds + cost.wall_seconds
        new_usd = self.spent_usd + cost.usd
        new_calls = self.spent_calls + cost.n_calls

        if new_tokens > self.max_llm_tokens:
            raise BudgetExhausted(
                f"LLM token budget exceeded: {new_tokens} > {self.max_llm_tokens}",
                kind="tokens", would_be=new_tokens, cap=self.max_llm_tokens,
            )
        if new_seconds > self.max_wall_seconds:
            raise BudgetExhausted(
                f"Wall-clock budget exceeded: {new_seconds:.1f}s > {self.max_wall_seconds}s",
                kind="wall_seconds", would_be=new_seconds, cap=self.max_wall_seconds,
            )
        if new_usd > self.max_usd_equivalent:
            raise BudgetExhausted(
                f"USD budget exceeded: ${new_usd:.4f} > ${self.max_usd_equivalent}",
                kind="usd", would_be=new_usd, cap=self.max_usd_equivalent,
            )
        if new_calls > self.max_skill_calls:
            raise BudgetExhausted(
                f"Skill-call budget exceeded: {new_calls} > {self.max_skill_calls}",
                kind="calls", would_be=new_calls, cap=self.max_skill_calls,
            )

        # All checks passed; commit
        self.spent_tokens = new_tokens
        self.spent_seconds = new_seconds
        self.spent_usd = new_usd
        self.spent_calls = new_calls

    # ------------------------------------------------------------------ lifecycle

    def clone(self) -> "Budget":
        """Return a fresh Budget with the same caps and zeroed counters.

        Used by the Runner to get a per-bundle tracker from the
        prototype stored on the Plan."""
        return Budget(
            max_llm_tokens=self.max_llm_tokens,
            max_wall_seconds=self.max_wall_seconds,
            max_usd_equivalent=self.max_usd_equivalent,
            max_skill_calls=self.max_skill_calls,
        )

    def snapshot(self) -> "BudgetSnapshot":
        """Frozen-view snapshot for inclusion in Trace events."""
        return BudgetSnapshot(
            max_llm_tokens=self.max_llm_tokens,
            max_wall_seconds=self.max_wall_seconds,
            max_usd_equivalent=self.max_usd_equivalent,
            max_skill_calls=self.max_skill_calls,
            spent_tokens=self.spent_tokens,
            spent_seconds=self.spent_seconds,
            spent_usd=self.spent_usd,
            spent_calls=self.spent_calls,
        )

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Budget":
        return cls(
            max_llm_tokens=int(d.get("max_llm_tokens", 100_000)),
            max_wall_seconds=float(d.get("max_wall_seconds", 90.0)),
            max_usd_equivalent=float(d.get("max_usd_equivalent", 0.50)),
            max_skill_calls=int(d.get("max_skill_calls", 12)),
            spent_tokens=int(d.get("spent_tokens", 0)),
            spent_seconds=float(d.get("spent_seconds", 0.0)),
            spent_usd=float(d.get("spent_usd", 0.0)),
            spent_calls=int(d.get("spent_calls", 0)),
        )


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable copy of a Budget's state at one point in time.

    Embedded in Trace events so a replay can see exactly what budget
    remained at each skill invocation.
    """

    max_llm_tokens: int
    max_wall_seconds: float
    max_usd_equivalent: float
    max_skill_calls: int
    spent_tokens: int
    spent_seconds: float
    spent_usd: float
    spent_calls: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BudgetSnapshot":
        return cls(
            max_llm_tokens=int(d["max_llm_tokens"]),
            max_wall_seconds=float(d["max_wall_seconds"]),
            max_usd_equivalent=float(d["max_usd_equivalent"]),
            max_skill_calls=int(d["max_skill_calls"]),
            spent_tokens=int(d["spent_tokens"]),
            spent_seconds=float(d["spent_seconds"]),
            spent_usd=float(d["spent_usd"]),
            spent_calls=int(d["spent_calls"]),
        )
