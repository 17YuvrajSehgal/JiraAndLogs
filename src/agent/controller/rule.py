"""RuleController — v1 hand-tuned cheap-first / escalate policy.

The cheap path runs `triage_numeric` (when available) + `retrieve_dense`.
If both are confident, the expensive retrievers and the verifier are
skipped at runtime via per-invocation `gate` functions. Otherwise the
runner escalates: hybrid + log-sequence + KG run; then composition;
then verifier; then novelty.

Capability gating happens at plan-emission time: skills whose
`required_flags` aren't satisfied are NEVER included. Runtime gates
only express "skip because cheap path is confident" — they can't
re-enable a skill that capabilities ruled out.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §5, §6.2, `XX_AGENTIC_IDEA.md` §4.1.
"""

from __future__ import annotations

from typing import Any

from ..budget import Budget
from ..capabilities import Capabilities
from ..plan import GateFn, Plan, SkillInvocation
from ..skills.registry import SkillRegistry
from ..trace import Trace
from ..types import InputBundle
from .base import Controller


# ---------------------------------------------------------------------------
# Default policy constants
# ---------------------------------------------------------------------------

#: Triage_numeric score >= this means HGB is confident enough to short-circuit
#: the expensive path (modulo the BiEncoder consensus check).
DEFAULT_TRIAGE_HIGH_CONFIDENCE = 0.90

#: BiEncoder must return at least this many matches to count as "consensus".
DEFAULT_MIN_TOP_K_MATCHES = 1

#: Plan-level budget caps. Mirrors agent-config.yaml > budget defaults
#: but can be overridden via the `config` arg to .plan().
DEFAULT_BUDGET_CAPS = {
    "max_llm_tokens": 100_000,
    "max_wall_seconds": 90.0,
    "max_usd_equivalent": 0.50,
    "max_skill_calls": 12,
}


# ---------------------------------------------------------------------------
# Skill name constants — match the registry keys in src/agent/skills/retrievers.py
# ---------------------------------------------------------------------------

CHEAP_RETRIEVER = "retrieve_dense"
TRIAGE_NUMERIC = "triage_numeric"

EXPENSIVE_RETRIEVERS = (
    "retrieve_log_sequence",
    "retrieve_hybrid_fusion",
    "retrieve_hybrid_fusion_llm",
    "retrieve_knowledge_graph",
)

VERIFIER = "verify_with_llm"

COMPOSE_L2 = "compose_l2"
COMPOSE_TRIAGE = "compose_triage"
COMPOSE_NOVELTY = "compose_novelty"

REFORMULATE_QUERY = "reformulate_query"

#: Max retriever-confidence below which compose_l2 is treated as
#: "consensus failed" — triggers reformulation when enabled.
DEFAULT_REFORMULATION_CONFIDENCE_FLOOR = 0.5


# ---------------------------------------------------------------------------
# RuleController
# ---------------------------------------------------------------------------


class RuleController(Controller):
    """Hand-tuned cheap-first / escalate policy.

    Construction takes the SkillRegistry — the controller can only
    reference registered skills. Ablations work by pre-pruning the
    registry (via SkillRegistry.copy_without / copy_only) BEFORE
    constructing the controller; the controller's plan() automatically
    omits unregistered skills.

    Args:
        registry: the (possibly already-ablated) SkillRegistry.
        cheap_path_threshold: triage_numeric.score >= this passes the
            cheap-path gate (default 0.9, matching agent-config.yaml).
        require_top1_consensus: bool. When True (default), the cheap
            path also requires retrieve_dense to return >= 1 match.
        budget_caps: dict of (kind -> cap) overriding DEFAULT_BUDGET_CAPS.
    """

    name = "rule"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        cheap_path_threshold: float = DEFAULT_TRIAGE_HIGH_CONFIDENCE,
        require_top1_consensus: bool = True,
        budget_caps: dict[str, Any] | None = None,
        max_reformulation_retries: int = 0,
        reformulation_confidence_floor: float = DEFAULT_REFORMULATION_CONFIDENCE_FLOOR,
    ) -> None:
        """
        Reformulation knobs (opt-in, off by default):

            max_reformulation_retries: when > 0 AND reformulate_query is
                registered, the Plan includes a reformulate_query step
                gated on "compose_l2 emitted a low-confidence result".
                Default 0 — reformulation is opt-in.
            reformulation_confidence_floor: max retriever triage_score
                below which compose_l2 is treated as "consensus failed"
                — the gate then opens. Default 0.5.

        Because the Plan model is static (controller emits one Plan
        per bundle), the reformulation hook produces ONE reformulated
        query — recorded in the trace as
        SkillOutput.extra["reformulated_query"]. Re-running retrievers
        on it would require a live-retrieval mode; for now this is an
        instrumentation hook + a measurement of how often the
        reformulation gate fires.
        """
        self.registry = registry
        self.cheap_path_threshold = cheap_path_threshold
        self.require_top1_consensus = require_top1_consensus
        self._budget_caps = {**DEFAULT_BUDGET_CAPS, **(budget_caps or {})}
        self.max_reformulation_retries = max_reformulation_retries
        self.reformulation_confidence_floor = reformulation_confidence_floor

    # ------------------------------------------------------------------ plan

    def plan(
        self,
        bundle: InputBundle,
        capabilities: Capabilities,
        *,
        state: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> Plan:
        del state, bundle    # RuleController ignores; CapabilityAwareRuleController reads them

        # Apply per-call config overrides (don't mutate self).
        cfg = (config or {}).get("cheap_path", {})
        threshold = float(cfg.get("triage_high_confidence", self.cheap_path_threshold))
        require_consensus = bool(
            cfg.get("require_top1_consensus", self.require_top1_consensus)
        )

        budget = Budget.from_dict({**self._budget_caps, **(config or {}).get("budget", {})})

        invocations: list[SkillInvocation] = []
        fallback_chains: dict[str, tuple[str, ...]] = {}

        # ------------------------------------------------------------------ cheap path
        # Skills here run UNCONDITIONALLY (no gate). The cheap-path
        # confidence check is read by *later* gates to decide whether to
        # escalate.

        if self._skill_runnable(TRIAGE_NUMERIC, capabilities):
            invocations.append(self._inv(TRIAGE_NUMERIC, budget))

        if self._skill_runnable(CHEAP_RETRIEVER, capabilities):
            invocations.append(self._inv(CHEAP_RETRIEVER, budget))

        # ------------------------------------------------------------------ escalation gate
        # Closure: captures the cheap-path threshold + consensus rule.
        # Returns True ⇒ "escalation needed, invoke me"; False ⇒ skip.
        escalation_gate = make_escalation_gate(
            threshold=threshold,
            require_consensus=require_consensus,
        )

        # ------------------------------------------------------------------ expensive retrievers
        # Gated on "escalation_needed". Order matches the cascade's
        # L2 retriever set so plan_id stability is intuitive.
        for retriever_name in EXPENSIVE_RETRIEVERS:
            if self._skill_runnable(retriever_name, capabilities):
                invocations.append(self._inv(retriever_name, budget, gate=escalation_gate))

        # ------------------------------------------------------------------ composition
        # compose_l2 always runs (when registered) — even on the cheap
        # path, the BiEncoder ranking needs to be wrapped into a
        # SkillOutput the runner can emit. The gate skips compose_l2
        # only if no retrievers ran at all (degenerate bundle).
        if self._skill_runnable(COMPOSE_L2, capabilities):
            invocations.append(self._inv(
                COMPOSE_L2, budget,
                gate=_any_retriever_ran,
            ))

        # ------------------------------------------------------------------ reformulation (opt-in)
        # When max_reformulation_retries > 0 AND the reformulate_query
        # skill is registered, emit it AFTER compose_l2 with a gate that
        # opens iff compose_l2 produced a low-confidence ranking — the
        # "L2 disagreed; try a reformulated query" signal.
        if (
            self.max_reformulation_retries > 0
            and self._skill_runnable(REFORMULATE_QUERY, capabilities)
        ):
            reform_gate = make_reformulation_gate(
                confidence_floor=self.reformulation_confidence_floor,
            )
            invocations.append(self._inv(
                REFORMULATE_QUERY, budget,
                gate=reform_gate,
            ))

        # compose_triage always runs — falls back to score=0 when no
        # triage skills produced output.
        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invocations.append(self._inv(COMPOSE_TRIAGE, budget))

        # ------------------------------------------------------------------ verifier
        # Verifier is gated on (escalation needed) AND (VERIFIER_KNOWN_HELPFUL
        # in capabilities). The capability check is already enforced by
        # `_skill_runnable` (verify_with_llm declares VERIFIER_KNOWN_HELPFUL
        # in required_flags), so here we only need the escalation gate.
        if self._skill_runnable(VERIFIER, capabilities):
            invocations.append(self._inv(VERIFIER, budget, gate=escalation_gate))

        # ------------------------------------------------------------------ novelty
        # Always last, when registered. Reads the verifier output (when
        # the verifier ran) + the retriever triage_scores (free signal) +
        # the learned classifier (Phase 2).
        if self._skill_runnable(COMPOSE_NOVELTY, capabilities):
            invocations.append(self._inv(COMPOSE_NOVELTY, budget))

        return Plan(
            invocations=tuple(invocations),
            global_budget=budget,
            fallback_chains=fallback_chains,
            controller_name=self.name,
        )

    # ------------------------------------------------------------------ helpers

    def _skill_runnable(self, name: str, capabilities: Capabilities) -> bool:
        """A skill is included iff registered AND its required_flags
        are present in capabilities."""
        skill = self.registry.try_get(name)
        if skill is None:
            return False
        return skill.can_invoke(capabilities)

    def _inv(
        self,
        name: str,
        global_budget: Budget,
        *,
        gate: GateFn | None = None,
    ) -> SkillInvocation:
        """Build a SkillInvocation with the skill's registered version.

        Per-call budget inherits the global budget caps; the Runner
        decides at execution time whether the skill fits."""
        skill = self.registry.get(name)
        return SkillInvocation(
            skill_name=name,
            skill_version=skill.version,
            inputs={},
            per_call_budget=global_budget.clone(),
            on_failure="fallback",
            gate=gate,
        )


# ---------------------------------------------------------------------------
# Gate functions — closures the controller bakes into the Plan
# ---------------------------------------------------------------------------


def make_escalation_gate(
    *,
    threshold: float = DEFAULT_TRIAGE_HIGH_CONFIDENCE,
    require_consensus: bool = True,
    min_matches: int = DEFAULT_MIN_TOP_K_MATCHES,
) -> GateFn:
    """Return a gate `(trace, budget) -> bool` for escalation-only skills.

    Returns True when the cheap path was NOT confident, meaning the
    expensive skill SHOULD run. Returns False when the cheap path IS
    confident, meaning the skill SHOULD be skipped.

    Cheap-path-confident criteria:
      - triage_numeric ran AND its triage_score >= threshold
      - retrieve_dense ran AND emitted >= min_matches matched_issue_ids
        (only checked when require_consensus is True)

    When triage_numeric didn't run (e.g. WoL — no numeric_features),
    cheap path can't be confident → escalate always.

    When retrieve_dense didn't run (degenerate bundle), cheap path
    can't be confident → escalate always.
    """
    def _gate(trace: Trace, budget) -> bool:    # noqa: ARG001 — budget unused in v1 gate
        del budget
        # Look up cheap-path outputs from the trace
        triage_out = trace.latest_output(TRIAGE_NUMERIC)
        dense_out = trace.latest_output(CHEAP_RETRIEVER)

        # If triage_numeric didn't run or didn't produce a score, we
        # have no triage signal — escalate.
        if triage_out is None or triage_out.triage_score is None:
            return True
        if float(triage_out.triage_score) < threshold:
            return True

        if require_consensus:
            if dense_out is None or len(dense_out.matched_issue_ids) < min_matches:
                return True

        # Both cheap-path checks passed — skip the expensive skill.
        return False

    _gate.__name__ = "escalation_gate"
    return _gate


def _any_retriever_ran(trace: Trace, budget) -> bool:
    """Compose_l2 gate: run iff at least one retriever produced output."""
    del budget
    for r in (CHEAP_RETRIEVER, *EXPENSIVE_RETRIEVERS):
        out = trace.latest_output(r)
        if out is not None and out.matched_issue_ids:
            return True
    return False


# ---------------------------------------------------------------------------
# Reformulation gate
# ---------------------------------------------------------------------------


def make_reformulation_gate(
    *,
    confidence_floor: float = DEFAULT_REFORMULATION_CONFIDENCE_FLOOR,
) -> GateFn:
    """Return a gate that opens when L2 consensus failed.

    Definition of "consensus failed" (XX_AGENTIC_IDEA §4.2):
      - compose_l2 ran AND
      - max retriever triage_score over the L2 set < `confidence_floor`.

    When the floor is met, the gate stays closed (no point reformulating
    if retrieval was already confident). When compose_l2 didn't run at
    all, the gate also stays closed — reformulation only fires after a
    failed first-pass retrieval, never as a cold start.
    """
    def _gate(trace: Trace, budget) -> bool:                       # noqa: ARG001
        del budget
        # Cold start — no compose_l2 output yet → don't reformulate.
        if trace.latest_output(COMPOSE_L2) is None:
            return False

        # Inspect the L2 retriever set's max confidence.
        max_conf = 0.0
        for r in (CHEAP_RETRIEVER, *EXPENSIVE_RETRIEVERS):
            out = trace.latest_output(r)
            if out is None or out.triage_score is None:
                continue
            max_conf = max(max_conf, float(out.triage_score))

        # Below the floor → consensus failed → open the gate.
        return max_conf < confidence_floor

    _gate.__name__ = "reformulation_gate"
    return _gate
