"""Smoke tests for memorygraph — pure Python, no external services.

Run:
    python -m memorygraph.tests.test_smoke

Exits 0 on success, non-zero on first failure. We avoid pytest here so
this runs with the same minimal toolchain the rest of the project does.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable
_SRC_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from loganalyzer.data.schema import JiraMemoryIssue, TriageWindow

from memorygraph.agent import Agent, RulePlanner
from memorygraph.skills import NumericBlendSkill, default_skill_registry
from memorygraph.entities import (
    EntityId,
    EntityKind,
    extract_jira_entities,
    extract_obs_entities,
)
from memorygraph.graph import MemoryGraphBuilder


# ---------------------------------------------------------------------------
# Fixtures — synthetic, lab-leakage-laden data so we can verify stripping
# ---------------------------------------------------------------------------


def _make_window(
    *,
    window_id: str = "win-1",
    service: str = "paymentservice",
    evidence: str = (
        "WINDOW window_id=win-1 service=paymentservice\n"
        "TRACES error_spans=120 p95_ms=850\n"
        "ERROR DeadlineExceeded calling paymentservice from checkoutservice"
    ),
    p95_ms: float = 850.0,
    error_rate: float = 0.30,
    restarts: float = 0.0,
) -> TriageWindow:
    raw = {
        "window_id": window_id,
        "service_name": service,
        "triage_feature_trace_latency_p95_ms": p95_ms,
        "triage_feature_trace_error_rate": error_rate,
        "triage_feature_k8s_restart_count": restarts,
        "triage_feature_log_error_count": 12,
    }
    return TriageWindow(
        window_id=window_id,
        dataset_run_id="syn-run",
        incident_episode_id="syn-ep",
        scenario_id="syn-scenario",
        scenario_family="syn-family",
        service_name=service,
        window_type="active_fault",
        start_time="2026-05-25T22:00:00+00:00",
        end_time="2026-05-25T22:01:00+00:00",
        triage_label="ticket_worthy",
        triage_severity=None,
        triage_components=None,
        triage_reason_class=None,
        is_hard_case=False,
        source="derived",
        evidence_text=evidence,
        raw=raw,
    )


def _make_jira(
    *,
    sid: str = "j-1",
    service: str = "paymentservice",
    fault_type: str = "paymentservice-unavailable",
    fault_class: str = "outage",
    severity: str = "critical",
    extra_label: str = "incident",
    components_line: str | None = None,
) -> JiraMemoryIssue:
    # NB: deliberately includes lab-leakage labels so we can verify they
    # are stripped.
    components = components_line if components_line is not None else f"{service}"
    memory_text = (
        f"Summary: {fault_class.title()} on {service}\n"
        f"Components: {components}\n"
        f"Labels: dataset-syn, scenario-{fault_type}, severity-{severity}, "
        f"root-{fault_class}, synthetic-incident, {extra_label}\n"
        f"Description: {fault_type} affecting {service}.\n"
    )
    return JiraMemoryIssue(
        jira_shadow_issue_id=sid,
        jira_issue_key="J-1",
        dataset_run_id="other-run",
        incident_episode_id="other-ep",
        available_as_memory_from="2026-05-20T00:00:00+00:00",
        scenario_id="payment-outage",
        scenario_family="payment-outage",
        affected_service=service,
        fault_type=fault_type,
        fault_compatibility_class=fault_class,
        severity=severity,
        memory_text=memory_text,
        resolution_notes="Rolled back paymentservice deploy; service restored.",
        linked_window_ids=[],
        linked_trace_ids=[],
        linked_alert_fingerprints=[],
        raw={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_obs_entity_extractor() -> None:
    win = _make_window()
    entities, summary = extract_obs_entities(win)
    keys = {e.id.key() for e in entities}
    assert "service:paymentservice" in keys, keys
    assert "component:paymentservice" in keys, keys
    # peer service from evidence text
    assert "service:checkoutservice" in keys, keys
    # error class from "DeadlineExceeded" -> timeout
    assert "error_class:timeout" in keys, keys
    # latency band (p95=850ms falls in 250ms..1s)
    assert "latency_band:p95_250ms_to_1s" in keys, keys
    assert summary["p95_ms"] == 850.0


def test_jira_entity_extractor_strips_lab_labels() -> None:
    issue = _make_jira(components_line="paymentservice, checkoutservice")
    entities, summary = extract_jira_entities(issue)
    keys = {e.id.key() for e in entities}
    assert "service:paymentservice" in keys
    assert "component:paymentservice" in keys
    assert "component:checkoutservice" in keys
    assert "severity:critical" in keys
    assert "fault_class:outage" in keys
    # Lab leakage MUST be dropped
    assert "incident" in summary["kept_labels"], summary["kept_labels"]
    dropped = " ".join(summary["dropped_labels"])
    for bad in ("scenario-", "dataset-", "severity-", "root-", "synthetic-incident"):
        assert bad in dropped, f"expected {bad} in dropped, got {dropped}"


def test_graph_builds_cross_domain_bridges() -> None:
    builder = MemoryGraphBuilder()
    # j-1: paymentservice (matches the window)
    # j-2: emailservice (no overlap with the window's entities)
    builder.add_jira_corpus([
        _make_jira(sid="j-1", service="paymentservice", components_line="paymentservice"),
        _make_jira(sid="j-2", service="emailservice", fault_type="emailservice-down", fault_class="outage", components_line="emailservice"),
    ])
    builder.add_window(_make_window())
    g = builder.graph
    candidates = g.jira_candidates_for("win-1")
    assert "j-1" in candidates, candidates
    # j-2 only has emailservice — the window never mentions emailservice,
    # so they share no entity.
    assert "j-2" not in candidates, candidates
    # Bridge weight: paymentservice has 1 of 2 Jira owners -> rarity 0.5
    bw = g.bridge_weight(EntityId("service", "paymentservice"))
    assert 0.4 < bw < 0.6, bw


def test_agent_end_to_end_with_rule_planner() -> None:
    builder = MemoryGraphBuilder()
    j1 = _make_jira(sid="j-1", service="paymentservice", components_line="paymentservice")
    j2 = _make_jira(
        sid="j-2", service="emailservice",
        fault_type="emailservice-down", fault_class="outage",
        components_line="emailservice",
    )
    builder.add_jira_corpus([j1, j2])
    window = _make_window()
    builder.add_window(window)
    agent = Agent(builder.graph, planner=RulePlanner())
    visible = {"j-1": j1, "j-2": j2}
    decision = agent.decide(window, visible)
    # Component filter should have shrunk the pool: only j-1 shares
    # paymentservice; j-2 shares no entity at this point.
    assert decision.n_candidates_after_filter >= 1
    assert decision.triage_score >= 0.0
    assert decision.decision in ("ticket_worthy", "noise")
    assert decision.skill_chain[-1] == "graph_traverse_explain"
    # The explanation should reference paymentservice graph evidence
    assert "paymentservice" in decision.explanation.lower() or "j-1" in decision.explanation.lower() or "J-1" in decision.explanation


def test_numeric_blend_skill_fit_and_predict() -> None:
    """NumericBlendSkill.fit trains a HGB head; .run writes ctx.numeric_score.

    Verifies the hybrid path's per-window numeric signal works end-to-end
    on a tiny synthetic train set with one obviously-discriminative
    feature.
    """
    feature_columns = [
        "triage_feature_trace_error_rate",
        "triage_feature_trace_latency_p95_ms",
        "triage_feature_k8s_restart_count",
        "triage_feature_log_error_count",
    ]
    train: list[TriageWindow] = []
    # 8 positives (high error rate) + 8 negatives (clean) — minimum for HGB
    # to bind a class boundary on this feature shape.
    for i in range(8):
        train.append(_make_window(
            window_id=f"pos-{i}", error_rate=0.6, p95_ms=900, restarts=1,
        ))
        train[-1].triage_label = "ticket_worthy"
    for i in range(8):
        clean = _make_window(
            window_id=f"neg-{i}", error_rate=0.001, p95_ms=20, restarts=0,
        )
        clean.triage_label = "noise"
        train.append(clean)

    # min_samples_leaf=2 because the synthetic dataset only has 16 rows;
    # the production default of 20 would refuse to split. v4/v5 corpora
    # use the production default.
    skill = NumericBlendSkill(min_samples_leaf=2)
    skill.fit(train, feature_columns)
    # The model is None only if sklearn is missing; in that case skip.
    if skill._model is None:
        return

    builder = MemoryGraphBuilder()
    builder.add_jira_corpus([_make_jira(sid="j-1")])
    bad = _make_window(window_id="hot", error_rate=0.7, p95_ms=1500, restarts=2)
    builder.add_window(bad)

    from memorygraph.skills import AgentContext
    ctx = AgentContext(window=bad, graph=builder.graph, visible_jira={"j-1": _make_jira(sid="j-1")})
    res = skill.run(ctx)
    assert res.ok
    assert ctx.numeric_score is not None
    assert 0.0 <= ctx.numeric_score <= 1.0
    # A window with error_rate=0.7 should score above 0.5 — the train set
    # made this trivially separable.
    assert ctx.numeric_score > 0.5, ctx.numeric_score


def test_hybrid_chain_includes_numeric_blend() -> None:
    """RulePlanner(with_numeric=True) must insert numeric_blend before triage_decide."""
    p = RulePlanner(with_numeric=True)
    builder = MemoryGraphBuilder()
    builder.add_jira_corpus([_make_jira()])
    builder.add_window(_make_window())

    from memorygraph.skills import AgentContext
    ctx = AgentContext(window=_make_window(), graph=builder.graph, visible_jira={})
    chain = p.plan(ctx)
    assert "numeric_blend" in chain
    nb_idx = chain.index("numeric_blend")
    td_idx = chain.index("triage_decide")
    assert nb_idx < td_idx, f"numeric_blend should precede triage_decide, got {chain}"


def test_window_node_is_transient() -> None:
    builder = MemoryGraphBuilder()
    builder.add_jira_corpus([_make_jira()])
    builder.add_window(_make_window())
    assert "win-1" in builder.graph.nodes
    builder.remove_window("win-1")
    assert "win-1" not in builder.graph.nodes
    # entity nodes themselves persist
    assert "service:paymentservice" in builder.graph.nodes
    # but obs owners on that entity must be empty again
    obs_owners = builder.graph.entity_owners["service:paymentservice"]["obs"]
    assert obs_owners == set()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run() -> int:
    tests = [
        ("obs_entity_extractor", test_obs_entity_extractor),
        ("jira_entity_extractor_strips_lab_labels", test_jira_entity_extractor_strips_lab_labels),
        ("graph_builds_cross_domain_bridges", test_graph_builds_cross_domain_bridges),
        ("agent_end_to_end_with_rule_planner", test_agent_end_to_end_with_rule_planner),
        ("numeric_blend_skill_fit_and_predict", test_numeric_blend_skill_fit_and_predict),
        ("hybrid_chain_includes_numeric_blend", test_hybrid_chain_includes_numeric_blend),
        ("window_node_is_transient", test_window_node_is_transient),
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"OK   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # pragma: no cover — surface any unexpected error
            failures += 1
            print(f"ERR  {name}: {type(exc).__name__}: {exc}")
    if failures:
        print(f"{failures} failure(s)")
        return 1
    print(f"{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
