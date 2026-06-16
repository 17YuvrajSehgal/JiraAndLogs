"""Offline tests for Phase 2.1 + 2.4 data loaders.

Covers what can be tested without real datasets:
  - OB loader, WoL loader, OTel Demo loader produce EvaluationCases
    when given a hand-crafted minimal layout.
  - Gold field translation:
      - OB: gold_matched_issue_ids from per-window-predictions.jsonl
      - WoL: gold_matched_issue_ids from biencoder-predictions.jsonl
      - OTel Demo: matched_memory_issue_ids → gold_matched_issue_ids
        (from window-memory-matchings.jsonl when comparison/ absent)
  - Capability profile is correct per dataset:
      - OB: numeric_features populated
      - WoL: numeric_features and log_lines both None (text-only)
      - OTel Demo: numeric_features populated (telemetry-rich)
  - Loaders raise clear errors when files are missing or splits empty.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_data_loaders -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.data_loaders import (
    load_ob_cases,
    load_otel_demo_cases,
    load_wol_cases,
)


# ---------------------------------------------------------------------------
# Synthetic dataset builders
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _ob_window(window_id: str, *, split: str = "test",
               triage_label: str = "ticket_worthy") -> dict:
    return {
        "window_id": window_id,
        "split": split,
        "scenario_family": "redis_oom",
        "service_name": "cartservice",
        "window_type": "active_fault",
        "triage_evidence_text": "lorem ipsum the cart service exploded",
        "triage_label": triage_label,
        "triage_feature_log_error_count": 12.0,
        "triage_feature_trace_error_rate": 0.05,
    }


def _ob_pred(window_id: str, *, pipeline_name: str = "bi_encoder_retrieval",
             gold: list[str] | None = None) -> dict:
    return {
        "window_id": window_id,
        "pipeline_name": pipeline_name,
        "matched_issue_ids": [],
        "gold_matched_issue_ids": gold or [],
        "gold_is_novel": False,
        "gold_label": "ticket_worthy" if gold else "noise",
        "triage_score": 0.5,
        "triage_decision": "ticket_worthy" if gold else "noise",
    }


def _wol_window(window_id: str, *, split: str = "test") -> dict:
    return {
        "window_id": window_id,
        "split": split,
        "scenario_family": "wol-spark",
        "service_name": "Spark Core",
        "window_type": "active_fault",
        "triage_evidence_text": "19/11/05 INFO FsHistoryProvider failed",
        "triage_label": "ticket_worthy",
        # WoL features are all zero (no telemetry)
        "triage_feature_log_error_count": 0.0,
    }


def _otel_window(window_id: str, *, split: str = "train") -> dict:
    return {
        "window_id": window_id,
        "split": split,
        "scenario_family": "otel-baseline",
        "service_name": "frontend",
        "window_type": "active_fault",
        "triage_evidence_text": "the otel frontend got slow",
        "triage_label": "ticket_worthy",
        "triage_feature_trace_count": 100.0,
    }


# ---------------------------------------------------------------------------
# OB loader
# ---------------------------------------------------------------------------


class TestOBLoader(unittest.TestCase):
    def _build_layout(self, td: Path) -> Path:
        gd = td / "ob-test-ds"
        _write_jsonl(gd / "global-triage-examples.jsonl", [
            _ob_window("w1", split="test"),
            _ob_window("w2", split="test", triage_label="noise"),
            _ob_window("w3", split="train"),
        ])
        _write_jsonl(
            gd / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl",
            [
                _ob_pred("w1", gold=["INC-1", "INC-2"]),
                _ob_pred("w2", gold=[]),
                # Also write a row for a different pipeline; should be ignored.
                _ob_pred("w1", pipeline_name="other_pipeline", gold=["BOGUS"]),
            ],
        )
        return gd

    def test_loads_test_split_with_gold(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_ob_cases(gd, split="test")
        self.assertEqual(len(cases), 2)
        # First case has gold; second doesn't
        c1, c2 = cases
        self.assertEqual(c1.bundle.window_id, "w1")
        self.assertEqual(c1.gold_matched_issue_ids, ("INC-1", "INC-2"))
        self.assertEqual(c2.gold_matched_issue_ids, ())

    def test_train_split_filters_out(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_ob_cases(gd, split="train")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].bundle.window_id, "w3")

    def test_ob_bundles_carry_numeric_features(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_ob_cases(gd, split="test")
        self.assertIsNotNone(cases[0].bundle.numeric_features)
        self.assertIn("triage_feature_log_error_count",
                      cases[0].bundle.numeric_features)

    def test_missing_examples_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                load_ob_cases(Path(td) / "nope", split="test")


# ---------------------------------------------------------------------------
# WoL loader
# ---------------------------------------------------------------------------


class TestWoLLoader(unittest.TestCase):
    def _build_layout(self, td: Path) -> Path:
        gd = td / "wol-test-ds"
        _write_jsonl(gd / "global-triage-examples.jsonl", [
            _wol_window("w1", split="test"),
            _wol_window("w2", split="test"),
        ])
        # WoL gold lives in tch-lite-refit/biencoder-predictions.jsonl
        _write_jsonl(gd / "tch-lite-refit" / "biencoder-predictions.jsonl", [
            {**_ob_pred("w1", gold=["WOL-1"]),
             "pipeline_name": "bi_encoder_retrieval"},
            {**_ob_pred("w2", gold=[]),
             "pipeline_name": "bi_encoder_retrieval"},
        ])
        return gd

    def test_loads_wol_cases(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_wol_cases(gd, split="test")
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].gold_matched_issue_ids, ("WOL-1",))

    def test_wol_bundles_have_no_numeric_features(self):
        """WoL is text-only by design — capability adapter relies on
        the loader NOT populating numeric_features (otherwise the
        observer would unlock NUMERIC_FEATURES, which would let
        triage_numeric run against OB-trained predictions)."""
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_wol_cases(gd, split="test")
        self.assertIsNone(cases[0].bundle.numeric_features)

    def test_wol_bundles_have_no_log_lines(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_wol_cases(gd, split="test")
        self.assertIsNone(cases[0].bundle.log_lines)

    def test_dataset_label_defaults_to_wol(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_layout(Path(td))
            cases = load_wol_cases(gd, split="test")
        self.assertEqual(cases[0].bundle.dataset, "wol")


# ---------------------------------------------------------------------------
# OTel Demo loader
# ---------------------------------------------------------------------------


class TestOtelDemoLoader(unittest.TestCase):
    def _build_with_matchings_only(self, td: Path) -> Path:
        gd = td / "otel-test-ds"
        _write_jsonl(gd / "global-triage-examples.jsonl", [
            _otel_window("w1", split="train"),
            _otel_window("w2", split="train"),
        ])
        # OTel-shape matchings file
        _write_jsonl(gd / "window-memory-matchings.jsonl", [
            {
                "window_id": "w1",
                "matched_memory_issue_ids": ["OTEL-1"],
                "triage_label": "ticket_worthy",
                "is_novel": False,
                "affected_service": "frontend",
                "scenario_family": "otel-baseline",
            },
            {
                "window_id": "w2",
                "matched_memory_issue_ids": [],
                "triage_label": "noise",
                "is_novel": False,
                "affected_service": "frontend",
                "scenario_family": "otel-baseline",
            },
        ])
        return gd

    def _build_with_comparison(self, td: Path) -> Path:
        gd = self._build_with_matchings_only(td)
        # Also write a comparison/ pipeline file — should take precedence
        _write_jsonl(
            gd / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl",
            [_ob_pred("w1", gold=["OTEL-CMP-1"])],
        )
        return gd

    def test_loads_via_matchings_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_with_matchings_only(Path(td))
            cases = load_otel_demo_cases(gd, split="train")
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].gold_matched_issue_ids, ("OTEL-1",))

    def test_comparison_takes_precedence_in_auto(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_with_comparison(Path(td))
            cases = load_otel_demo_cases(gd, split="train")
        # First case's gold should come from comparison, not matchings
        c1 = next(c for c in cases if c.bundle.window_id == "w1")
        self.assertEqual(c1.gold_matched_issue_ids, ("OTEL-CMP-1",))

    def test_explicit_matchings_source(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_with_comparison(Path(td))
            cases = load_otel_demo_cases(
                gd, split="train", gold_source="matchings",
            )
        c1 = next(c for c in cases if c.bundle.window_id == "w1")
        # Now reads from matchings → OTEL-1
        self.assertEqual(c1.gold_matched_issue_ids, ("OTEL-1",))

    def test_empty_split_raises_with_helpful_message(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_with_matchings_only(Path(td))
            with self.assertRaises(ValueError) as ctx:
                load_otel_demo_cases(gd, split="test")
        msg = str(ctx.exception)
        self.assertIn("test", msg)
        self.assertIn("train", msg)
        self.assertIn("try split='train'", msg)

    def test_dataset_label_defaults_to_otel_demo(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_with_matchings_only(Path(td))
            cases = load_otel_demo_cases(gd, split="train")
        self.assertEqual(cases[0].bundle.dataset, "otel_demo")


# ---------------------------------------------------------------------------
# Split-manifest override
# ---------------------------------------------------------------------------


class TestSplitManifestOverride(unittest.TestCase):
    """The v2-resplit manifest must override the JSONL's `split` field
    when both are present. This is how the OB stratified resplit gets
    applied without rewriting the JSONL and how OTel Demo gets a
    test/val split now that we've run the resplit on it."""

    def _build_ob_with_manifest(self, td: Path) -> Path:
        gd = td / "ob-manifest-test"
        # JSONL marks all 4 windows as "train"
        _write_jsonl(gd / "global-triage-examples.jsonl", [
            _ob_window("w1", split="train"),
            _ob_window("w2", split="train"),
            _ob_window("w3", split="train"),
            _ob_window("w4", split="train"),
        ])
        _write_jsonl(
            gd / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl",
            [
                _ob_pred("w1", gold=["X"]),
                _ob_pred("w2", gold=["Y"]),
                _ob_pred("w3", gold=["Z"]),
                _ob_pred("w4", gold=["W"]),
            ],
        )
        # Manifest reassigns: w1+w2 to test, w3 to val, w4 stays train
        manifest = {
            "schema_version": 2,
            "window_assignment": {
                "w1": "test",
                "w2": "test",
                "w3": "validation",
                "w4": "train",
            },
        }
        (gd / "triage-split-manifest-v2-resplit.json").write_text(
            json.dumps(manifest), encoding="utf-8",
        )
        return gd

    def test_manifest_overrides_jsonl_split(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_ob_with_manifest(Path(td))
            cases = load_ob_cases(gd, split="test")
        # JSONL says everything is "train"; manifest reassigns w1+w2 to test
        self.assertEqual({c.bundle.window_id for c in cases}, {"w1", "w2"})

    def test_manifest_validation_split(self):
        with tempfile.TemporaryDirectory() as td:
            gd = self._build_ob_with_manifest(Path(td))
            cases = load_ob_cases(gd, split="validation")
        self.assertEqual([c.bundle.window_id for c in cases], ["w3"])

    def test_manifest_unaffected_windows_fall_back_to_jsonl(self):
        """A window NOT in the manifest must fall back to its JSONL split."""
        with tempfile.TemporaryDirectory() as td:
            gd = Path(td) / "ob-partial-manifest"
            _write_jsonl(gd / "global-triage-examples.jsonl", [
                _ob_window("a", split="test"),                # JSONL: test
                _ob_window("b", split="train"),               # JSONL: train
            ])
            _write_jsonl(
                gd / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl",
                [_ob_pred("a", gold=["X"]), _ob_pred("b", gold=["Y"])],
            )
            # Manifest only assigns "b" → moved to test. "a" not listed → falls back.
            (gd / "triage-split-manifest-v2-resplit.json").write_text(
                json.dumps({"window_assignment": {"b": "test"}}),
                encoding="utf-8",
            )
            test_cases = load_ob_cases(gd, split="test")

        # "a" stays test (from JSONL), "b" becomes test (from manifest)
        self.assertEqual({c.bundle.window_id for c in test_cases}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
