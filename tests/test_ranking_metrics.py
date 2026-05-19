import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "research-lab"
sys.path.insert(0, str(SCRIPT_ROOT))

from build_cross_run_evaluation import f1_for_single_positive, metrics_from_ranks  # noqa: E402


class RankingMetricTests(unittest.TestCase):
    def test_f1_at_1_single_positive(self):
        self.assertEqual(f1_for_single_positive(1, 1), 1.0)
        self.assertEqual(f1_for_single_positive(2, 1), 0.0)
        self.assertEqual(f1_for_single_positive(3, 1), 0.0)
        self.assertEqual(f1_for_single_positive(4, 1), 0.0)
        self.assertEqual(f1_for_single_positive(None, 1), 0.0)

    def test_f1_at_3_single_positive(self):
        expected_hit_f1 = 0.5
        self.assertAlmostEqual(f1_for_single_positive(1, 3), expected_hit_f1)
        self.assertAlmostEqual(f1_for_single_positive(2, 3), expected_hit_f1)
        self.assertAlmostEqual(f1_for_single_positive(3, 3), expected_hit_f1)
        self.assertEqual(f1_for_single_positive(4, 3), 0.0)
        self.assertEqual(f1_for_single_positive(None, 3), 0.0)

    def test_metric_averages_include_f1(self):
        metrics = metrics_from_ranks(
            ranks_by_query={
                "rank-1": 1,
                "rank-2": 2,
                "rank-3": 3,
                "rank-4": 4,
                "missing": None,
            },
            example_count=25,
            positive_example_count=5,
        )
        self.assertEqual(metrics["recall_at_1"], 0.2)
        self.assertEqual(metrics["recall_at_3"], 0.6)
        self.assertEqual(metrics["f1_at_1"], 0.2)
        self.assertEqual(metrics["f1_at_3"], 0.3)


if __name__ == "__main__":
    unittest.main()
