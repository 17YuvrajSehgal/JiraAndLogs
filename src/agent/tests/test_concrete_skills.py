"""Offline tests for Phase 1.7 concrete skill wrappers.

Predictions-backed skills (6):
    - Load a stub per-window-predictions.jsonl
    - Filter by pipeline_name correctly
    - Return SkillOutput on hit; empty output on miss
    - Survive missing files via PredictionsNotFoundError
    - Honor the required_flags gate (can_invoke)

Composition skills (3):
    - compose_l2: BiEncoder-anchored overlap rerank + RRF (positions 2-5)
    - compose_triage: stacker (with fitted coefs) + fallback-max mode
    - compose_novelty: three-signal disjunction (each signal independently)

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_concrete_skills -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent import (
    AgentDecision,
    Capabilities,
    InputBundle,
    KG_GRAPH_MEMORY,
    MEMORY_TEXT,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    SkillOutput,
    TEXT_EVIDENCE,
    Trace,
    TraceEvent,
    UNORDERED_LOGS,
    VERIFIER_KNOWN_HELPFUL,
)
from agent.skills import (
    AgentContext,
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
    MemoryView,
    PredictionsNotFoundError,
    RetrieveDenseSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    TriageNumericSkill,
    VerifyWithLLMSkill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_pred(window_id: str, pipeline_name: str, **kwargs) -> dict:
    """Build a stub prediction record matching the cascade JSONL shape."""
    return {
        "window_id": window_id,
        "pipeline_name": pipeline_name,
        "triage_score": kwargs.get("triage_score", 0.5),
        "triage_decision": kwargs.get("triage_decision", "ticket_worthy"),
        "matched_issue_ids": kwargs.get("matched_issue_ids", []),
        "is_novel": kwargs.get("is_novel", False),
        "gold_label": kwargs.get("gold_label", "ticket_worthy"),
        "gold_matched_issue_ids": kwargs.get("gold_matched_issue_ids", []),
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_bundle(window_id: str = "w1") -> InputBundle:
    return InputBundle(
        window_id=window_id, dataset="ob",
        text_evidence="evidence text long enough",
        numeric_features={"f1": 0.1},
    )


def _empty_memory() -> MemoryView:
    return MemoryView([])


def _ctx_with_trace(trace: Trace) -> AgentContext:
    return AgentContext(bundle_id=trace.bundle_id, extra={"trace": trace})


# ---------------------------------------------------------------------------
# PredictionsBackedSkill — base behaviour
# ---------------------------------------------------------------------------


class TestPredictionsBackedSkill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_raises_PredictionsNotFoundError(self):
        skill = TriageNumericSkill(predictions_path=self.tmp_path / "nope.jsonl")
        with self.assertRaises(PredictionsNotFoundError):
            skill.invoke(_make_bundle(), _empty_memory(),
                         AgentContext(bundle_id="w1"))

    def test_existing_prediction_returns_skill_output(self):
        path = self.tmp_path / "preds.jsonl"
        _write_jsonl(path, [
            _stub_pred("w1", "hist_gradient_boosting_numeric",
                       triage_score=0.95, triage_decision="ticket_worthy",
                       matched_issue_ids=[]),
        ])
        skill = TriageNumericSkill(predictions_path=path)
        out = skill.invoke(_make_bundle("w1"), _empty_memory(),
                           AgentContext(bundle_id="w1"))
        self.assertEqual(out.skill, "triage_numeric")
        self.assertEqual(out.triage_score, 0.95)
        self.assertEqual(out.triage_decision, "ticket_worthy")

    def test_filter_by_pipeline_name(self):
        path = self.tmp_path / "mixed.jsonl"
        _write_jsonl(path, [
            _stub_pred("w1", "other_pipeline", triage_score=0.99),
            _stub_pred("w1", "hist_gradient_boosting_numeric", triage_score=0.42),
        ])
        skill = TriageNumericSkill(predictions_path=path)
        out = skill.invoke(_make_bundle("w1"), _empty_memory(),
                           AgentContext(bundle_id="w1"))
        # We want the HGB row (0.42), not the noise row (0.99)
        self.assertEqual(out.triage_score, 0.42)

    def test_missing_window_returns_empty_output(self):
        path = self.tmp_path / "preds.jsonl"
        _write_jsonl(path, [
            _stub_pred("w1", "hist_gradient_boosting_numeric"),
        ])
        skill = TriageNumericSkill(predictions_path=path)
        out = skill.invoke(_make_bundle("w_other"), _empty_memory(),
                           AgentContext(bundle_id="w_other"))
        self.assertEqual(out.skill, "triage_numeric")
        self.assertIsNone(out.triage_score)
        self.assertEqual(out.matched_issue_ids, ())
        self.assertTrue(out.extra.get("prediction_missing"))

    def test_lazy_load(self):
        path = self.tmp_path / "preds.jsonl"
        _write_jsonl(path, [_stub_pred("w1", "hist_gradient_boosting_numeric")])
        skill = TriageNumericSkill(predictions_path=path)
        # Before any invoke, nothing loaded
        self.assertEqual(skill.n_predictions_loaded(), 0)
        skill.invoke(_make_bundle("w1"), _empty_memory(),
                     AgentContext(bundle_id="w1"))
        self.assertEqual(skill.n_predictions_loaded(), 1)

    def test_from_global_dir_factory(self):
        # Default convention: <global_dir>/comparison/<predictions_subdir>/per-window-predictions.jsonl
        global_dir = self.tmp_path / "global"
        sub = global_dir / "comparison" / "v2a-resplit"
        sub.mkdir(parents=True, exist_ok=True)
        _write_jsonl(
            sub / "per-window-predictions.jsonl",
            [_stub_pred("w1", "hist_gradient_boosting_numeric", triage_score=0.7)],
        )
        skill = TriageNumericSkill.from_global_dir(global_dir)
        out = skill.invoke(_make_bundle("w1"), _empty_memory(),
                           AgentContext(bundle_id="w1"))
        self.assertEqual(out.triage_score, 0.7)


# ---------------------------------------------------------------------------
# Per-skill identity + gating
# ---------------------------------------------------------------------------


class TestSkillGating(unittest.TestCase):
    """Each skill's required_flags + cost_class match the AGENTIC-SYSTEM.md spec."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "p.jsonl"
        _write_jsonl(self.path, [])  # empty file is valid

    def tearDown(self):
        self.tmp.cleanup()

    def test_triage_numeric_requires_numeric_features(self):
        s = TriageNumericSkill(predictions_path=self.path)
        self.assertEqual(s.cost_class, "cheap")
        self.assertTrue(s.can_invoke(Capabilities(flags=frozenset({NUMERIC_FEATURES}))))
        self.assertFalse(s.can_invoke(Capabilities(flags=frozenset({TEXT_EVIDENCE}))))

    def test_retrieve_dense_requires_text_and_memory(self):
        s = RetrieveDenseSkill(predictions_path=self.path)
        self.assertEqual(s.cost_class, "cheap")
        self.assertTrue(s.can_invoke(
            Capabilities(flags=frozenset({TEXT_EVIDENCE, MEMORY_TEXT}))))
        # Missing MEMORY_TEXT — can't run
        self.assertFalse(s.can_invoke(
            Capabilities(flags=frozenset({TEXT_EVIDENCE}))))

    def test_retrieve_log_sequence_requires_ordered_logs(self):
        s = RetrieveLogSequenceSkill(predictions_path=self.path)
        self.assertTrue(s.can_invoke(Capabilities(flags=frozenset({ORDERED_LOGS}))))
        # WoL profile has UNORDERED_LOGS only — skill is skipped
        self.assertFalse(s.can_invoke(Capabilities(flags=frozenset({UNORDERED_LOGS}))))
        # And the failure mode is documented
        self.assertEqual(len(s.failure_modes), 1)
        self.assertIn("MODE3-TCH-LITE-WoL-RESULTS.md", s.failure_modes[0].citation)

    def test_retrieve_knowledge_graph_requires_kg_memory(self):
        s = RetrieveKnowledgeGraphSkill(predictions_path=self.path)
        self.assertTrue(s.can_invoke(Capabilities(flags=frozenset({KG_GRAPH_MEMORY}))))
        self.assertFalse(s.can_invoke(Capabilities()))

    def test_verify_with_llm_requires_known_helpful_flag(self):
        """The structural closure of RQ-A8 — without VERIFIER_KNOWN_HELPFUL the
        skill can't run, regardless of other evidence."""
        s = VerifyWithLLMSkill(predictions_path=self.path)
        self.assertEqual(s.cost_class, "expensive_llm")
        # OB-like profile: verifier helpful
        self.assertTrue(s.can_invoke(Capabilities(
            flags=frozenset({VERIFIER_KNOWN_HELPFUL, TEXT_EVIDENCE}))))
        # WoL-like profile: text+memory but NO verifier flag → can't run
        self.assertFalse(s.can_invoke(Capabilities(
            flags=frozenset({TEXT_EVIDENCE, MEMORY_TEXT}))))


# ---------------------------------------------------------------------------
# ComposeL2 — overlap rerank + RRF
# ---------------------------------------------------------------------------


class TestComposeL2(unittest.TestCase):
    def _trace_with_outputs(
        self,
        bi: tuple[str, ...] = (),
        hybrid: tuple[str, ...] = (),
        logseq: tuple[str, ...] = (),
        kg: tuple[str, ...] = (),
    ) -> Trace:
        t = Trace(bundle_id="w1", plan_id="p1")
        if bi:
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill="retrieve_dense",
                output=SkillOutput(skill="retrieve_dense", matched_issue_ids=bi),
            ))
        if hybrid:
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill="retrieve_hybrid_fusion",
                output=SkillOutput(skill="retrieve_hybrid_fusion", matched_issue_ids=hybrid),
            ))
        if logseq:
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill="retrieve_log_sequence",
                output=SkillOutput(skill="retrieve_log_sequence", matched_issue_ids=logseq),
            ))
        if kg:
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill="retrieve_knowledge_graph",
                output=SkillOutput(skill="retrieve_knowledge_graph", matched_issue_ids=kg),
            ))
        return t

    def test_position_1_picked_by_overlap_rerank(self):
        # BiEncoder top-3: [A, B, C].
        # Voters: hybrid says [B, ...], logseq says [B, ...]
        # → B has 2 voters → wins over A (0 voters)
        trace = self._trace_with_outputs(
            bi=("A", "B", "C"),
            hybrid=("B", "X", "Y"),
            logseq=("B", "X", "Z"),
        )
        compose = ComposeL2Skill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(trace))
        self.assertEqual(out.matched_issue_ids[0], "B")

    def test_position_1_falls_back_to_bi_top1_on_no_overlap(self):
        # BiEncoder: [A, B, C]; voters all disjoint → no overlap → fall back to A
        trace = self._trace_with_outputs(
            bi=("A", "B", "C"),
            hybrid=("X", "Y", "Z"),
            logseq=("P", "Q", "R"),
        )
        compose = ComposeL2Skill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(trace))
        self.assertEqual(out.matched_issue_ids[0], "A")

    def test_positions_2_to_5_filled_by_rrf(self):
        # All retrievers vote for X at top-1; RRF concentrates on X.
        # But position-1 picks one (X), so positions 2-5 fill from the rest.
        trace = self._trace_with_outputs(
            bi=("X", "A", "B", "C", "D"),
            hybrid=("X", "A", "E"),
            logseq=("X", "F", "G"),
            kg=("X", "H", "I"),
        )
        compose = ComposeL2Skill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(trace))
        self.assertEqual(out.matched_issue_ids[0], "X")
        # X must not appear twice
        self.assertEqual(out.matched_issue_ids.count("X"), 1)
        # 5 total
        self.assertEqual(len(out.matched_issue_ids), 5)

    def test_no_retrievers_in_trace_degrades_gracefully(self):
        t = Trace(bundle_id="w1", plan_id="p1")          # empty trace
        compose = ComposeL2Skill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertEqual(out.matched_issue_ids, ())
        self.assertEqual(out.confidence, 0.0)


# ---------------------------------------------------------------------------
# ComposeTriage — stacker + fallback-max
# ---------------------------------------------------------------------------


class TestComposeTriage(unittest.TestCase):
    def _trace_with_triage(self, scores: dict[str, float]) -> Trace:
        t = Trace(bundle_id="w1", plan_id="p1")
        for skill, score in scores.items():
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill=skill,
                output=SkillOutput(skill=skill, triage_score=score),
            ))
        return t

    def test_fallback_max_picks_highest_triage_score(self):
        t = self._trace_with_triage({
            "triage_numeric": 0.95,
            "retrieve_dense": 0.5,
            "retrieve_log_sequence": 0.3,
        })
        compose = ComposeTriageSkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertEqual(out.triage_score, 0.95)
        self.assertEqual(out.triage_decision, "ticket_worthy")
        self.assertEqual(out.extra["mode"], "fallback_max")

    def test_fallback_max_emits_noise_below_threshold(self):
        t = self._trace_with_triage({
            "triage_numeric": 0.2,
            "retrieve_dense": 0.3,
        })
        compose = ComposeTriageSkill(threshold=0.5)
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertEqual(out.triage_decision, "noise")

    def test_stacker_mode_with_coefficients(self):
        t = self._trace_with_triage({
            "triage_numeric": 1.0,
            "retrieve_dense": 0.0,
        })
        compose = ComposeTriageSkill(
            features=("triage_numeric", "retrieve_dense"),
            coefficients={"triage_numeric": 8.0, "retrieve_dense": 0.5},
            intercept=-4.0,
            threshold=0.5,
        )
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        # z = -4 + 8*1 + 0.5*0 = 4 → sigmoid(4) ≈ 0.982
        self.assertGreater(out.triage_score, 0.95)
        self.assertEqual(out.triage_decision, "ticket_worthy")
        self.assertEqual(out.extra["mode"], "stacker")

    def test_missing_feature_treated_as_zero(self):
        # `retrieve_dense` absent → contributes 0 to the stacker
        t = self._trace_with_triage({"triage_numeric": 0.5})
        compose = ComposeTriageSkill(
            features=("triage_numeric", "retrieve_dense"),
            coefficients={"triage_numeric": 1.0, "retrieve_dense": 1.0},
        )
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        # z = 0 + 1*0.5 + 1*0 = 0.5 → sigmoid(0.5) ≈ 0.622
        self.assertAlmostEqual(out.triage_score, 0.6225, places=3)


# ---------------------------------------------------------------------------
# ComposeNovelty — three-signal disjunction
# ---------------------------------------------------------------------------


class TestComposeNovelty(unittest.TestCase):
    def _trace_with(self, *, retriever_scores=None, verifier_novel=None) -> Trace:
        t = Trace(bundle_id="w1", plan_id="p1")
        for skill, score in (retriever_scores or {}).items():
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill=skill,
                output=SkillOutput(skill=skill, triage_score=score),
            ))
        if verifier_novel is not None:
            t.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end", skill="verify_with_llm",
                output=SkillOutput(skill="verify_with_llm", is_novel=verifier_novel),
            ))
        return t

    def test_free_signal_fires_when_all_retrievers_below_threshold(self):
        t = self._trace_with(retriever_scores={
            "retrieve_dense": 0.3,
            "retrieve_hybrid_fusion": 0.4,
        })
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertTrue(out.is_novel)
        self.assertTrue(out.extra["free_signal"])
        self.assertFalse(out.extra["agent_novel"])

    def test_free_signal_does_not_fire_when_any_retriever_above(self):
        t = self._trace_with(retriever_scores={
            "retrieve_dense": 0.9,
            "retrieve_hybrid_fusion": 0.4,
        })
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertFalse(out.is_novel)
        self.assertFalse(out.extra["free_signal"])

    def test_agent_novel_alone_fires(self):
        t = self._trace_with(
            retriever_scores={"retrieve_dense": 0.95},          # not free-signal novel
            verifier_novel=True,
        )
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertTrue(out.is_novel)
        self.assertTrue(out.extra["agent_novel"])
        self.assertFalse(out.extra["free_signal"])

    def test_learned_signal_via_ctx_extra(self):
        t = self._trace_with(retriever_scores={"retrieve_dense": 0.95})
        ctx = _ctx_with_trace(t)
        ctx.extra["learned_novelty_prob"] = 0.8
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), ctx)
        self.assertTrue(out.is_novel)
        self.assertTrue(out.extra["learned_signal"])

    def test_no_signals_returns_not_novel(self):
        t = self._trace_with(retriever_scores={"retrieve_dense": 0.95},
                             verifier_novel=False)
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertFalse(out.is_novel)

    def test_no_retrievers_in_trace_no_free_signal(self):
        # An empty trace shouldn't trigger free_signal — there's no data to support it.
        t = Trace(bundle_id="w1", plan_id="p1")
        compose = ComposeNoveltySkill()
        out = compose.invoke(_make_bundle(), _empty_memory(), _ctx_with_trace(t))
        self.assertFalse(out.is_novel)


if __name__ == "__main__":
    unittest.main()
