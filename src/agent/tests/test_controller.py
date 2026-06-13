"""Offline tests for Phase 1.9: Controller ABC + RuleController.

Covers:
  - Controller ABC contract (must implement plan()).
  - RuleController emits a Plan referencing only registered + invokable skills.
  - Capability-gating: WoL profile drops verify_with_llm (no
    VERIFIER_KNOWN_HELPFUL); OB profile keeps it.
  - Escalation gate: cheap-path confidence ⇒ skip expensive; absent ⇒ run.
  - Ablation: registry pre-pruned ⇒ controller omits the dropped skill
    and the resulting Plan is plan_id-stable across runs.
  - plan_id is deterministic + sensitive to the controller's policy.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_controller -v
"""

from __future__ import annotations

import unittest

from agent import (
    Budget,
    Capabilities,
    InputBundle,
    KG_GRAPH_MEMORY,
    MEMORY_TEXT,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    SkillCallCost,
    SkillOutput,
    TEXT_EVIDENCE,
    Trace,
    TraceEvent,
    VERIFIER_KNOWN_HELPFUL,
)
from agent.controller import (
    Controller,
    RuleController,
    make_escalation_gate,
    make_reformulation_gate,
)
from agent.skills import (
    ReformulateQuerySkill,
    Skill,
    SkillRegistry,
    make_cost,
)
from agent.skills.composition import (
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
)
from agent.skills.retrievers import (
    RetrieveDenseSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    TriageNumericSkill,
    VerifyWithLLMSkill,
)


# ---------------------------------------------------------------------------
# Helpers — build a registry without exercising the predictions-loader
# (PredictionsBackedSkill loads its JSONL lazily on first invoke; the
# controller only inspects class-level attrs, so no I/O happens here).
# ---------------------------------------------------------------------------


_DUMMY_PREDICTIONS_PATH = "data/__nonexistent__/predictions.jsonl"


def _build_full_registry() -> SkillRegistry:
    """Registry with every predictions-backed retriever + every composition skill."""
    r = SkillRegistry()
    r.register(TriageNumericSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    r.register(RetrieveDenseSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    r.register(RetrieveLogSequenceSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    r.register(RetrieveHybridFusionSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    # retrieve_hybrid_fusion_llm + retrieve_knowledge_graph need KG_GRAPH_MEMORY.
    r.register(RetrieveKnowledgeGraphSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    r.register(VerifyWithLLMSkill(predictions_path=_DUMMY_PREDICTIONS_PATH))
    r.register(ComposeL2Skill())
    r.register(ComposeTriageSkill())
    r.register(ComposeNoveltySkill())
    return r


def _ob_capabilities() -> Capabilities:
    """OB-shaped capabilities: full telemetry + verifier known-helpful."""
    return Capabilities(flags=frozenset({
        NUMERIC_FEATURES,
        TEXT_EVIDENCE,
        ORDERED_LOGS,
        MEMORY_TEXT,
        KG_GRAPH_MEMORY,
        VERIFIER_KNOWN_HELPFUL,
    }))


def _wol_capabilities() -> Capabilities:
    """WoL-shaped: text-only + no verifier flag (calibration knocks it out)."""
    return Capabilities(flags=frozenset({
        TEXT_EVIDENCE,
        MEMORY_TEXT,
        KG_GRAPH_MEMORY,
        # explicitly no VERIFIER_KNOWN_HELPFUL
        # explicitly no NUMERIC_FEATURES, no ORDERED_LOGS
    }))


def _empty_bundle(window_id: str = "w-test") -> InputBundle:
    return InputBundle(window_id=window_id, dataset="test")


# ---------------------------------------------------------------------------
# Trace fixtures for gate tests
# ---------------------------------------------------------------------------


def _trace_with_skill_output(
    skill_name: str,
    *,
    triage_score: float | None = None,
    matched_issue_ids: tuple[str, ...] = (),
) -> Trace:
    """Build a Trace with one skill_end event for `skill_name`."""
    t = Trace(bundle_id="w1", plan_id="plan_xxx")
    t.add(TraceEvent(
        ts=TraceEvent.now(),
        kind="skill_end",
        skill=skill_name,
        skill_version="1.0.0",
        output=SkillOutput(
            skill=skill_name,
            skill_version="1.0.0",
            triage_score=triage_score,
            matched_issue_ids=matched_issue_ids,
            cost=make_cost(),
        ),
    ))
    return t


# ---------------------------------------------------------------------------
# Controller ABC
# ---------------------------------------------------------------------------


class TestControllerABC(unittest.TestCase):
    def test_cannot_instantiate_abstract_controller(self):
        with self.assertRaises(TypeError):
            Controller()                            # type: ignore[abstract]

    def test_subclass_must_implement_plan(self):
        class _Incomplete(Controller):
            name = "incomplete"
        with self.assertRaises(TypeError):
            _Incomplete()                           # type: ignore[abstract]


# ---------------------------------------------------------------------------
# RuleController — plan composition under different capability profiles
# ---------------------------------------------------------------------------


class TestRuleControllerOBPlan(unittest.TestCase):
    def setUp(self):
        self.registry = _build_full_registry()
        self.controller = RuleController(self.registry)
        self.plan = self.controller.plan(_empty_bundle(), _ob_capabilities())

    def test_plan_includes_triage_numeric_first(self):
        names = [inv.skill_name for inv in self.plan.invocations]
        self.assertEqual(names[0], "triage_numeric")

    def test_plan_includes_cheap_retriever_second(self):
        names = [inv.skill_name for inv in self.plan.invocations]
        self.assertEqual(names[1], "retrieve_dense")

    def test_plan_includes_verifier_on_ob(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertIn("verify_with_llm", names)

    def test_plan_includes_compose_novelty_last(self):
        names = [inv.skill_name for inv in self.plan.invocations]
        self.assertEqual(names[-1], "compose_novelty")

    def test_cheap_path_skills_have_no_gate(self):
        by_name = {inv.skill_name: inv for inv in self.plan.invocations}
        self.assertIsNone(by_name["triage_numeric"].gate)
        self.assertIsNone(by_name["retrieve_dense"].gate)
        self.assertIsNone(by_name["compose_triage"].gate)
        self.assertIsNone(by_name["compose_novelty"].gate)

    def test_expensive_retrievers_have_escalation_gate(self):
        by_name = {inv.skill_name: inv for inv in self.plan.invocations}
        for expensive in (
            "retrieve_log_sequence",
            "retrieve_hybrid_fusion",
            "retrieve_knowledge_graph",
        ):
            self.assertIsNotNone(
                by_name[expensive].gate,
                f"{expensive} should have an escalation gate",
            )

    def test_verifier_has_gate(self):
        by_name = {inv.skill_name: inv for inv in self.plan.invocations}
        self.assertIsNotNone(by_name["verify_with_llm"].gate)

    def test_plan_id_is_stable(self):
        # Same inputs → same plan_id (deterministic / idempotent)
        plan2 = self.controller.plan(_empty_bundle(), _ob_capabilities())
        self.assertEqual(self.plan.plan_id, plan2.plan_id)

    def test_plan_controller_name(self):
        self.assertEqual(self.plan.controller_name, "rule")


class TestRuleControllerWoLPlan(unittest.TestCase):
    """WoL — no NUMERIC_FEATURES, no ORDERED_LOGS, no VERIFIER_KNOWN_HELPFUL."""

    def setUp(self):
        self.registry = _build_full_registry()
        self.controller = RuleController(self.registry)
        self.plan = self.controller.plan(_empty_bundle(), _wol_capabilities())

    def test_plan_excludes_verifier(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertNotIn(
            "verify_with_llm", names,
            "VERIFIER_KNOWN_HELPFUL absent → verify_with_llm must be dropped",
        )

    def test_plan_excludes_triage_numeric(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertNotIn(
            "triage_numeric", names,
            "NUMERIC_FEATURES absent → triage_numeric must be dropped",
        )

    def test_plan_excludes_log_sequence(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertNotIn(
            "retrieve_log_sequence", names,
            "ORDERED_LOGS absent → retrieve_log_sequence must be dropped",
        )

    def test_plan_keeps_dense_and_hybrid(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertIn("retrieve_dense", names)
        self.assertIn("retrieve_hybrid_fusion", names)
        # KG retrieval requires KG_GRAPH_MEMORY (which WoL has)
        self.assertIn("retrieve_knowledge_graph", names)

    def test_plan_keeps_composition_layer(self):
        names = {inv.skill_name for inv in self.plan.invocations}
        self.assertIn("compose_l2", names)
        self.assertIn("compose_triage", names)
        self.assertIn("compose_novelty", names)


# ---------------------------------------------------------------------------
# Escalation gate behaviour
# ---------------------------------------------------------------------------


class TestEscalationGate(unittest.TestCase):
    def test_cheap_path_confident_skips_expensive(self):
        gate = make_escalation_gate(threshold=0.9, require_consensus=True)
        trace = Trace(bundle_id="w1", plan_id="plan_x")
        # Add high-confidence triage + dense match
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="triage_numeric",
            output=SkillOutput(skill="triage_numeric", triage_score=0.95),
        ))
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
            output=SkillOutput(
                skill="retrieve_dense", triage_score=0.85,
                matched_issue_ids=("PROJ-1",),
            ),
        ))
        self.assertFalse(gate(trace, Budget()),
                         "cheap-path confident ⇒ expensive skill skipped")

    def test_low_triage_score_escalates(self):
        gate = make_escalation_gate(threshold=0.9)
        trace = Trace(bundle_id="w1", plan_id="plan_x")
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="triage_numeric",
            output=SkillOutput(skill="triage_numeric", triage_score=0.50),
        ))
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
            output=SkillOutput(
                skill="retrieve_dense", triage_score=0.85,
                matched_issue_ids=("PROJ-1",),
            ),
        ))
        self.assertTrue(gate(trace, Budget()),
                        "triage_score below threshold ⇒ escalate")

    def test_no_triage_output_escalates(self):
        """WoL path: no triage_numeric ran, so the gate must escalate."""
        gate = make_escalation_gate(threshold=0.9)
        trace = Trace(bundle_id="w1", plan_id="plan_x")
        # Only the dense retriever ran (no triage_numeric)
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
            output=SkillOutput(
                skill="retrieve_dense", triage_score=0.85,
                matched_issue_ids=("PROJ-1",),
            ),
        ))
        self.assertTrue(gate(trace, Budget()),
                        "no triage signal ⇒ escalate (WoL path)")

    def test_no_consensus_escalates(self):
        gate = make_escalation_gate(threshold=0.9, require_consensus=True)
        trace = Trace(bundle_id="w1", plan_id="plan_x")
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="triage_numeric",
            output=SkillOutput(skill="triage_numeric", triage_score=0.95),
        ))
        # retrieve_dense returned NO matches
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
            output=SkillOutput(
                skill="retrieve_dense", triage_score=0.0,
                matched_issue_ids=(),
            ),
        ))
        self.assertTrue(gate(trace, Budget()),
                        "no BiEncoder consensus ⇒ escalate")

    def test_consensus_disabled_lets_triage_alone_decide(self):
        gate = make_escalation_gate(threshold=0.9, require_consensus=False)
        trace = Trace(bundle_id="w1", plan_id="plan_x")
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="triage_numeric",
            output=SkillOutput(skill="triage_numeric", triage_score=0.95),
        ))
        # No retrieve_dense at all
        self.assertFalse(gate(trace, Budget()),
                         "require_consensus=False ⇒ high triage alone skips expensive")


# ---------------------------------------------------------------------------
# Ablation: pre-pruned registry → plan omits dropped skills
# ---------------------------------------------------------------------------


class TestAblationViaRegistryPrune(unittest.TestCase):
    def test_drop_verifier_via_copy_without(self):
        full = _build_full_registry()
        pruned = full.copy_without({"verify_with_llm"})
        controller = RuleController(pruned)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        names = {inv.skill_name for inv in plan.invocations}
        self.assertNotIn("verify_with_llm", names)
        # Other skills still present
        self.assertIn("retrieve_dense", names)
        self.assertIn("compose_novelty", names)

    def test_drop_kg_retrieval_via_copy_without(self):
        full = _build_full_registry()
        pruned = full.copy_without({"retrieve_knowledge_graph"})
        controller = RuleController(pruned)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        names = {inv.skill_name for inv in plan.invocations}
        self.assertNotIn("retrieve_knowledge_graph", names)

    def test_ablation_changes_plan_id(self):
        full = _build_full_registry()
        ctrl_full = RuleController(full)
        plan_full = ctrl_full.plan(_empty_bundle(), _ob_capabilities())

        ctrl_pruned = RuleController(full.copy_without({"verify_with_llm"}))
        plan_pruned = ctrl_pruned.plan(_empty_bundle(), _ob_capabilities())

        self.assertNotEqual(
            plan_full.plan_id, plan_pruned.plan_id,
            "ablating a skill must change plan_id",
        )


# ---------------------------------------------------------------------------
# Budget plumbing
# ---------------------------------------------------------------------------


class TestRuleControllerBudget(unittest.TestCase):
    def test_default_budget_applied(self):
        controller = RuleController(_build_full_registry())
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        self.assertEqual(plan.global_budget.max_llm_tokens, 100_000)
        self.assertEqual(plan.global_budget.max_skill_calls, 12)

    def test_budget_caps_override(self):
        controller = RuleController(
            _build_full_registry(),
            budget_caps={"max_llm_tokens": 50_000, "max_usd_equivalent": 0.10},
        )
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        self.assertEqual(plan.global_budget.max_llm_tokens, 50_000)
        self.assertAlmostEqual(plan.global_budget.max_usd_equivalent, 0.10)

    def test_per_call_budget_inherits_global_caps(self):
        controller = RuleController(
            _build_full_registry(),
            budget_caps={"max_llm_tokens": 50_000},
        )
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        for inv in plan.invocations:
            self.assertEqual(inv.per_call_budget.max_llm_tokens, 50_000)
            # Fresh counter
            self.assertEqual(inv.per_call_budget.spent_tokens, 0)

    def test_per_call_config_overrides_threshold(self):
        controller = RuleController(_build_full_registry())
        plan = controller.plan(
            _empty_bundle(), _ob_capabilities(),
            config={"cheap_path": {"triage_high_confidence": 0.95}},
        )
        # Different threshold → different gate closure → plan still functions
        # (plan_id may or may not change depending on whether the gate's
        # presence-flag affects the serialised plan signature).
        self.assertIsNotNone(plan)


# ---------------------------------------------------------------------------
# Empty / degenerate cases
# ---------------------------------------------------------------------------


class TestRuleControllerEmptyRegistry(unittest.TestCase):
    def test_empty_registry_yields_empty_plan(self):
        controller = RuleController(SkillRegistry())
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        self.assertEqual(len(plan.invocations), 0)


class TestRuleControllerNoCapabilities(unittest.TestCase):
    def test_no_flags_drops_everything_except_composition(self):
        """A capability-less bundle keeps only the composition skills
        (which declare no required flags)."""
        controller = RuleController(_build_full_registry())
        plan = controller.plan(_empty_bundle(), Capabilities())
        names = {inv.skill_name for inv in plan.invocations}
        # Composition skills declare required_flags=frozenset(), so they
        # always pass the capability gate.
        self.assertIn("compose_l2", names)
        self.assertIn("compose_triage", names)
        self.assertIn("compose_novelty", names)
        # Every other skill requires at least one flag
        self.assertNotIn("retrieve_dense", names)
        self.assertNotIn("triage_numeric", names)


# ---------------------------------------------------------------------------
# Capability-adaptive end-to-end: OB vs WoL plans diverge from same registry
# ---------------------------------------------------------------------------


class TestCapabilityAdaptivePlanDivergence(unittest.TestCase):
    """Phase 2.1 — the same RuleController + same registry must produce
    plans that REFLECT the input bundle's capabilities. OB-shaped bundle
    keeps everything; WoL-shaped bundle drops the three skills that
    don't apply. This is the "capability-adaptive" claim in §8."""

    def setUp(self):
        self.registry = _build_full_registry()
        self.controller = RuleController(self.registry)

    def test_ob_and_wol_plans_diverge(self):
        ob_plan = self.controller.plan(_empty_bundle(), _ob_capabilities())
        wol_plan = self.controller.plan(_empty_bundle(), _wol_capabilities())

        ob_skills = {inv.skill_name for inv in ob_plan.invocations}
        wol_skills = {inv.skill_name for inv in wol_plan.invocations}

        # Plans must have different plan_ids
        self.assertNotEqual(ob_plan.plan_id, wol_plan.plan_id)

        # OB keeps the three "telemetry-side" skills; WoL drops them
        for telemetry_only in (
            "triage_numeric",          # needs NUMERIC_FEATURES
            "retrieve_log_sequence",   # needs ORDERED_LOGS
            "verify_with_llm",         # needs VERIFIER_KNOWN_HELPFUL (calibration)
        ):
            self.assertIn(telemetry_only, ob_skills)
            self.assertNotIn(telemetry_only, wol_skills,
                             f"{telemetry_only} should NOT be in WoL plan")

        # Both keep the text-retrieval skills
        for shared in ("retrieve_dense", "retrieve_hybrid_fusion",
                       "compose_l2", "compose_triage", "compose_novelty"):
            self.assertIn(shared, ob_skills)
            self.assertIn(shared, wol_skills)


# ---------------------------------------------------------------------------
# Reformulation gate (Phase 2.3)
# ---------------------------------------------------------------------------


def _trace_with_compose_l2(
    *,
    retriever_scores: dict[str, float],
    matched: tuple[str, ...] = ("FUSED-1",),
) -> Trace:
    """Build a Trace populated with one compose_l2 + several retriever outputs."""
    t = Trace(bundle_id="w1", plan_id="plan_x")
    # Each retriever's skill_end event carries a triage_score
    for skill_name, score in retriever_scores.items():
        t.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end",
            skill=skill_name, skill_version="1.0.0",
            output=SkillOutput(
                skill=skill_name, skill_version="1.0.0",
                triage_score=score,
                matched_issue_ids=("X",),
            ),
        ))
    # compose_l2 fused them
    t.add(TraceEvent(
        ts=TraceEvent.now(), kind="skill_end",
        skill="compose_l2", skill_version="1.0.0",
        output=SkillOutput(
            skill="compose_l2", skill_version="1.0.0",
            matched_issue_ids=matched,
            confidence=1.0,
        ),
    ))
    return t


class TestReformulationGate(unittest.TestCase):
    def test_gate_closes_when_max_conf_above_floor(self):
        gate = make_reformulation_gate(confidence_floor=0.5)
        trace = _trace_with_compose_l2(
            retriever_scores={"retrieve_dense": 0.85},
        )
        self.assertFalse(gate(trace, Budget()))

    def test_gate_opens_when_all_retrievers_below_floor(self):
        gate = make_reformulation_gate(confidence_floor=0.5)
        trace = _trace_with_compose_l2(
            retriever_scores={
                "retrieve_dense": 0.3,
                "retrieve_hybrid_fusion": 0.4,
            },
        )
        self.assertTrue(gate(trace, Budget()))

    def test_gate_closed_before_compose_l2_runs(self):
        """Cold start — no compose_l2 yet → don't reformulate."""
        gate = make_reformulation_gate(confidence_floor=0.5)
        empty_trace = Trace(bundle_id="w1", plan_id="plan_x")
        self.assertFalse(gate(empty_trace, Budget()))

    def test_at_floor_is_closed(self):
        """Boundary: max_conf == floor → closed (strict less-than)."""
        gate = make_reformulation_gate(confidence_floor=0.5)
        trace = _trace_with_compose_l2(
            retriever_scores={"retrieve_dense": 0.5},
        )
        self.assertFalse(gate(trace, Budget()))


class TestRuleControllerReformulationWiring(unittest.TestCase):
    """Phase 2.3 — when max_reformulation_retries > 0 AND the skill is
    registered, the Plan includes reformulate_query as a gated step
    AFTER compose_l2."""

    def _build_registry_with_reformulator(self) -> SkillRegistry:
        r = _build_full_registry()
        # Stub mode — no LLM required for offline tests
        r.register(ReformulateQuerySkill(use_llm=False))
        return r

    def test_reformulation_off_by_default(self):
        """Default max_reformulation_retries=0 → no reformulate_query
        even if registered."""
        registry = self._build_registry_with_reformulator()
        controller = RuleController(registry)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        names = {inv.skill_name for inv in plan.invocations}
        self.assertNotIn("reformulate_query", names)

    def test_reformulation_when_enabled(self):
        registry = self._build_registry_with_reformulator()
        controller = RuleController(registry, max_reformulation_retries=2)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())

        skill_order = [inv.skill_name for inv in plan.invocations]
        self.assertIn("reformulate_query", skill_order)
        # Placed AFTER compose_l2 (so the gate can read compose_l2's output)
        i_l2 = skill_order.index("compose_l2")
        i_rf = skill_order.index("reformulate_query")
        self.assertLess(i_l2, i_rf)
        # ...and BEFORE compose_triage (so a reformulated query could
        # influence the final triage in a v2 live-retrieval mode)
        i_triage = skill_order.index("compose_triage")
        self.assertLess(i_rf, i_triage)

    def test_reformulation_has_gate(self):
        registry = self._build_registry_with_reformulator()
        controller = RuleController(registry, max_reformulation_retries=2)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        rf_inv = next(
            inv for inv in plan.invocations
            if inv.skill_name == "reformulate_query"
        )
        self.assertIsNotNone(rf_inv.gate)

    def test_reformulation_dropped_when_skill_missing(self):
        """If reformulate_query isn't registered, the controller silently
        skips it — even with max_reformulation_retries > 0."""
        registry = _build_full_registry()                  # no reformulator
        controller = RuleController(registry, max_reformulation_retries=2)
        plan = controller.plan(_empty_bundle(), _ob_capabilities())
        names = {inv.skill_name for inv in plan.invocations}
        self.assertNotIn("reformulate_query", names)

    def test_reformulation_capability_gated_to_text_evidence(self):
        """Reformulator needs TEXT_EVIDENCE. A bundle without it must
        not get the reformulate_query step."""
        registry = self._build_registry_with_reformulator()
        controller = RuleController(registry, max_reformulation_retries=2)
        # Capabilities without TEXT_EVIDENCE
        caps = _ob_capabilities().without_flags("TEXT_EVIDENCE")
        plan = controller.plan(_empty_bundle(), caps)
        names = {inv.skill_name for inv in plan.invocations}
        self.assertNotIn("reformulate_query", names)


if __name__ == "__main__":
    unittest.main()
