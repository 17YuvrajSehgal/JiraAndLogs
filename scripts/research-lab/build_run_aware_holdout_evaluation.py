#!/usr/bin/env python3
"""
Build a run-aware holdout evaluation from derived ranking datasets.

This evaluator treats each dataset run as one held-out fold. The current ranker
is deterministic, so the train split is recorded as a leakage guard and future
training contract; no model is fitted here.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_cross_run_evaluation import (
    PROFILES,
    calculate_metrics,
    list_derived_runs,
    load_run,
    profile_score_rows,
    read_json,
    repo_root_from_script,
    write_csv,
    write_json,
)


SCRIPT_VERSION = "0.2.0"
METRIC_FIELDS = ("mrr", "recall_at_1", "recall_at_3", "f1_at_1", "f1_at_3", "ndcg_at_3")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def average_metric_rows(rows: list[dict[str, Any]], profile_name: str) -> dict[str, Any]:
    profile_rows = [row for row in rows if row["profile"] == profile_name]
    if not profile_rows:
        return {
            "fold_count": 0,
            "query_count": 0,
            "example_count": 0,
            "positive_example_count": 0,
            "negative_example_count": 0,
            **{field: 0.0 for field in METRIC_FIELDS},
        }
    return {
        "fold_count": len(profile_rows),
        "query_count": sum(int(row["query_count"]) for row in profile_rows),
        "example_count": sum(int(row["example_count"]) for row in profile_rows),
        "positive_example_count": sum(int(row["positive_example_count"]) for row in profile_rows),
        "negative_example_count": sum(int(row["negative_example_count"]) for row in profile_rows),
        **{
            field: round(sum(float(row[field]) for row in profile_rows) / len(profile_rows), 6)
            for field in METRIC_FIELDS
        },
    }


def write_report(path: Path, evaluation: dict[str, Any], fold_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append(f"# Run-Aware Holdout Evaluation {evaluation['evaluation_id']}")
    lines.append("")
    lines.append(f"- Generated at: {evaluation['generated_at']}")
    lines.append(f"- Builder version: {evaluation['builder']['version']}")
    lines.append(f"- Dataset runs: {len(evaluation['dataset_runs'])}")
    lines.append(f"- Fold count: {evaluation['summary']['fold_count']}")
    lines.append(f"- Query issues: {evaluation['summary']['query_count']}")
    lines.append(f"- Ranking examples: {evaluation['summary']['example_count']}")
    lines.append("")
    lines.append("## Protocol")
    lines.append("")
    lines.append("Each fold holds out exactly one dataset run and records all other selected runs as the train split. The current scorer is deterministic, so no model is fitted; this report evaluates frozen per-run scores and establishes the split contract for the future supervised ranker.")
    lines.append("")
    lines.append("## Dataset Runs")
    lines.append("")
    lines.append("| Run | Raw tree SHA256 | Examples |")
    lines.append("| --- | --- | ---: |")
    for run in evaluation["dataset_runs"]:
        lines.append(f"| {run['dataset_run_id']} | `{run.get('raw_tree_sha256')}` | {run['example_count']} |")
    lines.append("")
    lines.append("## Summary Metrics")
    lines.append("")
    lines.append("| Profile | Uses candidate labels | Pooled MRR | Pooled Recall@1 | Pooled Recall@3 | Pooled F1@1 | Pooled F1@3 | Pooled nDCG@3 | Macro MRR | Macro Recall@1 | Macro Recall@3 | Macro F1@1 | Macro F1@3 | Macro nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for profile_name, profile in evaluation["profiles"].items():
        pooled = profile["pooled_metrics"]
        macro = profile["macro_fold_metrics"]
        lines.append(
            f"| {profile_name} | {profile['uses_candidate_labels']} | {pooled['mrr']} | {pooled['recall_at_1']} | {pooled['recall_at_3']} | {pooled['f1_at_1']} | {pooled['f1_at_3']} | {pooled['ndcg_at_3']} | {macro['mrr']} | {macro['recall_at_1']} | {macro['recall_at_3']} | {macro['f1_at_1']} | {macro['f1_at_3']} | {macro['ndcg_at_3']} |"
        )
    lines.append("")
    lines.append("F1@k is computed per Jira query with one relevant episode. A top-k hit has Precision@k = 1/k and Recall@k = 1, then the per-query harmonic mean is averaged across queries.")
    lines.append("")
    lines.append("## Fold Metrics")
    lines.append("")
    lines.append("| Test run | Profile | Queries | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in fold_rows:
        lines.append(
            f"| {row['test_dataset_run_id']} | {row['profile']} | {row['query_count']} | {row['mrr']} | {row['recall_at_1']} | {row['recall_at_3']} | {row['f1_at_1']} | {row['f1_at_3']} | {row['ndcg_at_3']} |"
        )
    lines.append("")
    lines.append("## Raw Telemetry Top Candidates")
    lines.append("")
    lines.append("| Fold | Query | Rank | Candidate scenario | Label | Score |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: |")
    for row in candidate_rows:
        if row["profile"] != "raw_telemetry" or int(row["rank"] or 999999) > 3:
            continue
        lines.append(
            f"| {row['fold_id']} | {row['query_id']} | {row['rank']} | {row['candidate_scenario_id']} | {row['label']} | {row['score']} |"
        )
    lines.append("")
    lines.append("## Caveat")
    lines.append("")
    lines.append(f"With only {len(evaluation['dataset_runs'])} selected runs, this is a pilot holdout check. Use it to catch leakage and regression issues. Do not treat it as a final product or paper claim until more runs and fault families are included.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    derived_root = Path(args.derived_root).resolve() if args.derived_root else repo_root / "data" / "derived"
    run_ids = args.dataset_run_id or list_derived_runs(derived_root)
    if len(run_ids) < 2:
        raise ValueError("Run-aware holdout evaluation requires at least two derived dataset runs.")

    evaluation_id = args.evaluation_id or "current"
    output_root = (
        Path(args.output_root).resolve()
        if args.output_root
        else derived_root / "holdout" / evaluation_id
    )
    if output_root.exists() and args.force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    run_summaries: list[dict[str, Any]] = []
    examples_by_run: dict[str, list[dict[str, Any]]] = {}
    for run_id in run_ids:
        run_summary, examples = load_run(derived_root, run_id)
        run_summaries.append(run_summary)
        examples_by_run[run_id] = examples

    all_examples = [example for run_examples in examples_by_run.values() for example in run_examples]
    fold_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    split_manifest = {
        "evaluation_id": evaluation_id,
        "generated_at": utc_now(),
        "split_type": "leave_one_dataset_run_out",
        "folds": [],
    }

    for test_run_id in run_ids:
        train_run_ids = [run_id for run_id in run_ids if run_id != test_run_id]
        test_examples = examples_by_run[test_run_id]
        fold_id = f"holdout::{test_run_id}"
        train_query_ids = {
            str(example["query_id"])
            for run_id in train_run_ids
            for example in examples_by_run[run_id]
        }
        test_query_ids = {str(example["query_id"]) for example in test_examples}
        query_overlap = sorted(train_query_ids & test_query_ids)
        split_manifest["folds"].append(
            {
                "fold_id": fold_id,
                "train_dataset_run_ids": train_run_ids,
                "test_dataset_run_id": test_run_id,
                "train_query_count": len(train_query_ids),
                "test_query_count": len(test_query_ids),
                "train_test_query_overlap_count": len(query_overlap),
                "train_test_query_overlap": query_overlap,
            }
        )

        for profile_name, profile in PROFILES.items():
            metrics = calculate_metrics(test_examples, profile["rank_field"])
            fold_rows.append(
                {
                    "fold_id": fold_id,
                    "profile": profile_name,
                    "uses_candidate_labels": profile["uses_candidate_labels"],
                    "test_dataset_run_id": test_run_id,
                    "train_dataset_run_ids": train_run_ids,
                    **{key: metrics[key] for key in ("query_count", "example_count", "positive_example_count", "negative_example_count")},
                    **{field: metrics[field] for field in METRIC_FIELDS},
                }
            )
            for row in profile_score_rows(test_examples, profile_name, profile):
                row["fold_id"] = fold_id
                row["test_dataset_run_id"] = test_run_id
                row["train_dataset_run_ids"] = train_run_ids
                candidate_rows.append(row)

    profiles: dict[str, dict[str, Any]] = {}
    for profile_name, profile in PROFILES.items():
        profiles[profile_name] = {
            "uses_candidate_labels": profile["uses_candidate_labels"],
            "pooled_metrics": calculate_metrics(all_examples, profile["rank_field"]),
            "macro_fold_metrics": average_metric_rows(fold_rows, profile_name),
        }

    evaluation = {
        "evaluation_id": evaluation_id,
        "generated_at": utc_now(),
        "builder": {
            "name": "build_run_aware_holdout_evaluation.py",
            "version": SCRIPT_VERSION,
        },
        "derived_root": str(derived_root),
        "output_root": str(output_root),
        "dataset_runs": run_summaries,
        "summary": {
            "dataset_run_count": len(run_ids),
            "fold_count": len(run_ids),
            "query_count": len({str(example["query_id"]) for example in all_examples}),
            "example_count": len(all_examples),
            "positive_example_count": sum(int(example.get("label", 0)) for example in all_examples),
            "negative_example_count": sum(1 - int(example.get("label", 0)) for example in all_examples),
        },
        "profiles": profiles,
        "split_manifest_path": str(output_root / "split-manifest.json"),
    }

    write_json(output_root / "run-aware-holdout-evaluation.json", evaluation)
    write_json(output_root / "split-manifest.json", split_manifest)
    write_csv(output_root / "fold-metrics.csv", fold_rows)
    write_csv(output_root / "holdout-candidate-scores.csv", candidate_rows)
    write_report(output_root / "run-aware-holdout-evaluation.md", evaluation, fold_rows, candidate_rows)

    return {
        "evaluation_id": evaluation_id,
        "output_root": str(output_root),
        "dataset_run_ids": run_ids,
        "profiles": profiles,
        "files_written": [
            "run-aware-holdout-evaluation.json",
            "run-aware-holdout-evaluation.md",
            "split-manifest.json",
            "fold-metrics.csv",
            "holdout-candidate-scores.csv",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", action="append", default=[])
    parser.add_argument("--evaluation-id")
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
