#!/usr/bin/env python3
"""
Build a global hard-negative ranking dataset across derived dataset runs.

The per-run derived builder pairs each Jira issue only with episodes from the
same dataset run. This builder creates the harder corpus used for ML, retrieval,
neural, language-model, and hybrid experiments: every selected Jira issue is
paired with every selected candidate episode across all runs.

Raw runs are treated as immutable input. All outputs are written under:

  data/derived/global/<GLOBAL_DATASET_ID>/
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_cross_run_evaluation import (
    PROFILES,
    build_ablation_reports,
    build_raw_failure_analysis,
    calculate_metrics,
    profile_score_rows,
)
from build_ranking_dataset import (
    build_ranking_examples,
    issue_query_text,
    listify,
    read_json,
    read_jsonl,
    write_csv,
    write_json,
    write_jsonl,
)


SCRIPT_VERSION = "0.1.0"
METRIC_FIELDS = ("mrr", "recall_at_1", "recall_at_3", "f1_at_1", "f1_at_3", "ndcg_at_3")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_run_ids(values: list[str]) -> list[str]:
    run_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            run_id = item.strip()
            if run_id and run_id not in seen:
                run_ids.append(run_id)
                seen.add(run_id)
    return run_ids


def list_derived_runs(derived_root: Path) -> list[str]:
    if not derived_root.exists():
        return []
    run_ids: list[str] = []
    for child in sorted(derived_root.iterdir()):
        if not child.is_dir() or child.name in {"aggregate", "corpora", "global", "holdout"}:
            continue
        if (child / "episode_features.jsonl").exists() and (child / "freeze-manifest.json").exists():
            run_ids.append(child.name)
    return run_ids


def run_ids_from_manifest(path: Path) -> list[str]:
    manifest = read_json(path)
    completed = manifest.get("completed_run_ids") or []
    if not completed:
        completed = [
            item.get("dataset_run_id")
            for item in manifest.get("selected_runs", [])
            if item.get("dataset_run_id")
        ]
    return normalize_run_ids([str(item) for item in completed])


def resolve_run_ids(args: argparse.Namespace, derived_root: Path) -> list[str]:
    explicit = normalize_run_ids(args.dataset_run_id or [])
    if explicit:
        return explicit

    if args.corpus_manifest:
        return run_ids_from_manifest(Path(args.corpus_manifest).resolve())

    if args.dataset_run_prefix:
        manifest_path = derived_root / "corpora" / args.dataset_run_prefix / "corpus-run-manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing corpus manifest for prefix {args.dataset_run_prefix}: {manifest_path}")
        return run_ids_from_manifest(manifest_path)

    run_ids = list_derived_runs(derived_root)
    if not run_ids:
        raise ValueError(f"No derived runs found under {derived_root}")
    return run_ids


def safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def service_overlap_bucket(value: Any) -> str:
    score = safe_float(value)
    if score >= 0.999:
        return "exact_service_overlap"
    if score > 0.0:
        return "partial_service_overlap"
    return "no_service_overlap"


def scenario_family(scenario_id: Any) -> str:
    text = str(scenario_id or "").lower()
    if "baseline" in text:
        return "baseline"
    if "nearmiss" in text:
        return "near_miss"
    if "restart" in text:
        return "restart"
    if "latency" in text:
        return "latency"
    if "config" in text:
        return "configuration"
    if "unavailable" in text or "degradation" in text or "failure" in text:
        return "outage_or_degradation"
    if "traffic" in text:
        return "traffic"
    return "other"


def default_split_for_run(run_ids: list[str]) -> dict[str, str]:
    if len(run_ids) >= 3:
        train = set(run_ids[:-2])
        validation = {run_ids[-2]}
        test = {run_ids[-1]}
    elif len(run_ids) == 2:
        train = {run_ids[0]}
        validation = set()
        test = {run_ids[1]}
    else:
        train = set(run_ids)
        validation = set()
        test = set()
    mapping: dict[str, str] = {}
    for run_id in run_ids:
        if run_id in train:
            mapping[run_id] = "train"
        elif run_id in validation:
            mapping[run_id] = "validation"
        else:
            mapping[run_id] = "test"
    return mapping


def load_selected_runs(repo_root: Path, derived_root: Path, run_ids: list[str]) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    run_summaries: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []

    for run_id in run_ids:
        raw_root = repo_root / "data" / "runs" / run_id
        derived_run_root = derived_root / run_id
        freeze_path = derived_run_root / "freeze-manifest.json"
        features_path = derived_run_root / "episode_features.jsonl"
        issues_path = raw_root / "jira_shadow_issues.jsonl"
        episodes_path = raw_root / "episodes.jsonl"
        validation_path = raw_root / "summaries" / "validation-report.json"

        for required in (freeze_path, features_path, issues_path, episodes_path):
            if not required.exists():
                raise FileNotFoundError(f"Missing required input for {run_id}: {required}")

        freeze_manifest = read_json(freeze_path)
        validation = read_json(validation_path) if validation_path.exists() else {}
        raw_issues = read_jsonl(issues_path)
        raw_episodes = read_jsonl(episodes_path)
        derived_features = read_jsonl(features_path)

        for issue in raw_issues:
            original_key = str(issue.get("jira_issue_key", ""))
            query_id = f"{run_id}::{original_key}"
            issue_copy = copy.deepcopy(issue)
            issue_copy["original_jira_issue_key"] = original_key
            issue_copy["query_id"] = query_id
            issue_copy["jira_issue_key"] = query_id
            issues.append(issue_copy)

            metadata = issue.get("metadata", {})
            queries.append(
                {
                    "query_id": query_id,
                    "dataset_run_id": run_id,
                    "original_jira_issue_key": original_key,
                    "jira_shadow_issue_id": issue.get("jira_shadow_issue_id"),
                    "true_candidate_episode_id": issue.get("incident_episode_id"),
                    "summary": metadata.get("summary"),
                    "issue_type": metadata.get("issue_type"),
                    "priority": metadata.get("priority"),
                    "status": metadata.get("status"),
                    "components": listify(metadata.get("components")),
                    "labels": listify(metadata.get("labels")),
                    "created_at": metadata.get("created_at"),
                    "resolved_at": metadata.get("resolved_at"),
                    "query_text": issue_query_text(issue),
                }
            )

        for episode in raw_episodes:
            episode_copy = copy.deepcopy(episode)
            episode_copy["source_dataset_run_id"] = run_id
            episodes.append(episode_copy)

        for record in derived_features:
            feature_copy = copy.deepcopy(record)
            feature_copy["source_dataset_run_id"] = run_id
            if not feature_copy.get("dataset_run_id"):
                feature_copy["dataset_run_id"] = run_id
            features.append(feature_copy)

        run_summaries.append(
            {
                "dataset_run_id": run_id,
                "raw_root": str(raw_root),
                "derived_root": str(derived_run_root),
                "raw_tree_sha256": freeze_manifest.get("raw_tree_sha256"),
                "builder": freeze_manifest.get("builder", {}),
                "source_counts": freeze_manifest.get("counts", {}),
                "validation_error_count": len(validation.get("errors", [])) if isinstance(validation, dict) else None,
                "validation_warning_count": len(validation.get("warnings", [])) if isinstance(validation, dict) else None,
                "query_count": len(raw_issues),
                "candidate_episode_count": len(raw_episodes),
            }
        )

    return run_summaries, issues, episodes, features, queries


def candidate_rows(episodes: list[dict[str, Any]], features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feature_by_episode = {
        str(record.get("incident_episode_id")): record
        for record in features
        if record.get("incident_episode_id")
    }
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        episode_id = str(episode.get("incident_episode_id"))
        feature = feature_by_episode.get(episode_id, {})
        rows.append(
            {
                "candidate_episode_id": episode_id,
                "dataset_run_id": episode.get("dataset_run_id"),
                "scenario_id": episode.get("scenario_id"),
                "scenario_family": scenario_family(episode.get("scenario_id")),
                "severity": episode.get("severity"),
                "incident_type": episode.get("incident_type"),
                "root_cause_category": episode.get("root_cause_category"),
                "jira_candidate": episode.get("jira_candidate"),
                "jira_issue_key": episode.get("jira_issue_key"),
                "affected_services": listify(episode.get("affected_services")),
                "start_time": episode.get("start_time"),
                "end_time": episode.get("end_time"),
                "window_count": feature.get("window_count"),
                "alert_fingerprint_count": feature.get("alert_fingerprint_count"),
                "historical_alert_event_count": feature.get("historical_alert_event_count"),
                "trace_count": feature.get("trace_count"),
                "exact_log_entries": feature.get("exact_log_entries"),
                "service_context_log_entries": feature.get("service_context_log_entries"),
                "namespace_context_log_entries": feature.get("namespace_context_log_entries"),
                "raw_restart_signal": feature.get("raw_restart_signal"),
                "raw_outage_signal": feature.get("raw_outage_signal"),
                "raw_latency_signal": feature.get("raw_latency_signal"),
                "raw_traffic_pressure_signal": feature.get("raw_traffic_pressure_signal"),
                "raw_recovery_complete_signal": feature.get("raw_recovery_complete_signal"),
                "raw_recovery_incomplete_signal": feature.get("raw_recovery_incomplete_signal"),
                "evidence_text": feature.get("evidence_text", ""),
                "raw_evidence_text": feature.get("raw_evidence_text", ""),
            }
        )
    return rows


def augment_examples(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    run_split: dict[str, str],
) -> None:
    query_by_id = {str(row["query_id"]): row for row in queries}
    episode_by_id = {str(row["incident_episode_id"]): row for row in episodes}
    candidate_count = len(episodes)

    for example in examples:
        query_id = str(example["jira_issue_key"])
        query = query_by_id[query_id]
        candidate = episode_by_id[str(example["candidate_episode_id"])]
        query_run_id = str(query["dataset_run_id"])
        candidate_run_id = str(candidate.get("dataset_run_id"))
        same_run = query_run_id == candidate_run_id
        label = int(example.get("label", 0))

        if label == 1:
            scope = "positive"
        elif same_run:
            scope = "same_run_negative"
        else:
            scope = "cross_run_hard_negative"

        example["query_id"] = query_id
        example["query_dataset_run_id"] = query_run_id
        example["original_jira_issue_key"] = query.get("original_jira_issue_key")
        example["candidate_dataset_run_id"] = candidate_run_id
        example["candidate_original_jira_issue_key"] = candidate.get("jira_issue_key")
        example["candidate_same_dataset_run"] = same_run
        example["candidate_scope"] = scope
        example["candidate_scenario_family"] = scenario_family(example.get("candidate_scenario_id"))
        example["candidate_service_overlap_bucket"] = service_overlap_bucket(example.get("raw_telemetry_service_overlap"))
        example["global_candidate_count_for_query"] = candidate_count
        example["split"] = run_split.get(query_run_id, "train")
        example["source_dataset_run_id"] = candidate_run_id
        example["scoring_policy"] = "global_hard_negative_v1_wrapped_label_aware_baseline_v0_and_raw_telemetry_v1"


def split_manifest(global_dataset_id: str, run_ids: list[str], queries: list[dict[str, Any]], run_split: dict[str, str]) -> dict[str, Any]:
    query_ids_by_run: dict[str, list[str]] = {}
    for query in queries:
        query_ids_by_run.setdefault(str(query["dataset_run_id"]), []).append(str(query["query_id"]))

    folds = []
    for test_run_id in run_ids:
        train_run_ids = [run_id for run_id in run_ids if run_id != test_run_id]
        folds.append(
            {
                "fold_id": f"leave-one-query-run-out::{test_run_id}",
                "train_query_dataset_run_ids": train_run_ids,
                "test_query_dataset_run_id": test_run_id,
                "train_query_ids": [
                    query_id
                    for run_id in train_run_ids
                    for query_id in query_ids_by_run.get(run_id, [])
                ],
                "test_query_ids": query_ids_by_run.get(test_run_id, []),
                "candidate_pool": "all selected candidate episodes are available to every query",
            }
        )

    return {
        "global_dataset_id": global_dataset_id,
        "generated_at": utc_now(),
        "split_contract": "split by query dataset run; never split rows from the same Jira query across train and test",
        "candidate_pool_policy": "all selected candidate episodes are paired with every selected Jira query",
        "default_split": {
            "train_dataset_run_ids": [run_id for run_id in run_ids if run_split.get(run_id) == "train"],
            "validation_dataset_run_ids": [run_id for run_id in run_ids if run_split.get(run_id) == "validation"],
            "test_dataset_run_ids": [run_id for run_id in run_ids if run_split.get(run_id) == "test"],
        },
        "leave_one_query_run_out_folds": folds,
        "leakage_guards": [
            "Use query_dataset_run_id for train/validation/test splits.",
            "Do not split individual pair rows randomly.",
            "Do not train production-facing models with candidate labels, scenario ids, root-cause labels, or severity labels unless running a label-aware sanity baseline.",
            "The candidate pool may include episodes from all runs, but train labels must come only from train queries.",
        ],
    }


def pipeline_schema() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "primary_pair_file": "global-ranking-examples.jsonl",
        "query_file": "queries.jsonl",
        "candidate_file": "candidate-episodes.jsonl",
        "label_field": "label",
        "query_id_field": "query_id",
        "candidate_id_field": "candidate_episode_id",
        "split_field": "split",
        "supported_pipeline_tracks": [
            {
                "track": "lexical",
                "examples": ["BM25", "TF-IDF cosine", "query-to-raw-evidence lexical retrieval"],
                "required_files": ["queries.jsonl", "candidate-episodes.jsonl"],
            },
            {
                "track": "classical_ml",
                "examples": ["logistic regression", "linear SVM", "random forest", "gradient boosting"],
                "required_files": ["global-ranking-examples.jsonl", "feature-columns.json"],
            },
            {
                "track": "neural",
                "examples": ["bi-encoder embeddings", "cross-encoder reranker", "MLP over engineered features"],
                "required_files": ["queries.jsonl", "candidate-episodes.jsonl", "global-ranking-examples.jsonl"],
            },
            {
                "track": "language_model",
                "examples": ["LLM zero-shot reranking", "LLM pairwise reranking", "LLM-generated rationale reranking"],
                "required_files": ["queries.jsonl", "candidate-episodes.jsonl", "global-candidate-scores.csv"],
            },
            {
                "track": "hybrid",
                "examples": ["BM25 plus feature ranker", "embedding retrieval plus learned reranker", "LLM reranker over top-k"],
                "required_files": ["global-ranking-examples.jsonl", "queries.jsonl", "candidate-episodes.jsonl"],
            },
        ],
        "recommended_numeric_feature_fields": [
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
            "window_count",
            "alert_fingerprint_count",
            "trace_count",
            "exact_log_entries",
            "service_context_log_entries",
            "namespace_context_log_entries",
        ],
        "production_safe_text_fields": {
            "query": "queries.query_text",
            "candidate": "candidate-episodes.raw_evidence_text",
        },
    }


def feature_columns(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": field,
            "type": "float",
            "source": "global-ranking-examples.jsonl",
            "production_safe": True,
        }
        for field in schema["recommended_numeric_feature_fields"]
    ]


def write_report(
    path: Path,
    global_dataset: dict[str, Any],
    profile_rows: list[dict[str, Any]],
    ablation_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append(f"# Global Hard-Negative Dataset {global_dataset['global_dataset_id']}")
    lines.append("")
    lines.append(f"- Generated at: {global_dataset['generated_at']}")
    lines.append(f"- Builder version: {global_dataset['builder']['version']}")
    lines.append(f"- Dataset runs: {global_dataset['summary']['dataset_run_count']}")
    lines.append(f"- Query issues: {global_dataset['summary']['query_count']}")
    lines.append(f"- Candidate episodes: {global_dataset['summary']['candidate_episode_count']}")
    lines.append(f"- Ranking examples: {global_dataset['summary']['example_count']}")
    lines.append(f"- Positive examples: {global_dataset['summary']['positive_example_count']}")
    lines.append(f"- Cross-run hard negatives: {global_dataset['summary']['cross_run_hard_negative_count']}")
    lines.append("")
    lines.append("## Why This Dataset Exists")
    lines.append("")
    lines.append("Each Jira query is paired with every candidate episode from every selected run. This makes the benchmark harder than the per-run dataset because a model must distinguish same-service incidents, near misses, restarts, outages, and traffic spikes across the whole corpus.")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Profile | Uses candidate labels | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for profile_name, profile in global_dataset["profiles"].items():
        metrics = profile["metrics"]
        lines.append(
            f"| {profile_name} | {profile['uses_candidate_labels']} | {metrics['mrr']} | {metrics['recall_at_1']} | {metrics['recall_at_3']} | {metrics['f1_at_1']} | {metrics['f1_at_3']} | {metrics['ndcg_at_3']} |"
        )
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
    lines.append("## Split Contract")
    lines.append("")
    split = global_dataset["split_manifest"]["default_split"]
    lines.append(f"- Train query runs: {', '.join(split['train_dataset_run_ids'])}")
    lines.append(f"- Validation query runs: {', '.join(split['validation_dataset_run_ids'])}")
    lines.append(f"- Test query runs: {', '.join(split['test_dataset_run_ids'])}")
    lines.append("- Candidate pool: all selected candidate episodes are available to every query.")
    lines.append("- Do not randomly split pair rows; split by `query_dataset_run_id`.")
    lines.append("")
    lines.append("## Raw Telemetry Failure Analysis")
    lines.append("")
    if failure_rows:
        reason_counts = Counter(str(row.get("likely_failure_reason")) for row in failure_rows)
        lines.append("| Likely reason | Count |")
        lines.append("| --- | ---: |")
        for reason, count in reason_counts.most_common():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("No raw telemetry top-1 misses were found.")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("- `global-ranking-examples.jsonl` / `.csv`: pairwise query-candidate rows with labels and numeric features.")
    lines.append("- `queries.jsonl` / `.csv`: one row per Jira query.")
    lines.append("- `candidate-episodes.jsonl` / `.csv`: one row per candidate episode, including text evidence.")
    lines.append("- `split-manifest.json`: train/validation/test and leave-one-run-out split definitions.")
    lines.append("- `pipeline-input-schema.json`: contract for lexical, ML, neural, language-model, and hybrid pipelines.")
    lines.append("")
    lines.append("## Top Raw Telemetry Candidates")
    lines.append("")
    lines.append("| Query | Rank | Candidate scenario | Candidate run | Label | Score |")
    lines.append("| --- | ---: | --- | --- | ---: | ---: |")
    for row in profile_rows:
        if row["profile"] != "raw_telemetry" or int(row["rank"] or 999999) > 3:
            continue
        lines.append(
            f"| {row['query_id']} | {row['rank']} | {row['candidate_scenario_id']} | {row.get('candidate_dataset_run_id')} | {row['label']} | {row['score']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    derived_root = Path(args.derived_root).resolve() if args.derived_root else repo_root / "data" / "derived"
    run_ids = resolve_run_ids(args, derived_root)
    if len(run_ids) < 2:
        raise ValueError("Global hard-negative dataset requires at least two selected runs.")

    global_dataset_id = args.global_dataset_id or "current"
    output_root = (
        Path(args.output_root).resolve()
        if args.output_root
        else derived_root / "global" / global_dataset_id
    )
    if output_root.exists() and args.force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    run_split = default_split_for_run(run_ids)
    run_summaries, issues, episodes, features, queries = load_selected_runs(repo_root, derived_root, run_ids)
    examples, _, _ = build_ranking_examples(issues, episodes, features)
    augment_examples(examples, queries, episodes, run_split)

    metrics_by_profile: dict[str, dict[str, Any]] = {}
    profile_rows: list[dict[str, Any]] = []
    for profile_name, profile in PROFILES.items():
        metrics_by_profile[profile_name] = calculate_metrics(examples, profile["rank_field"])
        rows = profile_score_rows(examples, profile_name, profile)
        for row in rows:
            example_lookup_key = (row.get("query_id"), row.get("candidate_episode_id"))
            # Keep candidate run visible in candidate-score exports.
            matching = next(
                (
                    item
                    for item in examples
                    if item.get("query_id") == example_lookup_key[0]
                    and item.get("candidate_episode_id") == example_lookup_key[1]
                ),
                {},
            )
            row["query_dataset_run_id"] = matching.get("query_dataset_run_id")
            row["candidate_dataset_run_id"] = matching.get("candidate_dataset_run_id")
            row["candidate_scope"] = matching.get("candidate_scope")
            row["split"] = matching.get("split")
        profile_rows.extend(rows)

    feature_by_global_episode = {
        f"{record.get('source_dataset_run_id') or record.get('dataset_run_id')}::{record.get('incident_episode_id')}": record
        for record in features
        if record.get("incident_episode_id")
    }
    ablation_rows, ablation_candidate_rows = build_ablation_reports(examples)
    raw_failure_rows = build_raw_failure_analysis(examples, feature_by_global_episode)
    split = split_manifest(global_dataset_id, run_ids, queries, run_split)
    schema = pipeline_schema()
    candidates = candidate_rows(episodes, features)

    positive_count = sum(int(example.get("label", 0)) for example in examples)
    summary = {
        "dataset_run_count": len(run_ids),
        "query_count": len(queries),
        "candidate_episode_count": len(episodes),
        "example_count": len(examples),
        "positive_example_count": positive_count,
        "negative_example_count": len(examples) - positive_count,
        "same_run_negative_count": sum(1 for example in examples if example.get("candidate_scope") == "same_run_negative"),
        "cross_run_hard_negative_count": sum(1 for example in examples if example.get("candidate_scope") == "cross_run_hard_negative"),
    }

    global_dataset = {
        "global_dataset_id": global_dataset_id,
        "generated_at": utc_now(),
        "builder": {
            "name": "build_global_hard_negative_dataset.py",
            "version": SCRIPT_VERSION,
        },
        "source_dataset_run_ids": run_ids,
        "derived_root": str(derived_root),
        "output_root": str(output_root),
        "dataset_runs": run_summaries,
        "summary": summary,
        "profiles": {
            profile_name: {
                "uses_candidate_labels": PROFILES[profile_name]["uses_candidate_labels"],
                "metrics": metrics,
            }
            for profile_name, metrics in metrics_by_profile.items()
        },
        "ablation_metrics": ablation_rows,
        "raw_telemetry_failure_analysis": raw_failure_rows,
        "split_manifest": split,
        "pipeline_input_schema": schema,
    }

    write_json(output_root / "global-ranking-report.json", global_dataset)
    write_report(output_root / "global-ranking-report.md", global_dataset, profile_rows, ablation_rows, raw_failure_rows)
    write_jsonl(output_root / "global-ranking-examples.jsonl", examples)
    write_csv(output_root / "global-ranking-examples.csv", examples)
    write_csv(output_root / "global-candidate-scores.csv", profile_rows)
    write_csv(output_root / "global-label-aware-candidate-scores.csv", [row for row in profile_rows if row["profile"] == "label_aware_baseline"])
    write_csv(output_root / "global-raw-telemetry-candidate-scores.csv", [row for row in profile_rows if row["profile"] == "raw_telemetry"])
    write_json(output_root / "global-ablation-metrics.json", ablation_rows)
    write_csv(output_root / "global-ablation-metrics.csv", ablation_rows)
    write_csv(output_root / "global-ablation-candidate-scores.csv", ablation_candidate_rows)
    write_json(output_root / "global-raw-telemetry-failure-analysis.json", raw_failure_rows)
    write_csv(output_root / "global-raw-telemetry-failure-analysis.csv", raw_failure_rows)
    write_jsonl(output_root / "queries.jsonl", queries)
    write_csv(output_root / "queries.csv", queries)
    write_jsonl(output_root / "candidate-episodes.jsonl", candidates)
    write_csv(output_root / "candidate-episodes.csv", candidates)
    write_json(output_root / "split-manifest.json", split)
    write_json(output_root / "pipeline-input-schema.json", schema)
    write_json(output_root / "feature-columns.json", feature_columns(schema))
    write_report(output_root / "README.md", global_dataset, profile_rows, ablation_rows, raw_failure_rows)

    return {
        "global_dataset_id": global_dataset_id,
        "output_root": str(output_root),
        "source_dataset_run_ids": run_ids,
        "summary": summary,
        "metrics": global_dataset["profiles"],
        "files_written": [
            "README.md",
            "global-ranking-report.json",
            "global-ranking-report.md",
            "global-ranking-examples.jsonl",
            "global-ranking-examples.csv",
            "global-candidate-scores.csv",
            "global-label-aware-candidate-scores.csv",
            "global-raw-telemetry-candidate-scores.csv",
            "global-ablation-metrics.json",
            "global-ablation-metrics.csv",
            "global-ablation-candidate-scores.csv",
            "global-raw-telemetry-failure-analysis.json",
            "global-raw-telemetry-failure-analysis.csv",
            "queries.jsonl",
            "queries.csv",
            "candidate-episodes.jsonl",
            "candidate-episodes.csv",
            "split-manifest.json",
            "pipeline-input-schema.json",
            "feature-columns.json",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", action="append", default=[])
    parser.add_argument("--dataset-run-prefix")
    parser.add_argument("--corpus-manifest")
    parser.add_argument("--global-dataset-id", default="current")
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
