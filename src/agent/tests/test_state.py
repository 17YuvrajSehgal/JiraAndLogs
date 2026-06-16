"""Offline tests for Phase 1.12: StateLayer + WindowState + ServiceStateView.

Covers:
  - WindowState construction from AgentDecision + InputBundle.
  - Round-trip serialization (to_dict / from_dict).
  - ServiceStateView: read-only, n_consecutive_with_top1, recovery
    detection, has_seen_scenario.
  - StateLayer.record auto-generates incident_id for ticket_worthy
    windows; preserves explicit incident_id when supplied.
  - Page-suppression rule:
      - Suppresses when (same top1, same scenario, no recovery) within
        lookback.
      - Does NOT suppress when scenario differs.
      - Does NOT suppress when top1 differs.
      - Does NOT suppress when a recovery_window has intervened.
      - Does NOT suppress when candidate top1 is None.
      - Does NOT suppress beyond lookback distance.
  - Ring buffer maxlen behaviour (oldest entries fall off).
  - Persistence: save() → reload via construction restores buffers.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_state -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import AgentDecision, InputBundle, SkillCallCost
from agent.state import (
    PageSuppressionResult,
    ServiceStateView,
    StateLayer,
    WindowState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(
    window_id: str = "w1",
    *,
    triage: str = "ticket_worthy",
    matched: tuple[str, ...] = ("PROJ-1",),
    is_novel: bool = False,
) -> AgentDecision:
    return AgentDecision(
        bundle_id=window_id,
        triage_decision=triage,                                     # type: ignore[arg-type]
        triage_score=0.9 if triage == "ticket_worthy" else 0.1,
        matched_issue_ids=matched,
        is_novel=is_novel,
    )


def _bundle(
    window_id: str = "w1",
    *,
    service: str = "cart",
    scenario: str = "redis_oom",
    window_type: str = "active_fault",
) -> InputBundle:
    return InputBundle(
        window_id=window_id, dataset="online_boutique",
        service_name=service, scenario_family=scenario,
        window_type=window_type,
    )


def _state(
    window_id: str,
    *,
    service: str = "cart",
    scenario: str = "redis_oom",
    window_type: str = "active_fault",
    top1: str | None = "PROJ-1",
    triage: str = "ticket_worthy",
    incident_id: str | None = None,
) -> WindowState:
    return WindowState(
        window_id=window_id,
        service_name=service,
        timestamp="2026-06-12T00:00:00.000+00:00",
        triage_decision=triage,                                     # type: ignore[arg-type]
        top1_match=top1,
        is_novel=False,
        incident_id=incident_id,
        scenario_family=scenario,
        window_type=window_type,
    )


# ---------------------------------------------------------------------------
# WindowState
# ---------------------------------------------------------------------------


class TestWindowStateConstruction(unittest.TestCase):
    def test_from_decision_takes_top1_from_matched(self):
        d = _decision(matched=("A", "B", "C"))
        b = _bundle()
        s = WindowState.from_decision(d, b)
        self.assertEqual(s.top1_match, "A")

    def test_from_decision_no_matches_top1_none(self):
        d = _decision(matched=())
        b = _bundle()
        s = WindowState.from_decision(d, b)
        self.assertIsNone(s.top1_match)

    def test_from_decision_inherits_bundle_fields(self):
        d = _decision()
        b = _bundle(service="checkout", scenario="latency_spike",
                    window_type="recovery_window")
        s = WindowState.from_decision(d, b)
        self.assertEqual(s.service_name, "checkout")
        self.assertEqual(s.scenario_family, "latency_spike")
        self.assertEqual(s.window_type, "recovery_window")
        self.assertTrue(s.is_recovery())

    def test_serialization_roundtrip(self):
        s1 = _state("w1", top1="PROJ-1", incident_id="inc-x")
        d = s1.to_dict()
        s2 = WindowState.from_dict(d)
        self.assertEqual(s1, s2)

    def test_matches_for_suppression(self):
        s = _state("w1", top1="PROJ-1", scenario="redis_oom")
        self.assertTrue(s.matches_for_suppression(
            top1="PROJ-1", scenario_family="redis_oom"))
        # Different top1
        self.assertFalse(s.matches_for_suppression(
            top1="PROJ-2", scenario_family="redis_oom"))
        # Different scenario
        self.assertFalse(s.matches_for_suppression(
            top1="PROJ-1", scenario_family="latency_spike"))
        # None top1 on either side
        self.assertFalse(s.matches_for_suppression(
            top1=None, scenario_family="redis_oom"))


# ---------------------------------------------------------------------------
# ServiceStateView
# ---------------------------------------------------------------------------


class TestServiceStateView(unittest.TestCase):
    def test_empty_view(self):
        v = ServiceStateView("cart", [])
        self.assertEqual(len(v), 0)
        self.assertFalse(v)
        self.assertIsNone(v.latest)

    def test_latest_is_newest(self):
        a, b = _state("w1"), _state("w2")
        v = ServiceStateView("cart", [a, b])
        self.assertEqual(v.latest, b)

    def test_n_consecutive_with_top1(self):
        # Buffer: oldest [PROJ-1, PROJ-1, PROJ-2, PROJ-1, PROJ-1, PROJ-1] newest
        states = [
            _state("w1", top1="PROJ-1"),
            _state("w2", top1="PROJ-1"),
            _state("w3", top1="PROJ-2"),
            _state("w4", top1="PROJ-1"),
            _state("w5", top1="PROJ-1"),
            _state("w6", top1="PROJ-1"),
        ]
        v = ServiceStateView("cart", states)
        # PROJ-1: last 3 are PROJ-1 contiguous, then PROJ-2 breaks
        self.assertEqual(v.n_consecutive_with_top1("PROJ-1"), 3)
        # PROJ-2: 0 (last window is PROJ-1)
        self.assertEqual(v.n_consecutive_with_top1("PROJ-2"), 0)
        # Empty input
        self.assertEqual(v.n_consecutive_with_top1(""), 0)

    def test_last_n(self):
        states = [_state(f"w{i}") for i in range(5)]
        v = ServiceStateView("cart", states)
        self.assertEqual(len(v.last_n(2)), 2)
        # Newest IS at the end, last_n returns oldest-first
        self.assertEqual(v.last_n(2)[-1].window_id, "w4")
        self.assertEqual(v.last_n(0), [])

    def test_recovery_helpers(self):
        states = [
            _state("w1", window_type="active_fault"),
            _state("w2", window_type="recovery_window"),
            _state("w3", window_type="recovery_window"),
            _state("w4", window_type="recovery_window"),
        ]
        v = ServiceStateView("cart", states)
        self.assertEqual(v.n_consecutive_recovery(), 3)
        self.assertTrue(v.saw_recovery_within(2))
        self.assertTrue(v.saw_recovery_within(3))

    def test_has_seen_scenario(self):
        states = [
            _state("w1", scenario="redis_oom"),
            _state("w2", scenario="latency_spike"),
        ]
        v = ServiceStateView("cart", states)
        self.assertTrue(v.has_seen_scenario("redis_oom"))
        self.assertTrue(v.has_seen_scenario("latency_spike"))
        self.assertFalse(v.has_seen_scenario("oom_kill"))
        self.assertFalse(v.has_seen_scenario(None))

    def test_view_is_immutable(self):
        v = ServiceStateView("cart", [_state("w1")])
        # No append/remove API; mutating the returned list doesn't affect the view
        lst = v.to_list()
        lst.append(_state("hacker"))
        self.assertEqual(len(v), 1)


# ---------------------------------------------------------------------------
# StateLayer construction
# ---------------------------------------------------------------------------


class TestStateLayerConstruction(unittest.TestCase):
    def test_default_buffer_size(self):
        sl = StateLayer()
        self.assertEqual(sl.buffer_size, 12)

    def test_buffer_size_must_be_positive(self):
        with self.assertRaises(ValueError):
            StateLayer(buffer_size=0)

    def test_suppression_lookback_must_fit_in_buffer(self):
        with self.assertRaises(ValueError):
            StateLayer(buffer_size=2, suppression_lookback=5)


# ---------------------------------------------------------------------------
# StateLayer.record
# ---------------------------------------------------------------------------


class TestStateLayerRecord(unittest.TestCase):
    def test_record_appends_to_service_buffer(self):
        sl = StateLayer()
        sl.record(_state("w1", service="cart"))
        sl.record(_state("w2", service="cart"))
        sl.record(_state("w3", service="checkout"))
        self.assertEqual(sl.n_windows_for("cart"), 2)
        self.assertEqual(sl.n_windows_for("checkout"), 1)
        self.assertEqual(sl.n_services(), 2)
        self.assertEqual(sl.services(), ["cart", "checkout"])

    def test_record_generates_incident_id_for_ticket_worthy(self):
        sl = StateLayer()
        stored = sl.record(_state("w1", triage="ticket_worthy", incident_id=None))
        self.assertIsNotNone(stored.incident_id)
        self.assertTrue(stored.incident_id.startswith("inc-"))

    def test_record_preserves_explicit_incident_id(self):
        sl = StateLayer()
        stored = sl.record(_state("w1", triage="ticket_worthy",
                                  incident_id="inc-from-suppression"))
        self.assertEqual(stored.incident_id, "inc-from-suppression")

    def test_record_does_not_generate_id_for_noise(self):
        sl = StateLayer()
        stored = sl.record(_state("w1", triage="noise", incident_id=None))
        self.assertIsNone(stored.incident_id)

    def test_ring_buffer_evicts_oldest(self):
        sl = StateLayer(buffer_size=3)
        for i in range(5):
            sl.record(_state(f"w{i}"))
        self.assertEqual(sl.n_windows_for("cart"), 3)
        view = sl.get_view("cart")
        ids = [w.window_id for w in view]
        self.assertEqual(ids, ["w2", "w3", "w4"])

    def test_get_view_unknown_service_empty(self):
        sl = StateLayer()
        view = sl.get_view("never-seen")
        self.assertEqual(len(view), 0)

    def test_clear_one_service(self):
        sl = StateLayer()
        sl.record(_state("w1", service="cart"))
        sl.record(_state("w2", service="checkout"))
        sl.clear("cart")
        self.assertEqual(sl.n_windows_for("cart"), 0)
        self.assertEqual(sl.n_windows_for("checkout"), 1)

    def test_clear_all(self):
        sl = StateLayer()
        sl.record(_state("w1", service="cart"))
        sl.record(_state("w2", service="checkout"))
        sl.clear()
        self.assertEqual(sl.n_services(), 0)


# ---------------------------------------------------------------------------
# Page-suppression rule (§7.2)
# ---------------------------------------------------------------------------


class TestPageSuppression(unittest.TestCase):
    def _layer_with_prior_active(self) -> StateLayer:
        """One prior ticket_worthy active_fault window in cart's buffer."""
        sl = StateLayer()
        sl.record(_state("w0", service="cart", top1="PROJ-1",
                         scenario="redis_oom", window_type="active_fault",
                         triage="ticket_worthy"))
        return sl

    def test_same_top1_same_scenario_suppresses(self):
        sl = self._layer_with_prior_active()
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
            window_type="active_fault",
        )
        self.assertTrue(result.suppress)
        self.assertIsNotNone(result.incident_id)
        # The prior record has an auto-generated incident_id, which we recover.
        self.assertTrue(result.incident_id.startswith("inc-"))

    def test_different_scenario_does_not_suppress(self):
        sl = self._layer_with_prior_active()
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="latency_spike",
            window_type="active_fault",
        )
        self.assertFalse(result.suppress)

    def test_different_top1_does_not_suppress(self):
        sl = self._layer_with_prior_active()
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-2",
            scenario_family="redis_oom",
        )
        self.assertFalse(result.suppress)

    def test_recovery_window_intervened_does_not_suppress(self):
        sl = StateLayer()
        sl.record(_state("w0", top1="PROJ-1", scenario="redis_oom",
                         triage="ticket_worthy"))
        sl.record(_state("w1", top1=None, scenario="redis_oom",
                         window_type="recovery_window", triage="noise"))
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
        )
        self.assertFalse(result.suppress)
        self.assertIn("recovery", result.reason.lower())

    def test_candidate_top1_none_does_not_suppress(self):
        sl = self._layer_with_prior_active()
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1=None,
            scenario_family="redis_oom",
        )
        self.assertFalse(result.suppress)

    def test_unknown_service_does_not_suppress(self):
        sl = self._layer_with_prior_active()
        result = sl.check_page_suppression(
            service_name="never-seen",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
        )
        self.assertFalse(result.suppress)

    def test_beyond_lookback_does_not_suppress(self):
        sl = StateLayer(buffer_size=12, suppression_lookback=3)
        # Old matching window at position w0, then 5 unrelated windows
        sl.record(_state("w0", top1="PROJ-1", scenario="redis_oom",
                         triage="ticket_worthy"))
        for i in range(1, 6):
            sl.record(_state(f"w{i}", top1=f"OTHER-{i}", scenario="other_scenario"))
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
        )
        self.assertFalse(result.suppress,
                         "match outside lookback should NOT suppress")

    def test_match_within_lookback_suppresses(self):
        sl = StateLayer(buffer_size=12, suppression_lookback=3)
        # Old matching window, then 2 unrelated, then we check — the
        # match should still be visible at lookback=3.
        sl.record(_state("w0", top1="PROJ-1", scenario="redis_oom",
                         triage="ticket_worthy"))
        sl.record(_state("w1", top1="OTHER", scenario="other"))
        sl.record(_state("w2", top1="OTHER", scenario="other"))
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
        )
        # The match was 2 windows ago, lookback is 3, so the rule sees it.
        self.assertTrue(result.suppress)

    def test_suppression_recovers_incident_id(self):
        sl = StateLayer()
        # Force a known incident_id for assertion.
        sl.record(_state("w0", top1="PROJ-1", scenario="redis_oom",
                         incident_id="inc-known", triage="ticket_worthy"))
        result = sl.check_page_suppression(
            service_name="cart",
            candidate_top1="PROJ-1",
            scenario_family="redis_oom",
        )
        self.assertTrue(result.suppress)
        self.assertEqual(result.incident_id, "inc-known")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestStateLayerPersistence(unittest.TestCase):
    def test_save_then_reload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.jsonl"
            sl1 = StateLayer(persistence_path=path)
            sl1.record(_state("w1", service="cart", top1="PROJ-1",
                              triage="ticket_worthy"))
            sl1.record(_state("w2", service="cart", top1="PROJ-2",
                              triage="ticket_worthy"))
            sl1.record(_state("w3", service="checkout", top1="PROJ-9",
                              triage="ticket_worthy"))
            sl1.save()

            # Construct a fresh instance; should auto-load.
            sl2 = StateLayer(persistence_path=path)
            self.assertEqual(sl2.n_services(), 2)
            self.assertEqual(sl2.n_windows_for("cart"), 2)
            self.assertEqual(sl2.n_windows_for("checkout"), 1)
            view = sl2.get_view("cart")
            self.assertEqual([w.window_id for w in view], ["w1", "w2"])

    def test_save_without_path_raises(self):
        sl = StateLayer()              # no persistence_path
        with self.assertRaises(ValueError):
            sl.save()

    def test_load_corrupt_line_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.jsonl"
            # Mix valid + invalid lines
            path.write_text(
                '{"window_id": "ok", "service_name": "cart", "timestamp": "t", '
                '"triage_decision": "noise"}\n'
                "not a json line\n"
                '{"missing_required": true}\n',
                encoding="utf-8",
            )
            sl = StateLayer(persistence_path=path)
            # Only the valid line is in the buffer
            self.assertEqual(sl.n_windows_for("cart"), 1)


# ---------------------------------------------------------------------------
# Incident-id generation
# ---------------------------------------------------------------------------


class TestIncidentIdGeneration(unittest.TestCase):
    def test_generate_incident_id_unique(self):
        ids = {StateLayer.generate_incident_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)
        for i in ids:
            self.assertTrue(i.startswith("inc-"))


# ---------------------------------------------------------------------------
# All-time incident set survives ring-buffer rollover
# ---------------------------------------------------------------------------


class TestSeenIncidentIds(unittest.TestCase):
    """Phase 1.15 found that `pages_per_incident` over the full OB test
    split was undercounting because the ring buffer (size 12) rolls off
    older windows. `seen_incident_ids` is the all-time set, separate
    from the buffer."""

    def test_unique_count_survives_buffer_eviction(self):
        sl = StateLayer(buffer_size=3)
        # Record more than buffer_size ticket_worthy windows for ONE service —
        # all incident_ids must remain countable.
        for i in range(10):
            sl.record(_state(f"w{i}", service="cart", top1=f"PROJ-{i}",
                              scenario=f"scen-{i}", triage="ticket_worthy"))
        # Ring buffer only retains the last 3
        self.assertEqual(sl.n_windows_for("cart"), 3)
        # But all 10 unique incident_ids remain
        self.assertEqual(sl.n_unique_incidents_seen(), 10)

    def test_seen_ids_returns_frozenset(self):
        sl = StateLayer()
        sl.record(_state("w1", triage="ticket_worthy"))
        s = sl.seen_incident_ids()
        self.assertIsInstance(s, frozenset)
        self.assertEqual(len(s), 1)

    def test_noise_decisions_do_not_create_incidents(self):
        sl = StateLayer()
        for i in range(5):
            sl.record(_state(f"w{i}", triage="noise"))
        self.assertEqual(sl.n_unique_incidents_seen(), 0)

    def test_clear_all_resets_seen_set(self):
        sl = StateLayer()
        sl.record(_state("w1", triage="ticket_worthy"))
        sl.clear()
        self.assertEqual(sl.n_unique_incidents_seen(), 0)

    def test_clear_one_service_does_not_reset_global_seen(self):
        # All-time count is intentionally global (cross-service); a
        # per-service clear leaves it untouched. This matches the
        # eval-harness's use: pages-per-incident is a run-level metric.
        sl = StateLayer()
        sl.record(_state("w1", service="cart", triage="ticket_worthy"))
        sl.record(_state("w2", service="checkout", triage="ticket_worthy"))
        sl.clear("cart")
        self.assertEqual(sl.n_unique_incidents_seen(), 2)


if __name__ == "__main__":
    unittest.main()
