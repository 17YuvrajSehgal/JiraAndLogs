"""Offline tests for Phase 1.11: AgentRunner.

Covers:
  - Basic run: emits plan_start, skill_start/end pairs, plan_end.
  - Decision building: compose_triage → triage_*, compose_l2 → matched,
    compose_novelty → is_novel.
  - Gate-closed skills: skill_skipped_by_gate, no skill_start/end.
  - Cache hit path: cache_hit + skill_end(from_cache=True); no skill cost
    added to total.
  - Cache miss path: cache.put called; skill.invoke called once.
  - Budget exhaustion: budget_exceeded event + plan aborts.
  - Skill exception: skill_failed event; on_failure="continue" keeps
    walking; on_failure="abort" halts.
  - Unregistered skill: skill_failed("not_registered").
  - Evaluation mode: wol → text_retrieval_generalisation;
    online_boutique → telemetry_diagnosis; explicit override wins.
  - Trace persistence: trace_root set → file written.
  - Health check: provider that reports unavailable → RunnerError.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_runner -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import (
    Budget,
    Capabilities,
    InputBundle,
    SkillCallCost,
    SkillOutput,
    TEXT_EVIDENCE,
    Trace,
    TraceEvent,
)
from agent.plan import Plan, SkillInvocation
from agent.runner import AgentRunner, RunnerError
from agent.skills import (
    AgentContext,
    MemoryView,
    NullSkillCache,
    Skill,
    SkillCache,
    SkillRegistry,
    make_cost,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _StubMemoryIssue:
    def __init__(self, issue_id: str):
        self.jira_shadow_issue_id = issue_id


def _bundle(window_id: str = "w-test", dataset: str = "online_boutique") -> InputBundle:
    return InputBundle(window_id=window_id, dataset=dataset, text_evidence="evidence")


def _memory(*ids: str) -> MemoryView:
    return MemoryView([_StubMemoryIssue(i) for i in ids])


# ---------------------------------------------------------------------------
# Stub skills — concrete implementations the runner can invoke without
# needing predictions JSONLs on disk.
# ---------------------------------------------------------------------------


class _RecordingSkill(Skill):
    """Skill that just records that it was invoked + returns a fixed output."""

    name = "recording"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(
        self,
        *,
        skill_name: str = "recording",
        triage_score: float | None = 0.5,
        matched: tuple[str, ...] = ("PROJ-1",),
        is_novel: bool | None = None,
        cost: SkillCallCost | None = None,
    ):
        # Subclass per-test by overriding `name` class-attr would normally
        # be cleaner, but we want per-instance customization without
        # creating dozens of classes.
        self._skill_name = skill_name
        self._triage_score = triage_score
        self._matched = matched
        self._is_novel = is_novel
        self._cost = cost or make_cost(llm_tokens=0, wall_seconds=0.001)
        self.invocations = 0

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._skill_name

    @name.setter
    def name(self, value: str) -> None:
        self._skill_name = value

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        self.invocations += 1
        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=self._triage_score,
            triage_decision="ticket_worthy" if (self._triage_score or 0) >= 0.5 else "noise",
            matched_issue_ids=self._matched,
            is_novel=self._is_novel,
            confidence=self._triage_score or 0.0,
            cost=self._cost,
        )


class _RaisingSkill(Skill):
    name = "raises"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(self, *, exc: Exception | None = None):
        self._exc = exc or RuntimeError("boom")
        self.invocations = 0

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        self.invocations += 1
        raise self._exc


class _ExpensiveSkill(Skill):
    """Skill whose cost will exceed a tight budget on deduction."""

    name = "expensive"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "expensive_llm"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=0.99, matched_issue_ids=("E-1",),
            cost=make_cost(llm_tokens=200_000, usd=1.0, wall_seconds=10.0),
        )


# ---------------------------------------------------------------------------
# Plan-construction helpers
# ---------------------------------------------------------------------------


def _inv(name: str, *, version: str = "1.0.0", gate=None,
         on_failure: str = "fallback") -> SkillInvocation:
    return SkillInvocation(
        skill_name=name, skill_version=version,
        inputs={},
        per_call_budget=Budget(),
        on_failure=on_failure,
        gate=gate,
    )


def _plan(invs: list[SkillInvocation], *, budget: Budget | None = None) -> Plan:
    return Plan(
        invocations=tuple(invs),
        global_budget=budget or Budget(),
    )


# ---------------------------------------------------------------------------
# AgentRunner construction
# ---------------------------------------------------------------------------


class TestRunnerConstruction(unittest.TestCase):
    def test_requires_registry(self):
        with self.assertRaises(RunnerError):
            AgentRunner(None)                                # type: ignore[arg-type]

    def test_default_cache_is_null(self):
        r = AgentRunner(SkillRegistry())
        self.assertIsInstance(r.cache, NullSkillCache)

    def test_provider_health_check_failure_raises(self):
        class _BadProvider:
            def is_available(self):
                class _H:
                    ok = False
                    message = "unreachable"
                return _H()

        with self.assertRaises(RunnerError) as ctx:
            AgentRunner(SkillRegistry(), llm=_BadProvider())
        self.assertIn("unreachable", str(ctx.exception))

    def test_provider_health_check_ok_passes(self):
        class _GoodProvider:
            def is_available(self):
                class _H:
                    ok = True
                    message = ""
                return _H()
        # Should not raise
        AgentRunner(SkillRegistry(), llm=_GoodProvider())

    def test_health_check_disabled(self):
        class _BadProvider:
            def is_available(self):
                class _H:
                    ok = False
                    message = "down"
                return _H()
        # Even a bad provider passes when health_check=False
        AgentRunner(SkillRegistry(), llm=_BadProvider(), health_check=False)

    def test_provider_without_is_available_is_accepted(self):
        # A bare provider stub without health check is permitted (tests etc.)
        AgentRunner(SkillRegistry(), llm=object())


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestRunnerBasicExecution(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.skill = _RecordingSkill(skill_name="recording")
        self.registry.register(self.skill)
        self.runner = AgentRunner(self.registry)

    def test_single_invocation_runs(self):
        plan = _plan([_inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory("M-1"))
        self.assertEqual(self.skill.invocations, 1)
        self.assertEqual(decision.bundle_id, "w-test")
        self.assertEqual(decision.plan_id, plan.plan_id)

    def test_skills_invoked_appears_in_decision(self):
        plan = _plan([_inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertIn("recording", decision.skills_invoked)

    def test_cost_aggregated_in_decision(self):
        plan = _plan([_inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory())
        # Stub returns 0.001s per call; n_calls=1.
        self.assertAlmostEqual(decision.cost.wall_seconds, 0.001)
        self.assertEqual(decision.cost.n_calls, 1)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


class TestRunnerGates(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.skill = _RecordingSkill(skill_name="recording")
        self.registry.register(self.skill)
        self.runner = AgentRunner(self.registry)

    def test_gate_open_runs_skill(self):
        plan = _plan([_inv("recording", gate=lambda trace, budget: True)])
        self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(self.skill.invocations, 1)

    def test_gate_closed_skips_skill(self):
        plan = _plan([_inv("recording", gate=lambda trace, budget: False)])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(self.skill.invocations, 0)
        self.assertNotIn("recording", decision.skills_invoked)

    def test_gate_closed_emits_skipped_event(self):
        plan = _plan([_inv("recording", gate=lambda trace, budget: False)])
        self.runner.run(plan, _bundle(), _memory())
        # Re-run + inspect trace via persistence path
        with tempfile.TemporaryDirectory() as td:
            runner = AgentRunner(self.registry, trace_root=td)
            runner.run(plan, _bundle("w2"), _memory(), persist_trace=True)
            trace = Trace.load(Path(td) / "w2.json")
            kinds = [e.kind for e in trace.events]
            self.assertIn("skill_skipped_by_gate", kinds)

    def test_gate_raises_treated_as_closed(self):
        def _bad_gate(trace, budget):
            raise ValueError("gate broken")
        plan = _plan([_inv("recording", gate=_bad_gate)])
        self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(self.skill.invocations, 0)


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestRunnerCache(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.skill = _RecordingSkill(skill_name="recording")
        self.registry.register(self.skill)
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = SkillCache(root=Path(self.tmp.name))
        self.runner = AgentRunner(self.registry, cache=self.cache)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_misses_then_caches(self):
        plan = _plan([_inv("recording")])
        self.runner.run(plan, _bundle(), _memory("M-1"))
        self.assertEqual(self.skill.invocations, 1)
        stats = self.cache.stats()
        self.assertEqual(stats["puts"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hits"], 0)

    def test_second_run_hits_cache(self):
        plan = _plan([_inv("recording")])
        self.runner.run(plan, _bundle(), _memory("M-1"))
        self.runner.run(plan, _bundle(), _memory("M-1"))
        # Skill invoked only once across both runs
        self.assertEqual(self.skill.invocations, 1)
        self.assertEqual(self.cache.stats()["hits"], 1)

    def test_cache_hit_does_not_charge_budget(self):
        plan = _plan([_inv("recording")])
        d1 = self.runner.run(plan, _bundle(), _memory("M-1"))
        d2 = self.runner.run(plan, _bundle(), _memory("M-1"))
        # First run paid the cost; second run's cost should be 0 (cache hit)
        self.assertAlmostEqual(d1.cost.wall_seconds, 0.001)
        self.assertEqual(d2.cost.wall_seconds, 0.0)
        self.assertEqual(d2.cost.n_calls, 0)

    def test_cache_hit_still_appears_in_skills_invoked(self):
        plan = _plan([_inv("recording")])
        self.runner.run(plan, _bundle(), _memory("M-1"))
        d2 = self.runner.run(plan, _bundle(), _memory("M-1"))
        self.assertIn("recording", d2.skills_invoked)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class TestRunnerBudget(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.registry.register(_ExpensiveSkill())
        self.registry.register(_RecordingSkill(skill_name="cheap1"))
        self.runner = AgentRunner(self.registry)

    def test_skill_cost_exceeds_budget_aborts_plan(self):
        tight = Budget(max_llm_tokens=100, max_usd_equivalent=0.001, max_skill_calls=5)
        plan = _plan([_inv("expensive"), _inv("cheap1")], budget=tight)
        decision = self.runner.run(plan, _bundle(), _memory())
        # Expensive ran (it doesn't know the budget upfront), but its
        # post-deduct exceeded the budget → plan aborts before cheap1.
        self.assertNotIn("cheap1", decision.skills_invoked)

    def test_aborted_plan_with_no_compose_yields_needs_review(self):
        tight = Budget(max_llm_tokens=100, max_usd_equivalent=0.001, max_skill_calls=5)
        plan = _plan([_inv("expensive")], budget=tight)
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(decision.triage_decision, "needs_review")
        self.assertEqual(decision.confidence, 0.0)


# ---------------------------------------------------------------------------
# Skill exception handling
# ---------------------------------------------------------------------------


class TestRunnerSkillFailure(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.raising = _RaisingSkill()
        self.recording = _RecordingSkill(skill_name="recording")
        self.registry.register(self.raising)
        self.registry.register(self.recording)
        self.runner = AgentRunner(self.registry)

    def test_skill_exception_records_skill_failed_event(self):
        plan = _plan([_inv("raises", on_failure="continue")])
        with tempfile.TemporaryDirectory() as td:
            runner = AgentRunner(self.registry, trace_root=td)
            runner.run(plan, _bundle("w-fail"), _memory())
            trace = Trace.load(Path(td) / "w-fail.json")
            kinds = [e.kind for e in trace.events]
            self.assertIn("skill_failed", kinds)

    def test_on_failure_continue_keeps_executing(self):
        plan = _plan([_inv("raises", on_failure="continue"), _inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory())
        # recording still ran after raises failed
        self.assertEqual(self.recording.invocations, 1)
        self.assertIn("recording", decision.skills_invoked)

    def test_on_failure_abort_stops_plan(self):
        plan = _plan([_inv("raises", on_failure="abort"), _inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(self.recording.invocations, 0)
        self.assertNotIn("recording", decision.skills_invoked)

    def test_unregistered_skill_recorded_as_failure(self):
        plan = _plan([_inv("nonexistent", on_failure="continue"), _inv("recording")])
        decision = self.runner.run(plan, _bundle(), _memory())
        # Recording still ran (on_failure=continue lets us advance past
        # the unresolved name).
        self.assertEqual(self.recording.invocations, 1)
        # And the decision still gets built
        self.assertEqual(decision.bundle_id, "w-test")


# ---------------------------------------------------------------------------
# AgentDecision derivation from composition outputs
# ---------------------------------------------------------------------------


class _ComposeTriageStub(Skill):
    name = "compose_triage"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(self, *, score: float = 0.87):
        self._score = score

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=self._score,
            triage_decision="ticket_worthy" if self._score >= 0.5 else "noise",
            confidence=self._score,
            cost=make_cost(),
        )


class _ComposeL2Stub(Skill):
    name = "compose_l2"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            matched_issue_ids=("FUSED-1", "FUSED-2", "FUSED-3"),
            confidence=1.0, cost=make_cost(),
        )


class _ComposeNoveltyStub(Skill):
    name = "compose_novelty"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(self, *, novel: bool = True):
        self._novel = novel

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            is_novel=self._novel, confidence=1.0, cost=make_cost(),
        )


class TestRunnerDecisionDerivation(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.registry.register(_ComposeTriageStub(score=0.87))
        self.registry.register(_ComposeL2Stub())
        self.registry.register(_ComposeNoveltyStub(novel=True))
        self.runner = AgentRunner(self.registry)

    def test_triage_fields_from_compose_triage(self):
        plan = _plan([
            _inv("compose_l2"), _inv("compose_triage"), _inv("compose_novelty"),
        ])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(decision.triage_decision, "ticket_worthy")
        self.assertAlmostEqual(decision.triage_score, 0.87)
        self.assertAlmostEqual(decision.confidence, 0.87)

    def test_matched_from_compose_l2(self):
        plan = _plan([_inv("compose_l2"), _inv("compose_triage"), _inv("compose_novelty")])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertEqual(decision.matched_issue_ids,
                         ("FUSED-1", "FUSED-2", "FUSED-3"))

    def test_is_novel_from_compose_novelty(self):
        plan = _plan([_inv("compose_l2"), _inv("compose_triage"), _inv("compose_novelty")])
        decision = self.runner.run(plan, _bundle(), _memory())
        self.assertTrue(decision.is_novel)

    def test_matched_falls_back_to_retrieve_dense(self):
        # Drop compose_l2; register retrieve_dense
        reg = SkillRegistry()
        reg.register(_RecordingSkill(skill_name="retrieve_dense",
                                      matched=("DENSE-1",), triage_score=0.6))
        reg.register(_ComposeTriageStub(score=0.6))
        reg.register(_ComposeNoveltyStub(novel=False))
        runner = AgentRunner(reg)
        plan = _plan([_inv("retrieve_dense"),
                      _inv("compose_triage"),
                      _inv("compose_novelty")])
        decision = runner.run(plan, _bundle(), _memory())
        self.assertEqual(decision.matched_issue_ids, ("DENSE-1",))


# ---------------------------------------------------------------------------
# Evaluation mode
# ---------------------------------------------------------------------------


class TestRunnerEvaluationMode(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()
        self.registry.register(_RecordingSkill(skill_name="r1"))
        self.runner = AgentRunner(self.registry)

    def test_wol_dataset_text_retrieval_mode(self):
        plan = _plan([_inv("r1")])
        d = self.runner.run(plan, _bundle(dataset="wol"), _memory())
        self.assertEqual(d.evaluation_mode, "text_retrieval_generalisation")

    def test_world_of_logs_alias(self):
        plan = _plan([_inv("r1")])
        d = self.runner.run(plan, _bundle(dataset="world_of_logs"), _memory())
        self.assertEqual(d.evaluation_mode, "text_retrieval_generalisation")

    def test_online_boutique_telemetry_mode(self):
        plan = _plan([_inv("r1")])
        d = self.runner.run(plan, _bundle(dataset="online_boutique"), _memory())
        self.assertEqual(d.evaluation_mode, "telemetry_diagnosis")

    def test_otel_demo_telemetry_mode(self):
        plan = _plan([_inv("r1")])
        d = self.runner.run(plan, _bundle(dataset="otel_demo"), _memory())
        self.assertEqual(d.evaluation_mode, "telemetry_diagnosis")

    def test_explicit_override_wins(self):
        plan = _plan([_inv("r1")])
        d = self.runner.run(
            plan, _bundle(dataset="wol"), _memory(),
            evaluation_mode="telemetry_diagnosis",
        )
        self.assertEqual(d.evaluation_mode, "telemetry_diagnosis")


# ---------------------------------------------------------------------------
# Trace persistence
# ---------------------------------------------------------------------------


class TestRunnerTracePersistence(unittest.TestCase):
    def test_trace_written_when_trace_root_set(self):
        reg = SkillRegistry()
        reg.register(_RecordingSkill(skill_name="r1"))
        with tempfile.TemporaryDirectory() as td:
            runner = AgentRunner(reg, trace_root=td, experiment="exp-A")
            decision = runner.run(
                _plan([_inv("r1")]),
                _bundle("w-T"),
                _memory(),
            )
            expected = Path(td) / "exp-A" / "w-T.json"
            self.assertTrue(expected.exists())
            self.assertEqual(decision.trace_path, str(expected))

            # Load and inspect
            trace = Trace.load(expected)
            self.assertEqual(trace.bundle_id, "w-T")
            kinds = {e.kind for e in trace.events}
            self.assertIn("plan_start", kinds)
            self.assertIn("plan_end", kinds)
            self.assertIn("skill_start", kinds)
            self.assertIn("skill_end", kinds)

    def test_no_trace_written_when_persist_disabled(self):
        reg = SkillRegistry()
        reg.register(_RecordingSkill(skill_name="r1"))
        with tempfile.TemporaryDirectory() as td:
            runner = AgentRunner(reg, trace_root=td)
            runner.run(_plan([_inv("r1")]), _bundle("w-no-persist"),
                       _memory(), persist_trace=False)
            self.assertFalse((Path(td) / "w-no-persist.json").exists())


if __name__ == "__main__":
    unittest.main()
