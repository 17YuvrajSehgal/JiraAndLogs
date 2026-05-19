#!/usr/bin/env python3
"""
Aggregate derived ranking datasets across one or more dataset runs.

Input:
  data/derived/<DATASET_RUN_ID>/ranking_examples.jsonl

Output:
  data/derived/aggregate/<AGGREGATE_ID>/

The aggregate layer never reads or mutates raw telemetry. It combines derived
ranking examples and recomputes query-level metrics across runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "0.2.0"

PROFILES = {
    "label_aware_baseline": {
        "rank_field": "rank",
        "score_field": "baseline_score",
        "text_score_field": "text_score",
        "uses_candidate_labels": True,
    },
    "raw_telemetry": {
        "rank_field": "raw_telemetry_rank",
        "score_field": "raw_telemetry_score",
        "text_score_field": "raw_telemetry_text_score",
        "uses_candidate_labels": False,
    },
}


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


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


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
            writer.writerow({key: csv_value(record.get(key)) for key in fieldnames})


def safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ndcg_for_single_positive(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def f1_for_single_positive(rank: int | None, k: int) -> float:
    if rank is None or rank > k:
        return 0.0
    precision = 1.0 / float(k)
    recall = 1.0
    return (2.0 * precision * recall) / (precision + recall)


def list_derived_runs(derived_root: Path) -> list[str]:
    if not derived_root.exists():
        return []
    run_ids: list[str] = []
    for child in sorted(derived_root.iterdir()):
        if not child.is_dir() or child.name == "aggregate":
            continue
        if (child / "ranking_examples.jsonl").exists():
            run_ids.append(child.name)
    return run_ids


def load_run(derived_root: Path, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_root = derived_root / run_id
    examples_path = run_root / "ranking_examples.jsonl"
    manifest_path = run_root / "freeze-manifest.json"
    report_path = run_root / "baseline-ranking-report.json"
    if not examples_path.exists():
        raise FileNotFoundError(f"Missing derived ranking examples: {examples_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing derived freeze manifest: {manifest_path}")

    manifest = read_json(manifest_path)
    report = read_json(report_path) if report_path.exists() else {}
    examples = read_jsonl(examples_path)
    for example in examples:
        example["query_id"] = f"{run_id}::{example.get('jira_issue_key')}"
        example["source_dataset_run_id"] = run_id
    run_summary = {
        "dataset_run_id": run_id,
        "derived_root": str(run_root),
        "raw_tree_sha256": manifest.get("raw_tree_sha256"),
        "builder": manifest.get("builder", {}),
        "source_counts": manifest.get("counts", {}),
        "profile_metrics": report.get("profiles", {}),
        "example_count": len(examples),
    }
    return run_summary, examples


def load_episode_features(derived_root: Path, run_id: str) -> list[dict[str, Any]]:
    features_path = derived_root / run_id / "episode_features.jsonl"
    if not features_path.exists():
        return []
    records = read_jsonl(features_path)
    for record in records:
        record["source_dataset_run_id"] = run_id
        if not record.get("dataset_run_id"):
            record["dataset_run_id"] = run_id
    return records


def rank_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def metrics_from_ranks(
    ranks_by_query: dict[str, int | None],
    example_count: int,
    positive_example_count: int,
) -> dict[str, Any]:
    query_count = len(ranks_by_query)
    return {
        "query_count": query_count,
        "example_count": example_count,
        "positive_example_count": positive_example_count,
        "negative_example_count": example_count - positive_example_count,
        "mrr": round(
            sum((1.0 / rank) if rank else 0.0 for rank in ranks_by_query.values()) / max(1, query_count),
            6,
        ),
        "recall_at_1": round(
            sum(1 for rank in ranks_by_query.values() if rank is not None and rank <= 1) / max(1, query_count),
            6,
        ),
        "recall_at_3": round(
            sum(1 for rank in ranks_by_query.values() if rank is not None and rank <= 3) / max(1, query_count),
            6,
        ),
        "f1_at_1": round(
            sum(f1_for_single_positive(rank, 1) for rank in ranks_by_query.values()) / max(1, query_count),
            6,
        ),
        "f1_at_3": round(
            sum(f1_for_single_positive(rank, 3) for rank in ranks_by_query.values()) / max(1, query_count),
            6,
        ),
        "ndcg_at_3": round(
            sum(ndcg_for_single_positive(rank) if rank is not None and rank <= 3 else 0.0 for rank in ranks_by_query.values())
            / max(1, query_count),
            6,
        ),
        "true_rank_by_query": ranks_by_query,
    }


def calculate_metrics(examples: list[dict[str, Any]], rank_field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["query_id"])].append(example)

    ranks_by_query: dict[str, int | None] = {}
    for query_id, query_examples in grouped.items():
        positive_ranks = [
            rank
            for rank in (rank_int(example.get(rank_field)) for example in query_examples if int(example.get("label", 0)) == 1)
            if rank is not None
        ]
        ranks_by_query[query_id] = min(positive_ranks) if positive_ranks else None

    return metrics_from_ranks(
        ranks_by_query=ranks_by_query,
        example_count=len(examples),
        positive_example_count=sum(int(example.get("label", 0)) for example in examples),
    )


def profile_score_rows(examples: list[dict[str, Any]], profile_name: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rank_field = profile["rank_field"]
    score_field = profile["score_field"]
    text_score_field = profile["text_score_field"]
    for example in examples:
        rows.append(
            {
                "profile": profile_name,
                "query_id": example.get("query_id"),
                "dataset_run_id": example.get("source_dataset_run_id"),
                "jira_issue_key": example.get("jira_issue_key"),
                "rank": rank_int(example.get(rank_field)),
                "candidate_episode_id": example.get("candidate_episode_id"),
                "candidate_scenario_id": example.get("candidate_scenario_id"),
                "label": int(example.get("label", 0)),
                "score": example.get(score_field),
                "text_score": example.get(text_score_field),
                "service_overlap": example.get("service_overlap"),
                "raw_telemetry_service_overlap": example.get("raw_telemetry_service_overlap"),
                "uses_candidate_labels": profile["uses_candidate_labels"],
            }
        )
    return sorted(rows, key=lambda row: (str(row["profile"]), str(row["query_id"]), int(row["rank"] or 999999)))


SCORE_COMPONENT_FIELDS = [
    "raw_telemetry_score",
    "raw_telemetry_text_score",
    "raw_telemetry_service_overlap",
    "raw_telemetry_activity_signal",
    "raw_telemetry_alert_signal",
    "raw_telemetry_log_signal",
    "raw_telemetry_trace_signal",
    "raw_telemetry_query_service_delta_signal",
    "raw_telemetry_restart_signal",
    "raw_telemetry_outage_signal",
    "raw_telemetry_traffic_pressure_signal",
    "raw_telemetry_latency_signal",
    "raw_telemetry_restart_event_signal",
    "raw_telemetry_rollout_unavailable_signal",
    "raw_telemetry_recovery_complete_signal",
    "raw_telemetry_recovery_incomplete_signal",
    "raw_telemetry_service_local_delta_signal",
    "raw_telemetry_shape_alignment",
    "raw_telemetry_confusion_penalty",
]


ABLATION_PROFILES: dict[str, dict[str, Any]] = {
    "jira_text_only": {
        "description": "Sanitized Jira query text against label-aware episode evidence text.",
        "uses_candidate_labels": True,
    },
    "service_overlap_only": {
        "description": "Jira component overlap with services observed in telemetry windows.",
        "uses_candidate_labels": False,
    },
    "raw_telemetry_text_only": {
        "description": "Sanitized Jira query text against raw logs, alerts, traces, and service names.",
        "uses_candidate_labels": False,
    },
    "volume_only": {
        "description": "Raw telemetry volume signals only: activity, alerts, logs, and traces.",
        "uses_candidate_labels": False,
    },
    "shape_features_only": {
        "description": "Raw telemetry shape signals only: restart, outage, recovery, deltas, and confusion penalties.",
        "uses_candidate_labels": False,
    },
    "full_raw_telemetry": {
        "description": "The production-facing raw telemetry ranker.",
        "uses_candidate_labels": False,
    },
}


def ablation_score(example: dict[str, Any], profile_name: str) -> float:
    if profile_name == "jira_text_only":
        return safe_float(example.get("text_score"))
    if profile_name == "service_overlap_only":
        return safe_float(example.get("raw_telemetry_service_overlap"))
    if profile_name == "raw_telemetry_text_only":
        return safe_float(example.get("raw_telemetry_text_score"))
    if profile_name == "volume_only":
        values = [
            safe_float(example.get("raw_telemetry_activity_signal")),
            safe_float(example.get("raw_telemetry_alert_signal")),
            safe_float(example.get("raw_telemetry_log_signal")),
            safe_float(example.get("raw_telemetry_trace_signal")),
        ]
        return sum(values) / len(values)
    if profile_name == "shape_features_only":
        return max(
            0.0,
            0.30 * safe_float(example.get("raw_telemetry_shape_alignment"))
            + 0.25 * safe_float(example.get("raw_telemetry_query_service_delta_signal"))
            + 0.20 * safe_float(example.get("raw_telemetry_restart_signal"))
            + 0.20 * safe_float(example.get("raw_telemetry_outage_signal"))
            + 0.05 * safe_float(example.get("raw_telemetry_latency_signal"))
            + 0.05 * safe_float(example.get("raw_telemetry_restart_event_signal"))
            + 0.05 * safe_float(example.get("raw_telemetry_recovery_complete_signal"))
            - 0.20 * safe_float(example.get("raw_telemetry_confusion_penalty")),
        )
    if profile_name == "full_raw_telemetry":
        return safe_float(example.get("raw_telemetry_score"))
    raise ValueError(f"Unsupported ablation profile: {profile_name}")


def build_ablation_reports(examples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["query_id"])].append(example)

    metric_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for profile_name, profile in ABLATION_PROFILES.items():
        ranks_by_query: dict[str, int | None] = {}
        for query_id, query_examples in grouped.items():
            ranked = sorted(
                query_examples,
                key=lambda item: (
                    -ablation_score(item, profile_name),
                    str(item.get("candidate_episode_id")),
                ),
            )
            true_rank: int | None = None
            for rank, example in enumerate(ranked, start=1):
                score = round(ablation_score(example, profile_name), 6)
                if int(example.get("label", 0)) == 1 and true_rank is None:
                    true_rank = rank
                candidate_rows.append(
                    {
                        "ablation_profile": profile_name,
                        "query_id": query_id,
                        "dataset_run_id": example.get("source_dataset_run_id"),
                        "jira_issue_key": example.get("jira_issue_key"),
                        "rank": rank,
                        "candidate_episode_id": example.get("candidate_episode_id"),
                        "candidate_scenario_id": example.get("candidate_scenario_id"),
                        "label": int(example.get("label", 0)),
                        "score": score,
                    }
                )
            ranks_by_query[query_id] = true_rank

        metrics = metrics_from_ranks(
            ranks_by_query=ranks_by_query,
            example_count=len(examples),
            positive_example_count=sum(int(example.get("label", 0)) for example in examples),
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
            str(row["query_id"]),
            int(row["rank"] or 999999),
        )
    )
    return metric_rows, candidate_rows


def feature_key(run_id: Any, episode_id: Any) -> str:
    return f"{run_id}::{episode_id}"


def get_candidate_features(
    feature_by_episode: dict[str, dict[str, Any]],
    example: dict[str, Any] | None,
) -> dict[str, Any]:
    if not example:
        return {}
    run_id = example.get("source_dataset_run_id") or example.get("dataset_run_id")
    episode_id = example.get("candidate_episode_id")
    return feature_by_episode.get(feature_key(run_id, episode_id), {})


def score_components(example: dict[str, Any] | None) -> dict[str, Any]:
    if not example:
        return {}
    return {field: example.get(field) for field in SCORE_COMPONENT_FIELDS}


def service_delta_summary(features: dict[str, Any]) -> dict[str, Any]:
    raw_counts = features.get("exact_log_entries_by_service_window_type", {})
    if not isinstance(raw_counts, dict):
        return {}
    summary: dict[str, Any] = {}
    for service_name, counts in sorted(raw_counts.items()):
        if not isinstance(counts, dict):
            continue
        active = int(counts.get("active_fault", 0) or 0)
        baseline = int(counts.get("pre_fault_baseline", 0) or 0)
        recovery = int(counts.get("recovery_window", 0) or 0)
        summary[service_name] = {
            "pre_fault_baseline": baseline,
            "active_fault": active,
            "recovery_window": recovery,
            "active_minus_baseline": active - baseline,
            "recovery_minus_active": recovery - active,
        }
    return summary


def likely_failure_reason(true_example: dict[str, Any] | None, rank1_example: dict[str, Any] | None) -> str:
    if not true_example or not rank1_example:
        return "missing_positive_candidate"
    true_scenario = str(true_example.get("candidate_scenario_id", "")).lower()
    rank1_scenario = str(rank1_example.get("candidate_scenario_id", "")).lower()
    true_restart = safe_float(true_example.get("raw_telemetry_restart_signal"))
    rank1_outage = safe_float(rank1_example.get("raw_telemetry_outage_signal"))
    true_delta = safe_float(true_example.get("raw_telemetry_query_service_delta_signal"))
    rank1_delta = safe_float(rank1_example.get("raw_telemetry_query_service_delta_signal"))
    rank1_pressure = safe_float(rank1_example.get("raw_telemetry_traffic_pressure_signal"))

    if "redis" in true_scenario and "redis" in rank1_scenario and true_restart > 0 and rank1_outage > 0:
        return "redis_restart_vs_redis_outage_confusion"
    if rank1_pressure > 0 and rank1_delta <= true_delta:
        return "traffic_pressure_overweighted"
    if rank1_delta > true_delta:
        return "service_delta_signal_favored_rank1"
    if safe_float(rank1_example.get("raw_telemetry_text_score")) > safe_float(true_example.get("raw_telemetry_text_score")):
        return "raw_text_overlap_favored_rank1"
    return "score_component_overlap"


def build_raw_failure_analysis(
    examples: list[dict[str, Any]],
    feature_by_episode: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["query_id"])].append(example)

    rows: list[dict[str, Any]] = []
    for query_id, query_examples in sorted(grouped.items()):
        positives = [example for example in query_examples if int(example.get("label", 0)) == 1]
        true_example = min(positives, key=lambda item: rank_int(item.get("raw_telemetry_rank")) or 999999) if positives else None
        true_rank = rank_int(true_example.get("raw_telemetry_rank")) if true_example else None
        if true_rank is not None and true_rank <= 1:
            continue
        ranked = sorted(query_examples, key=lambda item: rank_int(item.get("raw_telemetry_rank")) or 999999)
        rank1_example = ranked[0] if ranked else None
        true_features = get_candidate_features(feature_by_episode, true_example)
        rank1_features = get_candidate_features(feature_by_episode, rank1_example)
        rows.append(
            {
                "query_id": query_id,
                "dataset_run_id": (true_example or rank1_example or {}).get("source_dataset_run_id"),
                "jira_issue_key": (true_example or rank1_example or {}).get("jira_issue_key"),
                "true_candidate_episode_id": true_example.get("candidate_episode_id") if true_example else None,
                "true_candidate_scenario_id": true_example.get("candidate_scenario_id") if true_example else None,
                "true_rank": true_rank,
                "rank1_candidate_episode_id": rank1_example.get("candidate_episode_id") if rank1_example else None,
                "rank1_candidate_scenario_id": rank1_example.get("candidate_scenario_id") if rank1_example else None,
                "rank1_label": int(rank1_example.get("label", 0)) if rank1_example else None,
                "true_score_components": score_components(true_example),
                "rank1_score_components": score_components(rank1_example),
                "true_alert_names": true_features.get("alert_names", []),
                "rank1_alert_names": rank1_features.get("alert_names", []),
                "true_sampled_logs": list(true_features.get("sample_log_messages", []))[:8],
                "rank1_sampled_logs": list(rank1_features.get("sample_log_messages", []))[:8],
                "true_service_deltas": service_delta_summary(true_features),
                "rank1_service_deltas": service_delta_summary(rank1_features),
                "likely_failure_reason": likely_failure_reason(true_example, rank1_example),
            }
        )
    return rows


def write_report(
    path: Path,
    aggregate: dict[str, Any],
    profile_scores: list[dict[str, Any]],
    ablation_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append(f"# Cross-Run Evaluation {aggregate['aggregate_id']}")
    lines.append("")
    lines.append(f"- Generated at: {aggregate['generated_at']}")
    lines.append(f"- Builder version: {aggregate['builder']['version']}")
    lines.append(f"- Dataset runs: {len(aggregate['dataset_runs'])}")
    lines.append(f"- Query issues: {aggregate['summary']['query_count']}")
    lines.append(f"- Ranking examples: {aggregate['summary']['example_count']}")
    lines.append(f"- Positive examples: {aggregate['summary']['positive_example_count']}")
    lines.append(f"- Negative examples: {aggregate['summary']['negative_example_count']}")
    lines.append("")
    lines.append("## Runs")
    lines.append("")
    lines.append("| Run | Raw tree SHA256 | Examples |")
    lines.append("| --- | --- | ---: |")
    for run in aggregate["dataset_runs"]:
        lines.append(f"| {run['dataset_run_id']} | `{run.get('raw_tree_sha256')}` | {run['example_count']} |")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Profile | Uses candidate labels | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for profile_name, profile in aggregate["profiles"].items():
        metrics = profile["metrics"]
        lines.append(
            f"| {profile_name} | {profile['uses_candidate_labels']} | {metrics['mrr']} | {metrics['recall_at_1']} | {metrics['recall_at_3']} | {metrics['f1_at_1']} | {metrics['f1_at_3']} | {metrics['ndcg_at_3']} |"
        )
    lines.append("")
    lines.append("F1@k is computed per Jira query with one relevant episode. A top-k hit has Precision@k = 1/k and Recall@k = 1, then the per-query harmonic mean is averaged across queries.")
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
        lines.append("| Query | True rank | True scenario | Rank-1 scenario | Likely reason |")
        lines.append("| --- | ---: | --- | --- | --- |")
        for row in failure_rows:
            lines.append(
                f"| {row['query_id']} | {row['true_rank']} | {row['true_candidate_scenario_id']} | {row['rank1_candidate_scenario_id']} | {row['likely_failure_reason']} |"
            )
    else:
        lines.append("No raw telemetry top-1 misses were found.")
    lines.append("")
    lines.append("## Top Candidates")
    lines.append("")
    lines.append("| Profile | Query | Rank | Candidate scenario | Label | Score |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: |")
    for row in profile_scores:
        if int(row["rank"] or 999999) > 5:
            continue
        lines.append(
            f"| {row['profile']} | {row['query_id']} | {row['rank']} | {row['candidate_scenario_id']} | {row['label']} | {row['score']} |"
        )
    lines.append("")
    lines.append("## Caveat")
    lines.append("")
    lines.append("This aggregate is only as strong as the runs included. A single-run aggregate is useful for contract validation, not for statistical claims.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    derived_root = Path(args.derived_root).resolve() if args.derived_root else repo_root / "data" / "derived"
    run_ids = args.dataset_run_id or list_derived_runs(derived_root)
    if not run_ids:
        raise ValueError(f"No derived dataset runs found under {derived_root}")

    aggregate_id = args.aggregate_id or "current"
    output_root = (
        Path(args.output_root).resolve()
        if args.output_root
        else derived_root / "aggregate" / aggregate_id
    )
    if output_root.exists() and args.force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    run_summaries: list[dict[str, Any]] = []
    combined_examples: list[dict[str, Any]] = []
    combined_episode_features: list[dict[str, Any]] = []
    for run_id in run_ids:
        run_summary, examples = load_run(derived_root, run_id)
        run_summaries.append(run_summary)
        combined_examples.extend(examples)
        combined_episode_features.extend(load_episode_features(derived_root, run_id))

    metrics_by_profile: dict[str, dict[str, Any]] = {}
    profile_rows: list[dict[str, Any]] = []
    for profile_name, profile in PROFILES.items():
        metrics_by_profile[profile_name] = calculate_metrics(combined_examples, profile["rank_field"])
        profile_rows.extend(profile_score_rows(combined_examples, profile_name, profile))

    feature_by_episode = {
        feature_key(record.get("source_dataset_run_id") or record.get("dataset_run_id"), record.get("incident_episode_id")): record
        for record in combined_episode_features
        if record.get("incident_episode_id")
    }
    ablation_rows, ablation_candidate_rows = build_ablation_reports(combined_examples)
    raw_failure_rows = build_raw_failure_analysis(combined_examples, feature_by_episode)

    query_count = len({str(example["query_id"]) for example in combined_examples})
    aggregate = {
        "aggregate_id": aggregate_id,
        "generated_at": utc_now(),
        "builder": {
            "name": "build_cross_run_evaluation.py",
            "version": SCRIPT_VERSION,
        },
        "derived_root": str(derived_root),
        "output_root": str(output_root),
        "dataset_runs": run_summaries,
        "summary": {
            "dataset_run_count": len(run_summaries),
            "query_count": query_count,
            "example_count": len(combined_examples),
            "positive_example_count": sum(int(example.get("label", 0)) for example in combined_examples),
            "negative_example_count": sum(1 - int(example.get("label", 0)) for example in combined_examples),
        },
        "profiles": {
            profile_name: {
                "uses_candidate_labels": PROFILES[profile_name]["uses_candidate_labels"],
                "metrics": metrics,
            }
            for profile_name, metrics in metrics_by_profile.items()
        },
        "ablation_metrics": ablation_rows,
        "raw_telemetry_failure_analysis": raw_failure_rows,
    }

    write_json(output_root / "cross-run-evaluation.json", aggregate)
    write_jsonl(output_root / "combined-ranking-examples.jsonl", combined_examples)
    write_csv(output_root / "combined-ranking-examples.csv", combined_examples)
    write_csv(output_root / "cross-run-candidate-scores.csv", profile_rows)
    write_json(output_root / "ablation-metrics.json", ablation_rows)
    write_csv(output_root / "ablation-metrics.csv", ablation_rows)
    write_csv(output_root / "ablation-candidate-scores.csv", ablation_candidate_rows)
    write_json(output_root / "raw-telemetry-failure-analysis.json", raw_failure_rows)
    write_csv(output_root / "raw-telemetry-failure-analysis.csv", raw_failure_rows)
    write_report(output_root / "cross-run-evaluation.md", aggregate, profile_rows, ablation_rows, raw_failure_rows)

    return {
        "aggregate_id": aggregate_id,
        "output_root": str(output_root),
        "dataset_run_ids": run_ids,
        "profiles": aggregate["profiles"],
        "files_written": [
            "cross-run-evaluation.json",
            "cross-run-evaluation.md",
            "combined-ranking-examples.jsonl",
            "combined-ranking-examples.csv",
            "cross-run-candidate-scores.csv",
            "ablation-metrics.json",
            "ablation-metrics.csv",
            "ablation-candidate-scores.csv",
            "raw-telemetry-failure-analysis.json",
            "raw-telemetry-failure-analysis.csv",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", action="append", default=[])
    parser.add_argument("--aggregate-id")
    parser.add_argument("--repo-root")
    parser.add_argument("--derived-root")
    parser.add_argument("--output-root")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
