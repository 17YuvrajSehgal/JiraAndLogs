#!/usr/bin/env python3
"""
Shared helpers for the triage dataset and Jira-memory pipeline.

Defines:
  * the triage label vocabulary,
  * the scenario-family taxonomy (used for splits and memory-match ground truth),
  * deterministic derivation rules for per-window triage labels when no
    explicit scenario YAML triage block is present,
  * loaders for scenario YAML triage blocks (optional PyYAML),
  * JSON/JSONL utilities shared by the build scripts.

The triage task contract lives in docs/triage-task-contract.md. The dataset
plan lives in docs/dataset-v4-plan.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_VERSION = "0.1.0"

VALID_LABELS = ("ticket_worthy", "borderline", "noise")
VALID_SEVERITIES = ("minor", "major", "critical")
VALID_REASON_CLASSES = (
    "outage",
    "latency_regression",
    "restart_with_impact",
    "bad_config",
    "capacity",
    "dependency_failure",
    "data_consistency",
)
VALID_SOURCES = ("scenario_authored", "human_adjudicated", "derived")

DEFAULT_DERIVED_RULE_ID = "derive-from-scenario-fields-v1"

# Scenario family taxonomy. See docs/dataset-v4-plan.md.
SCENARIO_FAMILIES: dict[str, str] = {
    "baseline-normal-traffic": "baseline-normal",
    "paymentservice-unavailable-critical": "payment-outage",
    "paymentservice-pod-restart-major": "payment-outage",
    "cart-redis-degradation-critical": "cart-redis",
    "redis-cart-restart-major": "cart-redis",
    "redis-cart-restart-nearmiss": "cart-redis",
    "redis-cart-intermittent-failure-major": "cart-redis",
    "productcatalog-latency-major": "productcatalog-latency",
    "productcatalog-latency-nearmiss": "productcatalog-latency",
    "productcatalog-unavailable-critical": "productcatalog-outage",
    "productcatalog-bad-config-critical": "productcatalog-outage",
    "checkoutservice-pod-restart-major": "checkout-restart",
    "checkoutservice-partial-degradation-major": "checkout-restart",
    "checkoutservice-unavailable-critical": "checkout-outage",
    "currencyservice-unavailable-major": "currency-outage",
    "shippingservice-unavailable-major": "shipping-outage",
    "recommendationservice-unavailable-major": "recommendation-outage",
    "recommendationservice-pod-restart-nearmiss": "recommendation-outage",
    "adservice-unavailable-nearmiss": "ad-outage",
    "frontend-pod-restart-major": "frontend-restart",
    "frontend-cpu-nearmiss": "frontend-traffic-pressure",
    "loadgenerator-traffic-spike-nearmiss": "frontend-traffic-pressure",
    "loadgenerator-noisy-high-traffic-nearmiss": "frontend-traffic-pressure",
}

# Fault-type compatibility classes used for memory-match ground truth.
# Two issues match if they share fault_compatibility_class.
FAULT_TYPE_COMPATIBILITY: dict[str, str] = {
    # Outages
    "dependency_outage": "outage",
    "dependency_outage_nearmiss": "outage",
    "service_outage": "outage",
    "workload_outage": "outage",
    # Restarts
    "pod_restart": "restart",
    "pod_restart_nearmiss": "restart",
    "service_restart": "restart",
    "dependency_restart": "restart",
    "dependency_restart_nearmiss": "restart",
    "workload_restart": "restart",
    # Latency / degradation
    "service_latency": "latency",
    "latency_regression": "latency",
    "application_latency": "latency",
    "application_latency_nearmiss": "latency",
    "dependency_degradation": "latency",
    "dependency_intermittent_failure": "latency",
    "partial_service_degradation": "latency",
    # Capacity / traffic
    "traffic_pressure": "capacity",
    "traffic_spike": "capacity",
    "noisy_high_traffic": "capacity",
    "noisy_high_traffic_nearmiss": "capacity",
    "resource_saturation": "capacity",
    # Config
    "bad_config": "config",
    "bad_configuration": "config",
    "configuration_error": "config",
    # Data
    "data_consistency": "data",
    # No fault
    "none": "none",
}

# Reason class inferred from scenario incident_type when no explicit value
# is present on the scenario.
INCIDENT_TYPE_TO_REASON: dict[str, str] = {
    "outage": "outage",
    "degradation": "latency_regression",
    "service_outage": "outage",
    "service_restart": "restart_with_impact",
    "restart_with_impact": "restart_with_impact",
    "near_miss": "capacity",
    "baseline": "outage",  # unused: baseline windows are not ticket-worthy
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} line {line_number}: {exc}") from exc
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def scenario_family_for(scenario_id: str | None) -> str:
    if not scenario_id:
        return "unknown"
    return SCENARIO_FAMILIES.get(scenario_id, "unknown")


def fault_compatibility_class(fault_type: str | None) -> str:
    if not fault_type:
        return "none"
    return FAULT_TYPE_COMPATIBILITY.get(fault_type, "other")


def load_scenario_yaml(path: Path) -> dict[str, Any] | None:
    """Load a scenario YAML file. Returns None if PyYAML is unavailable or
    the file cannot be parsed. Callers should treat None as 'fall back to
    derived rules'."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception:
        return None


def scenario_yaml_path(scenarios_root: Path, scenario_id: str) -> Path | None:
    """Find the YAML file for a scenario_id under scenarios_root.
    Searches baselines/, faults/, and the root."""
    candidates = [
        scenarios_root / f"{scenario_id}.yaml",
        scenarios_root / "faults" / f"{scenario_id}.yaml",
        scenarios_root / "baselines" / f"{scenario_id}.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def authored_triage_label(
    scenario_yaml: dict[str, Any] | None,
    window_type: str,
) -> dict[str, Any] | None:
    """Return the scenario-authored triage label for a window type, or None
    if no authored label exists. Returns a dict with keys label, severity,
    components, reason_class, is_hard_case, rationale, family."""
    if not scenario_yaml:
        return None
    triage = scenario_yaml.get("triage")
    if not isinstance(triage, dict):
        return None
    per_window = triage.get("per_window")
    if not isinstance(per_window, dict):
        return None
    entry = per_window.get(window_type)
    if not isinstance(entry, dict):
        return None
    label = entry.get("triage_label")
    if label not in VALID_LABELS:
        return None
    family = triage.get("scenario_family") or scenario_family_for(
        scenario_yaml.get("scenario_id")
    )
    return {
        "label": label,
        "severity": entry.get("triage_severity"),
        "components": entry.get("triage_components"),
        "reason_class": entry.get("triage_reason_class"),
        "is_hard_case": bool(entry.get("is_hard_case", False)),
        "rationale": entry.get("rationale"),
        "family": family,
    }


def derive_triage_label(
    episode: dict[str, Any],
    window_type: str,
) -> dict[str, Any]:
    """Derive a per-window triage label from existing episode fields.
    Used when no scenario-authored or human-adjudicated label is available.
    Returns dict with label, severity, components, reason_class,
    is_hard_case, rationale, family."""
    scenario_id = str(episode.get("scenario_id", ""))
    family = scenario_family_for(scenario_id)
    jira_candidate = bool(episode.get("jira_candidate", False))
    severity = str(episode.get("severity", "")).lower() or None
    affected_services = list(episode.get("affected_services", []))
    incident_type = str(episode.get("incident_type", "")).lower()
    fault_type = None
    ground_truth = episode.get("ground_truth")
    if isinstance(ground_truth, dict):
        fault_type = ground_truth.get("fault_type")

    is_hard_case = "nearmiss" in scenario_id or "restart" in scenario_id

    if window_type in {"observation_window", "pre_fault_baseline"}:
        return {
            "label": "noise",
            "severity": None,
            "components": None,
            "reason_class": None,
            "is_hard_case": False,
            "rationale": (
                "Derived: baseline or pre-fault window; no injected fault."
            ),
            "family": family,
        }

    if window_type == "recovery_window":
        if jira_candidate:
            return {
                "label": "borderline",
                "severity": "minor" if severity in {"major", "critical"} else severity,
                "components": affected_services or None,
                "reason_class": INCIDENT_TYPE_TO_REASON.get(incident_type),
                "is_hard_case": True,
                "rationale": (
                    "Derived: recovery window for a Jira-worthy incident. "
                    "Residual impact may or may not be filed."
                ),
                "family": family,
            }
        return {
            "label": "noise",
            "severity": None,
            "components": None,
            "reason_class": None,
            "is_hard_case": False,
            "rationale": "Derived: recovery window for a non-Jira scenario.",
            "family": family,
        }

    if window_type == "active_fault":
        if jira_candidate:
            return {
                "label": "ticket_worthy",
                "severity": severity if severity in VALID_SEVERITIES else "major",
                "components": affected_services or ["unknown"],
                "reason_class": INCIDENT_TYPE_TO_REASON.get(incident_type, "outage"),
                "is_hard_case": is_hard_case,
                "rationale": (
                    "Derived: scenario marked jira_candidate=true; active "
                    "fault window."
                ),
                "family": family,
            }
        return {
            "label": "noise",
            "severity": None,
            "components": None,
            "reason_class": None,
            "is_hard_case": True,
            "rationale": (
                "Derived: scenario marked jira_candidate=false (near-miss or "
                "noise pattern). Hard case: the active fault may look "
                "suspicious despite not being filed."
            ),
            "family": family,
        }

    # Unknown window type — treat as noise with low confidence.
    return {
        "label": "noise",
        "severity": None,
        "components": None,
        "reason_class": None,
        "is_hard_case": False,
        "rationale": f"Derived: unknown window_type '{window_type}'; defaulted to noise.",
        "family": family,
    }


def build_triage_label_record(
    window: dict[str, Any],
    episode: dict[str, Any] | None,
    scenarios_root: Path | None,
    dataset_run_id: str,
) -> dict[str, Any]:
    """Build one TriageWindowLabel record. Prefers authored labels from the
    scenario YAML triage block; falls back to derived rules."""
    window_id = str(window.get("telemetry_window_id", window.get("window_id", "")))
    window_type = str(window.get("window_type", ""))
    if not window_type:
        labels = window.get("labels") or {}
        window_type = str(labels.get("window_type", ""))

    scenario_id = str(window.get("scenario_id") or (episode or {}).get("scenario_id") or "")
    incident_episode_id = window.get("incident_episode_id") or (
        (episode or {}).get("incident_episode_id")
    )

    authored = None
    if scenarios_root and scenario_id:
        path = scenario_yaml_path(scenarios_root, scenario_id)
        if path is not None:
            scenario_yaml = load_scenario_yaml(path)
            authored = authored_triage_label(scenario_yaml, window_type)

    if authored is not None:
        source = "scenario_authored"
        decision = authored
        derived_rule_id = None
    else:
        decision = derive_triage_label(episode or {}, window_type)
        source = "derived"
        derived_rule_id = DEFAULT_DERIVED_RULE_ID

    record: dict[str, Any] = {
        "telemetry_window_id": window_id,
        "dataset_run_id": dataset_run_id,
        "incident_episode_id": incident_episode_id,
        "scenario_id": scenario_id or None,
        "scenario_family": decision["family"],
        "window_type": window_type or None,
        "triage_label": decision["label"],
        "triage_severity": decision["severity"],
        "triage_components": decision["components"],
        "triage_reason_class": decision["reason_class"],
        "is_hard_case": decision["is_hard_case"],
        "rationale": decision["rationale"],
        "source": source,
        "adjudicator": None,
        "adjudicated_at": None,
        "derived_rule_id": derived_rule_id,
        "labels": {},
    }
    return record


FEATURE_COLUMNS: tuple[str, ...] = (
    "triage_feature_log_total_count",
    "triage_feature_log_error_count",
    "triage_feature_log_warning_count",
    "triage_feature_trace_count",
    "triage_feature_trace_span_count",
    "triage_feature_trace_error_count",
    "triage_feature_trace_error_rate",
    "triage_feature_trace_latency_p50_ms",
    "triage_feature_trace_latency_p95_ms",
    "triage_feature_metric_cpu_pct",
    "triage_feature_metric_memory_pct",
    "triage_feature_k8s_restart_count",
    "triage_feature_k8s_pod_unavailable_count",
    "triage_feature_alert_firing_count",
    "triage_feature_k8s_warning_event_count",
)

# Alerts that fire continuously regardless of the system under test. Excluding
# them sharpens alert_firing_count as a per-window signal.
CLUSTER_DEFAULT_ALERTS: frozenset[str] = frozenset(
    {
        "Watchdog",
        "InfoInhibitor",
        "KubeProxyInstanceUnreachable",
        "NodeClockNotSynchronising",
        "NodeClockSkewDetected",
        "TargetDown",
    }
)


def _parse_iso8601(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp into a UTC unix-seconds float. Tolerates
    fractional seconds, trailing Z, and Python 3.10 fromisoformat quirks."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        # Truncate sub-microsecond precision (Go-style 7-digit fractions
        # the kubectl JSON sometimes emits).
        if "." in text:
            head, _, tail = text.partition(".")
            sep = ""
            for marker in ("+", "-", "Z"):
                idx = tail.find(marker)
                if idx >= 0:
                    sep = tail[idx:]
                    tail = tail[:idx]
                    break
            tail = tail[:6]
            candidate = f"{head}.{tail}{sep}"
            try:
                return datetime.fromisoformat(candidate).timestamp()
            except ValueError:
                return None
        return None


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
            if isinstance(value, dict):
                return value
            return None
    except (json.JSONDecodeError, OSError):
        return None


def _prom_series(queries: dict[str, Any], name: str) -> list[dict[str, Any]]:
    query = queries.get(name) or {}
    response = query.get("response") or {}
    data = response.get("data") or {}
    result = data.get("result") or []
    return result if isinstance(result, list) else []


def _prom_values(queries: dict[str, Any], name: str) -> list[float]:
    out: list[float] = []
    for series in _prom_series(queries, name):
        for pair in series.get("values") or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                out.append(float(pair[1]))
            except (TypeError, ValueError):
                continue
    return out


def _prom_last_per_series_sum(queries: dict[str, Any], name: str) -> float:
    total = 0.0
    for series in _prom_series(queries, name):
        values = series.get("values") or []
        if not values:
            continue
        last = values[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 2:
            continue
        try:
            total += float(last[1])
        except (TypeError, ValueError):
            continue
    return total


def _zero_features() -> dict[str, float]:
    return {column: 0.0 for column in FEATURE_COLUMNS}


def _log_severity_from_body(line: str) -> str | None:
    """Return the severity reported in a JSON-shaped log body. Returns None
    when the body is not JSON or carries no severity-like key."""
    s = (line or "").strip()
    if not s or s[0] != "{":
        return None
    try:
        body = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("severity", "level", "log.level", "loglevel", "@level", "status"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value.strip().lower()
    return None


def _span_is_error(span: dict[str, Any]) -> bool:
    """Determine whether an OTel span represents an error.
    Checks span.status.code (OTel canonical) plus common attribute hints
    for gRPC and HTTP failures."""
    status = span.get("status") or {}
    code = status.get("code")
    if isinstance(code, str) and code.upper() in {"ERROR", "STATUS_CODE_ERROR"}:
        return True
    if isinstance(code, (int, float)) and int(code) == 2:
        return True
    for attribute in span.get("attributes") or []:
        key = attribute.get("key")
        value = attribute.get("value") or {}
        if key == "rpc.grpc.status_code":
            raw = value.get("intValue") or value.get("stringValue") or "0"
            try:
                if int(raw) != 0:
                    return True
            except (TypeError, ValueError):
                continue
        elif key in {"http.status_code", "http.response.status_code"}:
            raw = value.get("intValue") or value.get("stringValue") or "0"
            try:
                if int(raw) >= 500:
                    return True
            except (TypeError, ValueError):
                continue
        elif key == "error" and value.get("boolValue"):
            return True
    return False


def _span_duration_ms(span: dict[str, Any]) -> float | None:
    start = span.get("startTimeUnixNano")
    end = span.get("endTimeUnixNano")
    if start is None or end is None:
        return None
    try:
        delta_ns = int(end) - int(start)
    except (TypeError, ValueError):
        return None
    if delta_ns < 0:
        return None
    return delta_ns / 1_000_000.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if percentile <= 0:
        return ordered[0]
    if percentile >= 100:
        return ordered[-1]
    index = (percentile / 100.0) * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def numeric_features_from_raw(
    run_dir: Path,
    window_id: str,
) -> dict[str, float]:
    """Read raw exports for a window and compute production-safe numeric
    features. Returns a feature dict with every key in FEATURE_COLUMNS
    populated (zero when the underlying source is missing or empty).

    Source mapping:
      raw/prometheus/<window_id>.json -> restarts, cpu, memory, alert firing
        count (filtered against CLUSTER_DEFAULT_ALERTS)
      raw/loki/<window_id>.json       -> log totals + severity by parsing
        each JSON log body for severity/level keys
      raw/kubernetes/<window_id>.json -> max(0, desired - ready) for
        unavailable pods, warning events, container restart counts
      raw/tempo/<window_id>.json      -> trace count (from search summary),
        span count, error span count, error rate, latency p50/p95 from
        span duration distribution

    OnlineBoutique does not emit Prometheus app-level HTTP/RPC metrics, so
    request volume / error rate / latency derive from Tempo spans instead.
    """
    raw = run_dir / "raw"
    prom = _safe_read_json(raw / "prometheus" / f"{window_id}.json") or {}
    loki = _safe_read_json(raw / "loki" / f"{window_id}.json") or {}
    k8s = _safe_read_json(raw / "kubernetes" / f"{window_id}.json") or {}
    tempo = _safe_read_json(raw / "tempo" / f"{window_id}.json") or {}

    queries = prom.get("queries") or {}

    restart_values = _prom_values(queries, "restarts")
    prom_restart_delta = (max(restart_values) - min(restart_values)) if restart_values else 0.0

    cpu_values = _prom_values(queries, "cpu_usage")
    cpu_mean = (sum(cpu_values) / len(cpu_values)) if cpu_values else 0.0

    mem_values = _prom_values(queries, "memory_working_set")
    mem_mean = (sum(mem_values) / len(mem_values)) if mem_values else 0.0

    alert_firing = 0
    for series in _prom_series(queries, "alerts"):
        labels = series.get("metric") or {}
        if str(labels.get("alertstate", "")).lower() != "firing":
            continue
        if labels.get("alertname") in CLUSTER_DEFAULT_ALERTS:
            continue
        values = series.get("values") or []
        if not values:
            continue
        try:
            if float(values[-1][1]) > 0:
                alert_firing += 1
        except (TypeError, ValueError, IndexError):
            continue

    log_total = log_error = log_warning = 0
    loki_streams = (
        (loki.get("service_window") or {}).get("response", {}).get("data", {}).get("result")
        or []
    )
    error_levels = {"error", "err", "critical", "crit", "fatal", "panic"}
    warning_levels = {"warning", "warn"}
    for stream in loki_streams:
        labels = stream.get("stream") or {}
        stream_level = (
            labels.get("detected_level")
            or labels.get("severity")
            or labels.get("level")
            or ""
        ).strip().lower()
        for entry in stream.get("values") or []:
            log_total += 1
            try:
                line = entry[1]
            except (IndexError, TypeError):
                continue
            body_level = _log_severity_from_body(line) or stream_level
            if body_level in error_levels:
                log_error += 1
            elif body_level in warning_levels:
                log_warning += 1

    dep_response = ((k8s.get("deployment") or {}).get("response")) or {}
    dep_status = dep_response.get("status") or {}
    dep_spec = dep_response.get("spec") or {}
    desired = int(dep_spec.get("replicas") or 0)
    ready = int(dep_status.get("readyReplicas") or 0)
    available = int(dep_status.get("availableReplicas") or 0)
    unavailable_field = int(dep_status.get("unavailableReplicas") or 0)
    unavailable_from_replicas = max(
        unavailable_field, max(0, desired - ready), max(0, desired - available)
    )

    service_name = (k8s.get("service_name") or "").strip().lower()
    window_meta = k8s.get("window") or {}
    win_start = _parse_iso8601(window_meta.get("start_time"))
    win_end = _parse_iso8601(window_meta.get("end_time"))

    warning_events = 0
    scale_down_events = 0
    events_response = ((k8s.get("events") or {}).get("response")) or {}
    for item in events_response.get("items") or []:
        if str(item.get("type", "")).lower() == "warning":
            try:
                warning_events += int(item.get("count") or 1)
            except (TypeError, ValueError):
                warning_events += 1
        if str(item.get("reason", "")) == "ScalingReplicaSet":
            message = str(item.get("message") or "")
            if " to 0" not in message:
                continue
            if service_name and service_name not in message.lower():
                continue
            event_time = _parse_iso8601(
                item.get("lastTimestamp")
                or item.get("eventTime")
                or item.get("firstTimestamp")
            )
            if event_time is None:
                continue
            # k8s event timestamps are second-precision. Treat the event as
            # occupying the 1-second interval [event_time, event_time + 1)
            # and only count it when that interval fits entirely inside the
            # window [win_start, win_end). This biases boundary events to
            # the LATER window, which is what we want -- a scale-down at
            # the boundary belongs to the active_fault window that follows
            # the pre_fault_baseline, not to the baseline itself.
            event_end = event_time + 1.0
            if win_start is not None and event_end <= win_start:
                continue
            if win_end is not None and event_end > win_end:
                continue
            scale_down_events += 1

    # Unavailable signal combines two evidence sources:
    #   replicas-based -- non-zero only when the snapshot is taken while
    #     the deployment is between desired and ready (rare in our
    #     scenarios because the scenario runner restores replicas before
    #     export), and
    #   event-based   -- ScalingReplicaSet "Scaled ... to 0" events
    #     attributable to this window's service within the window's
    #     time bounds. This is the dominant source for ScaleDeployment
    #     fault scenarios where the deployment is restored by the time we
    #     read its current state.
    unavailable = max(unavailable_from_replicas, scale_down_events)

    k8s_restart = 0
    pods_response = ((k8s.get("pods") or {}).get("response")) or {}
    for pod in pods_response.get("items") or []:
        status = pod.get("status") or {}
        for cs in status.get("containerStatuses") or []:
            try:
                k8s_restart += int(cs.get("restartCount") or 0)
            except (TypeError, ValueError):
                continue

    search_response = ((tempo.get("search") or {}).get("response")) or {}
    search_traces = search_response.get("traces") or []
    trace_count = len(search_traces) if isinstance(search_traces, list) else 0
    if trace_count == 0:
        traces_top = tempo.get("traces")
        if isinstance(traces_top, dict):
            trace_count = len(traces_top)
        elif isinstance(traces_top, list):
            trace_count = len(traces_top)

    span_total = 0
    span_errors = 0
    durations_ms: list[float] = []
    traces_top = tempo.get("traces") or {}
    trace_iter = traces_top.values() if isinstance(traces_top, dict) else traces_top
    for trace in trace_iter:
        if not isinstance(trace, dict):
            continue
        body = trace.get("response") or trace
        for batch in body.get("batches") or []:
            for scope in batch.get("scopeSpans") or []:
                for span in scope.get("spans") or []:
                    span_total += 1
                    if _span_is_error(span):
                        span_errors += 1
                    duration = _span_duration_ms(span)
                    if duration is not None:
                        durations_ms.append(duration)
    trace_error_rate = (span_errors / span_total) if span_total > 0 else 0.0
    p50 = _percentile(durations_ms, 50.0)
    p95 = _percentile(durations_ms, 95.0)

    return {
        "triage_feature_log_total_count": float(log_total),
        "triage_feature_log_error_count": float(log_error),
        "triage_feature_log_warning_count": float(log_warning),
        "triage_feature_trace_count": float(trace_count),
        "triage_feature_trace_span_count": float(span_total),
        "triage_feature_trace_error_count": float(span_errors),
        "triage_feature_trace_error_rate": float(trace_error_rate),
        "triage_feature_trace_latency_p50_ms": float(p50),
        "triage_feature_trace_latency_p95_ms": float(p95),
        "triage_feature_metric_cpu_pct": float(cpu_mean),
        "triage_feature_metric_memory_pct": float(mem_mean),
        "triage_feature_k8s_restart_count": float(max(prom_restart_delta, k8s_restart)),
        "triage_feature_k8s_pod_unavailable_count": float(unavailable),
        "triage_feature_alert_firing_count": float(alert_firing),
        "triage_feature_k8s_warning_event_count": float(warning_events),
    }


def numeric_features_for_window(
    window: dict[str, Any],
    episode: dict[str, Any] | None,
    run_dir: Path | None = None,
) -> dict[str, float]:
    """Compute production-safe numeric features for a telemetry window.

    Preferred path (real telemetry): when ``run_dir`` is provided and raw
    exports exist for the window id, read them and compute features.
    Fallback (legacy/early collection): pull counts from the window's
    in-record ``features`` block if present; otherwise return zeros.
    """
    window_id = str(window.get("telemetry_window_id", window.get("window_id", "")))
    if run_dir is not None and window_id:
        raw_features = numeric_features_from_raw(run_dir, window_id)
        if any(value != 0.0 for value in raw_features.values()):
            return raw_features

    features = window.get("features") or {}
    metrics = features.get("metrics") or {}
    logs = features.get("logs") or {}
    traces = features.get("traces") or {}
    kubernetes = features.get("kubernetes") or {}

    def f(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    result = _zero_features()
    result.update(
        {
            "triage_feature_log_error_count": f(logs.get("error_count")),
            "triage_feature_log_warning_count": f(logs.get("warning_count")),
            "triage_feature_log_total_count": f(logs.get("total_count")),
            "triage_feature_metric_cpu_pct": f(metrics.get("cpu_pct")),
            "triage_feature_metric_memory_pct": f(metrics.get("memory_pct")),
            "triage_feature_trace_count": f(traces.get("count")),
            "triage_feature_trace_error_count": f(traces.get("error_count")),
            "triage_feature_trace_latency_p95_ms": f(traces.get("latency_p95_ms")),
            "triage_feature_k8s_restart_count": f(kubernetes.get("restart_count")),
            "triage_feature_k8s_pod_unavailable_count": f(kubernetes.get("pod_unavailable_count")),
        }
    )
    return result