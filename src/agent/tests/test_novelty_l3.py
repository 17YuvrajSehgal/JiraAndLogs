"""Offline tests for Phase 3.3: L3 novelty evaluator.

Covers:
  - NoveltyQuery.from_row builds from wol_project / scenario_family.
  - load_free_signal prefers precomputed is_novel_at_T when present;
    falls back to max_sim < threshold.
  - load_agent_signal / load_learned_signal handle missing files.
  - evaluate_l3_novelty disjunction logic:
      - free signal alone matches free_flagged column
      - adding agent strictly increases or maintains flag count
      - precision = 1.0 on pure-OOD set regardless of which signals fire
      - recall = 1.0 when free alone catches every query
      - per-project breakdown sums to overall counts
  - Empty inputs are handled.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_novelty_l3 -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.eval_harness import (
    DEFAULT_FREE_THRESHOLD,
    NoveltyQuery,
    NoveltyReport,
    evaluate_l3_novelty,
    load_agent_signal,
    load_free_signal,
    load_learned_signal,
    load_wol_ood_queries,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# NoveltyQuery + loaders
# ---------------------------------------------------------------------------


class TestNoveltyQuery(unittest.TestCase):
    def test_from_row_with_wol_project(self):
        q = NoveltyQuery.from_row({
            "window_id": "w1", "is_novel": True,
            "wol_project": "Spark", "scenario_family": "spark-oom",
        })
        self.assertEqual(q.window_id, "w1")
        self.assertTrue(q.gold_is_novel)
        self.assertEqual(q.project, "Spark")
        self.assertEqual(q.family, "spark-oom")

    def test_from_row_defaults(self):
        q = NoveltyQuery.from_row({"window_id": "w1"})
        self.assertFalse(q.gold_is_novel)
        self.assertEqual(q.project, "")
        self.assertEqual(q.family, "")


class TestLoaders(unittest.TestCase):
    def test_load_wol_ood_queries(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "windows.jsonl"
            _write_jsonl(p, [
                {"window_id": "w1", "is_novel": True, "wol_project": "Spark"},
                {"window_id": "w2", "is_novel": True, "wol_project": "Flink"},
            ])
            qs = load_wol_ood_queries(p)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0].project, "Spark")

    def test_load_free_signal_uses_precomputed_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "free.jsonl"
            _write_jsonl(p, [
                {"window_id": "w1", "max_sim": 0.3, "is_novel_at_0.5": True},
                {"window_id": "w2", "max_sim": 0.9, "is_novel_at_0.5": False},
            ])
            sig = load_free_signal(p, threshold=0.5)
        self.assertTrue(sig["w1"])
        self.assertFalse(sig["w2"])

    def test_load_free_signal_falls_back_to_max_sim(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "free.jsonl"
            # Threshold is 0.7 but only is_novel_at_0.5 is precomputed;
            # we re-evaluate against max_sim.
            _write_jsonl(p, [
                {"window_id": "w1", "max_sim": 0.6},
                {"window_id": "w2", "max_sim": 0.8},
            ])
            sig = load_free_signal(p, threshold=0.7)
        self.assertTrue(sig["w1"])               # 0.6 < 0.7 → novel
        self.assertFalse(sig["w2"])              # 0.8 >= 0.7 → not novel

    def test_load_agent_signal_missing_file(self):
        self.assertEqual(load_agent_signal("/nonexistent.jsonl"), {})

    def test_load_learned_signal_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.jsonl"
            _write_jsonl(p, [
                {"window_id": "w1", "learned_novelty_prob": 0.7},
                {"window_id": "w2", "learned_novelty_prob": 0.3},
            ])
            sig = load_learned_signal(p, threshold=0.5)
        self.assertTrue(sig["w1"])
        self.assertFalse(sig["w2"])


# ---------------------------------------------------------------------------
# Evaluator core
# ---------------------------------------------------------------------------


def _ood_queries(n_per_proj: int = 5) -> list[NoveltyQuery]:
    """Build a synthetic pure-OOD set (all gold_novel=True)."""
    out = []
    for proj in ("Spark", "Flink"):
        for i in range(n_per_proj):
            out.append(NoveltyQuery(
                window_id=f"{proj}-{i}",
                gold_is_novel=True,
                project=proj,
            ))
    return out


class TestEvaluatorPureOOD(unittest.TestCase):
    """All queries are gold_novel — precision should always be 1.0
    regardless of which signal fires (every flag is a TP)."""

    def test_free_signal_alone_catches_all(self):
        queries = _ood_queries(5)
        free_signal = {q.window_id: True for q in queries}
        report = evaluate_l3_novelty(
            queries=queries, free_signal=free_signal,
        )
        self.assertEqual(report.n_queries, 10)
        self.assertEqual(report.n_gold_novel, 10)
        self.assertEqual(report.free_flagged, 10)
        self.assertEqual(report.flagged_full_l3, 10)
        self.assertAlmostEqual(report.novel_precision, 1.0)
        self.assertAlmostEqual(report.novel_recall, 1.0)
        self.assertEqual(report.n_false_positive_l3, 0)

    def test_partial_free_then_agent_fills_in(self):
        queries = _ood_queries(5)
        # Free signal catches half; agent signal catches the rest
        free_signal = {q.window_id: i % 2 == 0
                       for i, q in enumerate(queries)}
        agent_signal = {q.window_id: i % 2 == 1
                        for i, q in enumerate(queries)}

        report = evaluate_l3_novelty(
            queries=queries,
            free_signal=free_signal, agent_signal=agent_signal,
        )
        self.assertEqual(report.free_flagged, 5)
        self.assertEqual(report.agent_flagged, 5)
        # Cumulative free → free+agent → full L3
        self.assertEqual(report.flagged_free_only, 5)
        self.assertEqual(report.flagged_free_or_agent, 10)
        self.assertEqual(report.flagged_full_l3, 10)
        # All flags are TP on the pure-OOD set
        self.assertAlmostEqual(report.novel_precision, 1.0)
        self.assertAlmostEqual(report.novel_recall, 1.0)


class TestEvaluatorMixedGold(unittest.TestCase):
    """Some queries are gold_novel, others aren't — precision +
    recall become non-trivial."""

    def test_mixed_set_precision_recall(self):
        queries = [
            NoveltyQuery(window_id="n1", gold_is_novel=True, project="A"),
            NoveltyQuery(window_id="n2", gold_is_novel=True, project="A"),
            NoveltyQuery(window_id="p1", gold_is_novel=False, project="A"),
            NoveltyQuery(window_id="p2", gold_is_novel=False, project="A"),
        ]
        # Free signal flags n1 (TP) + p1 (FP); misses n2 (FN); p2 not flagged (TN)
        free_signal = {"n1": True, "n2": False, "p1": True, "p2": False}
        report = evaluate_l3_novelty(
            queries=queries, free_signal=free_signal,
        )
        # Flagged: n1, p1 → 2 (1 TP, 1 FP)
        self.assertEqual(report.flagged_full_l3, 2)
        self.assertEqual(report.n_true_positive_l3, 1)
        self.assertEqual(report.n_false_positive_l3, 1)
        # precision = 1 / 2 = 0.5
        self.assertAlmostEqual(report.novel_precision, 0.5)
        # recall = 1 / 2 = 0.5
        self.assertAlmostEqual(report.novel_recall, 0.5)


class TestPerProjectBreakdown(unittest.TestCase):
    def test_per_project_sums_match_overall(self):
        queries = _ood_queries(3)         # 6 total, 3 per project
        free_signal = {q.window_id: True for q in queries}
        report = evaluate_l3_novelty(
            queries=queries, free_signal=free_signal,
        )
        # Two projects
        self.assertEqual(set(report.per_project), {"Spark", "Flink"})
        for proj in ("Spark", "Flink"):
            b = report.per_project[proj]
            self.assertEqual(b["n_queries"], 3)
            self.assertEqual(b["n_gold_novel"], 3)
            self.assertEqual(b["flagged_full_l3"], 3)
            self.assertEqual(b["precision"], 1.0)
            self.assertEqual(b["recall"], 1.0)
        # Per-project sums match overall
        total_n = sum(b["n_queries"] for b in report.per_project.values())
        self.assertEqual(total_n, report.n_queries)


class TestEvaluatorEmpty(unittest.TestCase):
    def test_no_queries(self):
        report = evaluate_l3_novelty(queries=[], free_signal={})
        self.assertEqual(report.n_queries, 0)
        self.assertAlmostEqual(report.novel_precision, 0.0)
        self.assertAlmostEqual(report.novel_recall, 0.0)


class TestSignalsPresenceFlags(unittest.TestCase):
    def test_no_optional_signals(self):
        queries = _ood_queries(2)
        free = {q.window_id: True for q in queries}
        report = evaluate_l3_novelty(queries=queries, free_signal=free)
        self.assertFalse(report.agent_signal_present)
        self.assertFalse(report.learned_signal_present)

    def test_with_agent_signal(self):
        queries = _ood_queries(2)
        free = {q.window_id: True for q in queries}
        agent = {queries[0].window_id: True}
        report = evaluate_l3_novelty(
            queries=queries, free_signal=free, agent_signal=agent,
        )
        self.assertTrue(report.agent_signal_present)


if __name__ == "__main__":
    unittest.main()
