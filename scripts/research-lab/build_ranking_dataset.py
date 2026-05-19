#!/usr/bin/env python3
"""
Build a derived ranking dataset and deterministic baseline evaluation from a
validated research-lab run.

The raw dataset under data/runs/<run_id> is treated as immutable input. This
script writes derived artifacts under data/derived/<run_id>.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from build_cross_run_evaluation import (
    ABLATION_PROFILES,
    ablation_score,
    likely_failure_reason,
    metrics_from_ranks,
    rank_int,
    score_components,
    service_delta_summary,
)

SCRIPT_VERSION = "0.4.0"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}

LEAKY_LABEL_PREFIXES = (
    "dataset-",
    "scenario-",
    "synthetic-",
    "root-",
    "severity-",
)

TOKEN_RE = re.compile(r"[a-z0-9_]+")
HEX_ID_RE = re.compile(r"\b[a-f0-9]{16,64}\b", re.IGNORECASE)
DATASET_RUN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-[a-z0-9_.-]+\b", re.IGNORECASE)
WINDOW_ID_RE = re.compile(r"\b[\w.-]+-\d{8}T\d{6}Z-[\w.-]+\b", re.IGNORECASE)
ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
SCENARIO_SLUG_CONTEXT_RE = re.compile(r"\b(?:during|scenario)\s+[a-z0-9]+(?:-[a-z0-9]+){1,}\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


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


def write_csv(path: Path, records: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fields: list[str] = []
        seen: set[str] = set()
        for record in records:
            for key in record:
                if key not in seen:
                    fields.append(key)
                    seen.add(key)
        fieldnames = fields
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {key: csv_value(record.get(key)) for key in fieldnames}
            writer.writerow(row)


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def string_set(values: Iterable[Any]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def jaccard(left: Iterable[Any], right: Iterable[Any]) -> float:
    left_set = string_set(left)
    right_set = string_set(right)
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_tree(root: Path) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative_path = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        records.append(
            {
                "relative_path": relative_path,
                "bytes": path.stat().st_size,
                "sha256": file_hash,
            }
        )

    digest = hashlib.sha256()
    for record in records:
        digest.update(record["relative_path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
    return records, digest.hexdigest()


def clean_text(text: str) -> str:
    text = SCENARIO_SLUG_CONTEXT_RE.sub(" ", text)
    text = HEX_ID_RE.sub(" ", text)
    text = WINDOW_ID_RE.sub(" ", text)
    text = DATASET_RUN_RE.sub(" ", text)
    text = ISSUE_KEY_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    cleaned = clean_text(text.lower())
    return [token for token in TOKEN_RE.findall(cleaned) if token not in STOPWORDS and len(token) > 1]


def filtered_labels(labels: Iterable[Any]) -> list[str]:
    kept: list[str] = []
    for label in labels:
        value = str(label).strip()
        lower = value.lower()
        if not value:
            continue
        if any(lower.startswith(prefix) for prefix in LEAKY_LABEL_PREFIXES):
            continue
        if lower == "telemetry-linked":
            continue
        kept.append(value)
    return kept


def issue_query_text(issue: dict[str, Any]) -> str:
    metadata = issue.get("metadata", {})
    parts = [
        metadata.get("summary", ""),
        metadata.get("issue_type", ""),
        metadata.get("priority", ""),
        " ".join(listify(metadata.get("components"))),
        " ".join(filtered_labels(listify(metadata.get("labels")))),
    ]
    return clean_text(" ".join(str(part) for part in parts if part))


def priority_to_severity(priority: str | None) -> str | None:
    if not priority:
        return None
    value = priority.strip().lower()
    if value in {"blocker", "highest", "critical", "p0", "p1"}:
        return "critical"
    if value in {"major", "high", "p2"}:
        return "major"
    if value in {"minor", "medium", "p3"}:
        return "minor"
    if value in {"low", "lowest", "none", "p4"}:
        return "none"
    return value


def get_nested(record: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def int_feature(record: dict[str, Any], path: list[str]) -> int:
    value = get_nested(record, path, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def keyword_presence(text: str, terms: Iterable[str]) -> float:
    lowered = text.lower()
    return 1.0 if any(term.lower() in lowered for term in terms) else 0.0


def alert_presence(alert_names: Iterable[str], terms: Iterable[str]) -> float:
    compact_names = " ".join(normalized_name(name) for name in alert_names)
    return 1.0 if any(normalized_name(term) in compact_names for term in terms) else 0.0


def positive_delta_signal(active: int, baseline: int) -> float:
    delta = max(0, active - baseline)
    if delta <= 0:
        return 0.0
    return min(1.0, math.log10(1 + delta) / 2.0)


def service_window_delta_signal(issue_services: Iterable[Any], features: dict[str, Any]) -> float:
    counts = features.get("exact_log_entries_by_service_window_type", {})
    best = 0.0
    for service in issue_services:
        normalized_service = normalized_name(service)
        if not normalized_service:
            continue
        service_counts = counts.get(normalized_service, {})
        if not isinstance(service_counts, dict):
            continue
        active = int(service_counts.get("active_fault", 0) or 0)
        baseline = int(service_counts.get("pre_fault_baseline", 0) or 0)
        best = max(best, positive_delta_signal(active, baseline))
    return best


def parse_log_message(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return str(parsed.get("message") or parsed.get("msg") or text).strip()
    except json.JSONDecodeError:
        pass
    return text


def sample_loki_messages(path: Path, limit: int = 12) -> list[str]:
    if not path.exists() or limit <= 0:
        return []
    try:
        loki = read_json(path)
    except (OSError, json.JSONDecodeError):
        return []

    messages: list[str] = []
    seen: set[str] = set()
    for section_name in ("service_window", "service_context"):
        section = loki.get(section_name, {})
        result = get_nested(section, ["response", "data", "result"], [])
        for stream in listify(result):
            for value in listify(stream.get("values")):
                if not isinstance(value, list) or len(value) < 2:
                    continue
                message = clean_text(parse_log_message(str(value[1])))
                if not message or message in seen:
                    continue
                seen.add(message)
                messages.append(message[:240])
                if len(messages) >= limit:
                    return messages
    return messages


def sample_tempo_summaries(path: Path, limit: int = 20) -> list[str]:
    if not path.exists() or limit <= 0:
        return []
    try:
        tempo = read_json(path)
    except (OSError, json.JSONDecodeError):
        return []

    traces = get_nested(tempo, ["search", "response", "traces"], [])
    summaries: list[str] = []
    seen: set[str] = set()
    for trace in listify(traces):
        root_service = str(trace.get("rootServiceName") or "").strip()
        root_name = str(trace.get("rootTraceName") or "").strip()
        summary = clean_text(" ".join(part for part in (root_service, root_name) if part))
        if not summary or summary in seen:
            continue
        seen.add(summary)
        summaries.append(summary[:180])
        if len(summaries) >= limit:
            break
    return summaries


def alert_name_map(alerts: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for alert in alerts:
        fingerprint = str(alert.get("alert_fingerprint", "")).strip()
        name = str(alert.get("alert_name", "")).strip()
        if fingerprint and name:
            mapping[fingerprint] = name
    return mapping


def build_episode_features(
    run_root: Path,
    episodes: list[dict[str, Any]],
    windows_by_episode: dict[str, list[dict[str, Any]]],
    alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names_by_fingerprint = alert_name_map(alerts)
    alerts_by_episode: dict[str, set[str]] = defaultdict(set)
    for alert in alerts:
        episode_id = str(alert.get("incident_episode_id", "")).strip()
        fingerprint = str(alert.get("alert_fingerprint", "")).strip()
        if episode_id and fingerprint:
            alerts_by_episode[episode_id].add(fingerprint)

    features: list[dict[str, Any]] = []
    raw_loki_root = run_root / "raw" / "loki"
    raw_tempo_root = run_root / "raw" / "tempo"
    for episode in episodes:
        episode_id = str(episode["incident_episode_id"])
        windows = windows_by_episode.get(episode_id, [])
        services = listify(episode.get("affected_services"))
        raw_services = sorted({str(window.get("service_name")) for window in windows if window.get("service_name")})
        alert_fingerprints = set(map(str, listify(episode.get("alert_fingerprints")))) | alerts_by_episode[episode_id]
        alert_names = sorted({names_by_fingerprint.get(fp, fp) for fp in alert_fingerprints if fp})

        exact_by_window_type: Counter[str] = Counter()
        trace_by_window_type: Counter[str] = Counter()
        historical_alerts_by_window_type: Counter[str] = Counter()
        k8s_restart_events_by_window_type: Counter[str] = Counter()
        k8s_restart_counters_by_window_type: Counter[str] = Counter()
        k8s_rollout_unavailable_by_window_type: Counter[str] = Counter()
        exact_by_service_window_type: dict[str, Counter[str]] = defaultdict(Counter)
        for window in windows:
            window_type = str(get_nested(window, ["labels", "window_type"], "unknown") or "unknown")
            service_name = normalized_name(window.get("service_name", ""))
            exact_count = int_feature(window, ["features", "logs", "entry_count"])
            trace_count = int_feature(window, ["features", "traces", "trace_count"])
            historical_alert_count = int_feature(window, ["features", "metrics", "historical_alert_event_count"])
            k8s_restart_events = int_feature(window, ["features", "kubernetes", "restart_event_count"])
            k8s_restart_counters = int_feature(window, ["features", "kubernetes", "container_restart_total"])
            desired_replicas = int_feature(window, ["features", "kubernetes", "deployment_desired_replicas"])
            available_replicas = int_feature(window, ["features", "kubernetes", "deployment_available_replicas"])
            exact_by_window_type[window_type] += exact_count
            trace_by_window_type[window_type] += trace_count
            historical_alerts_by_window_type[window_type] += historical_alert_count
            k8s_restart_events_by_window_type[window_type] += k8s_restart_events
            k8s_restart_counters_by_window_type[window_type] += k8s_restart_counters
            if desired_replicas > available_replicas:
                k8s_rollout_unavailable_by_window_type[window_type] += desired_replicas - available_replicas
            if service_name:
                exact_by_service_window_type[service_name][window_type] += exact_count

        exact_log_entries = sum(exact_by_window_type.values())
        service_context_log_entries = sum(int_feature(window, ["features", "logs", "context_entry_count"]) for window in windows)
        namespace_context_log_entries = sum(
            int_feature(window, ["features", "logs", "namespace_context_entry_count"]) for window in windows
        )
        historical_alert_event_count = sum(historical_alerts_by_window_type.values())
        trace_ids = sorted({str(trace_id) for window in windows for trace_id in listify(window.get("trace_ids"))})
        log_messages: list[str] = []
        seen_messages: set[str] = set()
        trace_summaries: list[str] = []
        seen_trace_summaries: set[str] = set()
        for window in windows:
            window_id = str(window.get("telemetry_window_id", ""))
            for message in sample_loki_messages(raw_loki_root / f"{window_id}.json", limit=6):
                if message not in seen_messages:
                    seen_messages.add(message)
                    log_messages.append(message)
                if len(log_messages) >= 40:
                    break
            if len(log_messages) >= 40:
                break
        for window in windows:
            window_id = str(window.get("telemetry_window_id", ""))
            for summary in sample_tempo_summaries(raw_tempo_root / f"{window_id}.json", limit=8):
                if summary not in seen_trace_summaries:
                    seen_trace_summaries.add(summary)
                    trace_summaries.append(summary)
                if len(trace_summaries) >= 40:
                    break
            if len(trace_summaries) >= 40:
                break

        labels = episode.get("labels", {})
        ground_truth = episode.get("ground_truth", {})
        title = labels.get("title", "")
        evidence_parts = [
            title,
            episode.get("severity", ""),
            episode.get("incident_type", ""),
            episode.get("root_cause_category", ""),
            ground_truth.get("fault_type", ""),
            ground_truth.get("expected_user_impact", ""),
            ground_truth.get("expected_error_rate", ""),
            ground_truth.get("expected_latency_impact", ""),
            " ".join(str(service) for service in services),
            " ".join(alert_names),
            " ".join(log_messages),
        ]
        evidence_text = clean_text(" ".join(str(part) for part in evidence_parts if part))
        raw_evidence_parts = [
            " ".join(str(service) for service in raw_services),
            " ".join(alert_names),
            " ".join(log_messages),
            " ".join(trace_summaries),
        ]
        raw_evidence_text = clean_text(" ".join(str(part) for part in raw_evidence_parts if part))
        log_text = " ".join(log_messages)
        trace_text = " ".join(trace_summaries)
        restart_signal = max(
            0.5 * alert_presence(alert_names, ["KubeDeploymentReplicasMismatch"]),
            keyword_presence(
                log_text,
                [
                    "restarted",
                    "restart",
                    "created container",
                    "started container",
                    "deleted pod",
                    "pod was restarted",
                ],
            ),
        )
        outage_alert_signal = alert_presence(alert_names, ["KubePodNotReady", "KubeContainerWaiting"])
        outage_log_signal = keyword_presence(
            log_text,
            [
                "redisconnectionexception",
                "connecttimeout",
                "connection refused",
                "not possible to connect",
                "rediscartstore",
                "rediscache.getasync",
                "stackexchangeredis",
                "upstream connect error",
                "service unavailable",
                "exception stack trace",
            ],
        )
        outage_signal = max(outage_log_signal, 0.5 * outage_alert_signal)
        traffic_pressure_signal = alert_presence(
            alert_names,
            ["CPUThrottlingHigh", "OnlineBoutiqueNearMissResourcePressure"],
        )
        latency_signal = keyword_presence(
            f"{log_text} {trace_text}",
            ["extra latency", "latency enabled", "duration: 750ms", "duration:750ms"],
        )
        active_exact = exact_by_window_type.get("active_fault", 0)
        pre_fault_exact = exact_by_window_type.get("pre_fault_baseline", 0)
        recovery_exact = exact_by_window_type.get("recovery_window", 0)
        active_alerts = historical_alerts_by_window_type.get("active_fault", 0)
        pre_fault_alerts = historical_alerts_by_window_type.get("pre_fault_baseline", 0)
        active_restart_events = k8s_restart_events_by_window_type.get("active_fault", 0)
        pre_fault_restart_events = k8s_restart_events_by_window_type.get("pre_fault_baseline", 0)
        active_restart_counters = k8s_restart_counters_by_window_type.get("active_fault", 0)
        pre_fault_restart_counters = k8s_restart_counters_by_window_type.get("pre_fault_baseline", 0)
        active_rollout_unavailable = k8s_rollout_unavailable_by_window_type.get("active_fault", 0)
        recovery_rollout_unavailable = k8s_rollout_unavailable_by_window_type.get("recovery_window", 0)
        restart_event_signal = max(
            positive_delta_signal(active_restart_events, pre_fault_restart_events),
            positive_delta_signal(active_restart_counters, pre_fault_restart_counters),
        )
        rollout_unavailable_signal = min(1.0, math.log10(1 + active_rollout_unavailable) / 1.5) if active_rollout_unavailable > 0 else 0.0
        service_local_delta_signal = 0.0
        for service_counts in exact_by_service_window_type.values():
            service_local_delta_signal = max(
                service_local_delta_signal,
                positive_delta_signal(int(service_counts.get("active_fault", 0) or 0), int(service_counts.get("pre_fault_baseline", 0) or 0)),
            )
        if active_exact > pre_fault_exact:
            active_delta = max(1, active_exact - pre_fault_exact)
            recovery_gap = max(0, recovery_exact - pre_fault_exact)
            recovery_complete_signal = round(max(0.0, min(1.0, 1.0 - (recovery_gap / active_delta))), 6)
        else:
            recovery_complete_signal = 0.0

        features.append(
            {
                "dataset_run_id": episode.get("dataset_run_id"),
                "incident_episode_id": episode_id,
                "scenario_id": episode.get("scenario_id"),
                "jira_candidate": bool(episode.get("jira_candidate")),
                "severity": episode.get("severity"),
                "incident_type": episode.get("incident_type"),
                "root_cause_category": episode.get("root_cause_category"),
                "affected_services": services,
                "raw_services": raw_services,
                "window_count": len(windows),
                "alert_fingerprint_count": len(alert_fingerprints),
                "alert_names": alert_names,
                "trace_count": len(trace_ids),
                "exact_log_entries": exact_log_entries,
                "exact_log_entries_by_window_type": dict(sorted(exact_by_window_type.items())),
                "trace_count_by_window_type": dict(sorted(trace_by_window_type.items())),
                "historical_alert_events_by_window_type": dict(sorted(historical_alerts_by_window_type.items())),
                "kubernetes_restart_events_by_window_type": dict(sorted(k8s_restart_events_by_window_type.items())),
                "kubernetes_restart_counters_by_window_type": dict(sorted(k8s_restart_counters_by_window_type.items())),
                "kubernetes_rollout_unavailable_by_window_type": dict(sorted(k8s_rollout_unavailable_by_window_type.items())),
                "exact_log_entries_by_service_window_type": {
                    service_name: dict(sorted(counter.items()))
                    for service_name, counter in sorted(exact_by_service_window_type.items())
                },
                "active_fault_exact_log_entries": active_exact,
                "pre_fault_baseline_exact_log_entries": pre_fault_exact,
                "recovery_window_exact_log_entries": recovery_exact,
                "active_fault_historical_alert_event_count": active_alerts,
                "pre_fault_baseline_historical_alert_event_count": pre_fault_alerts,
                "active_to_pre_exact_log_delta_signal": round(positive_delta_signal(active_exact, pre_fault_exact), 6),
                "active_to_pre_alert_delta_signal": round(positive_delta_signal(active_alerts, pre_fault_alerts), 6),
                "raw_restart_event_signal": round(restart_event_signal, 6),
                "raw_rollout_unavailable_signal": round(rollout_unavailable_signal, 6),
                "raw_recovery_complete_signal": recovery_complete_signal,
                "raw_recovery_incomplete_signal": round(1.0 - recovery_complete_signal if active_exact > pre_fault_exact else 0.0, 6),
                "raw_service_local_delta_signal": round(service_local_delta_signal, 6),
                "raw_restart_signal": round(max(restart_signal, restart_event_signal), 6),
                "raw_outage_signal": round(max(outage_signal, rollout_unavailable_signal), 6),
                "raw_traffic_pressure_signal": round(traffic_pressure_signal, 6),
                "raw_latency_signal": round(latency_signal, 6),
                "service_context_log_entries": service_context_log_entries,
                "namespace_context_log_entries": namespace_context_log_entries,
                "historical_alert_event_count": historical_alert_event_count,
                "sample_log_messages": log_messages,
                "trace_summaries": trace_summaries,
                "evidence_text": evidence_text,
                "raw_evidence_text": raw_evidence_text,
            }
        )
    return features


def bm25_scores(documents: dict[str, list[str]], query_tokens: list[str]) -> dict[str, float]:
    if not documents:
        return {}
    doc_count = len(documents)
    avgdl = sum(len(tokens) for tokens in documents.values()) / max(1, doc_count)
    document_frequency: Counter[str] = Counter()
    for tokens in documents.values():
        document_frequency.update(set(tokens))

    k1 = 1.5
    b = 0.75
    scores: dict[str, float] = {}
    query_counts = Counter(query_tokens)
    for document_id, tokens in documents.items():
        token_counts = Counter(tokens)
        document_length = max(1, len(tokens))
        score = 0.0
        for token, query_weight in query_counts.items():
            if token not in token_counts:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
            tf = token_counts[token]
            denominator = tf + k1 * (1 - b + b * document_length / max(avgdl, 1))
            score += query_weight * idf * ((tf * (k1 + 1)) / denominator)
        scores[document_id] = score
    return scores


def ndcg_for_single_positive(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def calculate_profile_metrics(
    issues: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    rank_field: str,
) -> dict[str, Any]:
    ranks_by_issue: dict[str, int | None] = {}
    for issue in issues:
        issue_key = str(issue.get("jira_issue_key", ""))
        positives = [
            int(example[rank_field])
            for example in examples
            if example["jira_issue_key"] == issue_key and int(example["label"]) == 1
        ]
        ranks_by_issue[issue_key] = min(positives) if positives else None

    metrics = metrics_from_ranks(
        ranks_by_query=ranks_by_issue,
        example_count=len(examples),
        positive_example_count=sum(int(example["label"]) for example in examples),
    )
    metrics["candidate_episode_count"] = len(episodes)
    metrics["true_rank_by_issue"] = metrics.pop("true_rank_by_query")
    return metrics


def ranked_rows_for_profile(
    examples: list[dict[str, Any]],
    score_field: str,
    text_score_field: str,
    rank_field: str,
    profile_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["jira_issue_key"])].append(example)

    for issue_key, issue_examples in grouped.items():
        issue_examples.sort(
            key=lambda item: (
                -float(item[score_field]),
                -float(item[text_score_field]),
                str(item["candidate_episode_id"]),
            )
        )
        for rank, example in enumerate(issue_examples, start=1):
            example[rank_field] = rank
            if profile_name == "label_aware_baseline":
                example["rank"] = rank
            rows.append(
                {
                    "profile": profile_name,
                    "jira_issue_key": issue_key,
                    "rank": rank,
                    "candidate_episode_id": example["candidate_episode_id"],
                    "candidate_scenario_id": example["candidate_scenario_id"],
                    "label": example["label"],
                    "score": example[score_field],
                    "text_score": example[text_score_field],
                    "service_overlap": example["service_overlap"],
                    "severity_match": example["severity_match"],
                    "raw_service_overlap": example["raw_telemetry_service_overlap"],
                    "raw_query_service_delta_signal": example.get("raw_telemetry_query_service_delta_signal", 0.0),
                    "raw_restart_signal": example.get("raw_telemetry_restart_signal", 0.0),
                    "raw_outage_signal": example.get("raw_telemetry_outage_signal", 0.0),
                    "raw_traffic_pressure_signal": example.get("raw_telemetry_traffic_pressure_signal", 0.0),
                    "raw_restart_event_signal": example.get("raw_telemetry_restart_event_signal", 0.0),
                    "raw_rollout_unavailable_signal": example.get("raw_telemetry_rollout_unavailable_signal", 0.0),
                    "raw_recovery_complete_signal": example.get("raw_telemetry_recovery_complete_signal", 0.0),
                    "raw_recovery_incomplete_signal": example.get("raw_telemetry_recovery_incomplete_signal", 0.0),
                    "raw_service_local_delta_signal": example.get("raw_telemetry_service_local_delta_signal", 0.0),
                    "raw_shape_alignment": example.get("raw_telemetry_shape_alignment", 0.0),
                    "raw_confusion_penalty": example.get("raw_telemetry_confusion_penalty", 0.0),
                }
            )
    return rows


def build_ranking_examples(
    issues: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    episode_features: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    feature_by_episode = {record["incident_episode_id"]: record for record in episode_features}
    label_aware_documents = {
        episode_id: tokenize(features.get("evidence_text", ""))
        for episode_id, features in feature_by_episode.items()
    }
    raw_documents = {
        episode_id: tokenize(features.get("raw_evidence_text", ""))
        for episode_id, features in feature_by_episode.items()
    }

    examples: list[dict[str, Any]] = []

    for issue in issues:
        metadata = issue.get("metadata", {})
        issue_key = str(issue.get("jira_issue_key", ""))
        true_episode_id = str(issue.get("incident_episode_id", ""))
        query_text = issue_query_text(issue)
        query_tokens = tokenize(query_text)
        label_aware_bm25 = bm25_scores(label_aware_documents, query_tokens)
        raw_telemetry_bm25 = bm25_scores(raw_documents, query_tokens)
        max_label_aware_bm25 = max(label_aware_bm25.values()) if label_aware_bm25 else 0.0
        max_raw_telemetry_bm25 = max(raw_telemetry_bm25.values()) if raw_telemetry_bm25 else 0.0
        issue_services = listify(metadata.get("components"))
        issue_severity = priority_to_severity(str(metadata.get("priority", "")))
        issue_alerts = set(map(str, listify(get_nested(issue, ["telemetry_links", "alert_fingerprints"], []))))
        issue_traces = set(map(str, listify(get_nested(issue, ["telemetry_links", "trace_ids"], []))))
        query_token_set = set(query_tokens)
        query_outage_intent = 1.0 if {"outage", "critical", "blocker"} & query_token_set else 0.0
        query_degradation_intent = 1.0 if {"degradation", "major", "latency", "slow"} & query_token_set else 0.0
        query_specific_dependency = 1.0 if any(
            normalized_name(service) not in {"", "frontend", "checkoutservice"} for service in issue_services
        ) else 0.0

        for episode in episodes:
            episode_id = str(episode["incident_episode_id"])
            features = feature_by_episode[episode_id]
            episode_alerts = set(map(str, listify(episode.get("alert_fingerprints"))))
            episode_traces = set(map(str, listify(episode.get("trace_ids"))))
            bm25_raw = label_aware_bm25.get(episode_id, 0.0)
            text_score = bm25_raw / max_label_aware_bm25 if max_label_aware_bm25 > 0 else 0.0
            service_overlap = jaccard(issue_services, episode.get("affected_services", []))
            severity_match = 1.0 if issue_severity and issue_severity == str(episode.get("severity", "")).lower() else 0.0
            incident_term_match = 1.0 if str(episode.get("incident_type", "")).lower() in set(query_tokens) else 0.0
            telemetry_strength = min(1.0, math.log10(1 + features["exact_log_entries"] + features["trace_count"]) / 4.0)
            baseline_score = (
                0.55 * text_score
                + 0.30 * service_overlap
                + 0.10 * severity_match
                + 0.03 * incident_term_match
                + 0.02 * telemetry_strength
            )
            raw_bm25 = raw_telemetry_bm25.get(episode_id, 0.0)
            raw_text_score = raw_bm25 / max_raw_telemetry_bm25 if max_raw_telemetry_bm25 > 0 else 0.0
            raw_service_overlap = jaccard(issue_services, features.get("raw_services", []))
            raw_alert_signal = min(
                1.0,
                math.log10(1 + features["alert_fingerprint_count"] + features["historical_alert_event_count"]) / 2.0,
            )
            raw_log_signal = min(1.0, math.log10(1 + features["exact_log_entries"]) / 4.0)
            raw_trace_signal = min(1.0, math.log10(1 + features["trace_count"]) / 3.0)
            raw_activity_signal = min(
                1.0,
                math.log10(
                    1
                    + features["exact_log_entries"]
                    + (features["trace_count"] * 10)
                    + (features["historical_alert_event_count"] * 50)
                )
                / 5.0,
            )
            raw_query_service_delta_signal = service_window_delta_signal(issue_services, features)
            raw_restart_signal = float(features.get("raw_restart_signal", 0.0) or 0.0)
            raw_outage_signal = float(features.get("raw_outage_signal", 0.0) or 0.0)
            raw_traffic_pressure_signal = float(features.get("raw_traffic_pressure_signal", 0.0) or 0.0)
            raw_latency_signal = float(features.get("raw_latency_signal", 0.0) or 0.0)
            if query_outage_intent:
                raw_shape_alignment = max(raw_outage_signal, 0.4 * raw_query_service_delta_signal)
            elif query_degradation_intent:
                raw_shape_alignment = max(
                    raw_query_service_delta_signal,
                    raw_restart_signal,
                    raw_latency_signal * raw_query_service_delta_signal,
                )
            else:
                raw_shape_alignment = raw_query_service_delta_signal
            raw_traffic_pressure_penalty = (
                raw_traffic_pressure_signal
                * query_specific_dependency
                * max(0.0, 1.0 - query_outage_intent)
                * max(0.0, 1.0 - raw_query_service_delta_signal)
            )
            raw_outage_vs_degradation_penalty = (
                raw_outage_signal
                * query_degradation_intent
                * max(0.0, 1.0 - query_outage_intent)
                * max(0.0, 1.0 - raw_restart_signal)
                * max(0.0, 1.0 - raw_query_service_delta_signal)
            )
            raw_confusion_penalty = max(raw_traffic_pressure_penalty, raw_outage_vs_degradation_penalty)
            raw_telemetry_score = (
                0.34 * raw_text_score
                + 0.26 * raw_service_overlap
                + 0.12 * raw_activity_signal
                + 0.04 * raw_alert_signal
                + 0.02 * raw_log_signal
                + 0.01 * raw_trace_signal
                + 0.16 * raw_shape_alignment
                + 0.05 * raw_query_service_delta_signal
                - 0.10 * raw_confusion_penalty
            )
            label = 1 if episode_id == true_episode_id else 0
            example = {
                "dataset_run_id": issue.get("dataset_run_id"),
                "jira_issue_key": issue_key,
                "jira_shadow_issue_id": issue.get("jira_shadow_issue_id"),
                "query_text": query_text,
                "candidate_episode_id": episode_id,
                "candidate_scenario_id": episode.get("scenario_id"),
                "candidate_severity": episode.get("severity"),
                "candidate_incident_type": episode.get("incident_type"),
                "candidate_root_cause_category": episode.get("root_cause_category"),
                "candidate_services": episode.get("affected_services", []),
                "label": label,
                "bm25_raw": round(bm25_raw, 6),
                "text_score": round(text_score, 6),
                "service_overlap": round(service_overlap, 6),
                "severity_match": severity_match,
                "incident_term_match": incident_term_match,
                "telemetry_strength": round(telemetry_strength, 6),
                "baseline_score": round(baseline_score, 6),
                "raw_telemetry_bm25_raw": round(raw_bm25, 6),
                "raw_telemetry_text_score": round(raw_text_score, 6),
                "raw_telemetry_service_overlap": round(raw_service_overlap, 6),
                "raw_telemetry_activity_signal": round(raw_activity_signal, 6),
                "raw_telemetry_alert_signal": round(raw_alert_signal, 6),
                "raw_telemetry_log_signal": round(raw_log_signal, 6),
                "raw_telemetry_trace_signal": round(raw_trace_signal, 6),
                "raw_telemetry_query_service_delta_signal": round(raw_query_service_delta_signal, 6),
                "raw_telemetry_restart_signal": round(raw_restart_signal, 6),
                "raw_telemetry_outage_signal": round(raw_outage_signal, 6),
                "raw_telemetry_traffic_pressure_signal": round(raw_traffic_pressure_signal, 6),
                "raw_telemetry_latency_signal": round(raw_latency_signal, 6),
                "raw_telemetry_restart_event_signal": round(float(features.get("raw_restart_event_signal", 0.0) or 0.0), 6),
                "raw_telemetry_rollout_unavailable_signal": round(float(features.get("raw_rollout_unavailable_signal", 0.0) or 0.0), 6),
                "raw_telemetry_recovery_complete_signal": round(float(features.get("raw_recovery_complete_signal", 0.0) or 0.0), 6),
                "raw_telemetry_recovery_incomplete_signal": round(float(features.get("raw_recovery_incomplete_signal", 0.0) or 0.0), 6),
                "raw_telemetry_service_local_delta_signal": round(float(features.get("raw_service_local_delta_signal", 0.0) or 0.0), 6),
                "raw_telemetry_shape_alignment": round(raw_shape_alignment, 6),
                "raw_telemetry_confusion_penalty": round(raw_confusion_penalty, 6),
                "raw_telemetry_score": round(raw_telemetry_score, 6),
                "provenance_alert_overlap_count": len(issue_alerts & episode_alerts),
                "provenance_trace_overlap_count": len(issue_traces & episode_traces),
                "window_count": features["window_count"],
                "alert_fingerprint_count": features["alert_fingerprint_count"],
                "trace_count": features["trace_count"],
                "exact_log_entries": features["exact_log_entries"],
                "service_context_log_entries": features["service_context_log_entries"],
                "namespace_context_log_entries": features["namespace_context_log_entries"],
                "scoring_policy": "label_aware_baseline_v0_and_raw_telemetry_v1",
            }
            examples.append(example)

    rankings_by_profile = {
        "label_aware_baseline": ranked_rows_for_profile(
            examples,
            score_field="baseline_score",
            text_score_field="text_score",
            rank_field="rank",
            profile_name="label_aware_baseline",
        ),
        "raw_telemetry": ranked_rows_for_profile(
            examples,
            score_field="raw_telemetry_score",
            text_score_field="raw_telemetry_text_score",
            rank_field="raw_telemetry_rank",
            profile_name="raw_telemetry",
        ),
    }
    metrics_by_profile = {
        "label_aware_baseline": calculate_profile_metrics(issues, episodes, examples, "rank"),
        "raw_telemetry": calculate_profile_metrics(issues, episodes, examples, "raw_telemetry_rank"),
    }
    return examples, metrics_by_profile, rankings_by_profile


def build_ablation_reports(examples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["jira_issue_key"])].append(example)

    metric_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    positive_count = sum(int(example.get("label", 0)) for example in examples)
    for profile_name, profile in ABLATION_PROFILES.items():
        ranks_by_issue: dict[str, int | None] = {}
        for issue_key, issue_examples in grouped.items():
            ranked = sorted(
                issue_examples,
                key=lambda item: (
                    -ablation_score(item, profile_name),
                    str(item.get("candidate_episode_id")),
                ),
            )
            true_rank: int | None = None
            for rank, example in enumerate(ranked, start=1):
                if int(example.get("label", 0)) == 1 and true_rank is None:
                    true_rank = rank
                candidate_rows.append(
                    {
                        "ablation_profile": profile_name,
                        "dataset_run_id": example.get("dataset_run_id"),
                        "jira_issue_key": issue_key,
                        "rank": rank,
                        "candidate_episode_id": example.get("candidate_episode_id"),
                        "candidate_scenario_id": example.get("candidate_scenario_id"),
                        "label": int(example.get("label", 0)),
                        "score": round(ablation_score(example, profile_name), 6),
                    }
                )
            ranks_by_issue[issue_key] = true_rank

        metrics = metrics_from_ranks(
            ranks_by_query=ranks_by_issue,
            example_count=len(examples),
            positive_example_count=positive_count,
        )
        metric_rows.append(
            {
                "ablation_profile": profile_name,
                "description": profile["description"],
                "uses_candidate_labels": profile["uses_candidate_labels"],
                **{key: value for key, value in metrics.items() if key != "true_rank_by_query"},
            }
        )

    candidate_rows.sort(
        key=lambda row: (
            str(row["ablation_profile"]),
            str(row["jira_issue_key"]),
            int(row["rank"] or 999999),
        )
    )
    return metric_rows, candidate_rows


def build_raw_failure_analysis(
    examples: list[dict[str, Any]],
    episode_features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    feature_by_episode = {
        str(record.get("incident_episode_id")): record
        for record in episode_features
        if record.get("incident_episode_id")
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["jira_issue_key"])].append(example)

    rows: list[dict[str, Any]] = []
    for issue_key, issue_examples in sorted(grouped.items()):
        positives = [example for example in issue_examples if int(example.get("label", 0)) == 1]
        true_example = min(positives, key=lambda item: rank_int(item.get("raw_telemetry_rank")) or 999999) if positives else None
        true_rank = rank_int(true_example.get("raw_telemetry_rank")) if true_example else None
        if true_rank is not None and true_rank <= 1:
            continue

        ranked = sorted(issue_examples, key=lambda item: rank_int(item.get("raw_telemetry_rank")) or 999999)
        rank1_example = ranked[0] if ranked else None
        true_features = feature_by_episode.get(str(true_example.get("candidate_episode_id"))) if true_example else {}
        rank1_features = feature_by_episode.get(str(rank1_example.get("candidate_episode_id"))) if rank1_example else {}
        rows.append(
            {
                "query_id": issue_key,
                "dataset_run_id": (true_example or rank1_example or {}).get("dataset_run_id"),
                "jira_issue_key": issue_key,
                "true_candidate_episode_id": true_example.get("candidate_episode_id") if true_example else None,
                "true_candidate_scenario_id": true_example.get("candidate_scenario_id") if true_example else None,
                "true_rank": true_rank,
                "rank1_candidate_episode_id": rank1_example.get("candidate_episode_id") if rank1_example else None,
                "rank1_candidate_scenario_id": rank1_example.get("candidate_scenario_id") if rank1_example else None,
                "rank1_label": int(rank1_example.get("label", 0)) if rank1_example else None,
                "true_score_components": score_components(true_example),
                "rank1_score_components": score_components(rank1_example),
                "true_alert_names": true_features.get("alert_names", []) if true_features else [],
                "rank1_alert_names": rank1_features.get("alert_names", []) if rank1_features else [],
                "true_sampled_logs": list(true_features.get("sample_log_messages", []))[:8] if true_features else [],
                "rank1_sampled_logs": list(rank1_features.get("sample_log_messages", []))[:8] if rank1_features else [],
                "true_service_deltas": service_delta_summary(true_features or {}),
                "rank1_service_deltas": service_delta_summary(rank1_features or {}),
                "likely_failure_reason": likely_failure_reason(true_example, rank1_example),
            }
        )
    return rows


def flatten_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        rows.append(
            {
                "dataset_run_id": episode.get("dataset_run_id"),
                "incident_episode_id": episode.get("incident_episode_id"),
                "scenario_id": episode.get("scenario_id"),
                "fault_id": episode.get("fault_id"),
                "start_time": episode.get("start_time"),
                "end_time": episode.get("end_time"),
                "affected_services": listify(episode.get("affected_services")),
                "severity": episode.get("severity"),
                "incident_type": episode.get("incident_type"),
                "root_cause_category": episode.get("root_cause_category"),
                "jira_candidate": episode.get("jira_candidate"),
                "jira_issue_key": episode.get("jira_issue_key"),
                "window_count": len(listify(episode.get("telemetry_window_ids"))),
                "alert_count": len(listify(episode.get("alert_fingerprints"))),
                "trace_count": len(listify(episode.get("trace_ids"))),
            }
        )
    return rows


def flatten_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        rows.append(
            {
                "dataset_run_id": window.get("dataset_run_id"),
                "telemetry_window_id": window.get("telemetry_window_id"),
                "incident_episode_id": window.get("incident_episode_id"),
                "scenario_id": window.get("scenario_id"),
                "service_name": window.get("service_name"),
                "window_type": get_nested(window, ["labels", "window_type"]),
                "severity": get_nested(window, ["labels", "severity"]),
                "incident_type": get_nested(window, ["labels", "incident_type"]),
                "root_cause_category": get_nested(window, ["labels", "root_cause_category"]),
                "start_time": window.get("start_time"),
                "end_time": window.get("end_time"),
                "exact_log_entries": int_feature(window, ["features", "logs", "entry_count"]),
                "service_context_log_entries": int_feature(window, ["features", "logs", "context_entry_count"]),
                "namespace_context_log_entries": int_feature(window, ["features", "logs", "namespace_context_entry_count"]),
                "trace_count": int_feature(window, ["features", "traces", "trace_count"]),
                "historical_alert_event_count": int_feature(window, ["features", "metrics", "historical_alert_event_count"]),
            }
        )
    return rows


def flatten_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in issues:
        metadata = issue.get("metadata", {})
        rows.append(
            {
                "dataset_run_id": issue.get("dataset_run_id"),
                "jira_issue_key": issue.get("jira_issue_key"),
                "jira_shadow_issue_id": issue.get("jira_shadow_issue_id"),
                "incident_episode_id": issue.get("incident_episode_id"),
                "summary": metadata.get("summary"),
                "issue_type": metadata.get("issue_type"),
                "status": metadata.get("status"),
                "priority": metadata.get("priority"),
                "components": listify(metadata.get("components")),
                "labels": listify(metadata.get("labels")),
                "created_at": metadata.get("created_at"),
                "resolved_at": metadata.get("resolved_at"),
                "linked_window_count": len(listify(get_nested(issue, ["telemetry_links", "telemetry_window_ids"]))),
                "linked_alert_count": len(listify(get_nested(issue, ["telemetry_links", "alert_fingerprints"]))),
                "linked_trace_count": len(listify(get_nested(issue, ["telemetry_links", "trace_ids"]))),
                "query_text": issue_query_text(issue),
            }
        )
    return rows


def write_report(
    path: Path,
    run_id: str,
    freeze_manifest: dict[str, Any],
    metrics_by_profile: dict[str, dict[str, Any]],
    rankings_by_profile: dict[str, list[dict[str, Any]]],
    ablation_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> None:
    label_metrics = metrics_by_profile["label_aware_baseline"]
    raw_metrics = metrics_by_profile["raw_telemetry"]
    lines: list[str] = []
    lines.append(f"# Baseline Ranking Report {run_id}")
    lines.append("")
    lines.append(f"- Generated at: {freeze_manifest['derived_generated_at']}")
    lines.append(f"- Builder version: {SCRIPT_VERSION}")
    lines.append(f"- Raw file count: {freeze_manifest['raw_file_count']}")
    lines.append(f"- Raw byte count: {freeze_manifest['raw_total_bytes']}")
    lines.append(f"- Raw tree SHA256: `{freeze_manifest['raw_tree_sha256']}`")
    lines.append(f"- Query issues: {label_metrics['query_count']}")
    lines.append(f"- Candidate episodes: {label_metrics['candidate_episode_count']}")
    lines.append(f"- Ranking examples: {label_metrics['example_count']}")
    lines.append(f"- Positive examples: {label_metrics['positive_example_count']}")
    lines.append(f"- Negative examples: {label_metrics['negative_example_count']}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Profile | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(
        f"| label_aware_baseline | {label_metrics['mrr']} | {label_metrics['recall_at_1']} | {label_metrics['recall_at_3']} | {label_metrics['f1_at_1']} | {label_metrics['f1_at_3']} | {label_metrics['ndcg_at_3']} |"
    )
    lines.append(
        f"| raw_telemetry | {raw_metrics['mrr']} | {raw_metrics['recall_at_1']} | {raw_metrics['recall_at_3']} | {raw_metrics['f1_at_1']} | {raw_metrics['f1_at_3']} | {raw_metrics['ndcg_at_3']} |"
    )
    lines.append("")
    lines.append("F1@k is computed per Jira query with one relevant episode. A top-k hit has Precision@k = 1/k and Recall@k = 1, then the per-query harmonic mean is averaged across queries.")
    lines.append("")
    lines.append("`label_aware_baseline` is a sanity-check profile that can use lab labels. `raw_telemetry` is the stricter production-facing profile; it does not score candidate severity, incident type, root-cause category, scenario title, fault type, or expected-impact labels.")
    lines.append("")
    lines.append("## Ablation Metrics")
    lines.append("")
    lines.append("| Ablation | Uses candidate labels | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in ablation_rows:
        lines.append(
            f"| {row['ablation_profile']} | {row['uses_candidate_labels']} | {row['mrr']} | {row['recall_at_1']} | {row['recall_at_3']} | {row['f1_at_1']} | {row['f1_at_3']} | {row['ndcg_at_3']} |"
        )
    lines.append("")
    lines.append("## Raw Telemetry Failure Analysis")
    lines.append("")
    if failure_rows:
        lines.append("| Jira issue | True rank | True scenario | Rank-1 scenario | Likely reason |")
        lines.append("| --- | ---: | --- | --- | --- |")
        for row in failure_rows:
            lines.append(
                f"| {row['jira_issue_key']} | {row['true_rank']} | {row['true_candidate_scenario_id']} | {row['rank1_candidate_scenario_id']} | {row['likely_failure_reason']} |"
            )
    else:
        lines.append("No raw telemetry top-1 misses were found.")
    lines.append("")
    lines.append("## Label-Aware Top Rankings")
    lines.append("")
    lines.append("| Jira issue | Rank | Candidate scenario | Label | Score | Text | Service | Severity |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in rankings_by_profile["label_aware_baseline"]:
        if int(row["rank"]) > 5:
            continue
        lines.append(
            "| {jira_issue_key} | {rank} | {candidate_scenario_id} | {label} | {score} | {text_score} | {service_overlap} | {severity_match} |".format(
                **row
            )
        )
    lines.append("")
    lines.append("## Raw Telemetry Top Rankings")
    lines.append("")
    lines.append("| Jira issue | Rank | Candidate scenario | Label | Score | Text | Service | Shape | Delta | Penalty |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rankings_by_profile["raw_telemetry"]:
        if int(row["rank"]) > 5:
            continue
        lines.append(
            "| {jira_issue_key} | {rank} | {candidate_scenario_id} | {label} | {score} | {text_score} | {raw_service_overlap} | {raw_shape_alignment} | {raw_query_service_delta_signal} | {raw_confusion_penalty} |".format(
                **row
            )
        )
    lines.append("")
    lines.append("## Scoring Policy")
    lines.append("")
    lines.append("Label-aware baseline:")
    lines.append("")
    lines.append("- 55% BM25 text match between sanitized Jira query text and episode evidence text.")
    lines.append("- 30% affected-service overlap.")
    lines.append("- 10% Jira priority to episode severity match.")
    lines.append("- 3% incident-type term match.")
    lines.append("- 2% telemetry strength from log and trace volume.")
    lines.append("")
    lines.append("Raw telemetry profile:")
    lines.append("")
    lines.append("- 34% BM25 text match between sanitized Jira query text and raw candidate evidence text.")
    lines.append("- 26% service overlap from Jira components and telemetry-window service names.")
    lines.append("- 12% activity signal from raw log, trace, and historical-alert volume.")
    lines.append("- 4% alert-volume signal from alert names and historical alert event counts.")
    lines.append("- 2% exact log-volume signal.")
    lines.append("- 1% trace-volume signal.")
    lines.append("- 16% telemetry-shape alignment from active-window deltas, restart-like alerts, outage-like logs, and query intent.")
    lines.append("- 5% issue-service active-window delta signal.")
    lines.append("- Up to 10% penalty for common confusions, such as traffic-pressure near-misses without service-local deltas or outage-like evidence for non-outage queries.")
    lines.append("")
    lines.append("Identity leakage controls are active. Dataset ids, episode ids, telemetry window ids, Jira keys, alert fingerprints, trace ids, generated scenario slugs, generated root-cause labels, and generated severity labels are removed from scoring text. Alert and trace overlaps are still exported as audit features, but they are not used in `baseline_score`.")
    lines.append("")
    lines.append("## Research Caveat")
    lines.append("")
    lines.append("This first run has only two positive Jira issues, so the metrics are a smoke-test proof of the pipeline, not a statistically meaningful model claim. The next research step is to collect more runs and keep this same derived-data contract stable.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(path: Path, run_id: str) -> None:
    content = f"""# Derived Ranking Dataset {run_id}

This directory is generated from `data/runs/{run_id}` by:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\research-lab\\build-ranking-dataset.ps1 -DatasetRunId "{run_id}"
```

Files:

- `freeze-manifest.json`: raw dataset checksums, validation summary, and derived build metadata.
- `episodes.csv` / `episodes.jsonl`: compact episode table.
- `windows.csv` / `windows.jsonl`: compact telemetry-window table.
- `issues.csv` / `issues.jsonl`: compact Jira shadow issue table.
- `episode_features.jsonl`: episode-level evidence features used by ranking.
- `ranking_examples.jsonl` / `ranking_examples.csv`: issue-to-episode training and evaluation pairs.
- `candidate_scores.csv`: ranked candidates per Jira issue for all scoring profiles.
- `label_aware_candidate_scores.csv`: ranked candidates for the lab-label sanity profile.
- `raw_telemetry_candidate_scores.csv`: ranked candidates for the raw telemetry profile.
- `ablation-metrics.json` / `ablation-metrics.csv`: first ablation metrics for text, service, volume, shape, and full raw telemetry scoring.
- `ablation-candidate-scores.csv`: ranked candidate rows for each ablation profile.
- `raw-telemetry-failure-analysis.json` / `raw-telemetry-failure-analysis.csv`: raw telemetry top-1 misses with score components, alerts, sampled logs, service deltas, and likely failure reason.
- `baseline-ranking-report.json` / `baseline-ranking-report.md`: deterministic baseline metrics and interpretation.

Raw files are not copied here. Rebuild this directory from the raw run whenever the feature policy changes.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    run_root = Path(args.run_root).resolve() if args.run_root else repo_root / "data" / "runs" / args.dataset_run_id
    output_root = Path(args.output_root).resolve() if args.output_root else repo_root / "data" / "derived" / args.dataset_run_id

    if not run_root.exists():
        raise FileNotFoundError(f"Dataset run folder does not exist: {run_root}")
    if output_root.exists() and args.force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    manifest = read_json(run_root / "manifest.json")
    episodes = read_jsonl(run_root / "episodes.jsonl")
    windows = read_jsonl(run_root / "telemetry_windows.jsonl")
    alerts = read_jsonl(run_root / "alerts.jsonl")
    issues = read_jsonl(run_root / "jira_shadow_issues.jsonl")
    validation_report_path = run_root / "summaries" / "validation-report.json"
    validation_report = read_json(validation_report_path) if validation_report_path.exists() else {}

    if manifest.get("dataset_run_id") != args.dataset_run_id:
        raise ValueError("Manifest dataset_run_id does not match requested run id.")

    windows_by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        windows_by_episode[str(window.get("incident_episode_id", ""))].append(window)

    checksum_records, tree_hash = checksum_tree(run_root)
    freeze_manifest = {
        "dataset_run_id": args.dataset_run_id,
        "derived_generated_at": utc_now(),
        "builder": {
            "name": "build_ranking_dataset.py",
            "version": SCRIPT_VERSION,
            "scoring_policy": "label_aware_baseline_v0_and_raw_telemetry_v1",
        },
        "raw_run_root": str(run_root),
        "derived_output_root": str(output_root),
        "raw_file_count": len(checksum_records),
        "raw_total_bytes": sum(int(record["bytes"]) for record in checksum_records),
        "raw_tree_sha256": tree_hash,
        "raw_files": checksum_records,
        "source_manifest": manifest,
        "source_validation_report": validation_report,
        "counts": {
            "episodes": len(episodes),
            "telemetry_windows": len(windows),
            "alert_events": len(alerts),
            "jira_shadow_issues": len(issues),
        },
    }

    episode_features = build_episode_features(run_root, episodes, windows_by_episode, alerts)
    examples, metrics_by_profile, rankings_by_profile = build_ranking_examples(issues, episodes, episode_features)
    ablation_rows, ablation_candidate_rows = build_ablation_reports(examples)
    raw_failure_rows = build_raw_failure_analysis(examples, episode_features)
    combined_rankings = rankings_by_profile["label_aware_baseline"] + rankings_by_profile["raw_telemetry"]
    report = {
        "dataset_run_id": args.dataset_run_id,
        "generated_at": utc_now(),
        "builder_version": SCRIPT_VERSION,
        "metrics": metrics_by_profile["label_aware_baseline"],
        "profiles": {
            "label_aware_baseline": {
                "metrics": metrics_by_profile["label_aware_baseline"],
                "weights": {
                    "bm25_text": 0.55,
                    "service_overlap": 0.30,
                    "severity_match": 0.10,
                    "incident_term_match": 0.03,
                    "telemetry_strength": 0.02,
                },
                "uses_candidate_labels": True,
                "description": "Sanity-check profile that can use lab labels such as severity and incident type.",
            },
            "raw_telemetry": {
                "metrics": metrics_by_profile["raw_telemetry"],
                "weights": {
                    "bm25_raw_evidence_text": 0.34,
                    "service_overlap": 0.26,
                    "activity_signal": 0.12,
                    "alert_signal": 0.04,
                    "log_signal": 0.02,
                    "trace_signal": 0.01,
                    "telemetry_shape_alignment": 0.16,
                    "issue_service_active_delta": 0.05,
                    "confusion_penalty": -0.10,
                },
                "uses_candidate_labels": False,
                "description": "Production-facing profile using telemetry-window services, alert names, sampled logs, trace summaries, volume signals, active-window deltas, and telemetry-shape signals.",
            },
        },
        "scoring_policy": {
            "name": "label_aware_baseline_v0_and_raw_telemetry_v1",
            "not_scored": [
                "provenance_alert_overlap_count",
                "provenance_trace_overlap_count",
            ],
            "leakage_controls": [
                "dataset ids removed from scoring text",
                "episode ids removed from scoring text",
                "telemetry window ids removed from scoring text",
                "jira keys removed from scoring text",
                "hex trace ids and alert fingerprints removed from scoring text",
                "scenario slug phrases removed from scoring text",
                "scenario and dataset labels excluded from Jira query text",
                "generated root-cause and severity labels excluded from Jira query text",
            ],
        },
        "rankings": combined_rankings,
        "rankings_by_profile": rankings_by_profile,
        "ablation_metrics": ablation_rows,
        "raw_telemetry_failure_analysis": raw_failure_rows,
    }

    episode_rows = flatten_episodes(episodes)
    window_rows = flatten_windows(windows)
    issue_rows = flatten_issues(issues)

    write_json(output_root / "freeze-manifest.json", freeze_manifest)
    write_jsonl(output_root / "episodes.jsonl", episode_rows)
    write_csv(output_root / "episodes.csv", episode_rows)
    write_jsonl(output_root / "windows.jsonl", window_rows)
    write_csv(output_root / "windows.csv", window_rows)
    write_jsonl(output_root / "issues.jsonl", issue_rows)
    write_csv(output_root / "issues.csv", issue_rows)
    write_jsonl(output_root / "episode_features.jsonl", episode_features)
    write_jsonl(output_root / "ranking_examples.jsonl", examples)
    write_csv(output_root / "ranking_examples.csv", examples)
    write_csv(output_root / "candidate_scores.csv", combined_rankings)
    write_csv(output_root / "label_aware_candidate_scores.csv", rankings_by_profile["label_aware_baseline"])
    write_csv(output_root / "raw_telemetry_candidate_scores.csv", rankings_by_profile["raw_telemetry"])
    write_json(output_root / "ablation-metrics.json", ablation_rows)
    write_csv(output_root / "ablation-metrics.csv", ablation_rows)
    write_csv(output_root / "ablation-candidate-scores.csv", ablation_candidate_rows)
    write_json(output_root / "raw-telemetry-failure-analysis.json", raw_failure_rows)
    write_csv(output_root / "raw-telemetry-failure-analysis.csv", raw_failure_rows)
    write_json(output_root / "baseline-ranking-report.json", report)
    write_report(
        output_root / "baseline-ranking-report.md",
        args.dataset_run_id,
        freeze_manifest,
        metrics_by_profile,
        rankings_by_profile,
        ablation_rows,
        raw_failure_rows,
    )
    write_readme(output_root / "README.md", args.dataset_run_id)

    return {
        "dataset_run_id": args.dataset_run_id,
        "output_root": str(output_root),
        "metrics": metrics_by_profile,
        "raw_tree_sha256": tree_hash,
        "files_written": [
            "README.md",
            "freeze-manifest.json",
            "episodes.csv",
            "episodes.jsonl",
            "windows.csv",
            "windows.jsonl",
            "issues.csv",
            "issues.jsonl",
            "episode_features.jsonl",
            "ranking_examples.csv",
            "ranking_examples.jsonl",
            "candidate_scores.csv",
            "label_aware_candidate_scores.csv",
            "raw_telemetry_candidate_scores.csv",
            "ablation-metrics.json",
            "ablation-metrics.csv",
            "ablation-candidate-scores.csv",
            "raw-telemetry-failure-analysis.json",
            "raw-telemetry-failure-analysis.csv",
            "baseline-ranking-report.json",
            "baseline-ranking-report.md",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--run-root")
    parser.add_argument("--output-root")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    result = build(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
