"""EvalHarness — composes Controller + Runner + StateLayer over cases.

Per-case lifecycle::

    capabilities = observer.observe(bundle, ctx)
    view = state_layer.get_view(bundle.service_name)          # optional
    plan = controller.plan(bundle, capabilities, state=view)
    decision = runner.run(plan, bundle, memory,
                          evaluation_mode=contract.evaluation_mode)
    if decision.evaluation_mode != contract.evaluation_mode:
        raise EvaluationModeMismatch(...)                     # §14 refusal
    if state_layer and apply_page_suppression:
        result = state_layer.check_page_suppression(...)
        if result.suppress:
            decision ← downgrade ticket_worthy → borderline + attach incident_id
    state_layer.record(WindowState.from_decision(decision, bundle))
    case_results.append(_score(decision, case))

After iterating all cases, the harness aggregates retrieval / triage /
novelty / pages-per-incident metrics into an `EvaluationReport`.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §12 (apples-to-apples), §14 (WoL
framing), §7 (state-driven page-suppression).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Iterable

from ..capabilities_observer import CapabilitiesObserver, ObservationContext
from ..controller import Controller
from ..runner import AgentRunner
from ..state import PageSuppressionResult, StateLayer, WindowState
from ..types import AgentDecision, SkillCallCost
from .exceptions import EvaluationModeMismatch
from .metrics import (
    hit_at_k,
    pages_per_incident,
    reciprocal_rank,
)
from .types import (
    ApplesToApplesContract,
    CaseResult,
    EvaluationCase,
    EvaluationReport,
)


log = logging.getLogger(__name__)


class EvalHarness:
    """Orchestrator that runs the agent over a stream of EvaluationCases.

    Args:
        controller: Controller subclass (typically RuleController).
        runner: AgentRunner instance (wired to the same SkillRegistry
            the controller targeted).
        observer: CapabilitiesObserver (defaults to a stateless instance).
        observation_ctx: ObservationContext passed to the observer for
            every case. None ⇒ a default ObservationContext().
        state_layer: optional StateLayer for cross-window state +
            page-suppression. When None, the harness runs each case
            in isolation (no suppression, no stateful hints).
        apply_page_suppression: when True (default) and a state layer
            is set, the harness applies §7.2 suppression.
    """

    def __init__(
        self,
        controller: Controller,
        runner: AgentRunner,
        *,
        observer: CapabilitiesObserver | None = None,
        observation_ctx: ObservationContext | None = None,
        state_layer: StateLayer | None = None,
        apply_page_suppression: bool = True,
    ) -> None:
        self.controller = controller
        self.runner = runner
        self.observer = observer or CapabilitiesObserver()
        self.observation_ctx = observation_ctx or ObservationContext()
        self.state_layer = state_layer
        self.apply_page_suppression = apply_page_suppression

    # ------------------------------------------------------------------ evaluate

    def evaluate(
        self,
        cases: Iterable[EvaluationCase],
        *,
        contract: ApplesToApplesContract,
        experiment_name: str = "eval",
        ablation: str = "",
        keep_case_details: bool = True,
    ) -> EvaluationReport:
        """Run the agent over every case; return an EvaluationReport.

        Raises:
            EvaluationModeMismatch: if any decision's evaluation_mode
                disagrees with `contract.evaluation_mode`.
        """
        case_list = list(cases)
        case_results: list[CaseResult] = []
        plan_ids: list[str] = []

        for case in case_list:
            result = self._evaluate_one(
                case=case,
                contract=contract,
                ablation=ablation,
                experiment_name=experiment_name,
            )
            case_results.append(result)
            if result.decision.plan_id and result.decision.plan_id not in plan_ids:
                plan_ids.append(result.decision.plan_id)

        report = self._aggregate(
            case_results=case_results,
            contract=contract,
            experiment_name=experiment_name,
            ablation=ablation,
            plan_ids=plan_ids,
            keep_case_details=keep_case_details,
        )
        return report

    # ------------------------------------------------------------------ per-case

    def _evaluate_one(
        self,
        *,
        case: EvaluationCase,
        contract: ApplesToApplesContract,
        ablation: str,
        experiment_name: str,
    ) -> CaseResult:
        # 1. Observe capabilities
        capabilities = self.observer.observe(case.bundle, self.observation_ctx)

        # 2. Read state (if a state layer is wired)
        state_view = None
        if self.state_layer is not None:
            state_view = self.state_layer.get_view(case.bundle.service_name or "")

        # 3. Plan
        plan = self.controller.plan(
            case.bundle, capabilities, state=state_view,
        )

        # 4. Run — let the runner auto-infer evaluation_mode from
        # bundle.dataset. We DO NOT pass contract.evaluation_mode here;
        # if we did, we'd silently coerce mismatched bundles instead of
        # catching them in step 5.
        decision = self.runner.run(
            plan, case.bundle, case.memory,
            ablation=ablation,
        )

        # 5. Refuse cross-mode rows (§14)
        if decision.evaluation_mode != contract.evaluation_mode:
            raise EvaluationModeMismatch(
                bundle_id=case.bundle_id,
                expected=contract.evaluation_mode,
                actual=decision.evaluation_mode,
            )

        # 6. Page-suppression + state update
        suppression: PageSuppressionResult | None = None
        if self.state_layer is not None:
            decision, suppression = self._apply_suppression_and_record(
                decision=decision, bundle=case.bundle,
            )

        # 7. Score
        return self._score(case=case, decision=decision, suppression=suppression)

    # ------------------------------------------------------------------ suppression hook

    def _apply_suppression_and_record(
        self,
        *,
        decision: AgentDecision,
        bundle,
    ) -> tuple[AgentDecision, PageSuppressionResult | None]:
        suppression: PageSuppressionResult | None = None
        service_name = bundle.service_name or ""
        candidate_top1 = (
            decision.matched_issue_ids[0] if decision.matched_issue_ids else None
        )

        if (
            self.apply_page_suppression
            and decision.triage_decision == "ticket_worthy"
            and candidate_top1 is not None
        ):
            suppression = self.state_layer.check_page_suppression(
                service_name=service_name,
                candidate_top1=candidate_top1,
                scenario_family=bundle.scenario_family,
                window_type=bundle.window_type,
            )
            if suppression.suppress:
                decision = dataclasses.replace(
                    decision,
                    triage_decision="borderline",
                )

        # Build the WindowState — attach incident_id from suppression when present
        incident_id = suppression.incident_id if (suppression and suppression.suppress) else None
        ws = WindowState.from_decision(decision, bundle, incident_id=incident_id)
        stored = self.state_layer.record(ws)

        # If record() auto-generated an incident_id (ticket_worthy + no prior),
        # surface it back so the CaseResult / downstream consumers know.
        if stored.incident_id and incident_id is None and decision.triage_decision == "ticket_worthy":
            # Note: AgentDecision has no incident_id field; we surface it
            # via the CaseResult only. Decision is unchanged.
            pass

        return decision, suppression

    # ------------------------------------------------------------------ scoring

    def _score(
        self,
        *,
        case: EvaluationCase,
        decision: AgentDecision,
        suppression: PageSuppressionResult | None,
    ) -> CaseResult:
        matched = list(decision.matched_issue_ids)
        gold = list(case.gold_matched_issue_ids)

        # Retrieval — only meaningful when gold is populated.
        if gold:
            h1 = hit_at_k(matched, gold, 1)
            h5 = hit_at_k(matched, gold, 5)
            h10 = hit_at_k(matched, gold, 10)
            rr = reciprocal_rank(matched, gold)
            rank: int | None = None
            gold_set = set(gold)
            for i, c in enumerate(matched, start=1):
                if c in gold_set:
                    rank = i
                    break
        else:
            h1 = h5 = h10 = None
            rr = None
            rank = None

        # Score triage on the PRE-suppression decision. Page suppression only
        # fires when the agent decided "ticket_worthy" (see _process_window) and
        # then downgrades it to "borderline" for paging; that downgrade is a
        # paging action, not a triage error, so it must not deflate triage
        # accuracy. The suppress flag uniquely identifies these windows.
        effective_triage = (
            "ticket_worthy"
            if (suppression is not None and suppression.suppress)
            else decision.triage_decision
        )
        triage_correct = effective_triage == case.gold_triage
        is_novel_correct = bool(decision.is_novel) == bool(case.gold_is_novel)

        return CaseResult(
            bundle_id=case.bundle_id,
            decision=decision,
            hit_at_1=h1,
            hit_at_5=h5,
            hit_at_10=h10,
            rank_of_first_hit=rank,
            reciprocal_rank=rr,
            triage_correct=triage_correct,
            is_novel_correct=is_novel_correct,
            gold_matched_issue_ids=tuple(gold),
            gold_triage=case.gold_triage,
            gold_is_novel=case.gold_is_novel,
            suppression_fired=bool(suppression and suppression.suppress),
            suppression_incident_id=(
                suppression.incident_id if (suppression and suppression.suppress) else None
            ),
        )

    # ------------------------------------------------------------------ aggregate

    def _aggregate(
        self,
        *,
        case_results: list[CaseResult],
        contract: ApplesToApplesContract,
        experiment_name: str,
        ablation: str,
        plan_ids: list[str],
        keep_case_details: bool,
    ) -> EvaluationReport:
        n_cases = len(case_results)

        # Filter for retrieval rule #4: len(gold) >= 1.
        retrieval_cases = [c for c in case_results if c.gold_matched_issue_ids]
        n_eval = len(retrieval_cases)

        def _mean(field_name: str) -> float:
            if n_eval == 0:
                return 0.0
            total = sum(
                int(getattr(c, field_name)) for c in retrieval_cases
                if getattr(c, field_name) is not None
            )
            return total / n_eval

        hit_at_1 = _mean("hit_at_1")
        hit_at_5 = _mean("hit_at_5")
        hit_at_10 = _mean("hit_at_10")

        mrr = (
            sum(c.reciprocal_rank or 0.0 for c in retrieval_cases) / n_eval
            if n_eval else 0.0
        )

        # Triage accuracy across ALL cases (gold_triage defaults to
        # ticket_worthy, so this is meaningful even for retrieval-only
        # gold).
        triage_accuracy = (
            sum(1 for c in case_results if c.triage_correct) / n_cases
            if n_cases else 0.0
        )

        # Novelty — recall + precision over the cases with gold_is_novel
        # available. Decisions with is_novel=True are predicted novel.
        gold_novel = [c for c in case_results if c.gold_is_novel]
        pred_novel = [c for c in case_results if c.decision.is_novel]
        true_pos = [c for c in pred_novel if c.gold_is_novel]
        novel_recall = (
            len(true_pos) / len(gold_novel) if gold_novel else 0.0
        )
        novel_precision = (
            len(true_pos) / len(pred_novel) if pred_novel else 0.0
        )

        # Pages per incident.
        # When a state layer is wired, the StateLayer is the authoritative
        # source of incident_ids — it auto-generates one per new
        # ticket_worthy window and re-attaches the existing one on
        # suppression. We pull from there to capture all incidents in
        # one shot. Without a state layer, fall back to whatever
        # incident_ids landed in CaseResult.suppression_incident_id.
        triage_decisions = [c.decision.triage_decision for c in case_results]
        if self.state_layer is not None:
            # Use the all-time `seen_incident_ids` (survives ring-buffer
            # rollover) so the metric is accurate over long runs.
            n_pages, _, _ = pages_per_incident(triage_decisions, ())
            n_incidents = self.state_layer.n_unique_incidents_seen()
            p_per_i = n_pages / n_incidents if n_incidents else 0.0
        else:
            n_pages, n_incidents, p_per_i = pages_per_incident(
                triage_decisions=triage_decisions,
                incident_ids=(c.suppression_incident_id for c in case_results),
            )

        n_suppressions = sum(1 for c in case_results if c.suppression_fired)

        total_cost = SkillCallCost.zero()
        for c in case_results:
            total_cost = total_cost + c.decision.cost

        # Cache stats — best-effort.
        cache_hit_rate = 0.0
        cache_stats = getattr(self.runner.cache, "stats", None)
        if callable(cache_stats):
            try:
                cache_hit_rate = float(cache_stats().get("hit_rate", 0.0))
            except Exception:                                                # noqa: BLE001
                cache_hit_rate = 0.0

        return EvaluationReport(
            name=experiment_name + (f":{ablation}" if ablation else ""),
            n_cases=n_cases,
            n_evaluable_retrieval_cases=n_eval,
            contract=contract,
            hit_at_1=hit_at_1,
            hit_at_5=hit_at_5,
            hit_at_10=hit_at_10,
            mrr=mrr,
            triage_accuracy=triage_accuracy,
            novel_recall=novel_recall,
            novel_precision=novel_precision,
            n_pages_emitted=n_pages,
            n_incidents=n_incidents,
            pages_per_incident=p_per_i,
            n_suppressions_fired=n_suppressions,
            total_cost=total_cost,
            cache_hit_rate=cache_hit_rate,
            experiment_name=experiment_name,
            ablation=ablation,
            plan_ids_seen=tuple(plan_ids),
            case_results=tuple(case_results) if keep_case_details else (),
        )

    def __repr__(self) -> str:
        return (
            f"EvalHarness(controller={self.controller.name!r}, "
            f"state_layer={'on' if self.state_layer else 'off'})"
        )
