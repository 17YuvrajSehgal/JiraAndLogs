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


SCRIPT_VERSION = "0.1.0"

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
    for episode in episodes:
        episode_id = str(episode["incident_episode_id"])
        windows = windows_by_episode.get(episode_id, [])
        services = listify(episode.get("affected_services"))
        alert_fingerprints = set(map(str, listify(episode.get("alert_fingerprints")))) | alerts_by_episode[episode_id]
        alert_names = sorted({names_by_fingerprint.get(fp, fp) for fp in alert_fingerprints if fp})

        exact_log_entries = sum(int_feature(window, ["features", "logs", "entry_count"]) for window in windows)
        service_context_log_entries = sum(int_feature(window, ["features", "logs", "context_entry_count"]) for window in windows)
        namespace_context_log_entries = sum(
            int_feature(window, ["features", "logs", "namespace_context_entry_count"]) for window in windows
        )
        historical_alert_event_count = sum(
            int_feature(window, ["features", "metrics", "historical_alert_event_count"]) for window in windows
        )
        trace_ids = sorted({str(trace_id) for window in windows for trace_id in listify(window.get("trace_ids"))})
        log_messages: list[str] = []
        seen_messages: set[str] = set()
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
                "window_count": len(windows),
                "alert_fingerprint_count": len(alert_fingerprints),
                "alert_names": alert_names,
                "trace_count": len(trace_ids),
                "exact_log_entries": exact_log_entries,
                "service_context_log_entries": service_context_log_entries,
                "namespace_context_log_entries": namespace_context_log_entries,
                "historical_alert_event_count": historical_alert_event_count,
                "sample_log_messages": log_messages,
                "evidence_text": evidence_text,
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


def build_ranking_examples(
    issues: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    episode_features: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    feature_by_episode = {record["incident_episode_id"]: record for record in episode_features}
    episode_by_id = {record["incident_episode_id"]: record for record in episodes}
    documents = {
        episode_id: tokenize(features.get("evidence_text", ""))
        for episode_id, features in feature_by_episode.items()
    }

    examples: list[dict[str, Any]] = []
    rankings: list[dict[str, Any]] = []

    for issue in issues:
        metadata = issue.get("metadata", {})
        issue_key = str(issue.get("jira_issue_key", ""))
        true_episode_id = str(issue.get("incident_episode_id", ""))
        query_text = issue_query_text(issue)
        query_tokens = tokenize(query_text)
        raw_bm25 = bm25_scores(documents, query_tokens)
        max_bm25 = max(raw_bm25.values()) if raw_bm25 else 0.0
        issue_services = listify(metadata.get("components"))
        issue_severity = priority_to_severity(str(metadata.get("priority", "")))
        issue_alerts = set(map(str, listify(get_nested(issue, ["telemetry_links", "alert_fingerprints"], []))))
        issue_traces = set(map(str, listify(get_nested(issue, ["telemetry_links", "trace_ids"], []))))

        issue_examples: list[dict[str, Any]] = []
        for episode in episodes:
            episode_id = str(episode["incident_episode_id"])
            features = feature_by_episode[episode_id]
            episode_alerts = set(map(str, listify(episode.get("alert_fingerprints"))))
            episode_traces = set(map(str, listify(episode.get("trace_ids"))))
            bm25_raw = raw_bm25.get(episode_id, 0.0)
            text_score = bm25_raw / max_bm25 if max_bm25 > 0 else 0.0
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
                "provenance_alert_overlap_count": len(issue_alerts & episode_alerts),
                "provenance_trace_overlap_count": len(issue_traces & episode_traces),
                "window_count": features["window_count"],
                "alert_fingerprint_count": features["alert_fingerprint_count"],
                "trace_count": features["trace_count"],
                "exact_log_entries": features["exact_log_entries"],
                "service_context_log_entries": features["service_context_log_entries"],
                "namespace_context_log_entries": features["namespace_context_log_entries"],
                "scoring_policy": "baseline_v0_no_identity_overlap",
            }
            issue_examples.append(example)

        issue_examples.sort(
            key=lambda item: (
                -float(item["baseline_score"]),
                -float(item["text_score"]),
                str(item["candidate_episode_id"]),
            )
        )
        for rank, example in enumerate(issue_examples, start=1):
            example["rank"] = rank
            rankings.append(
                {
                    "jira_issue_key": issue_key,
                    "rank": rank,
                    "candidate_episode_id": example["candidate_episode_id"],
                    "candidate_scenario_id": example["candidate_scenario_id"],
                    "label": example["label"],
                    "baseline_score": example["baseline_score"],
                    "text_score": example["text_score"],
                    "service_overlap": example["service_overlap"],
                    "severity_match": example["severity_match"],
                }
            )
        examples.extend(issue_examples)

    ranks_by_issue: dict[str, int | None] = {}
    for issue in issues:
        issue_key = str(issue.get("jira_issue_key", ""))
        positives = [
            int(example["rank"])
            for example in examples
            if example["jira_issue_key"] == issue_key and int(example["label"]) == 1
        ]
        ranks_by_issue[issue_key] = min(positives) if positives else None

    query_count = len(issues)
    metrics = {
        "query_count": query_count,
        "candidate_episode_count": len(episodes),
        "example_count": len(examples),
        "positive_example_count": sum(int(example["label"]) for example in examples),
        "negative_example_count": sum(1 - int(example["label"]) for example in examples),
        "mrr": round(
            sum((1.0 / rank) if rank else 0.0 for rank in ranks_by_issue.values()) / max(1, query_count),
            6,
        ),
        "recall_at_1": round(
            sum(1 for rank in ranks_by_issue.values() if rank is not None and rank <= 1) / max(1, query_count),
            6,
        ),
        "recall_at_3": round(
            sum(1 for rank in ranks_by_issue.values() if rank is not None and rank <= 3) / max(1, query_count),
            6,
        ),
        "ndcg_at_3": round(
            sum(ndcg_for_single_positive(rank) if rank is not None and rank <= 3 else 0.0 for rank in ranks_by_issue.values())
            / max(1, query_count),
            6,
        ),
        "true_rank_by_issue": ranks_by_issue,
    }
    return examples, metrics, rankings


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
    metrics: dict[str, Any],
    rankings: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append(f"# Baseline Ranking Report {run_id}")
    lines.append("")
    lines.append(f"- Generated at: {freeze_manifest['derived_generated_at']}")
    lines.append(f"- Builder version: {SCRIPT_VERSION}")
    lines.append(f"- Raw file count: {freeze_manifest['raw_file_count']}")
    lines.append(f"- Raw byte count: {freeze_manifest['raw_total_bytes']}")
    lines.append(f"- Raw tree SHA256: `{freeze_manifest['raw_tree_sha256']}`")
    lines.append(f"- Query issues: {metrics['query_count']}")
    lines.append(f"- Candidate episodes: {metrics['candidate_episode_count']}")
    lines.append(f"- Ranking examples: {metrics['example_count']}")
    lines.append(f"- Positive examples: {metrics['positive_example_count']}")
    lines.append(f"- Negative examples: {metrics['negative_example_count']}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    for key in ("mrr", "recall_at_1", "recall_at_3", "ndcg_at_3"):
        lines.append(f"| {key} | {metrics[key]} |")
    lines.append("")
    lines.append("## Top Rankings")
    lines.append("")
    lines.append("| Jira issue | Rank | Candidate scenario | Label | Score | Text | Service | Severity |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in rankings:
        if int(row["rank"]) > 5:
            continue
        lines.append(
            "| {jira_issue_key} | {rank} | {candidate_scenario_id} | {label} | {baseline_score} | {text_score} | {service_overlap} | {severity_match} |".format(
                **row
            )
        )
    lines.append("")
    lines.append("## Scoring Policy")
    lines.append("")
    lines.append("The baseline score is deterministic and intentionally simple:")
    lines.append("")
    lines.append("- 55% BM25 text match between sanitized Jira query text and episode evidence text.")
    lines.append("- 30% affected-service overlap.")
    lines.append("- 10% Jira priority to episode severity match.")
    lines.append("- 3% incident-type term match.")
    lines.append("- 2% telemetry strength from log and trace volume.")
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
- `candidate_scores.csv`: ranked candidates per Jira issue.
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
            "scoring_policy": "baseline_v0_no_identity_overlap",
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
    examples, metrics, rankings = build_ranking_examples(issues, episodes, episode_features)
    report = {
        "dataset_run_id": args.dataset_run_id,
        "generated_at": utc_now(),
        "builder_version": SCRIPT_VERSION,
        "metrics": metrics,
        "scoring_policy": {
            "name": "baseline_v0_no_identity_overlap",
            "weights": {
                "bm25_text": 0.55,
                "service_overlap": 0.30,
                "severity_match": 0.10,
                "incident_term_match": 0.03,
                "telemetry_strength": 0.02,
            },
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
        "rankings": rankings,
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
    write_csv(output_root / "candidate_scores.csv", rankings)
    write_json(output_root / "baseline-ranking-report.json", report)
    write_report(output_root / "baseline-ranking-report.md", args.dataset_run_id, freeze_manifest, metrics, rankings)
    write_readme(output_root / "README.md", args.dataset_run_id)

    return {
        "dataset_run_id": args.dataset_run_id,
        "output_root": str(output_root),
        "metrics": metrics,
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
