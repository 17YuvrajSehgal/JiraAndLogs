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
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "0.1.0"

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


def ndcg_for_single_positive(rank: int | None) -> float:
    if rank is None:
        return 0.0
    import math

    return 1.0 / math.log2(rank + 1)


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


def rank_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    query_count = len(grouped)
    return {
        "query_count": query_count,
        "example_count": len(examples),
        "positive_example_count": sum(int(example.get("label", 0)) for example in examples),
        "negative_example_count": sum(1 - int(example.get("label", 0)) for example in examples),
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
        "ndcg_at_3": round(
            sum(ndcg_for_single_positive(rank) if rank is not None and rank <= 3 else 0.0 for rank in ranks_by_query.values())
            / max(1, query_count),
            6,
        ),
        "true_rank_by_query": ranks_by_query,
    }


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


def write_report(path: Path, aggregate: dict[str, Any], profile_scores: list[dict[str, Any]]) -> None:
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
    lines.append("| Profile | Uses candidate labels | MRR | Recall@1 | Recall@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for profile_name, profile in aggregate["profiles"].items():
        metrics = profile["metrics"]
        lines.append(
            f"| {profile_name} | {profile['uses_candidate_labels']} | {metrics['mrr']} | {metrics['recall_at_1']} | {metrics['recall_at_3']} | {metrics['ndcg_at_3']} |"
        )
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
    for run_id in run_ids:
        run_summary, examples = load_run(derived_root, run_id)
        run_summaries.append(run_summary)
        combined_examples.extend(examples)

    metrics_by_profile: dict[str, dict[str, Any]] = {}
    profile_rows: list[dict[str, Any]] = []
    for profile_name, profile in PROFILES.items():
        metrics_by_profile[profile_name] = calculate_metrics(combined_examples, profile["rank_field"])
        profile_rows.extend(profile_score_rows(combined_examples, profile_name, profile))

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
    }

    write_json(output_root / "cross-run-evaluation.json", aggregate)
    write_jsonl(output_root / "combined-ranking-examples.jsonl", combined_examples)
    write_csv(output_root / "combined-ranking-examples.csv", combined_examples)
    write_csv(output_root / "cross-run-candidate-scores.csv", profile_rows)
    write_report(output_root / "cross-run-evaluation.md", aggregate, profile_rows)

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
