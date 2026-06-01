"""V2 multi-channel evidence bundle for one incident episode.

For each humanized ticket, we want the LLM to see an engineer-shaped
evidence surface — not just log lines. Real triage spans four streams:

    log_lines     -> Move A characteristic signature
                     (memorygraph.log_signatures.signature_for_episode)
    metric_obs    -> paraphrased top-K |delta_*| features from the
                     pre-computed global-triage-examples.jsonl. Captures
                     "what changed vs baseline baseline" the way an
                     engineer scans Grafana panels.
    trace_summary -> current trace p95 / p50 / error_rate / count from
                     the same derived row.
    k8s_state     -> current restart_count / warning_event_count /
                     pod_unavailable_count.
    alert_names   -> firing alerts for this episode from alerts.jsonl,
                     deduped, with kind-cluster noise alerts removed.

Plus pass-throughs:
    symptom_phrase  -> caller-supplied (from symptom_map.py); never the
                       real scenario_id.
    trace_id_quoted -> first trace_id from telemetry_links; engineers
                       paste these verbatim in real Jira.

Persona-step slicing per LLM-Jira-enhancement.md sec 13.12 / sec 5
happens in `slice_for_step(bundle, step_kind)`. The bundle itself
contains every channel at full fidelity; slicing decides which the
persona-step sees. cs-agent gets only symptom; senior-sre gets all.

Bias-free guarantee: every string in the bundle is run through
`find_lab_tokens` before being returned. Any line carrying a lab token
(`scenario`, `fault`, `chaos`, `synthetic`, taxonomy strings, etc.) is
silently dropped — never reaches the LLM. This is defense-in-depth on
top of the V1 sanitizer firewall.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_REPO_SRC = Path(__file__).resolve().parent.parent
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from memorygraph.log_signatures import signature_for_episode  # noqa: E402

from .sanitizer import find_lab_tokens  # noqa: E402


# ---------------------------------------------------------------------------
# Paraphrase table — curated feature suffix -> engineer-voice phrase.
# Only features with units we trust appear here. Anything not in this
# table is skipped, so a future broken-unit feature can't slip in.
# ---------------------------------------------------------------------------


def _signed_int(v: float) -> str:
    n = int(round(v))
    return f"{n:+d}" if n else "0"


def _signed_float(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}f}"


def _signed_pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


def _latency_delta(label: str, ms: float) -> str:
    if abs(ms) >= 1000:
        return f"{label} {ms / 1000:+.2f}s vs baseline"
    return f"{label} {ms:+.0f}ms vs baseline"


_PARAPHRASERS: dict[str, Callable[[float], str]] = {
    # Trace deltas
    "delta_trace_latency_p95_ms": lambda v: _latency_delta("trace p95 latency", v),
    "delta_trace_latency_p50_ms": lambda v: _latency_delta("trace p50 latency", v),
    "delta_trace_error_count": lambda v: f"{_signed_int(v)} new error spans vs baseline",
    "delta_trace_error_rate": lambda v: f"trace error rate {_signed_pct(v)} vs baseline",
    "delta_trace_count": lambda v: f"{_signed_int(v)} traces (volume change vs baseline)",
    "delta_trace_span_count": lambda v: f"{_signed_int(v)} spans vs baseline",
    # RPC-level deltas (M0-M5 supplement)
    "delta_m05_rpc_server_requests_per_sec": lambda v: f"RPC server traffic {_signed_float(v)}/sec",
    "delta_m05_rpc_server_errors_per_sec": lambda v: f"RPC server errors {_signed_float(v)}/sec",
    "delta_m05_rpc_status_ok_per_sec": lambda v: f"RPC OK throughput {_signed_float(v)}/sec",
    "delta_m05_rpc_status_internal_per_sec": lambda v: f"RPC Internal-status rate {_signed_float(v)}/sec",
    "delta_m05_rpc_status_unavailable_per_sec": lambda v: f"RPC Unavailable-status rate {_signed_float(v)}/sec",
    "delta_m05_rpc_status_deadline_exceeded_per_sec": lambda v: f"RPC DeadlineExceeded rate {_signed_float(v)}/sec",
    # Business-event deltas
    "delta_m05_orders_placed_per_sec": lambda v: f"orders-placed {_signed_float(v)}/sec",
    "delta_m05_payments_success_per_sec": lambda v: f"payment success {_signed_float(v)}/sec",
    "delta_m05_payments_error_per_sec": lambda v: f"payment errors {_signed_float(v)}/sec",
    "delta_m05_cart_operations_success_per_sec": lambda v: f"cart-ops success {_signed_float(v)}/sec",
    "delta_m05_cart_operations_error_per_sec": lambda v: f"cart-ops errors {_signed_float(v)}/sec",
    "delta_m05_cart_get_success_per_sec": lambda v: f"cart-get success {_signed_float(v)}/sec",
    "delta_m05_cart_get_error_per_sec": lambda v: f"cart-get errors {_signed_float(v)}/sec",
    "delta_m05_cart_add_success_per_sec": lambda v: f"cart-add success {_signed_float(v)}/sec",
    "delta_m05_cart_add_error_per_sec": lambda v: f"cart-add errors {_signed_float(v)}/sec",
    "delta_m05_catalog_lookups_hit_per_sec": lambda v: f"catalog lookups hit {_signed_float(v)}/sec",
    "delta_m05_catalog_lookups_miss_per_sec": lambda v: f"catalog lookups miss {_signed_float(v)}/sec",
    "delta_m05_recommendations_served_per_sec": lambda v: f"recommendations served {_signed_float(v)}/sec",
    # K8s deltas
    "delta_k8s_restart_count": lambda v: f"{_signed_int(v)} pod restarts vs baseline",
    "delta_k8s_warning_event_count": lambda v: f"{_signed_int(v)} new k8s warning events",
    "delta_k8s_pod_unavailable_count": lambda v: f"{_signed_int(v)} pods marked unavailable",
    # Log volume deltas
    "delta_log_error_count": lambda v: f"{_signed_int(v)} new error log lines",
}


# Alert names that fire constantly in kind clusters or as Prometheus
# heartbeats — engineers ignore them. Drop from the bundle so the LLM
# doesn't pretend they're significant.
_NOISE_ALERTS: frozenset[str] = frozenset(
    {
        "Watchdog",                       # Prometheus heartbeat — always firing
        "TargetDown",                     # Often non-app exporters in kind
        "KubeProxyInstanceUnreachable",   # kind-cluster artifact
    }
)


# ---------------------------------------------------------------------------
# Bundle dataclass
# ---------------------------------------------------------------------------


@dataclass
class EvidenceBundle:
    """Full evidence for one episode. Slicing per step happens via
    `slice_for_step` after."""

    episode_id: str
    log_lines: list[str] = field(default_factory=list)
    log_lines_source: str = "empty"  # "diff" | "plain_fallback" | "empty"
    log_lines_service: str | None = None

    metric_observations: list[str] = field(default_factory=list)
    trace_summary: dict[str, Any] = field(default_factory=dict)
    k8s_state: dict[str, Any] = field(default_factory=dict)
    alert_names: list[str] = field(default_factory=list)

    symptom_phrase: str = ""
    trace_id_quoted: str | None = None

    primary_service: str | None = None

    def is_low_signal(self) -> bool:
        """Bundle has essentially no fault evidence — caller may decide
        to mark the ticket prose-only per rule 3c in sec 13.3."""
        return (
            not self.log_lines
            and not self.metric_observations
            and not self.alert_names
            and float(self.trace_summary.get("trace_error_rate") or 0) < 0.01
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_triage_rows_for_episode(
    global_triage_path: Path,
    episode_id: str,
) -> list[dict[str, Any]]:
    """All active_fault triage_examples rows for this episode (one per
    affected service). Returns [] if file missing or no matches."""
    out: list[dict[str, Any]] = []
    if not global_triage_path.exists():
        return out
    needle = f"{episode_id}-active_fault-"
    with global_triage_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            wid = rec.get("window_id", "")
            if needle in wid or wid == f"{episode_id}-active_fault":
                out.append(rec)
    return out


def _paraphrase_deltas(
    rows: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[str]:
    """Pick top-K |delta_*| across services for the episode, paraphrase
    via the curated table. Aggregates cross-service: for each feature
    suffix, the largest-magnitude value across rows wins."""
    best_per_suffix: dict[str, tuple[float, float]] = {}
    for row in rows:
        for col, val in row.items():
            if not col.startswith("triage_feature_"):
                continue
            suffix = col[len("triage_feature_"):]
            if suffix not in _PARAPHRASERS:
                continue
            if not isinstance(val, (int, float)) or val == 0:
                continue
            mag = abs(float(val))
            prev = best_per_suffix.get(suffix)
            if prev is None or mag > prev[0]:
                best_per_suffix[suffix] = (mag, float(val))

    ranked = sorted(
        best_per_suffix.items(), key=lambda kv: -kv[1][0]
    )
    out: list[str] = []
    for suffix, (_mag, val) in ranked[:top_k]:
        try:
            out.append(_PARAPHRASERS[suffix](val))
        except (TypeError, ValueError):
            continue
    return out


def _summarize_trace(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-service trace summary — pick the most-impacted row (worst
    p95) as representative."""
    if not rows:
        return {}
    by_impact = sorted(
        rows,
        key=lambda r: float(
            r.get("triage_feature_trace_latency_p95_ms") or 0
        ),
        reverse=True,
    )
    pick = by_impact[0]
    out: dict[str, Any] = {}
    for col in (
        "trace_count",
        "trace_error_count",
        "trace_error_rate",
        "trace_latency_p50_ms",
        "trace_latency_p95_ms",
        "trace_span_count",
    ):
        v = pick.get(f"triage_feature_{col}")
        if v is not None:
            out[col] = v
    return out


def _summarize_k8s(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-service k8s summary — max across services per metric."""
    out: dict[str, Any] = {}
    for col in (
        "k8s_restart_count",
        "k8s_warning_event_count",
        "k8s_pod_unavailable_count",
    ):
        vals = [r.get(f"triage_feature_{col}", 0) or 0 for r in rows]
        m = max(vals) if vals else 0
        if m:
            out[col] = m
    return out


def _load_alert_names_for_episode(
    alerts_path: Path,
    episode_id: str,
) -> list[str]:
    """Firing alerts whose `incident_episode_id` matches, deduped,
    noise-filtered. Order = first-seen (preserves time-of-fire order)."""
    if not alerts_path.exists():
        return []
    names: list[str] = []
    seen: set[str] = set()
    with alerts_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("incident_episode_id") != episode_id:
                continue
            if rec.get("status") != "firing":
                continue
            name = rec.get("alert_name", "")
            if not name or name in _NOISE_ALERTS or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def _pick_trace_id_to_quote(
    shadow_record: dict[str, Any] | None,
) -> str | None:
    if not shadow_record:
        return None
    links = shadow_record.get("telemetry_links") or {}
    trace_ids = links.get("trace_ids") or []
    return trace_ids[0] if trace_ids else None


def _strip_unsafe(strings: list[str]) -> list[str]:
    """Sanitizer guard — drop any string carrying a lab token."""
    return [s for s in strings if s and not find_lab_tokens(s)]


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def build_evidence(
    run_dir: Path,
    episode_id: str,
    components: list[str],
    *,
    global_triage_path: Path,
    alerts_path: Path,
    symptom_phrase: str = "",
    shadow_record: dict[str, Any] | None = None,
    top_k_deltas: int = 5,
    top_k_logs: int = 5,
) -> EvidenceBundle:
    """Assemble the multi-channel evidence bundle for one episode."""
    svc_used, log_lines, log_source = signature_for_episode(
        run_dir, episode_id, components, top_k=top_k_logs,
    )
    log_lines = _strip_unsafe(log_lines)

    triage_rows = _load_triage_rows_for_episode(
        global_triage_path, episode_id
    )
    metric_obs = _strip_unsafe(
        _paraphrase_deltas(triage_rows, top_k=top_k_deltas)
    )
    trace_summary = _summarize_trace(triage_rows)
    k8s_state = _summarize_k8s(triage_rows)
    alert_names = _strip_unsafe(
        _load_alert_names_for_episode(alerts_path, episode_id)
    )
    trace_id_quoted = _pick_trace_id_to_quote(shadow_record)
    if trace_id_quoted and find_lab_tokens(trace_id_quoted):
        trace_id_quoted = None

    # The symptom_phrase comes from symptom_map and is caller-supplied;
    # double-check it just in case.
    safe_symptom = symptom_phrase if not find_lab_tokens(symptom_phrase) else ""

    return EvidenceBundle(
        episode_id=episode_id,
        log_lines=log_lines,
        log_lines_source=log_source,
        log_lines_service=svc_used,
        metric_observations=metric_obs,
        trace_summary=trace_summary,
        k8s_state=k8s_state,
        alert_names=alert_names,
        symptom_phrase=safe_symptom,
        trace_id_quoted=trace_id_quoted,
        primary_service=svc_used,
    )


# ---------------------------------------------------------------------------
# Persona-step slicing
# ---------------------------------------------------------------------------


# Per LLM-Jira-enhancement.md sec 13.12: each persona-step sees only
# the channels appropriate to what that person would have access to in
# real triage. Conservative — better to under-expose than over-expose.
_STEP_SLICES: dict[str, dict[str, Any]] = {
    "report": {
        "log_lines": 0, "metric_obs": 0, "trace_summary": False,
        "k8s_state": False, "alert_names": 0, "trace_id_quoted": False,
    },
    "ack": {
        "log_lines": 1, "metric_obs": 1, "trace_summary": False,
        "k8s_state": True, "alert_names": 3, "trace_id_quoted": False,
    },
    "hypothesis": {
        "log_lines": 4, "metric_obs": 3, "trace_summary": True,
        "k8s_state": True, "alert_names": 0, "trace_id_quoted": True,
    },
    "redirect": {
        "log_lines": 3, "metric_obs": 5, "trace_summary": True,
        "k8s_state": True, "alert_names": 3, "trace_id_quoted": True,
    },
    "resolve": {
        "log_lines": 3, "metric_obs": 3, "trace_summary": True,
        "k8s_state": True, "alert_names": 3, "trace_id_quoted": True,
    },
}


def slice_for_step(
    bundle: EvidenceBundle,
    step_kind: str,
) -> dict[str, Any]:
    """Project the bundle down to what step_kind's persona has access to."""
    cfg = _STEP_SLICES.get(step_kind)
    if cfg is None:
        return {"symptom_phrase": bundle.symptom_phrase}
    out: dict[str, Any] = {"symptom_phrase": bundle.symptom_phrase}
    if cfg["log_lines"] > 0 and bundle.log_lines:
        out["log_lines"] = bundle.log_lines[: cfg["log_lines"]]
    if cfg["metric_obs"] > 0 and bundle.metric_observations:
        out["metric_observations"] = bundle.metric_observations[
            : cfg["metric_obs"]
        ]
    if cfg["trace_summary"] and bundle.trace_summary:
        out["trace_summary"] = bundle.trace_summary
    if cfg["k8s_state"] and bundle.k8s_state:
        out["k8s_state"] = bundle.k8s_state
    if cfg["alert_names"] > 0 and bundle.alert_names:
        out["alert_names"] = bundle.alert_names[: cfg["alert_names"]]
    if cfg["trace_id_quoted"] and bundle.trace_id_quoted:
        out["trace_id_quoted"] = bundle.trace_id_quoted
    return out
