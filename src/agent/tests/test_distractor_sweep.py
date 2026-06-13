"""Offline tests for Phase 3.4: similarity-weighted distractor sweep.

Covers:
  - _compute_metrics matches the cascade's Hit@K / MRR conventions.
  - inject_uniform produces the same shape + zero-distractor case.
  - compute_window_weights: mean ≈ 1.0; cap honored; zero-mean fallback.
  - inject_similarity_weighted respects per-window probabilities.
  - run_uniform_sweep at 0% returns the original Hit@K.
  - run_similarity_weighted_sweep returns 0% baseline identical to uniform.
  - TF-IDF helper handles empty distractor list (returns zeros).
  - Loaders skip malformed lines.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_distractor_sweep -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.eval_harness import (
    compute_max_similarity_per_window,
    compute_window_weights,
    inject_similarity_weighted,
    inject_uniform,
    load_distractor_texts,
    load_window_texts_for_cascade,
    run_similarity_weighted_sweep,
    run_uniform_sweep,
)
from agent.eval_harness.distractor_sweep import _compute_metrics


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _pred(window_id: str, *, matched=("A", "B", "C", "D", "E"),
          gold=("A",)) -> dict:
    return {
        "window_id": window_id,
        "matched_issue_ids": list(matched),
        "gold_matched_issue_ids": list(gold),
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics(unittest.TestCase):
    def test_hit_at_1_5_mrr(self):
        preds = [
            _pred("w1", matched=("A", "B", "C"), gold=("A",)),     # H@1 = 1
            _pred("w2", matched=("X", "Y", "A"), gold=("A",)),     # rr=1/3
            _pred("w3", matched=("X", "Y"), gold=("A",)),          # no hit
        ]
        m = _compute_metrics(preds)
        self.assertEqual(m["n_with_gold"], 3)
        self.assertAlmostEqual(m["hit_at_1"], 1.0 / 3.0)
        self.assertAlmostEqual(m["hit_at_5"], 2.0 / 3.0)
        # 1.0 + 1/3 + 0 = 1.333… / 3 = 0.444
        self.assertAlmostEqual(m["mrr"], (1.0 + 1.0 / 3.0) / 3.0)

    def test_excludes_empty_gold(self):
        preds = [
            _pred("w1", matched=("A",), gold=()),                  # excluded
            _pred("w2", matched=("A",), gold=("A",)),
        ]
        m = _compute_metrics(preds)
        self.assertEqual(m["n_with_gold"], 1)
        self.assertAlmostEqual(m["hit_at_1"], 1.0)


# ---------------------------------------------------------------------------
# Uniform injection
# ---------------------------------------------------------------------------


class TestInjectUniform(unittest.TestCase):
    def test_zero_distractors_returns_copy(self):
        cascade = [_pred("w1"), _pred("w2")]
        out = inject_uniform(cascade, 0, 100, seed=42)
        # Distinct list but equivalent rows
        self.assertIsNot(out, cascade)
        self.assertEqual(out, [dict(p) for p in cascade])

    def test_high_ratio_displaces_many_slots(self):
        # 1000 distractors, 100 memory → p ~= 0.91 per slot
        cascade = [_pred(f"w{i}") for i in range(50)]
        out = inject_uniform(cascade, 1000, 100, seed=42)
        n_distracted = sum(
            1 for p in out for m in p["matched_issue_ids"]
            if m.startswith("DISTRACTOR-")
        )
        n_total = sum(len(p["matched_issue_ids"]) for p in out)
        # 50 windows × 5 slots = 250 total
        self.assertEqual(n_total, 250)
        # Expected ~91% displacement; allow generous bound
        self.assertGreater(n_distracted, 200)


# ---------------------------------------------------------------------------
# Window weights
# ---------------------------------------------------------------------------


class TestComputeWindowWeights(unittest.TestCase):
    def test_mean_normalized_to_1(self):
        sims = [0.1, 0.2, 0.3, 0.4]
        w = compute_window_weights(sims)
        mean = sum(w) / len(w)
        self.assertAlmostEqual(mean, 1.0, places=5)

    def test_zero_mean_falls_back_to_uniform(self):
        w = compute_window_weights([0.0, 0.0, 0.0])
        self.assertEqual(w, [1.0, 1.0, 1.0])

    def test_cap_honored(self):
        # One outlier window 10× the rest
        sims = [0.1, 0.1, 0.1, 1.0]
        w = compute_window_weights(sims, weight_cap=3.0)
        self.assertLessEqual(max(w), 3.0)

    def test_empty(self):
        self.assertEqual(compute_window_weights([]), [])


# ---------------------------------------------------------------------------
# Similarity-weighted injection
# ---------------------------------------------------------------------------


class TestInjectSimilarityWeighted(unittest.TestCase):
    def test_zero_distractors_no_op(self):
        cascade = [_pred("w1"), _pred("w2")]
        out, mean_p = inject_similarity_weighted(
            cascade, 0, 100,
            window_weights=[1.0, 1.0], seed=42,
        )
        self.assertEqual(mean_p, 0.0)
        self.assertEqual(out, [dict(p) for p in cascade])

    def test_weight_mismatch_raises(self):
        cascade = [_pred("w1"), _pred("w2")]
        with self.assertRaises(ValueError):
            inject_similarity_weighted(
                cascade, 10, 100,
                window_weights=[1.0],          # too short
                seed=42,
            )

    def test_realized_mean_p_close_to_baseline(self):
        # When weights are all 1.0, mean_p should equal p_baseline.
        cascade = [_pred(f"w{i}") for i in range(20)]
        n_d = 50
        n_m = 100
        _, mean_p = inject_similarity_weighted(
            cascade, n_d, n_m,
            window_weights=[1.0] * 20, seed=42,
        )
        self.assertAlmostEqual(mean_p, n_d / (n_d + n_m))

    def test_heavier_weights_get_more_displacement(self):
        """Window with weight 3.0 should see ~3× more displacement than
        window with weight 0.5."""
        n_windows = 30
        cascade = [_pred(f"w{i}") for i in range(n_windows)]
        # Half the windows weight 3.0, half weight 0.0
        weights = [3.0] * (n_windows // 2) + [0.0] * (n_windows - n_windows // 2)
        out, _ = inject_similarity_weighted(
            cascade, 100, 100,
            window_weights=weights, seed=42,
        )
        # Count distractor slots in the first half (heavy) vs second half (zero)
        n_heavy = sum(
            1 for p in out[:n_windows // 2]
            for m in p["matched_issue_ids"]
            if m.startswith("DISTRACTOR-")
        )
        n_zero = sum(
            1 for p in out[n_windows // 2:]
            for m in p["matched_issue_ids"]
            if m.startswith("DISTRACTOR-")
        )
        # Heavy windows have many distractors; zero-weight windows have none
        self.assertGreater(n_heavy, 0)
        self.assertEqual(n_zero, 0)


# ---------------------------------------------------------------------------
# Sweep drivers
# ---------------------------------------------------------------------------


class TestSweepDrivers(unittest.TestCase):
    def setUp(self):
        # 10 windows, each top-5 hit at position 1
        self.cascade = [_pred(f"w{i}") for i in range(10)]

    def test_uniform_zero_ratio_preserves_hit_at_1(self):
        report = run_uniform_sweep(
            self.cascade,
            distractor_pool_size=100, memory_size=100,
            ratios_pct=(0,),
        )
        self.assertEqual(report.method, "uniform")
        self.assertAlmostEqual(report.ratios[0].hit_at_1, 1.0)

    def test_weighted_zero_ratio_preserves_hit_at_1(self):
        weights = [1.0] * 10
        report = run_similarity_weighted_sweep(
            self.cascade, window_weights=weights,
            distractor_pool_size=100, memory_size=100,
            ratios_pct=(0,),
        )
        self.assertEqual(report.method, "similarity_weighted")
        self.assertAlmostEqual(report.ratios[0].hit_at_1, 1.0)

    def test_uniform_high_ratio_drops_hit_at_1(self):
        report = run_uniform_sweep(
            self.cascade,
            distractor_pool_size=1000, memory_size=100,
            ratios_pct=(50,),
        )
        # With p ≈ 0.83 the top-1 slot is replaced often → Hit@1 way down
        self.assertLess(report.ratios[0].hit_at_1, 0.4)

    def test_sweep_serialization_roundtrip(self):
        report = run_uniform_sweep(
            self.cascade,
            distractor_pool_size=100, memory_size=100,
            ratios_pct=(0, 50),
        )
        d = report.to_dict()
        self.assertEqual(d["method"], "uniform")
        self.assertEqual(len(d["ratios"]), 2)
        self.assertEqual(d["ratios"][0]["ratio_pct"], 0)


# ---------------------------------------------------------------------------
# TF-IDF similarity helper
# ---------------------------------------------------------------------------


class TestTfIdfSimilarity(unittest.TestCase):
    def test_empty_distractors_returns_zeros(self):
        sims, summary = compute_max_similarity_per_window(
            ["window text"], [],
        )
        self.assertEqual(sims, [0.0])
        self.assertEqual(summary["n_distractors"], 0)

    def test_empty_windows(self):
        sims, summary = compute_max_similarity_per_window([], ["d"])
        self.assertEqual(sims, [])
        self.assertEqual(summary["n_windows"], 0)

    def test_sim_higher_when_overlap_exists(self):
        # Window vocab overlaps distractor 1 but not distractor 2.
        sims, summary = compute_max_similarity_per_window(
            ["cart redis timeout connection failed"],
            ["cart redis connection error",                   # high overlap
             "the quick brown fox jumps"],                    # zero overlap
        )
        # Top-1 sim should be > 0; max should be on the overlapping distractor
        self.assertGreater(sims[0], 0.0)
        self.assertGreater(summary["sim_max_max"], 0.2)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


class TestLoaders(unittest.TestCase):
    def test_load_window_texts_for_cascade(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "examples.jsonl"
            _write_jsonl(p, [
                {"window_id": "w1", "triage_evidence_text": "cart error"},
                {"window_id": "w2", "triage_evidence_text": "redis timeout"},
            ])
            cascade = [_pred("w1"), _pred("w2"), _pred("w3")]
            texts = load_window_texts_for_cascade(cascade, p)
        self.assertEqual(texts, ["cart error", "redis timeout", ""])

    def test_load_distractor_texts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "distractors.jsonl"
            _write_jsonl(p, [
                {"description_code": "qt crash",
                 "timeline": [{"body_code": "stacktrace here"}]},
                {"description_code": "minecraft crash"},
                {},                                            # no text → skipped
            ])
            texts = load_distractor_texts(p)
        self.assertEqual(len(texts), 2)
        self.assertIn("qt crash", texts[0])
        self.assertIn("stacktrace here", texts[0])
        self.assertEqual(texts[1], "minecraft crash")

    def test_distractor_loader_limit(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "distractors.jsonl"
            _write_jsonl(p, [
                {"description_code": f"d{i}"} for i in range(5)
            ])
            texts = load_distractor_texts(p, limit=3)
        self.assertEqual(len(texts), 3)


if __name__ == "__main__":
    unittest.main()
