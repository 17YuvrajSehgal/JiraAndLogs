"""Offline tests for Phase 2.5: AblationHarness.

Covers:
  - AblationSpec validation (can't mix disable + enable_exact; name required).
  - Serialization round-trip for AblationSpec + AblationConfig.
  - _MaskedObserver strips configured flags from observation output.
  - run_grid: baseline + ablations produce distinct reports with the
    expected metric deltas.
  - disable_skills drops the named skill from the plan.
  - enable_skills_exact keeps only the listed skills.
  - mask_capabilities removes flags so capability-gated skills are
    silently skipped.
  - Each ablation gets a FRESH StateLayer (suppression counts don't
    leak across ablations).

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_ablation_harness -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import (
    Capabilities,
    InputBundle,
    MEMORY_TEXT,
    NUMERIC_FEATURES,
    SkillCallCost,
    SkillOutput,
    TEXT_EVIDENCE,
)
from agent.capabilities_observer import CapabilitiesObserver, ObservationContext
from agent.eval_harness import (
    AblationConfig,
    AblationGridResult,
    AblationHarness,
    AblationSpec,
    ApplesToApplesContract,
    EvaluationCase,
)
from agent.eval_harness.ablation import _MaskedObserver
from agent.skills import (
    AgentContext,
    MemoryView,
    Skill,
    SkillRegistry,
    make_cost,
)
from agent.state import StateLayer


# ---------------------------------------------------------------------------
# AblationSpec validation + serialization
# ---------------------------------------------------------------------------


class TestAblationSpec(unittest.TestCase):
    def test_name_required(self):
        with self.assertRaises(ValueError):
            AblationSpec(name="")

    def test_cant_mix_disable_and_enable_exact(self):
        with self.assertRaises(ValueError):
            AblationSpec(
                name="mix",
                disable_skills=("a",),
                enable_skills_exact=("b",),
            )

    def test_serialization_roundtrip(self):
        spec = AblationSpec(
            name="no_verifier",
            disable_skills=("verify_with_llm",),
            mask_capabilities=("ORDERED_LOGS",),
            description="What if there were no verifier?",
        )
        spec2 = AblationSpec.from_dict(spec.to_dict())
        self.assertEqual(spec, spec2)


class TestAblationConfig(unittest.TestCase):
    def test_serialization_roundtrip(self):
        config = AblationConfig(
            name="exp1",
            baseline_name="full",
            ablations=(
                AblationSpec(name="no_v", disable_skills=("verify_with_llm",)),
                AblationSpec(name="dense_only",
                             enable_skills_exact=("retrieve_dense", "compose_l2",
                                                  "compose_triage", "compose_novelty")),
            ),
        )
        d = config.to_dict()
        config2 = AblationConfig.from_dict(d)
        self.assertEqual(config, config2)


# ---------------------------------------------------------------------------
# _MaskedObserver
# ---------------------------------------------------------------------------


class TestMaskedObserver(unittest.TestCase):
    def setUp(self):
        # An OB-shaped bundle with numeric features + text
        self.bundle = InputBundle(
            window_id="w1", dataset="online_boutique",
            text_evidence="lorem ipsum dolor sit amet",
            numeric_features={"x": 1.0, "y": 2.0},
        )
        self.observer = CapabilitiesObserver()

    def test_empty_mask_is_passthrough(self):
        wrapped = _MaskedObserver(self.observer, mask=())
        caps = wrapped.observe(self.bundle, ObservationContext())
        self.assertIn(NUMERIC_FEATURES, caps.flags)

    def test_mask_strips_flag(self):
        wrapped = _MaskedObserver(self.observer, mask=(NUMERIC_FEATURES,))
        caps = wrapped.observe(self.bundle, ObservationContext())
        self.assertNotIn(NUMERIC_FEATURES, caps.flags)
        # TEXT_EVIDENCE still present
        self.assertIn(TEXT_EVIDENCE, caps.flags)


# ---------------------------------------------------------------------------
# Stub skills for harness end-to-end
# ---------------------------------------------------------------------------


class _StubRetrieveDense(Skill):
    name = "retrieve_dense"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE, MEMORY_TEXT})
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        ranking = tuple(bundle.extra.get("desired_ranking", ()))
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            matched_issue_ids=ranking, triage_score=0.4,
            confidence=0.4, cost=make_cost(),
        )


class _StubTriageNumeric(Skill):
    """Mimics triage_numeric — needs NUMERIC_FEATURES. Used to verify
    that mask_capabilities causes it to be dropped from the plan."""
    name = "triage_numeric"
    version = "1.0.0"
    required_flags = frozenset({NUMERIC_FEATURES})
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=0.99,                # confident triage
            triage_decision="ticket_worthy",
            confidence=0.99, cost=make_cost(),
        )


class _StubComposeTriage(Skill):
    name = "compose_triage"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        # Read from the trace: triage_numeric output sets the score.
        trace = ctx.extra.get("trace")
        score = 0.0
        if trace is not None:
            num_out = trace.latest_output("triage_numeric")
            if num_out is not None and num_out.triage_score is not None:
                score = float(num_out.triage_score)
        decision = "ticket_worthy" if score >= 0.5 else "noise"
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=score, triage_decision=decision,
            confidence=score, cost=make_cost(),
        )


class _StubComposeL2(Skill):
    name = "compose_l2"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        trace = ctx.extra.get("trace")
        ranking: tuple[str, ...] = ()
        if trace is not None:
            dense_out = trace.latest_output("retrieve_dense")
            if dense_out is not None:
                ranking = dense_out.matched_issue_ids
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            matched_issue_ids=ranking,
            confidence=1.0 if ranking else 0.0, cost=make_cost(),
        )


class _StubComposeNovelty(Skill):
    name = "compose_novelty"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            is_novel=False, confidence=1.0, cost=make_cost(),
        )


def _build_full_registry() -> SkillRegistry:
    r = SkillRegistry()
    r.register(_StubTriageNumeric())
    r.register(_StubRetrieveDense())
    r.register(_StubComposeL2())
    r.register(_StubComposeTriage())
    r.register(_StubComposeNovelty())
    return r


def _build_case(window_id: str, *, desired_ranking=("A",),
                gold=("A",)) -> EvaluationCase:
    bundle = InputBundle(
        window_id=window_id,
        dataset="online_boutique",
        text_evidence="lorem ipsum dolor sit amet",
        numeric_features={"x": 1.0},
        service_name="cart",
        scenario_family="redis_oom",
        window_type="active_fault",
        extra={"desired_ranking": desired_ranking},
    )
    return EvaluationCase(
        bundle=bundle, memory=MemoryView([]),
        gold_matched_issue_ids=gold,
    )


# ---------------------------------------------------------------------------
# run_grid end-to-end
# ---------------------------------------------------------------------------


class TestAblationGrid(unittest.TestCase):
    def setUp(self):
        self.registry = _build_full_registry()
        self.cases = [_build_case(f"w{i}") for i in range(5)]
        self.contract = ApplesToApplesContract(
            dataset_id="test-ds", split="test",
            evaluation_mode="telemetry_diagnosis",
        )

    def test_baseline_plus_one_ablation(self):
        config = AblationConfig(
            name="exp1",
            ablations=(
                AblationSpec(name="no_dense", disable_skills=("retrieve_dense",)),
            ),
        )
        harness = AblationHarness(self.registry)
        result = harness.run_grid(self.cases, config, contract=self.contract)

        self.assertEqual(result.config.name, "exp1")
        self.assertIn("no_dense", result.ablation_reports)
        # Baseline: retrieve_dense ran, so compose_l2 has a ranking; hit_at_1=1.0
        self.assertAlmostEqual(result.baseline_report.hit_at_1, 1.0)
        # Ablation: retrieve_dense missing → compose_l2 has no input → no
        # matched_issue_ids → 0 hits.
        self.assertAlmostEqual(
            result.ablation_reports["no_dense"].hit_at_1, 0.0,
        )

    def test_enable_skills_exact_keeps_only_listed(self):
        config = AblationConfig(
            name="exp1",
            ablations=(
                AblationSpec(
                    name="dense_only",
                    enable_skills_exact=(
                        "retrieve_dense", "compose_l2",
                        "compose_triage", "compose_novelty",
                    ),
                ),
            ),
        )
        harness = AblationHarness(self.registry)
        result = harness.run_grid(self.cases, config, contract=self.contract)

        report = result.ablation_reports["dense_only"]
        # triage_numeric is dropped; compose_triage falls back to 0.0
        # → triage_decision="noise" → cases that were "ticket_worthy"
        # under baseline now triage as "noise".
        self.assertLess(
            report.triage_accuracy, result.baseline_report.triage_accuracy,
        )

    def test_mask_capabilities_strips_flag(self):
        config = AblationConfig(
            name="exp1",
            ablations=(
                AblationSpec(
                    name="no_numeric",
                    mask_capabilities=("NUMERIC_FEATURES",),
                ),
            ),
        )
        harness = AblationHarness(
            self.registry,
            observation_ctx=ObservationContext(
                dataset_id="test-ds", has_memory_text=True,
            ),
        )
        result = harness.run_grid(self.cases, config, contract=self.contract)

        # With NUMERIC_FEATURES masked, triage_numeric can't be invoked
        # → compose_triage gets no signal → triage_decision="noise"
        report = result.ablation_reports["no_numeric"]
        # baseline gets triage_score=0.99 → ticket_worthy (correct)
        # ablation gets 0.0 → noise (incorrect for these stub cases)
        self.assertLess(report.triage_accuracy,
                        result.baseline_report.triage_accuracy)

    def test_summary_rows_include_deltas(self):
        config = AblationConfig(
            name="exp1",
            ablations=(
                AblationSpec(name="no_dense", disable_skills=("retrieve_dense",)),
            ),
        )
        harness = AblationHarness(self.registry)
        result = harness.run_grid(self.cases, config, contract=self.contract)
        rows = result.to_summary_rows()
        # baseline + 1 ablation
        self.assertEqual(len(rows), 2)
        names = [r["ablation"] for r in rows]
        self.assertEqual(names[0], "baseline")
        self.assertEqual(names[1], "no_dense")
        # delta_hit_at_5 vs baseline
        self.assertIn("delta_hit_at_5", rows[1])
        self.assertLess(rows[1]["delta_hit_at_5"], 0.0)

    def test_state_layer_does_not_leak_across_ablations(self):
        # Two ablations whose state buffers would conflict if shared
        config = AblationConfig(
            name="exp1",
            ablations=(
                AblationSpec(name="a1", disable_skills=()),
                AblationSpec(name="a2", disable_skills=("retrieve_dense",)),
            ),
        )
        # Use a factory that returns a fresh StateLayer each time;
        # capture the instances created.
        instances = []
        def _factory():
            sl = StateLayer()
            instances.append(sl)
            return sl

        harness = AblationHarness(
            self.registry,
            state_layer_factory=_factory,
        )
        harness.run_grid(self.cases, config, contract=self.contract)
        # 1 baseline + 2 ablations = 3 fresh state layers
        self.assertEqual(len(instances), 3)
        # All three are distinct objects
        self.assertEqual(len({id(sl) for sl in instances}), 3)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestAblationGridResultSerialization(unittest.TestCase):
    def test_write_to_creates_file(self):
        registry = _build_full_registry()
        cases = [_build_case("w1")]
        config = AblationConfig(
            name="exp",
            ablations=(AblationSpec(name="no_d", disable_skills=("retrieve_dense",)),),
        )
        contract = ApplesToApplesContract(
            dataset_id="test", evaluation_mode="telemetry_diagnosis",
        )
        harness = AblationHarness(registry)
        result = harness.run_grid(cases, config, contract=contract)

        with tempfile.TemporaryDirectory() as td:
            p = result.write_to(Path(td) / "ablation.json")
            self.assertTrue(p.exists())
            import json
            d = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(d["config"]["name"], "exp")
            self.assertIn("baseline_report", d)
            self.assertIn("no_d", d["ablation_reports"])
            self.assertIn("summary_rows", d)


if __name__ == "__main__":
    unittest.main()
