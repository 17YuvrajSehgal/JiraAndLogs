"""Offline unit tests for Phase 1.4 dataclasses.

Covers:
    - Capabilities (flag set + richness + masking)
    - InputBundle + sub-records (LogLine, TraceSummary, K8sEvent)
    - SkillCallCost arithmetic
    - SkillOutput + AgentDecision serialization roundtrip
    - Budget enforcement (can_afford, deduct, BudgetExhausted)
    - Plan hashing + ablation (with_disabled_skills)
    - Trace event accumulation + JSON roundtrip

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_dataclasses -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import (
    ALL_FLAGS,
    AgentDecision,
    Budget,
    BudgetExhausted,
    BudgetSnapshot,
    Capabilities,
    InputBundle,
    K8S_EVENTS,
    K8sEvent,
    LogLine,
    MEMORY_TEXT,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    Plan,
    SkillCallCost,
    SkillInvocation,
    SkillOutput,
    TEXT_EVIDENCE,
    Trace,
    TraceEvent,
    TraceSummary,
    UNORDERED_LOGS,
    VERIFIER_KNOWN_HELPFUL,
)


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities(unittest.TestCase):
    def test_empty_capabilities(self):
        c = Capabilities()
        self.assertFalse(c.has(NUMERIC_FEATURES))
        self.assertFalse(c.has_any([NUMERIC_FEATURES, ORDERED_LOGS]))
        self.assertTrue(c.has_all([]))

    def test_with_flags_returns_new_instance(self):
        c = Capabilities()
        c2 = c.with_flags(NUMERIC_FEATURES, TEXT_EVIDENCE)
        self.assertFalse(c.has(NUMERIC_FEATURES))                # original unchanged
        self.assertTrue(c2.has(NUMERIC_FEATURES))
        self.assertTrue(c2.has(TEXT_EVIDENCE))
        self.assertTrue(c2.has_all([NUMERIC_FEATURES, TEXT_EVIDENCE]))

    def test_without_flags(self):
        c = Capabilities(flags=frozenset({NUMERIC_FEATURES, TEXT_EVIDENCE}))
        c2 = c.without_flags(NUMERIC_FEATURES)
        self.assertTrue(c2.has(TEXT_EVIDENCE))
        self.assertFalse(c2.has(NUMERIC_FEATURES))

    def test_richness_keeps_per_flag_detail(self):
        c = Capabilities(flags=frozenset({ORDERED_LOGS}))
        c2 = c.with_richness(ORDERED_LOGS, n_lines=47, max_span_s=312)
        self.assertEqual(c2.get_richness(ORDERED_LOGS, "n_lines"), 47)
        self.assertEqual(c2.get_richness(ORDERED_LOGS, "max_span_s"), 312)
        self.assertIsNone(c2.get_richness(ORDERED_LOGS, "missing"))

    def test_mask_is_alias_for_without_flags(self):
        c = Capabilities(flags=frozenset({NUMERIC_FEATURES, TEXT_EVIDENCE}))
        self.assertEqual(c.mask([NUMERIC_FEATURES]), c.without_flags(NUMERIC_FEATURES))

    def test_all_flags_constant_is_complete(self):
        # Every flag constant defined in capabilities.py is in ALL_FLAGS
        expected = {
            NUMERIC_FEATURES, TEXT_EVIDENCE, ORDERED_LOGS, UNORDERED_LOGS,
            "TRACE_SUMMARY", K8S_EVENTS, "METRIC_SNAPSHOTS",
            MEMORY_TEXT, "KG_GRAPH_MEMORY", "KG_GRAPH_WINDOW",
            VERIFIER_KNOWN_HELPFUL,
        }
        self.assertEqual(set(ALL_FLAGS), expected)

    def test_serialization_roundtrip(self):
        c = Capabilities(
            flags=frozenset({NUMERIC_FEATURES, ORDERED_LOGS}),
            richness={ORDERED_LOGS: {"n_lines": 5}},
        )
        c2 = Capabilities.from_dict(c.to_dict())
        self.assertEqual(c.flags, c2.flags)
        self.assertEqual(c.richness, c2.richness)


# ---------------------------------------------------------------------------
# InputBundle
# ---------------------------------------------------------------------------


class TestInputBundle(unittest.TestCase):
    def test_minimal_bundle(self):
        b = InputBundle(window_id="w1", dataset="ob")
        self.assertEqual(b.window_id, "w1")
        self.assertIsNone(b.text_evidence)
        self.assertIsNone(b.numeric_features)
        self.assertEqual(b.cache_key(), "ob/w1")

    def test_bundle_roundtrip_with_all_fields(self):
        b = InputBundle(
            window_id="w1", dataset="ob",
            text_evidence="cart-redis timeout",
            numeric_features={"latency_p99": 1.5, "error_rate": 0.3},
            log_lines=(
                LogLine(ts_ns=100, service="cart", severity="error", line="oops"),
                LogLine(ts_ns=200, service="redis", severity="warn", line="slow"),
            ),
            log_lines_ordered=True,
            trace_summary=TraceSummary(
                n_spans=12, error_spans=3, p99_latency_ms=520.0,
                affected_services=("cart", "redis"),
                summary_text="cart calls to redis exceeded SLO",
            ),
            k8s_events=(
                K8sEvent(ts_ns=300, kind="Pod", reason="Killing",
                         message="OOM", object_name="cart-abc"),
            ),
            metric_snapshots={"cpu_pct": (0.6, 0.7, 0.85)},
            scenario_family="cart-redis-degradation",
            service_name="cart",
            window_type="active_fault",
            extra={"custom_field": "value"},
        )
        d = b.to_dict()
        b2 = InputBundle.from_dict(d)
        self.assertEqual(b.window_id, b2.window_id)
        self.assertEqual(b.text_evidence, b2.text_evidence)
        self.assertEqual(b.numeric_features, b2.numeric_features)
        self.assertEqual(len(b2.log_lines), 2)
        self.assertEqual(b2.log_lines[0].service, "cart")
        self.assertEqual(b2.trace_summary.n_spans, 12)
        self.assertEqual(b2.k8s_events[0].reason, "Killing")
        self.assertEqual(b2.metric_snapshots["cpu_pct"], (0.6, 0.7, 0.85))
        self.assertEqual(b2.scenario_family, "cart-redis-degradation")
        self.assertEqual(b2.extra["custom_field"], "value")

    def test_replace_extra_does_not_mutate_original(self):
        b = InputBundle(window_id="w1", dataset="ob", extra={"a": 1})
        b2 = b.replace_extra(b=2)
        self.assertEqual(b.extra, {"a": 1})
        self.assertEqual(b2.extra, {"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# SkillCallCost + SkillOutput
# ---------------------------------------------------------------------------


class TestSkillCallCost(unittest.TestCase):
    def test_zero(self):
        z = SkillCallCost.zero()
        self.assertEqual(z.llm_tokens, 0)
        self.assertEqual(z.usd, 0.0)
        # zero() is the additive identity — every field is 0, including
        # n_calls (so accumulating N costs gives n_calls=N, not N+1).
        self.assertEqual(z.n_calls, 0)

    def test_addition(self):
        a = SkillCallCost(llm_tokens=10, usd=0.001, n_calls=1)
        b = SkillCallCost(llm_tokens=20, usd=0.002, n_calls=2)
        s = a + b
        self.assertEqual(s.llm_tokens, 30)
        self.assertAlmostEqual(s.usd, 0.003)
        self.assertEqual(s.n_calls, 3)


class TestSkillOutput(unittest.TestCase):
    def test_default(self):
        o = SkillOutput(skill="retrieve_dense")
        self.assertEqual(o.skill, "retrieve_dense")
        self.assertIsNone(o.triage_score)
        self.assertEqual(o.matched_issue_ids, ())

    def test_roundtrip(self):
        o = SkillOutput(
            skill="retrieve_dense", skill_version="1.0.0",
            triage_score=0.85, triage_decision="ticket_worthy",
            matched_issue_ids=("PROJ-1", "PROJ-2"),
            confidence=0.9,
            evidence_used=("TEXT_EVIDENCE", "MEMORY_TEXT"),
            cost=SkillCallCost(llm_tokens=100, usd=0.0001),
            extra={"top1_overlap": True},
        )
        o2 = SkillOutput.from_dict(o.to_dict())
        self.assertEqual(o.skill, o2.skill)
        self.assertEqual(o.matched_issue_ids, o2.matched_issue_ids)
        self.assertEqual(o.evidence_used, o2.evidence_used)
        self.assertEqual(o.cost.llm_tokens, o2.cost.llm_tokens)
        self.assertEqual(o.extra, o2.extra)


# ---------------------------------------------------------------------------
# AgentDecision
# ---------------------------------------------------------------------------


class TestAgentDecision(unittest.TestCase):
    def test_default_evaluation_mode(self):
        d = AgentDecision(
            bundle_id="w1",
            triage_decision="ticket_worthy",
            triage_score=0.9,
        )
        self.assertEqual(d.evaluation_mode, "telemetry_diagnosis")

    def test_wol_evaluation_mode(self):
        d = AgentDecision(
            bundle_id="wol-q-x", triage_decision="ticket_worthy",
            triage_score=0.8, evaluation_mode="text_retrieval_generalisation",
        )
        d2 = AgentDecision.from_dict(d.to_dict())
        self.assertEqual(d2.evaluation_mode, "text_retrieval_generalisation")

    def test_roundtrip(self):
        d = AgentDecision(
            bundle_id="w1", triage_decision="ticket_worthy",
            triage_score=0.9,
            matched_issue_ids=("PROJ-1",),
            is_novel=False, confidence=0.95,
            plan_id="plan_abc123",
            skills_invoked=("retrieve_dense", "compose_l2"),
            cost=SkillCallCost(llm_tokens=50),
            trace_path="data/agent_traces/exp/w1.json",
        )
        d2 = AgentDecision.from_dict(d.to_dict())
        self.assertEqual(d.bundle_id, d2.bundle_id)
        self.assertEqual(d.skills_invoked, d2.skills_invoked)
        self.assertEqual(d.cost.llm_tokens, d2.cost.llm_tokens)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class TestBudget(unittest.TestCase):
    def test_can_afford_under_cap(self):
        b = Budget(max_llm_tokens=100, max_usd_equivalent=1.0,
                   max_wall_seconds=10.0, max_skill_calls=5)
        self.assertTrue(b.can_afford(SkillCallCost(llm_tokens=10, usd=0.1)))

    def test_cant_afford_over_cap(self):
        b = Budget(max_llm_tokens=100)
        self.assertFalse(b.can_afford(SkillCallCost(llm_tokens=200)))

    def test_deduct_succeeds_under_cap(self):
        b = Budget(max_llm_tokens=100, max_usd_equivalent=1.0)
        b.deduct(SkillCallCost(llm_tokens=30, usd=0.3, n_calls=1))
        b.deduct(SkillCallCost(llm_tokens=20, usd=0.2, n_calls=1))
        self.assertEqual(b.spent_tokens, 50)
        self.assertAlmostEqual(b.spent_usd, 0.5)
        self.assertEqual(b.spent_calls, 2)

    def test_deduct_raises_BudgetExhausted_on_tokens(self):
        b = Budget(max_llm_tokens=50)
        b.deduct(SkillCallCost(llm_tokens=40, n_calls=1))
        with self.assertRaises(BudgetExhausted) as ctx:
            b.deduct(SkillCallCost(llm_tokens=20, n_calls=1))
        self.assertEqual(ctx.exception.kind, "tokens")
        # State unchanged on exception
        self.assertEqual(b.spent_tokens, 40)

    def test_deduct_raises_on_usd(self):
        b = Budget(max_usd_equivalent=0.1)
        with self.assertRaises(BudgetExhausted) as ctx:
            b.deduct(SkillCallCost(usd=0.2))
        self.assertEqual(ctx.exception.kind, "usd")

    def test_deduct_raises_on_calls(self):
        b = Budget(max_skill_calls=2)
        b.deduct(SkillCallCost(n_calls=1))
        b.deduct(SkillCallCost(n_calls=1))
        with self.assertRaises(BudgetExhausted) as ctx:
            b.deduct(SkillCallCost(n_calls=1))
        self.assertEqual(ctx.exception.kind, "calls")

    def test_clone_resets_counters(self):
        b = Budget(max_llm_tokens=100)
        b.deduct(SkillCallCost(llm_tokens=50))
        c = b.clone()
        self.assertEqual(c.max_llm_tokens, 100)
        self.assertEqual(c.spent_tokens, 0)

    def test_snapshot_is_frozen(self):
        b = Budget()
        b.deduct(SkillCallCost(llm_tokens=10))
        s = b.snapshot()
        self.assertIsInstance(s, BudgetSnapshot)
        self.assertEqual(s.spent_tokens, 10)
        # Mutating the original Budget does NOT change the snapshot
        b.deduct(SkillCallCost(llm_tokens=5))
        self.assertEqual(s.spent_tokens, 10)

    def test_remaining(self):
        b = Budget(max_llm_tokens=100, max_usd_equivalent=1.0)
        b.deduct(SkillCallCost(llm_tokens=30, usd=0.3))
        r = b.remaining()
        self.assertEqual(r["llm_tokens"], 70)
        self.assertAlmostEqual(r["usd"], 0.7)

    def test_roundtrip(self):
        b = Budget(max_llm_tokens=200, max_usd_equivalent=0.5)
        b.deduct(SkillCallCost(llm_tokens=50, usd=0.1))
        b2 = Budget.from_dict(b.to_dict())
        self.assertEqual(b2.max_llm_tokens, 200)
        self.assertEqual(b2.spent_tokens, 50)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class TestPlan(unittest.TestCase):
    def test_plan_id_is_stable(self):
        p1 = Plan(invocations=(
            SkillInvocation(skill_name="a"),
            SkillInvocation(skill_name="b"),
        ))
        p2 = Plan(invocations=(
            SkillInvocation(skill_name="a"),
            SkillInvocation(skill_name="b"),
        ))
        self.assertEqual(p1.plan_id, p2.plan_id)

    def test_plan_id_changes_with_invocations(self):
        p1 = Plan(invocations=(SkillInvocation(skill_name="a"),))
        p2 = Plan(invocations=(SkillInvocation(skill_name="b"),))
        self.assertNotEqual(p1.plan_id, p2.plan_id)

    def test_plan_id_starts_with_plan_prefix(self):
        p = Plan(invocations=(SkillInvocation(skill_name="x"),))
        self.assertTrue(p.plan_id.startswith("plan_"))

    def test_with_disabled_skills_drops_them(self):
        p = Plan(invocations=(
            SkillInvocation(skill_name="a"),
            SkillInvocation(skill_name="b"),
            SkillInvocation(skill_name="c"),
        ))
        p2 = p.with_disabled_skills({"b"})
        self.assertEqual([i.skill_name for i in p2.invocations], ["a", "c"])
        # plan_id is different
        self.assertNotEqual(p.plan_id, p2.plan_id)

    def test_with_disabled_skills_keeps_fallback_chains_consistent(self):
        p = Plan(
            invocations=(SkillInvocation(skill_name="a"),),
            fallback_chains={"a": ("b", "c"), "b": ("d",)},
        )
        p2 = p.with_disabled_skills({"b"})
        # "b" is removed both as a fallback target and as a key
        self.assertEqual(p2.fallback_chains["a"], ("c",))
        self.assertNotIn("b", p2.fallback_chains)

    def test_roundtrip_preserves_plan_id(self):
        p = Plan(invocations=(SkillInvocation(skill_name="x"),))
        d = p.to_dict()
        p2 = Plan.from_dict(d)
        self.assertEqual(p.plan_id, p2.plan_id)

    def test_gate_is_not_serialised(self):
        # Gate functions can't survive JSON; that's documented.
        # has_gate flag IS serialised so a debugger can see it existed.
        p = Plan(invocations=(
            SkillInvocation(skill_name="x", gate=lambda trace, budget: True),
        ))
        d = p.to_dict()
        self.assertTrue(d["invocations"][0]["has_gate"])
        p2 = Plan.from_dict(d)
        self.assertIsNone(p2.invocations[0].gate)


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class TestTrace(unittest.TestCase):
    def test_empty_trace(self):
        t = Trace(bundle_id="w1", plan_id="plan_x")
        self.assertEqual(t.n_skill_calls(), 0)
        self.assertFalse(t.had_error())
        self.assertEqual(t.skill_names_invoked(), ())

    def test_add_events_tracks_skill_names(self):
        t = Trace(bundle_id="w1", plan_id="plan_x")
        t.add(TraceEvent(ts=TraceEvent.now(), kind="plan_start"))
        t.add(TraceEvent(ts=TraceEvent.now(), kind="skill_start", skill="retrieve_dense"))
        t.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
            output=SkillOutput(skill="retrieve_dense", triage_score=0.7),
        ))
        t.add(TraceEvent(ts=TraceEvent.now(), kind="skill_start", skill="verify_with_llm"))
        t.add(TraceEvent(ts=TraceEvent.now(), kind="skill_failed", skill="verify_with_llm",
                         error="timeout"))
        self.assertEqual(t.n_skill_calls(), 2)
        self.assertTrue(t.had_error())
        self.assertEqual(
            t.skill_names_invoked(),
            ("retrieve_dense", "verify_with_llm"),
        )

    def test_latest_output_returns_most_recent_for_skill(self):
        t = Trace(bundle_id="w1", plan_id="plan_x")
        # Two skill_end events for the same skill — older then newer
        old_out = SkillOutput(skill="retrieve_dense", triage_score=0.5)
        new_out = SkillOutput(skill="retrieve_dense", triage_score=0.8)
        t.add(TraceEvent(ts=TraceEvent.now(), kind="skill_end",
                         skill="retrieve_dense", output=old_out))
        t.add(TraceEvent(ts=TraceEvent.now(), kind="skill_end",
                         skill="retrieve_dense", output=new_out))
        latest = t.latest_output("retrieve_dense")
        self.assertEqual(latest.triage_score, 0.8)
        self.assertIsNone(t.latest_output("nonexistent_skill"))

    def test_close_sets_final_decision(self):
        t = Trace(bundle_id="w1", plan_id="plan_x")
        d = AgentDecision(bundle_id="w1", triage_decision="noise", triage_score=0.1)
        t.close(d)
        self.assertEqual(t.final_decision, d)
        self.assertIsNotNone(t.finished_at)

    def test_serialization_roundtrip(self):
        t = Trace(bundle_id="w1", plan_id="plan_x")
        t.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end", skill="x",
            output=SkillOutput(skill="x"),
        ))
        t.close(AgentDecision(bundle_id="w1", triage_decision="ticket_worthy",
                              triage_score=0.9))
        d = t.to_dict()
        t2 = Trace.from_dict(d)
        self.assertEqual(t.bundle_id, t2.bundle_id)
        self.assertEqual(len(t.events), len(t2.events))
        self.assertEqual(t.final_decision.triage_decision,
                         t2.final_decision.triage_decision)

    def test_write_and_load_from_disk(self):
        t = Trace(bundle_id="w-disk", plan_id="plan_x")
        t.add(TraceEvent(ts=TraceEvent.now(), kind="plan_start"))
        t.close(AgentDecision(bundle_id="w-disk", triage_decision="noise",
                              triage_score=0.1))
        with tempfile.TemporaryDirectory() as tmpdir:
            path = t.write_to(tmpdir, experiment="test-exp")
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "w-disk.json")
            t2 = Trace.load(path)
            self.assertEqual(t2.bundle_id, "w-disk")
            self.assertEqual(t2.final_decision.bundle_id, "w-disk")


# ---------------------------------------------------------------------------
# Smoke: every class imports from `agent`
# ---------------------------------------------------------------------------


class TestPublicAPI(unittest.TestCase):
    def test_all_exports_importable(self):
        from agent import (  # noqa: F401
            AgentDecision, Budget, BudgetExhausted, BudgetSnapshot,
            Capabilities, InputBundle, K8sEvent, LogLine,
            Plan, SkillCallCost, SkillInvocation, SkillOutput,
            Trace, TraceEvent, TraceSummary,
        )
        # All present


if __name__ == "__main__":
    unittest.main()
