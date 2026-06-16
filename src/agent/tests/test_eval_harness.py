"""Offline tests for Phase 1.13: eval_harness.

Covers:
  - Pure metric functions: hit_at_k, reciprocal_rank, mean variants
    (with the empty-gold filter), pages_per_incident.
  - CaseResult + EvaluationReport serialization round-trip.
  - EvalHarness end-to-end with stub controller + stub runner stand-ins:
      - Hit@K is correctly averaged across cases.
      - Empty-gold cases are excluded from retrieval averages.
      - Triage accuracy reflects decision vs gold_triage.
      - EvaluationModeMismatch raised when modes disagree.
      - Page-suppression downgrades ticket_worthy→borderline and
        recovers prior incident_id.
      - State layer auto-populates incident counts for the report.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_eval_harness -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import (
    Capabilities,
    InputBundle,
    MEMORY_TEXT,
    SkillCallCost,
    SkillOutput,
    TEXT_EVIDENCE,
    Trace,
)
from agent.capabilities_observer import CapabilitiesObserver, ObservationContext
from agent.controller import RuleController
from agent.eval_harness import (
    ApplesToApplesContract,
    ApplesToApplesViolation,
    CaseResult,
    EvalHarness,
    EvaluationCase,
    EvaluationModeMismatch,
    EvaluationReport,
    hit_at_k,
    mean_hit_at_k,
    mean_reciprocal_rank,
    pages_per_incident,
    reciprocal_rank,
)
from agent.runner import AgentRunner
from agent.skills import (
    AgentContext,
    MemoryView,
    Skill,
    SkillRegistry,
    make_cost,
)
from agent.state import StateLayer


# ---------------------------------------------------------------------------
# Pure metrics
# ---------------------------------------------------------------------------


class TestHitAtK(unittest.TestCase):
    def test_top1_in_gold(self):
        self.assertTrue(hit_at_k(["A", "B", "C"], ["A"], 1))

    def test_top1_not_in_gold(self):
        self.assertFalse(hit_at_k(["B", "A"], ["A"], 1))
        self.assertTrue(hit_at_k(["B", "A"], ["A"], 2))

    def test_empty_gold_is_false(self):
        self.assertFalse(hit_at_k(["A"], [], 1))

    def test_k_zero_returns_false(self):
        self.assertFalse(hit_at_k(["A"], ["A"], 0))

    def test_k_larger_than_matched(self):
        self.assertTrue(hit_at_k(["A"], ["A"], 10))


class TestReciprocalRank(unittest.TestCase):
    def test_first_position(self):
        self.assertAlmostEqual(reciprocal_rank(["A", "B"], ["A"]), 1.0)

    def test_second_position(self):
        self.assertAlmostEqual(reciprocal_rank(["B", "A"], ["A"]), 0.5)

    def test_no_hit(self):
        self.assertAlmostEqual(reciprocal_rank(["X", "Y"], ["A"]), 0.0)

    def test_empty_gold_returns_zero(self):
        self.assertAlmostEqual(reciprocal_rank(["A"], []), 0.0)


class TestMeans(unittest.TestCase):
    def test_mean_hit_at_k_filters_empty_gold(self):
        matched = [["A"], ["X"], ["B"]]
        gold = [["A"], [], ["B"]]              # second case has empty gold
        m = mean_hit_at_k(matched, gold, 1)
        # Only 2 evaluable cases; both hit → 2/2 = 1.0
        self.assertAlmostEqual(m, 1.0)

    def test_mean_hit_at_k_partial(self):
        matched = [["A"], ["X"], ["B"]]
        gold = [["A"], ["Y"], ["B"]]
        m = mean_hit_at_k(matched, gold, 1)
        # 2/3 hit
        self.assertAlmostEqual(m, 2.0 / 3.0, places=5)

    def test_mean_mrr_filters_empty(self):
        m = mean_reciprocal_rank(
            [["A"], ["X"], ["B", "X"]],
            [["A"], [], ["X"]],
        )
        # Evaluable: 1.0 + 0.5 = 1.5 / 2 = 0.75
        self.assertAlmostEqual(m, 0.75)

    def test_mean_zero_evaluable(self):
        self.assertAlmostEqual(mean_hit_at_k([], [], 1), 0.0)
        self.assertAlmostEqual(
            mean_hit_at_k([["A"]], [[]], 1), 0.0)


class TestPagesPerIncident(unittest.TestCase):
    def test_basic(self):
        n, i, ratio = pages_per_incident(
            ["ticket_worthy", "ticket_worthy", "ticket_worthy", "noise", "borderline"],
            ["inc-1", "inc-1", "inc-2", None, "inc-1"],
        )
        self.assertEqual(n, 3)         # 3 ticket_worthy
        self.assertEqual(i, 2)         # 2 unique incidents
        self.assertAlmostEqual(ratio, 1.5)

    def test_needs_review_counts_as_page(self):
        n, _, _ = pages_per_incident(
            ["needs_review", "noise"],
            ["inc-1", None],
        )
        self.assertEqual(n, 1)

    def test_no_incidents_returns_zero_ratio(self):
        n, i, ratio = pages_per_incident(["ticket_worthy"], [None])
        self.assertEqual((n, i, ratio), (1, 0, 0.0))


# ---------------------------------------------------------------------------
# Case + Report serialization
# ---------------------------------------------------------------------------


class TestSerialization(unittest.TestCase):
    def test_caseresult_roundtrip(self):
        from agent import AgentDecision
        c = CaseResult(
            bundle_id="w1",
            decision=AgentDecision(
                bundle_id="w1",
                triage_decision="ticket_worthy",
                triage_score=0.9,
                matched_issue_ids=("A",),
            ),
            hit_at_1=True, hit_at_5=True, hit_at_10=True,
            rank_of_first_hit=1, reciprocal_rank=1.0,
            triage_correct=True, is_novel_correct=True,
            gold_matched_issue_ids=("A",),
            suppression_fired=False,
        )
        c2 = CaseResult.from_dict(c.to_dict())
        self.assertEqual(c, c2)

    def test_report_write_and_load(self):
        contract = ApplesToApplesContract(
            dataset_id="ob-2026", split="test", gold_relation="coarse",
            memory_pool_size=100,
        )
        report = EvaluationReport(
            name="exp1", n_cases=10, n_evaluable_retrieval_cases=8,
            contract=contract,
            hit_at_1=0.5, hit_at_5=0.8, hit_at_10=0.9, mrr=0.6,
            triage_accuracy=0.7,
        )
        with tempfile.TemporaryDirectory() as td:
            p = report.write_to(Path(td) / "report.json")
            self.assertTrue(p.exists())
            loaded = EvaluationReport.from_dict(
                __import__("json").loads(p.read_text(encoding="utf-8"))
            )
            self.assertEqual(loaded.hit_at_5, 0.8)
            self.assertEqual(loaded.contract.dataset_id, "ob-2026")


# ---------------------------------------------------------------------------
# End-to-end harness — stub skills produce deterministic outputs
# ---------------------------------------------------------------------------


class _GoldHitTriage(Skill):
    """Stub compose_triage that emits a fixed score for every bundle."""
    name = "compose_triage"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(self, score: float = 0.9):
        self._score = score

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=self._score,
            triage_decision="ticket_worthy" if self._score >= 0.5 else "noise",
            confidence=self._score,
            cost=make_cost(),
        )


class _StubRetrieveDense(Skill):
    """Stub retrieve_dense — emits the bundle's desired_ranking.

    This is what makes compose_l2's `_any_retriever_ran` gate open, so
    the rest of the composition layer actually fires."""
    name = "retrieve_dense"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE, MEMORY_TEXT})
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        ranking = tuple(bundle.extra.get("desired_ranking", ()))
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            matched_issue_ids=ranking,
            triage_score=0.4,                            # below cheap-path threshold
            confidence=0.4, cost=make_cost(),
        )


class _BundleEchoCompose(Skill):
    """Stub compose_l2 — emits a fixed ranking the test controls.

    Reads the desired ranking from bundle.extra['desired_ranking']."""
    name = "compose_l2"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        ranking = tuple(bundle.extra.get("desired_ranking", ()))
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            matched_issue_ids=ranking,
            confidence=1.0, cost=make_cost(),
        )


class _NoveltyEcho(Skill):
    """Stub compose_novelty — reads desired_novelty from bundle.extra."""
    name = "compose_novelty"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            is_novel=bool(bundle.extra.get("desired_novelty", False)),
            confidence=1.0, cost=make_cost(),
        )


def _build_registry(*, triage_score: float = 0.9) -> SkillRegistry:
    r = SkillRegistry()
    r.register(_StubRetrieveDense())
    r.register(_GoldHitTriage(score=triage_score))
    r.register(_BundleEchoCompose())
    r.register(_NoveltyEcho())
    return r


def _harness(
    *,
    triage_score: float = 0.9,
    state_layer: StateLayer | None = None,
    apply_suppression: bool = True,
) -> tuple[EvalHarness, AgentRunner]:
    registry = _build_registry(triage_score=triage_score)
    controller = RuleController(registry)
    runner = AgentRunner(registry)
    harness = EvalHarness(
        controller=controller, runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=ObservationContext(dataset_id="test-ds"),
        state_layer=state_layer,
        apply_page_suppression=apply_suppression,
    )
    return harness, runner


def _case(
    window_id: str,
    *,
    desired_ranking: tuple[str, ...] = ("A", "B", "C"),
    gold_matched: tuple[str, ...] = ("A",),
    service: str = "cart",
    scenario: str = "redis_oom",
    window_type: str = "active_fault",
    gold_triage: str = "ticket_worthy",
    desired_novelty: bool = False,
    gold_is_novel: bool = False,
) -> EvaluationCase:
    bundle = InputBundle(
        window_id=window_id,
        dataset="online_boutique",
        text_evidence="lorem ipsum dolor sit amet",
        service_name=service,
        scenario_family=scenario,
        window_type=window_type,
        extra={
            "desired_ranking": desired_ranking,
            "desired_novelty": desired_novelty,
        },
    )
    return EvaluationCase(
        bundle=bundle,
        memory=MemoryView([]),
        gold_matched_issue_ids=gold_matched,
        gold_triage=gold_triage,                    # type: ignore[arg-type]
        gold_is_novel=gold_is_novel,
    )


class TestHarnessEndToEnd(unittest.TestCase):
    def setUp(self):
        self.contract = ApplesToApplesContract(
            dataset_id="ob-test", split="test",
            gold_relation="coarse", memory_pool_size=10,
            evaluation_mode="telemetry_diagnosis",
        )

    def test_basic_aggregation(self):
        harness, _ = _harness()
        cases = [
            _case("w1", desired_ranking=("A", "B"), gold_matched=("A",)),
            _case("w2", desired_ranking=("X", "A"), gold_matched=("A",)),
            _case("w3", desired_ranking=("X", "Y"), gold_matched=("Z",)),
        ]
        report = harness.evaluate(cases, contract=self.contract,
                                  experiment_name="basic")
        self.assertEqual(report.n_cases, 3)
        self.assertEqual(report.n_evaluable_retrieval_cases, 3)
        # Hit@1: w1 hits A in position 1; w2 misses (X); w3 misses → 1/3
        self.assertAlmostEqual(report.hit_at_1, 1.0 / 3.0, places=5)
        # Hit@5: w1 + w2 hit → 2/3
        self.assertAlmostEqual(report.hit_at_5, 2.0 / 3.0, places=5)
        # MRR: 1.0 + 0.5 + 0.0 = 1.5 / 3
        self.assertAlmostEqual(report.mrr, 0.5, places=5)

    def test_empty_gold_excluded_from_retrieval_metrics(self):
        harness, _ = _harness()
        cases = [
            _case("w1", desired_ranking=("A",), gold_matched=("A",)),
            _case("w2", desired_ranking=("Y",), gold_matched=()),    # no gold
        ]
        report = harness.evaluate(cases, contract=self.contract)
        self.assertEqual(report.n_evaluable_retrieval_cases, 1)
        self.assertAlmostEqual(report.hit_at_1, 1.0)

    def test_triage_accuracy_across_all_cases(self):
        harness, _ = _harness(triage_score=0.9)            # always ticket_worthy
        cases = [
            _case("w1", gold_triage="ticket_worthy"),
            _case("w2", gold_triage="noise"),
        ]
        report = harness.evaluate(cases, contract=self.contract)
        self.assertEqual(report.n_cases, 2)
        self.assertAlmostEqual(report.triage_accuracy, 0.5)

    def test_novelty_metrics(self):
        harness, _ = _harness()
        cases = [
            # Truly novel + predicted novel → true positive
            _case("w1", desired_novelty=True, gold_is_novel=True),
            # Truly novel + predicted not-novel → false negative
            _case("w2", desired_novelty=False, gold_is_novel=True),
            # Not novel + predicted novel → false positive
            _case("w3", desired_novelty=True, gold_is_novel=False),
            # Not novel + predicted not-novel → true negative
            _case("w4", desired_novelty=False, gold_is_novel=False),
        ]
        report = harness.evaluate(cases, contract=self.contract)
        # recall = TP / actual positives = 1 / 2 = 0.5
        self.assertAlmostEqual(report.novel_recall, 0.5)
        # precision = TP / predicted positives = 1 / 2 = 0.5
        self.assertAlmostEqual(report.novel_precision, 0.5)

    def test_plan_id_is_captured(self):
        harness, _ = _harness()
        report = harness.evaluate([_case("w1")], contract=self.contract)
        self.assertEqual(len(report.plan_ids_seen), 1)
        self.assertTrue(report.plan_ids_seen[0].startswith("plan_"))


# ---------------------------------------------------------------------------
# Mode-mismatch refusal (§14)
# ---------------------------------------------------------------------------


class TestModeMismatchRefusal(unittest.TestCase):
    def test_wol_decision_in_telemetry_contract_raises(self):
        harness, _ = _harness()
        # Bundle dataset='wol' → decision mode = text_retrieval_generalisation
        bundle = InputBundle(
            window_id="w-wol", dataset="wol",
            text_evidence="lorem ipsum dolor sit amet",
            service_name="apache",
        )
        case = EvaluationCase(
            bundle=bundle, memory=MemoryView([]),
            gold_matched_issue_ids=("X",),
        )
        contract = ApplesToApplesContract(
            dataset_id="ob-test", evaluation_mode="telemetry_diagnosis",
        )
        with self.assertRaises(EvaluationModeMismatch) as ctx:
            harness.evaluate([case], contract=contract)
        self.assertEqual(ctx.exception.expected, "telemetry_diagnosis")
        self.assertEqual(ctx.exception.actual, "text_retrieval_generalisation")

    def test_evaluation_mode_mismatch_is_apples_to_apples_violation(self):
        # Subclass check — tools that catch ApplesToApplesViolation
        # also catch EvaluationModeMismatch.
        self.assertTrue(issubclass(EvaluationModeMismatch, ApplesToApplesViolation))


# ---------------------------------------------------------------------------
# Page-suppression integration
# ---------------------------------------------------------------------------


class TestHarnessSuppression(unittest.TestCase):
    def setUp(self):
        self.contract = ApplesToApplesContract(
            dataset_id="ob-test", split="test",
        )

    def test_suppression_downgrades_repeat_ticket_to_borderline(self):
        sl = StateLayer()
        harness, _ = _harness(state_layer=sl)
        cases = [
            _case("w1", desired_ranking=("PROJ-1",), gold_matched=("PROJ-1",)),
            _case("w2", desired_ranking=("PROJ-1",), gold_matched=("PROJ-1",)),
        ]
        report = harness.evaluate(cases, contract=self.contract)
        results = list(report.case_results)
        self.assertEqual(results[0].decision.triage_decision, "ticket_worthy")
        # w2 hits the same top1+scenario → suppressed to borderline
        self.assertEqual(results[1].decision.triage_decision, "borderline")
        self.assertTrue(results[1].suppression_fired)
        self.assertEqual(report.n_suppressions_fired, 1)

    def test_pages_per_incident_drops_under_suppression(self):
        sl = StateLayer()
        harness, _ = _harness(state_layer=sl)
        # 3 windows that all hit the same incident
        cases = [
            _case(f"w{i}", desired_ranking=("PROJ-1",), gold_matched=("PROJ-1",))
            for i in range(3)
        ]
        report = harness.evaluate(cases, contract=self.contract)
        # 1 page (the first), then 2 suppressions → n_pages=1, n_incidents=1
        self.assertEqual(report.n_pages_emitted, 1)
        self.assertEqual(report.n_incidents, 1)
        self.assertAlmostEqual(report.pages_per_incident, 1.0)

    def test_suppression_disabled_keeps_all_pages(self):
        sl = StateLayer()
        harness, _ = _harness(state_layer=sl, apply_suppression=False)
        cases = [
            _case(f"w{i}", desired_ranking=("PROJ-1",), gold_matched=("PROJ-1",))
            for i in range(3)
        ]
        report = harness.evaluate(cases, contract=self.contract)
        # 3 pages, but state still records 3 unique incident_ids per
        # ticket_worthy
        self.assertEqual(report.n_pages_emitted, 3)
        self.assertEqual(report.n_incidents, 3)


# ---------------------------------------------------------------------------
# No-state-layer mode
# ---------------------------------------------------------------------------


class TestHarnessNoStateLayer(unittest.TestCase):
    def test_runs_without_state_layer(self):
        contract = ApplesToApplesContract(dataset_id="ob-test")
        harness, _ = _harness()                            # state_layer=None
        cases = [_case("w1", desired_ranking=("A",), gold_matched=("A",))]
        report = harness.evaluate(cases, contract=contract)
        self.assertEqual(report.n_pages_emitted, 1)
        self.assertEqual(report.n_suppressions_fired, 0)


if __name__ == "__main__":
    unittest.main()
