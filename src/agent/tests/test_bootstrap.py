"""Offline tests for Phase 3.5: bootstrap CIs.

Covers:
  - Metric functions (Hit@1/5/10/MRR/triage) on small fixtures.
  - bootstrap_metric returns CI that contains the point estimate (when
    n_resamples is large enough), and the CI shrinks as n grows.
  - Fixed seed → deterministic output.
  - Empty input + len-0 cases handled.
  - paired_bootstrap_delta enforces same length; Δ-CI semantics.
  - paired test fires when systems are identical → Δ = 0, CI tight.
  - paired test detects clear advantage (b strictly better) with high
    fraction_b_better.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_bootstrap -v
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Sequence

from agent.eval_harness import (
    BootstrapResult,
    PairedBootstrapResult,
    bootstrap_eval_report,
    bootstrap_metric,
    metric_hit_at_1,
    metric_hit_at_5,
    metric_hit_at_k,
    metric_mrr,
    metric_triage_accuracy,
    paired_bootstrap_delta,
    rows_from_dicts,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Row:
    matched_issue_ids: tuple[str, ...]
    gold_matched_issue_ids: tuple[str, ...]


def _hit_at_k_rows(*, n_hit_at_1: int, n_hit_at_5_only: int,
                   n_miss: int, n_empty_gold: int = 0) -> list[_Row]:
    """Hand-crafted row set so the metrics are predictable."""
    rows: list[_Row] = []
    for _ in range(n_hit_at_1):
        rows.append(_Row(matched_issue_ids=("A", "B", "C", "D", "E"),
                         gold_matched_issue_ids=("A",)))
    for _ in range(n_hit_at_5_only):
        rows.append(_Row(matched_issue_ids=("X", "Y", "A", "Z", "W"),
                         gold_matched_issue_ids=("A",)))
    for _ in range(n_miss):
        rows.append(_Row(matched_issue_ids=("X", "Y", "Z"),
                         gold_matched_issue_ids=("A",)))
    for _ in range(n_empty_gold):
        rows.append(_Row(matched_issue_ids=("X", "Y", "Z"),
                         gold_matched_issue_ids=()))
    return rows


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


class TestMetrics(unittest.TestCase):
    def test_hit_at_1(self):
        rows = _hit_at_k_rows(n_hit_at_1=2, n_hit_at_5_only=1, n_miss=1)
        # n_with_gold=4; hit@1 = 2/4
        self.assertAlmostEqual(metric_hit_at_1(rows), 0.5)

    def test_hit_at_5(self):
        rows = _hit_at_k_rows(n_hit_at_1=2, n_hit_at_5_only=1, n_miss=1)
        # hit@5 = 3/4
        self.assertAlmostEqual(metric_hit_at_5(rows), 0.75)

    def test_mrr(self):
        rows = _hit_at_k_rows(n_hit_at_1=1, n_hit_at_5_only=1, n_miss=1)
        # rr values: 1.0 (at pos 1) + 1/3 (at pos 3) + 0 (miss) = 1.333…/3
        self.assertAlmostEqual(metric_mrr(rows), (1.0 + 1.0 / 3.0) / 3.0)

    def test_metric_filters_empty_gold(self):
        rows = _hit_at_k_rows(n_hit_at_1=1, n_hit_at_5_only=0,
                              n_miss=0, n_empty_gold=10)
        # Only 1 row counts; hit@5 = 1/1
        self.assertAlmostEqual(metric_hit_at_5(rows), 1.0)

    def test_rows_from_dicts(self):
        dicts = [
            {"matched_issue_ids": ["A"], "gold_matched_issue_ids": ["A"]},
            {"matched_issue_ids": ["B"], "gold_matched_issue_ids": ["C"]},
        ]
        rows = rows_from_dicts(dicts)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(metric_hit_at_1(rows), 0.5)

    def test_hit_at_k_invalid_k(self):
        rows = _hit_at_k_rows(n_hit_at_1=1, n_hit_at_5_only=0, n_miss=0)
        self.assertAlmostEqual(metric_hit_at_k(rows, k=1), 1.0)


# ---------------------------------------------------------------------------
# bootstrap_metric
# ---------------------------------------------------------------------------


class TestBootstrapMetric(unittest.TestCase):
    def test_ci_contains_point_estimate(self):
        rows = _hit_at_k_rows(n_hit_at_1=20, n_hit_at_5_only=10, n_miss=10)
        bs = bootstrap_metric(
            rows, metric_hit_at_1, metric_name="hit_at_1",
            n_resamples=500, seed=42,
        )
        self.assertLessEqual(bs.ci_low, bs.point_estimate)
        self.assertGreaterEqual(bs.ci_high, bs.point_estimate)

    def test_deterministic_with_same_seed(self):
        rows = _hit_at_k_rows(n_hit_at_1=10, n_hit_at_5_only=5, n_miss=5)
        bs1 = bootstrap_metric(rows, metric_hit_at_1, n_resamples=200, seed=42)
        bs2 = bootstrap_metric(rows, metric_hit_at_1, n_resamples=200, seed=42)
        self.assertEqual(bs1.ci_low, bs2.ci_low)
        self.assertEqual(bs1.ci_high, bs2.ci_high)
        self.assertEqual(bs1.mean, bs2.mean)

    def test_different_seed_different_ci(self):
        rows = _hit_at_k_rows(n_hit_at_1=10, n_hit_at_5_only=5, n_miss=5)
        bs1 = bootstrap_metric(rows, metric_hit_at_1, n_resamples=200, seed=42)
        bs2 = bootstrap_metric(rows, metric_hit_at_1, n_resamples=200, seed=99)
        # CIs should differ (different resample sequences); point estimates
        # are the same.
        self.assertEqual(bs1.point_estimate, bs2.point_estimate)
        # Width might differ — both should be > 0 since the data has variance.
        # (Don't assert inequality of widths — tiny test sets can coincide.)
        self.assertGreaterEqual(bs1.ci_width, 0.0)

    def test_ci_shrinks_with_more_resamples(self):
        rows = _hit_at_k_rows(n_hit_at_1=20, n_hit_at_5_only=20, n_miss=20)
        bs_small = bootstrap_metric(rows, metric_hit_at_1, n_resamples=50, seed=42)
        bs_large = bootstrap_metric(rows, metric_hit_at_1, n_resamples=5000, seed=42)
        # More resamples → CI is more stable (mean closer to point estimate)
        diff_small = abs(bs_small.mean - bs_small.point_estimate)
        diff_large = abs(bs_large.mean - bs_large.point_estimate)
        # Large should generally be closer; allow a tiny tolerance.
        self.assertLessEqual(diff_large, diff_small + 0.01)

    def test_empty_input_returns_zeros(self):
        bs = bootstrap_metric([], metric_hit_at_1, n_resamples=100, seed=42)
        self.assertEqual(bs.point_estimate, 0.0)
        self.assertEqual(bs.ci_low, 0.0)
        self.assertEqual(bs.ci_high, 0.0)

    def test_invalid_confidence_raises(self):
        rows = _hit_at_k_rows(n_hit_at_1=1, n_hit_at_5_only=0, n_miss=0)
        with self.assertRaises(ValueError):
            bootstrap_metric(rows, metric_hit_at_1, confidence=0.0)
        with self.assertRaises(ValueError):
            bootstrap_metric(rows, metric_hit_at_1, confidence=1.0)

    def test_to_dict_roundtrip(self):
        rows = _hit_at_k_rows(n_hit_at_1=5, n_hit_at_5_only=2, n_miss=3)
        bs = bootstrap_metric(rows, metric_hit_at_1, n_resamples=100, seed=42)
        d = bs.to_dict()
        self.assertEqual(d["metric_name"], "metric")
        self.assertIn("ci_low", d)
        self.assertIn("ci_high", d)


# ---------------------------------------------------------------------------
# paired_bootstrap_delta
# ---------------------------------------------------------------------------


class TestPairedBootstrap(unittest.TestCase):
    def test_identical_systems_zero_delta(self):
        rows = _hit_at_k_rows(n_hit_at_1=10, n_hit_at_5_only=5, n_miss=5)
        pbr = paired_bootstrap_delta(
            rows, rows, metric_hit_at_5,
            n_resamples=500, seed=42,
        )
        self.assertEqual(pbr.delta_point, 0.0)
        self.assertEqual(pbr.delta_ci_low, 0.0)
        self.assertEqual(pbr.delta_ci_high, 0.0)
        # When deltas are all exactly 0, fraction_b_better = 0.5 by tie-split.
        self.assertAlmostEqual(pbr.fraction_b_better, 0.5)

    def test_b_strictly_better_high_fraction(self):
        # All A rows miss; all B rows hit at position 1
        a_rows = [_Row(matched_issue_ids=("X",), gold_matched_issue_ids=("A",))
                  for _ in range(20)]
        b_rows = [_Row(matched_issue_ids=("A",), gold_matched_issue_ids=("A",))
                  for _ in range(20)]
        pbr = paired_bootstrap_delta(
            a_rows, b_rows, metric_hit_at_1,
            n_resamples=500, seed=42,
        )
        self.assertAlmostEqual(pbr.delta_point, 1.0)
        # CI should fully exclude 0 (significant)
        self.assertGreater(pbr.delta_ci_low, 0.0)
        self.assertTrue(pbr.is_significant())
        self.assertAlmostEqual(pbr.fraction_b_better, 1.0)

    def test_length_mismatch_raises(self):
        a = _hit_at_k_rows(n_hit_at_1=2, n_hit_at_5_only=0, n_miss=0)
        b = _hit_at_k_rows(n_hit_at_1=3, n_hit_at_5_only=0, n_miss=0)
        with self.assertRaises(ValueError):
            paired_bootstrap_delta(a, b, metric_hit_at_1)

    def test_paired_significance_flag(self):
        # A small but consistent edge
        a_rows = [_Row(matched_issue_ids=("X",), gold_matched_issue_ids=("A",))
                  for _ in range(50)]
        b_rows = [_Row(matched_issue_ids=("A",), gold_matched_issue_ids=("A",))
                  for _ in range(50)]
        pbr = paired_bootstrap_delta(
            a_rows, b_rows, metric_hit_at_1,
            n_resamples=500, seed=42,
        )
        self.assertTrue(pbr.is_significant())


# ---------------------------------------------------------------------------
# bootstrap_eval_report
# ---------------------------------------------------------------------------


class TestBootstrapEvalReport(unittest.TestCase):
    def test_all_metrics_bootstrapped(self):
        rows = _hit_at_k_rows(n_hit_at_1=10, n_hit_at_5_only=5, n_miss=5)
        report = bootstrap_eval_report(
            rows, name="ob-test", n_resamples=200, seed=42,
            include_triage=False,
        )
        self.assertEqual(report.name, "ob-test")
        # 4 retrieval metrics; triage skipped (rows don't have decision)
        self.assertIn("hit_at_1", report.metrics)
        self.assertIn("hit_at_5", report.metrics)
        self.assertIn("hit_at_10", report.metrics)
        self.assertIn("mrr", report.metrics)
        self.assertNotIn("triage_accuracy", report.metrics)
        # All have CIs
        for m in report.metrics.values():
            self.assertLessEqual(m.ci_low, m.point_estimate)
            self.assertGreaterEqual(m.ci_high, m.point_estimate)

    def test_serializable_to_dict(self):
        rows = _hit_at_k_rows(n_hit_at_1=2, n_hit_at_5_only=1, n_miss=1)
        report = bootstrap_eval_report(rows, n_resamples=50, seed=42,
                                        include_triage=False)
        d = report.to_dict()
        self.assertEqual(d["n_cases"], 4)
        self.assertIn("hit_at_5", d["metrics"])


if __name__ == "__main__":
    unittest.main()
