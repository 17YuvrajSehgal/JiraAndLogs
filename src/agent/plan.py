"""Plan + SkillInvocation — what the Controller emits, what the Runner executes.

The controller policy lives in `agent.controller`. It inspects the
bundle + capabilities + state and returns a `Plan`. The Runner
(`agent.runner`) executes the Plan deterministically, populating the
Trace as it goes.

Plans are inspectable, hashable (via `plan_id`), and serialisable —
they can be saved to disk for ablation re-runs or replay. The
`controller_name` field records which Controller produced the Plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .budget import Budget


# A gate function inspects the Trace-so-far and the remaining Budget,
# deciding whether the next SkillInvocation should fire. The gate is
# the v1 mechanism for "only run skill X if skill Y said low confidence"
# (the cheap-first → escalate policy).
GateFn = Callable[[Any, Budget], bool]
# Note: type-hint uses Any for Trace to avoid a circular import here.


OnFailurePolicy = Literal["abort", "fallback", "continue"]


@dataclass(frozen=True)
class SkillInvocation:
    """One step of a Plan.

    - `skill_name` / `skill_version` — registry lookup keys. The
      Runner pulls the matching Skill instance and calls `.invoke()`.
    - `inputs` — extra kwargs passed to the skill (e.g. {"top_k": 5}).
      Skill-specific; the Runner forwards verbatim.
    - `per_call_budget` — Budget the Runner enforces for this call.
      Subset of the global Plan budget.
    - `on_failure` — what to do when the skill raises:
        - "fallback" → consult the Plan's fallback_chains
        - "abort"    → halt the whole Plan, emit a NEEDS_REVIEW decision
        - "continue" → skip this skill; continue with the rest
    - `gate` — optional function that decides at runtime whether to
      invoke this skill. Useful for "only verify if cheap path said
      escalate". When None, always invoked (subject to budget).
    """

    skill_name: str
    skill_version: str = "0.0.0"
    inputs: dict[str, Any] = field(default_factory=dict)
    per_call_budget: Budget = field(default_factory=Budget)
    on_failure: OnFailurePolicy = "fallback"
    gate: GateFn | None = None

    # NOTE: `gate` is intentionally NOT serialised — callables don't
    # JSON-encode cleanly. Plans deserialised from disk have gate=None,
    # which means "always invoke". For replay this is fine because the
    # Trace tells us whether the skill actually ran originally.

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "inputs": dict(self.inputs),
            "per_call_budget": self.per_call_budget.to_dict(),
            "on_failure": self.on_failure,
            "has_gate": self.gate is not None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillInvocation":
        return cls(
            skill_name=str(d["skill_name"]),
            skill_version=str(d.get("skill_version", "0.0.0")),
            inputs=dict(d.get("inputs") or {}),
            per_call_budget=Budget.from_dict(d.get("per_call_budget") or {}),
            on_failure=d.get("on_failure", "fallback"),
            gate=None,
        )


@dataclass(frozen=True)
class Plan:
    """An ordered execution plan for one bundle.

    The Runner executes `invocations` in order; for each step, it:
        1. Evaluates the `gate` (if any) against the Trace-so-far.
        2. Checks the global Budget can afford a worst-case skill cost
           (read from the SkillInvocation.per_call_budget).
        3. Invokes the skill.
        4. Records the result in the Trace.
        5. On failure, consults `on_failure` + `fallback_chains`.

    `plan_id` is a stable hash of the plan contents — useful for
    debugging ("which plan produced this AgentDecision?") and for
    replay assertions.
    """

    invocations: tuple[SkillInvocation, ...]
    global_budget: Budget = field(default_factory=Budget)
    fallback_chains: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # `controller_name` records which Controller produced the Plan —
    # used by ablations comparing RuleController, CapabilityAwareRuleController,
    # and (future) LearnedController.
    controller_name: str = "rule"
    plan_id: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id:
            object.__setattr__(self, "plan_id", self._compute_plan_id())

    def _compute_plan_id(self) -> str:
        """SHA-1 over the serialised invocation list + budget caps.

        Stable across runs: the same controller given the same inputs
        produces the same plan_id."""
        signature = {
            "controller": self.controller_name,
            "budget": {
                "max_llm_tokens": self.global_budget.max_llm_tokens,
                "max_wall_seconds": self.global_budget.max_wall_seconds,
                "max_usd_equivalent": self.global_budget.max_usd_equivalent,
                "max_skill_calls": self.global_budget.max_skill_calls,
            },
            "invocations": [
                {
                    "skill_name": inv.skill_name,
                    "skill_version": inv.skill_version,
                    "inputs": inv.inputs,
                    "on_failure": inv.on_failure,
                    "has_gate": inv.gate is not None,
                }
                for inv in self.invocations
            ],
            "fallback_chains": {
                k: list(v) for k, v in self.fallback_chains.items()
            },
        }
        canon = json.dumps(signature, sort_keys=True, default=str)
        return "plan_" + hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]

    # ------------------------------------------------------------------ ablation

    def with_disabled_skills(self, disabled: set[str]) -> "Plan":
        """Return a Plan with the named skills removed from `invocations`.

        Used by the §9 ablation harness. The plan_id is recomputed."""
        new_invocations = tuple(
            inv for inv in self.invocations
            if inv.skill_name not in disabled
        )
        return Plan(
            invocations=new_invocations,
            global_budget=self.global_budget,
            fallback_chains={
                k: tuple(s for s in v if s not in disabled)
                for k, v in self.fallback_chains.items()
                if k not in disabled
            },
            controller_name=self.controller_name,
            plan_id="",
        )

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "controller_name": self.controller_name,
            "global_budget": self.global_budget.to_dict(),
            "fallback_chains": {
                k: list(v) for k, v in self.fallback_chains.items()
            },
            "invocations": [inv.to_dict() for inv in self.invocations],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(
            invocations=tuple(
                SkillInvocation.from_dict(i) for i in (d.get("invocations") or ())
            ),
            global_budget=Budget.from_dict(d.get("global_budget") or {}),
            fallback_chains={
                k: tuple(v) for k, v in (d.get("fallback_chains") or {}).items()
            },
            controller_name=str(d.get("controller_name", "rule")),
            # plan_id is recomputed in __post_init__ unless we explicitly
            # accept the deserialised one. For replay-correctness we
            # accept it.
            plan_id=str(d.get("plan_id", "")),
        )

    # ------------------------------------------------------------------ debug

    def __repr__(self) -> str:
        names = ",".join(inv.skill_name for inv in self.invocations)
        return f"Plan({self.plan_id} {self.controller_name} [{names}])"
