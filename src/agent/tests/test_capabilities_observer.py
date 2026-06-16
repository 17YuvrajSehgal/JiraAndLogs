"""Offline tests for the Capabilities Observer + Verifier calibration.

Covers:
    - Each capability flag fires exactly when its evidence is present.
    - Richness fields are populated correctly.
    - ORDERED vs UNORDERED logs branch on the log_lines_ordered flag.
    - WoL profile (text-only) produces the expected limited capability set.
    - OB profile (full telemetry) produces the full capability set.
    - VerifierCalibration: known_helpful ⊂ known_harmful precedence,
      default_policy fallback, YAML loading.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_capabilities_observer -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import (
    CapabilitiesObserver,
    InputBundle,
    K8S_EVENTS,
    K8sEvent,
    KG_GRAPH_MEMORY,
    KG_GRAPH_WINDOW,
    LogLine,
    MEMORY_TEXT,
    METRIC_SNAPSHOTS,
    NUMERIC_FEATURES,
    ObservationContext,
    ORDERED_LOGS,
    TEXT_EVIDENCE,
    TRACE_SUMMARY,
    TraceSummary,
    UNORDERED_LOGS,
    VERIFIER_KNOWN_HELPFUL,
    VerifierCalibration,
    observe,
)


# ---------------------------------------------------------------------------
# VerifierCalibration
# ---------------------------------------------------------------------------


class TestVerifierCalibration(unittest.TestCase):
    def test_known_helpful_returns_true(self):
        c = VerifierCalibration(known_helpful_distributions=frozenset({"ob"}))
        self.assertTrue(c.is_helpful("ob"))

    def test_known_harmful_returns_false(self):
        c = VerifierCalibration(known_harmful_distributions=frozenset({"wol"}))
        self.assertFalse(c.is_helpful("wol"))

    def test_default_policy_skip_for_unknown(self):
        c = VerifierCalibration(default_policy="skip")
        self.assertFalse(c.is_helpful("never-seen-before"))

    def test_default_policy_enable_for_unknown(self):
        c = VerifierCalibration(default_policy="enable")
        self.assertTrue(c.is_helpful("never-seen-before"))

    def test_known_harmful_wins_over_known_helpful(self):
        # If someone accidentally puts the same id in both lists,
        # the harmful list wins (safer).
        c = VerifierCalibration(
            known_helpful_distributions=frozenset({"both"}),
            known_harmful_distributions=frozenset({"both"}),
        )
        self.assertFalse(c.is_helpful("both"))

    def test_from_dict_empty(self):
        c = VerifierCalibration.from_dict({})
        self.assertEqual(c.default_policy, "skip")
        self.assertFalse(c.is_helpful("anything"))

    def test_from_dict_populated(self):
        c = VerifierCalibration.from_dict({
            "known_helpful_distributions": ["ob", "otel"],
            "known_harmful_distributions": ["wol"],
            "default_policy": "enable",
        })
        self.assertTrue(c.is_helpful("ob"))
        self.assertTrue(c.is_helpful("otel"))
        self.assertFalse(c.is_helpful("wol"))
        self.assertTrue(c.is_helpful("unknown"))   # default=enable

    def test_yaml_file_roundtrip(self):
        yaml_content = """
experiment:
  dataset_id: foo
verifier_calibration:
  known_helpful_distributions:
    - ob
  known_harmful_distributions:
    - wol
  default_policy: skip
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "agent-config.yaml"
            path.write_text(yaml_content, encoding="utf-8")
            c = VerifierCalibration.from_yaml_file(path)
            self.assertTrue(c.is_helpful("ob"))
            self.assertFalse(c.is_helpful("wol"))


# ---------------------------------------------------------------------------
# Observer — single-flag behaviour
# ---------------------------------------------------------------------------


class TestObserverPerFlag(unittest.TestCase):
    def test_numeric_features_present(self):
        b = InputBundle(window_id="w", dataset="ob",
                        numeric_features={"latency": 1.5, "errors": 0.3})
        c = observe(b)
        self.assertTrue(c.has(NUMERIC_FEATURES))
        self.assertEqual(c.get_richness(NUMERIC_FEATURES, "n_columns"), 2)

    def test_numeric_features_absent(self):
        b = InputBundle(window_id="w", dataset="wol")
        c = observe(b)
        self.assertFalse(c.has(NUMERIC_FEATURES))

    def test_text_evidence_below_min_chars_does_not_fire(self):
        # The min-chars threshold (8) rejects degenerate stubs.
        b = InputBundle(window_id="w", dataset="ob", text_evidence="short")
        c = observe(b)
        self.assertFalse(c.has(TEXT_EVIDENCE))

    def test_text_evidence_above_threshold_fires(self):
        b = InputBundle(window_id="w", dataset="ob",
                        text_evidence="redis connection timeout in cart service")
        c = observe(b)
        self.assertTrue(c.has(TEXT_EVIDENCE))
        self.assertEqual(
            c.get_richness(TEXT_EVIDENCE, "n_chars"),
            len("redis connection timeout in cart service"),
        )

    def test_ordered_logs_fires_when_ordered(self):
        b = InputBundle(window_id="w", dataset="ob",
                        log_lines=(LogLine(ts_ns=100, service="cart", line="err"),
                                   LogLine(ts_ns=200, service="redis", line="slow")),
                        log_lines_ordered=True)
        c = observe(b)
        self.assertTrue(c.has(ORDERED_LOGS))
        self.assertFalse(c.has(UNORDERED_LOGS))
        self.assertEqual(c.get_richness(ORDERED_LOGS, "n_lines"), 2)
        self.assertEqual(c.get_richness(ORDERED_LOGS, "n_services"), 2)
        # span = (200 - 100) / 1e9 = 1e-7 seconds
        self.assertAlmostEqual(
            c.get_richness(ORDERED_LOGS, "max_span_seconds"), 0.0, places=6,
        )

    def test_unordered_logs_fires_when_not_ordered(self):
        # WoL profile: log_quotes pasted into a ticket; no temporal order.
        b = InputBundle(window_id="w", dataset="wol",
                        log_lines=(LogLine(service="kafka", line="OOM"),
                                   LogLine(service="kafka", line="rebalance timeout")),
                        log_lines_ordered=False)
        c = observe(b)
        self.assertTrue(c.has(UNORDERED_LOGS))
        self.assertFalse(c.has(ORDERED_LOGS))
        self.assertEqual(c.get_richness(UNORDERED_LOGS, "n_lines"), 2)

    def test_trace_summary_fires_when_n_spans_positive(self):
        b = InputBundle(window_id="w", dataset="ob",
                        trace_summary=TraceSummary(n_spans=10, error_spans=2))
        c = observe(b)
        self.assertTrue(c.has(TRACE_SUMMARY))
        self.assertEqual(c.get_richness(TRACE_SUMMARY, "n_spans"), 10)
        self.assertEqual(c.get_richness(TRACE_SUMMARY, "error_spans"), 2)

    def test_trace_summary_with_zero_spans_does_not_fire(self):
        # n_spans=0 means no actual trace data; skipping is correct.
        b = InputBundle(window_id="w", dataset="ob",
                        trace_summary=TraceSummary(n_spans=0))
        c = observe(b)
        self.assertFalse(c.has(TRACE_SUMMARY))

    def test_k8s_events_fires(self):
        b = InputBundle(window_id="w", dataset="ob",
                        k8s_events=(K8sEvent(reason="Killing"),
                                    K8sEvent(reason="OOMKilling")))
        c = observe(b)
        self.assertTrue(c.has(K8S_EVENTS))
        self.assertEqual(c.get_richness(K8S_EVENTS, "n_events"), 2)

    def test_metric_snapshots_fires(self):
        b = InputBundle(window_id="w", dataset="ob",
                        metric_snapshots={"cpu_pct": (0.5, 0.6),
                                          "mem_pct": (0.4, 0.5)})
        c = observe(b)
        self.assertTrue(c.has(METRIC_SNAPSHOTS))
        self.assertEqual(c.get_richness(METRIC_SNAPSHOTS, "n_series"), 2)


# ---------------------------------------------------------------------------
# Observer — context flags
# ---------------------------------------------------------------------------


class TestObserverContextFlags(unittest.TestCase):
    def test_memory_text_from_context(self):
        b = InputBundle(window_id="w", dataset="ob")
        c_no = observe(b, ObservationContext(has_memory_text=False))
        c_yes = observe(b, ObservationContext(has_memory_text=True))
        self.assertFalse(c_no.has(MEMORY_TEXT))
        self.assertTrue(c_yes.has(MEMORY_TEXT))

    def test_kg_graph_memory_from_context(self):
        b = InputBundle(window_id="w", dataset="ob")
        c = observe(b, ObservationContext(has_kg_graph_memory=True))
        self.assertTrue(c.has(KG_GRAPH_MEMORY))

    def test_kg_graph_window_from_context(self):
        b = InputBundle(window_id="w", dataset="wol")
        c = observe(b, ObservationContext(has_kg_graph_window=True))
        self.assertTrue(c.has(KG_GRAPH_WINDOW))

    def test_verifier_known_helpful_via_calibration(self):
        cal = VerifierCalibration(known_helpful_distributions=frozenset({"ob"}))
        b = InputBundle(window_id="w", dataset="ob")
        c = observe(b, ObservationContext(dataset_id="ob",
                                          verifier_calibration=cal))
        self.assertTrue(c.has(VERIFIER_KNOWN_HELPFUL))

    def test_verifier_skipped_for_harmful_dataset(self):
        cal = VerifierCalibration(known_harmful_distributions=frozenset({"wol"}))
        b = InputBundle(window_id="w", dataset="wol")
        c = observe(b, ObservationContext(dataset_id="wol",
                                          verifier_calibration=cal))
        self.assertFalse(c.has(VERIFIER_KNOWN_HELPFUL))


# ---------------------------------------------------------------------------
# Observer — dataset profile integration
# ---------------------------------------------------------------------------


class TestObserverProfiles(unittest.TestCase):
    """End-to-end: typical bundles + contexts for each dataset → expected flag sets."""

    def _ob_bundle(self) -> InputBundle:
        return InputBundle(
            window_id="ob-w42", dataset="online_boutique",
            text_evidence="cart-redis: connection refused after pod restart",
            numeric_features={"latency_p99": 1.5, "error_rate": 0.3},
            log_lines=(
                LogLine(ts_ns=1, service="cart", line="redis err"),
                LogLine(ts_ns=2, service="redis", line="restart"),
            ),
            log_lines_ordered=True,
            trace_summary=TraceSummary(n_spans=12, error_spans=3),
            k8s_events=(K8sEvent(reason="Killing"),),
            metric_snapshots={"cpu_pct": (0.5, 0.7)},
            scenario_family="cart-redis-degradation",
            service_name="cart", window_type="active_fault",
        )

    def _wol_bundle(self) -> InputBundle:
        return InputBundle(
            window_id="wol-q-1234", dataset="wol",
            text_evidence="org.apache.kafka.OutOfMemoryError on broker-3",
            log_lines=(
                LogLine(service="kafka", line="OOM"),
                LogLine(service="kafka", line="rebalance"),
            ),
            log_lines_ordered=False,
            scenario_family="wol-kafka",
        )

    def test_ob_profile_has_full_telemetry(self):
        cal = VerifierCalibration(known_helpful_distributions=frozenset({"ob-id"}))
        ctx = ObservationContext(
            dataset_id="ob-id", has_memory_text=True,
            has_kg_graph_memory=True, has_kg_graph_window=True,
            verifier_calibration=cal,
        )
        c = observe(self._ob_bundle(), ctx)

        expected = {
            NUMERIC_FEATURES, TEXT_EVIDENCE, ORDERED_LOGS, TRACE_SUMMARY,
            K8S_EVENTS, METRIC_SNAPSHOTS,
            MEMORY_TEXT, KG_GRAPH_MEMORY, KG_GRAPH_WINDOW,
            VERIFIER_KNOWN_HELPFUL,
        }
        self.assertEqual(c.flags, frozenset(expected))
        # UNORDERED_LOGS is mutually exclusive with ORDERED_LOGS
        self.assertFalse(c.has(UNORDERED_LOGS))

    def test_wol_profile_is_text_only(self):
        # WoL has: text + unordered logs + memory_text. No telemetry.
        # Verifier is NOT helpful on WoL (Mode 3 §3.9 finding).
        cal = VerifierCalibration(known_harmful_distributions=frozenset({"wol-id"}))
        ctx = ObservationContext(
            dataset_id="wol-id", has_memory_text=True,
            has_kg_graph_memory=True,        # we have LLM-extracted memory entities
            has_kg_graph_window=False,        # RQ-A6 not yet fixed
            verifier_calibration=cal,
        )
        c = observe(self._wol_bundle(), ctx)

        expected = {
            TEXT_EVIDENCE, UNORDERED_LOGS, MEMORY_TEXT, KG_GRAPH_MEMORY,
        }
        self.assertEqual(c.flags, frozenset(expected))
        # Crucial: NO verifier (structural closure of RQ-A8)
        self.assertFalse(c.has(VERIFIER_KNOWN_HELPFUL))
        # NO telemetry-derived flags
        self.assertFalse(c.has(NUMERIC_FEATURES))
        self.assertFalse(c.has(TRACE_SUMMARY))
        self.assertFalse(c.has(K8S_EVENTS))
        self.assertFalse(c.has(METRIC_SNAPSHOTS))
        self.assertFalse(c.has(ORDERED_LOGS))

    def test_wol_profile_with_rqa6_fix_has_kg_graph_window(self):
        # After RQ-A6 fix, WoL gets KG_GRAPH_WINDOW
        ctx = ObservationContext(
            dataset_id="wol-id",
            has_kg_graph_memory=True,
            has_kg_graph_window=True,           # ← the fix
        )
        c = observe(self._wol_bundle(), ctx)
        self.assertTrue(c.has(KG_GRAPH_WINDOW))

    def test_observer_is_deterministic(self):
        # Same inputs → same outputs, always.
        b = self._ob_bundle()
        ctx = ObservationContext(dataset_id="ob-id")
        c1 = observe(b, ctx)
        c2 = observe(b, ctx)
        self.assertEqual(c1.flags, c2.flags)
        self.assertEqual(c1.richness, c2.richness)

    def test_observer_class_and_function_agree(self):
        b = self._wol_bundle()
        c1 = observe(b)
        c2 = CapabilitiesObserver().observe(b)
        self.assertEqual(c1.flags, c2.flags)


# ---------------------------------------------------------------------------
# ObservationContext — agent-config integration
# ---------------------------------------------------------------------------


class TestObservationContextFromConfig(unittest.TestCase):
    def test_from_agent_config_extracts_dataset_and_calibration(self):
        config = {
            "experiment": {
                "name": "wol-baseline",
                "dataset_id": "2026-06-15-wol-real-v2-global",
            },
            "verifier_calibration": {
                "known_helpful_distributions": ["2026-05-25-dataset-v5-large-global"],
                "known_harmful_distributions": ["2026-06-15-wol-real-v2-global"],
                "default_policy": "skip",
            },
        }
        ctx = ObservationContext.from_agent_config(
            config, has_kg_graph_memory=True, has_kg_graph_window=False,
        )
        self.assertEqual(ctx.dataset_id, "2026-06-15-wol-real-v2-global")
        self.assertTrue(ctx.has_kg_graph_memory)
        self.assertFalse(ctx.has_kg_graph_window)
        # WoL is in known_harmful → verifier off
        self.assertFalse(ctx.verifier_calibration.is_helpful(ctx.dataset_id))
        # OB would be in known_helpful → verifier on
        self.assertTrue(
            ctx.verifier_calibration.is_helpful("2026-05-25-dataset-v5-large-global")
        )


if __name__ == "__main__":
    unittest.main()
