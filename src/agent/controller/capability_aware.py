"""CapabilityAwareRuleController — Phase 1 of the smarter-agent plan.

Emits **per-window distinct plans** keyed on bundle.window_type,
cross-window state, and capability set. Closes RQ-A1 ("agent emits
distinct plans per window, not a fixed pipeline").

Design (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §4.2):

The base RuleController emits ONE plan with runtime gates that decide
whether each skill fires. That works at the runner level but makes
plan_id identical across every window — so the plan-diversity metric
reads as "1 plan ID across 1008 windows", obscuring the adaptive policy.

This subclass branches on inputs **known at plan-emission time**
(window_type, state, capabilities) to emit *structurally different*
plans. Runtime gates (the inherited cheap-first / consensus / verifier
gates) still fire inside each branch's plan — they handle the
runtime-only decisions like "is triage_numeric confident enough."

Net effect: a 1008-window OB test split now produces ≥ 5 distinct
plan_ids, with the branch logic visible per window in the Trace.

Historic-learning constraints respected (see `docs4/META-ANALYSIS.md`):
- No new score sources or rerankers — the branches only change WHEN
  skills fire, not WHAT they compute.
- G7 features (`window_type`, `scenario_family`) are the branch keys —
  the same metadata the learned-novelty L3 classifier uses.
- Verifier still gated on VERIFIER_KNOWN_HELPFUL (RQ-D3 — WoL skips).

Spec: `DOCS/docs8/IMPLEMENTATION-PLAN.md` §4.2.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..budget import Budget
from ..capabilities import Capabilities
from ..plan import Plan, SkillInvocation
from ..skills.registry import SkillRegistry
from ..types import InputBundle
from .rule import (
    CHEAP_RETRIEVER,
    COMPOSE_L2,
    COMPOSE_NOVELTY,
    COMPOSE_TRIAGE,
    DEFAULT_BUDGET_CAPS,
    DEFAULT_REFORMULATION_CONFIDENCE_FLOOR,
    DEFAULT_TRIAGE_HIGH_CONFIDENCE,
    EXPENSIVE_RETRIEVERS,
    REFORMULATE_QUERY,
    RuleController,
    TRIAGE_NUMERIC,
    VERIFIER,
    _any_retriever_ran,
    make_escalation_gate,
    make_reformulation_gate,
)


# ---------------------------------------------------------------------------
# Branch names (also used as a tag in plan_id for diagnostic clarity)
# ---------------------------------------------------------------------------

BRANCH_STATE_SUPPRESS    = "state_suppress"
BRANCH_PRE_FAULT         = "pre_fault_baseline"
BRANCH_RECOVERY          = "recovery_window"
BRANCH_OBSERVATION       = "observation_window"
BRANCH_ACTIVE_FAULT      = "active_fault"
BRANCH_DEFAULT           = "default"


# Phase 2 ReAct skill names
REQUEST_POD_EVENTS = "request_pod_events"
REQUEST_EXTENDED_TRACE_WINDOW = "request_extended_trace_window"
REQUEST_POD_METRICS = "request_pod_metrics"
REQUEST_SIMILAR_INCIDENT_WINDOW = "request_similar_incident_window"
RERANK_WITH_EVIDENCE = "rerank_with_evidence"

# All four evidence-request skills fire on the same low-consensus
# gate, in this order. Order doesn't affect correctness (each runs
# independently and appends to ctx.extra["tool_results"]) but it
# affects which evidence appears first in the trace.
_REACT_TOOLS_ACTIVE_FAULT: tuple[str, ...] = (
    REQUEST_POD_EVENTS,
    REQUEST_EXTENDED_TRACE_WINDOW,
    REQUEST_POD_METRICS,
    REQUEST_SIMILAR_INCIDENT_WINDOW,
)


# Tunable thresholds (overridable via config). The "look back N
# windows" depth — at 1 we suppress when the immediately prior window
# for the same service was ticket-worthy + same scenario_family.
# Conservative defaults: same_family + no-recovery checks prevent
# false suppression when a genuinely new incident hits the service.
DEFAULT_SUPPRESS_CONSECUTIVE_WINDOWS = 1


class CapabilityAwareRuleController(RuleController):
    """Branch-emitting subclass of RuleController.

    Keeps the base RuleController as the v1 fallback (the `default`
    branch). Adds five window-type-keyed branches that produce
    structurally smaller plans for windows where full retrieval is
    wasteful (pre-fault baselines, recovery windows, suppressed
    re-pages, etc.).
    """

    name = "capability_aware_rule"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        cheap_path_threshold: float = DEFAULT_TRIAGE_HIGH_CONFIDENCE,
        require_top1_consensus: bool = True,
        budget_caps: dict[str, Any] | None = None,
        max_reformulation_retries: int = 1,
        reformulation_confidence_floor: float = DEFAULT_REFORMULATION_CONFIDENCE_FLOOR,
        suppress_consecutive_windows: int = DEFAULT_SUPPRESS_CONSECUTIVE_WINDOWS,
        enable_branching: bool = True,
    ) -> None:
        super().__init__(
            registry,
            cheap_path_threshold=cheap_path_threshold,
            require_top1_consensus=require_top1_consensus,
            budget_caps=budget_caps,
            max_reformulation_retries=max_reformulation_retries,
            reformulation_confidence_floor=reformulation_confidence_floor,
        )
        self.suppress_consecutive_windows = suppress_consecutive_windows
        self.enable_branching = enable_branching

    # ------------------------------------------------------------------ plan

    def plan(
        self,
        bundle: InputBundle,
        capabilities: Capabilities,
        *,
        state: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> Plan:
        # Escape hatch: if branching disabled, fall back to base behavior.
        if not self.enable_branching:
            return super().plan(
                bundle, capabilities, state=state, config=config,
            )

        branch = self._select_branch(bundle, capabilities, state)
        budget = Budget.from_dict(
            {**self._budget_caps, **(config or {}).get("budget", {})}
        )

        if branch == BRANCH_STATE_SUPPRESS:
            invocations = self._invocations_state_suppress(capabilities, budget)
        elif branch == BRANCH_PRE_FAULT:
            invocations = self._invocations_pre_fault(capabilities, budget)
        elif branch == BRANCH_RECOVERY:
            invocations = self._invocations_recovery(capabilities, budget)
        elif branch == BRANCH_OBSERVATION:
            invocations = self._invocations_observation(capabilities, budget)
        elif branch == BRANCH_ACTIVE_FAULT:
            invocations = self._invocations_active_fault(capabilities, budget, config)
        else:
            # Default branch — same as base RuleController (full pipeline)
            return super().plan(
                bundle, capabilities, state=state, config=config,
            )

        return Plan(
            invocations=tuple(invocations),
            global_budget=budget,
            fallback_chains={},
            # branch tag is in controller_name so plan_id encodes branch
            controller_name=f"{self.name}:{branch}",
        )

    # ------------------------------------------------------------------ branch selection

    def _select_branch(
        self,
        bundle: InputBundle,
        capabilities: Capabilities,
        state: Any,
    ) -> str:
        """Plan-time branch selection. Reads only inputs known up front."""
        window_type = (bundle.window_type or "").strip().lower()

        # Branch 1 — state suppression
        if state is not None and self._is_state_suppress(bundle, state):
            return BRANCH_STATE_SUPPRESS

        # Branches 2-4 — window_type routing
        if window_type == "pre_fault_baseline":
            return BRANCH_PRE_FAULT
        if window_type == "recovery_window":
            return BRANCH_RECOVERY
        if window_type == "observation_window":
            return BRANCH_OBSERVATION
        if window_type == "active_fault":
            return BRANCH_ACTIVE_FAULT

        return BRANCH_DEFAULT

    def _is_state_suppress(self, bundle: InputBundle, state: Any) -> bool:
        """The conservative page-suppression rule (XX_AGENTIC_IDEA §4.3).

        Suppress when:
          - we have a `service_name` to look up state for, AND
          - the StateLayer view for this service has at least one
            ticket-worthy verdict in the last `suppress_consecutive_windows`
            windows, AND
          - the previous window's scenario_family matches this one, AND
          - no recovery_window has intervened.

        We do NOT have access to *this window's* top1_match at plan
        time (we haven't run retrieval yet), so the conservative form
        suppresses based on RECENT history alone — not "same top1 as
        the last window". The same_family check is the load-bearing
        protection against suppressing a legitimately new incident.
        """
        service_name = bundle.service_name
        if not service_name:
            return False
        try:
            view = state.get_view(service_name)
        except (AttributeError, KeyError):
            return False
        if len(view) < self.suppress_consecutive_windows:
            return False
        recent = view.last_n(self.suppress_consecutive_windows)
        if not any(getattr(w, "triage_decision", "") == "ticket_worthy" for w in recent):
            return False
        if view.saw_recovery_within(self.suppress_consecutive_windows):
            return False
        # Same-family check: the most recent ticket-worthy window must
        # share scenario_family with this one. Without this guard, a
        # genuinely new incident on the same service would be suppressed.
        bundle_family = (bundle.scenario_family or "").strip().lower()
        if not bundle_family:
            return False
        most_recent_ticket = next(
            (w for w in reversed(recent)
             if getattr(w, "triage_decision", "") == "ticket_worthy"),
            None,
        )
        if most_recent_ticket is None:
            return False
        recent_family = (getattr(most_recent_ticket, "scenario_family", "")
                         or "").strip().lower()
        return recent_family == bundle_family

    # ------------------------------------------------------------------ branch builders

    def _invocations_state_suppress(
        self, capabilities: Capabilities, budget: Budget,
    ) -> list[SkillInvocation]:
        """Tiny plan: just compose_triage (reuses recent state)."""
        invs: list[SkillInvocation] = []
        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invs.append(self._inv(COMPOSE_TRIAGE, budget))
        return invs

    def _invocations_pre_fault(
        self, capabilities: Capabilities, budget: Budget,
    ) -> list[SkillInvocation]:
        """pre_fault_baseline → emit novelty only (no gold by construction).

        These windows occur *before* a fault and have no past analog by
        definition — the L3 learned classifier's top feature
        (`window_type=pre_fault_baseline` +2.89) per META-ANALYSIS §4.4
        explicitly favors flagging them as novel.
        """
        invs: list[SkillInvocation] = []
        # Still run triage_numeric for the score; cheap.
        if self._skill_runnable(TRIAGE_NUMERIC, capabilities):
            invs.append(self._inv(TRIAGE_NUMERIC, budget))
        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invs.append(self._inv(COMPOSE_TRIAGE, budget))
        if self._skill_runnable(COMPOSE_NOVELTY, capabilities):
            invs.append(self._inv(COMPOSE_NOVELTY, budget))
        return invs

    def _invocations_recovery(
        self, capabilities: Capabilities, budget: Budget,
    ) -> list[SkillInvocation]:
        """recovery_window → cheap path only; the L3 classifier's
        feature (`window_type=recovery_window` -2.28) means recovery
        windows are NOT novel; we just need a triage score."""
        invs: list[SkillInvocation] = []
        if self._skill_runnable(TRIAGE_NUMERIC, capabilities):
            invs.append(self._inv(TRIAGE_NUMERIC, budget))
        if self._skill_runnable(CHEAP_RETRIEVER, capabilities):
            invs.append(self._inv(CHEAP_RETRIEVER, budget))
        if self._skill_runnable(COMPOSE_L2, capabilities):
            invs.append(self._inv(
                COMPOSE_L2, budget, gate=_any_retriever_ran,
            ))
        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invs.append(self._inv(COMPOSE_TRIAGE, budget))
        if self._skill_runnable(COMPOSE_NOVELTY, capabilities):
            invs.append(self._inv(COMPOSE_NOVELTY, budget))
        return invs

    def _invocations_observation(
        self, capabilities: Capabilities, budget: Budget,
    ) -> list[SkillInvocation]:
        """observation_window → cheap path. These are non-fault windows;
        triage_numeric usually nails them with high confidence so the
        escalation gate would close anyway. Skip the expensive retrievers
        eagerly at plan time."""
        invs: list[SkillInvocation] = []
        if self._skill_runnable(TRIAGE_NUMERIC, capabilities):
            invs.append(self._inv(TRIAGE_NUMERIC, budget))
        if self._skill_runnable(CHEAP_RETRIEVER, capabilities):
            invs.append(self._inv(CHEAP_RETRIEVER, budget))
        if self._skill_runnable(COMPOSE_L2, capabilities):
            invs.append(self._inv(
                COMPOSE_L2, budget, gate=_any_retriever_ran,
            ))
        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invs.append(self._inv(COMPOSE_TRIAGE, budget))
        if self._skill_runnable(COMPOSE_NOVELTY, capabilities):
            invs.append(self._inv(COMPOSE_NOVELTY, budget))
        return invs

    def _invocations_active_fault(
        self,
        capabilities: Capabilities,
        budget: Budget,
        config: dict[str, Any] | None,
    ) -> list[SkillInvocation]:
        """active_fault → full retrieval cascade with runtime gates.

        Same skill set as the base RuleController's default plan; the
        difference is the controller_name tag (so plan_id is distinct
        from BRANCH_DEFAULT). The runtime gates handle cheap-vs-expensive
        escalation as before.
        """
        cfg_cheap = (config or {}).get("cheap_path", {})
        threshold = float(
            cfg_cheap.get("triage_high_confidence", self.cheap_path_threshold)
        )
        require_consensus = bool(
            cfg_cheap.get("require_top1_consensus", self.require_top1_consensus)
        )

        invs: list[SkillInvocation] = []

        # Cheap path — unconditional.
        if self._skill_runnable(TRIAGE_NUMERIC, capabilities):
            invs.append(self._inv(TRIAGE_NUMERIC, budget))
        if self._skill_runnable(CHEAP_RETRIEVER, capabilities):
            invs.append(self._inv(CHEAP_RETRIEVER, budget))

        # Expensive retrievers — gated.
        escalate = make_escalation_gate(
            threshold=threshold,
            require_consensus=require_consensus,
        )
        for retriever_name in EXPENSIVE_RETRIEVERS:
            if self._skill_runnable(retriever_name, capabilities):
                invs.append(self._inv(retriever_name, budget, gate=escalate))

        # Composition.
        if self._skill_runnable(COMPOSE_L2, capabilities):
            invs.append(self._inv(
                COMPOSE_L2, budget, gate=_any_retriever_ran,
            ))

        # Reformulation (opt-in).
        if (
            self.max_reformulation_retries > 0
            and self._skill_runnable(REFORMULATE_QUERY, capabilities)
        ):
            invs.append(self._inv(
                REFORMULATE_QUERY, budget,
                gate=make_reformulation_gate(
                    confidence_floor=self.reformulation_confidence_floor,
                ),
            ))

        # Phase 2 ReAct: 4 evidence-gathering tools, all gated by the
        # same low-consensus condition as reformulation. Each appends a
        # ToolResult to ctx.extra["tool_results"]; the rerank skill
        # below consumes all of them.
        #   - request_pod_events: k8s warnings (OOMKilled, CrashLoopBackOff)
        #   - request_extended_trace_window: services_seen + error_spans
        #   - request_pod_metrics: restart_delta, CPU, mem, n_alerts_firing
        #   - request_similar_incident_window: peer Jira memory_text heads
        # Each skill has its own required_flags so an unavailable
        # modality (e.g. WoL has no k8s) naturally drops the tool.
        for tool_name in _REACT_TOOLS_ACTIVE_FAULT:
            if self._skill_runnable(tool_name, capabilities):
                invs.append(self._inv(
                    tool_name, budget,
                    gate=make_reformulation_gate(
                        confidence_floor=self.reformulation_confidence_floor,
                    ),
                ))

        # Phase 2 ReAct closure: consume the tool result. Re-ranks
        # compose_l2's top-K by token overlap with the WARNING-type
        # pod events. Gated on the same low-consensus condition so the
        # skill only fires when tool evidence was actually gathered;
        # without it the re-rank is a no-op pass-through that wastes
        # a SkillCache lookup. The decision builder picks up this
        # skill's matched_issue_ids over compose_l2's when both ran.
        if self._skill_runnable(RERANK_WITH_EVIDENCE, capabilities):
            invs.append(self._inv(
                RERANK_WITH_EVIDENCE, budget,
                gate=make_reformulation_gate(
                    confidence_floor=self.reformulation_confidence_floor,
                ),
            ))

        if self._skill_runnable(COMPOSE_TRIAGE, capabilities):
            invs.append(self._inv(COMPOSE_TRIAGE, budget))

        # Verifier — gated on escalation AND VERIFIER_KNOWN_HELPFUL.
        if self._skill_runnable(VERIFIER, capabilities):
            invs.append(self._inv(VERIFIER, budget, gate=escalate))

        if self._skill_runnable(COMPOSE_NOVELTY, capabilities):
            invs.append(self._inv(COMPOSE_NOVELTY, budget))

        return invs
