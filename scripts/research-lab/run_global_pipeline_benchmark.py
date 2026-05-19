#!/usr/bin/env python3
"""
Run baseline pipeline benchmarks on a global hard-negative dataset.

This is the first benchmark harness for comparing different ranking approaches
against the same query-candidate pool and split contract. It intentionally uses
only the Python standard library so the initial lexical, heuristic, hybrid, and
classical ML checks can run before adding heavier neural or LLM dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from build_cross_run_evaluation import metrics_from_ranks
from build_ranking_dataset import bm25_scores, tokenize


SCRIPT_VERSION = "0.1.0"
METRIC_FIELDS = ("mrr", "recall_at_1", "recall_at_3", "f1_at_1", "f1_at_3", "ndcg_at_3")


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


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def load_global_dataset(global_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    examples = read_jsonl(global_root / "global-ranking-examples.jsonl")
    queries = read_jsonl(global_root / "queries.jsonl")
    candidates = read_jsonl(global_root / "candidate-episodes.jsonl")
    schema = read_json(global_root / "pipeline-input-schema.json")
    split = read_json(global_root / "split-manifest.json")
    return examples, queries, candidates, schema, split


def examples_by_query(examples: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[str(example["query_id"])].append(example)
    return grouped


def metrics_for_scores(examples: list[dict[str, Any]], score_by_pair: dict[tuple[str, str], float]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped = examples_by_query(examples)
    ranks_by_query: dict[str, int | None] = {}
    rows: list[dict[str, Any]] = []
    for query_id, query_examples in grouped.items():
        ranked = sorted(
            query_examples,
            key=lambda row: (
                -score_by_pair.get((str(row["query_id"]), str(row["candidate_episode_id"])), 0.0),
                str(row["candidate_episode_id"]),
            ),
        )
        true_rank: int | None = None
        for rank, row in enumerate(ranked, start=1):
            score = round(score_by_pair.get((str(row["query_id"]), str(row["candidate_episode_id"])), 0.0), 6)
            if int(row.get("label", 0)) == 1 and true_rank is None:
                true_rank = rank
            rows.append(
                {
                    "query_id": query_id,
                    "query_dataset_run_id": row.get("query_dataset_run_id"),
                    "split": row.get("split"),
                    "rank": rank,
                    "candidate_episode_id": row.get("candidate_episode_id"),
                    "candidate_dataset_run_id": row.get("candidate_dataset_run_id"),
                    "candidate_scenario_id": row.get("candidate_scenario_id"),
                    "candidate_scope": row.get("candidate_scope"),
                    "label": int(row.get("label", 0)),
                    "score": score,
                }
            )
        ranks_by_query[query_id] = true_rank
    metrics = metrics_from_ranks(
        ranks_by_query=ranks_by_query,
        example_count=len(examples),
        positive_example_count=sum(int(row.get("label", 0)) for row in examples),
    )
    return metrics, rows


def split_metrics(examples: list[dict[str, Any]], score_by_pair: dict[tuple[str, str], float]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for split_name in ("train", "validation", "test"):
        split_examples = [row for row in examples if row.get("split") == split_name]
        if split_examples:
            result[split_name], _ = metrics_for_scores(split_examples, score_by_pair)
    return result


def raw_telemetry_scores(examples: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {
        (str(row["query_id"]), str(row["candidate_episode_id"])): safe_float(row.get("raw_telemetry_score"))
        for row in examples
    }


def lexical_bm25_scores(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[tuple[str, str], float]:
    query_by_id = {str(row["query_id"]): str(row.get("query_text", "")) for row in queries}
    documents = {
        str(row["candidate_episode_id"]): tokenize(str(row.get("raw_evidence_text", "")))
        for row in candidates
    }
    scores: dict[tuple[str, str], float] = {}
    candidate_ids = list(documents)
    for query_id, query_text in query_by_id.items():
        raw_scores = bm25_scores(documents, tokenize(query_text))
        max_score = max(raw_scores.values()) if raw_scores else 0.0
        for candidate_id in candidate_ids:
            normalized = raw_scores.get(candidate_id, 0.0) / max_score if max_score > 0 else 0.0
            scores[(query_id, candidate_id)] = normalized
    # Restrict to actual pair rows in case a caller supplied a subset.
    pair_keys = {(str(row["query_id"]), str(row["candidate_episode_id"])) for row in examples}
    return {key: score for key, score in scores.items() if key in pair_keys}


def hybrid_scores(
    examples: list[dict[str, Any]],
    lexical_scores: dict[tuple[str, str], float],
    raw_scores: dict[tuple[str, str], float],
) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = {}
    for row in examples:
        key = (str(row["query_id"]), str(row["candidate_episode_id"]))
        scores[key] = (0.55 * lexical_scores.get(key, 0.0)) + (0.45 * raw_scores.get(key, 0.0))
    return scores


def train_numeric_logistic(
    examples: list[dict[str, Any]],
    feature_fields: list[str],
    epochs: int = 600,
    learning_rate: float = 0.25,
    l2: float = 0.001,
) -> dict[str, Any]:
    train_rows = [row for row in examples if row.get("split") == "train"]
    if not train_rows:
        raise ValueError("Cannot train logistic baseline: no train rows found.")

    means: list[float] = []
    stds: list[float] = []
    for field in feature_fields:
        values = [safe_float(row.get(field)) for row in train_rows]
        mean = sum(values) / max(1, len(values))
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
        std = math.sqrt(variance) or 1.0
        means.append(mean)
        stds.append(std)

    def vector(row: dict[str, Any]) -> list[float]:
        return [
            (safe_float(row.get(field)) - means[index]) / stds[index]
            for index, field in enumerate(feature_fields)
        ]

    x_train = [vector(row) for row in train_rows]
    y_train = [int(row.get("label", 0)) for row in train_rows]
    positives = sum(y_train)
    negatives = len(y_train) - positives
    positive_weight = negatives / max(1, positives)
    weights = [0.0 for _ in feature_fields]
    bias = 0.0

    for _ in range(epochs):
        grad_w = [0.0 for _ in weights]
        grad_b = 0.0
        total_weight = 0.0
        for features, label in zip(x_train, y_train):
            z = bias + sum(weight * value for weight, value in zip(weights, features))
            pred = sigmoid(z)
            row_weight = positive_weight if label == 1 else 1.0
            error = (pred - label) * row_weight
            total_weight += row_weight
            grad_b += error
            for index, value in enumerate(features):
                grad_w[index] += error * value
        denom = max(1.0, total_weight)
        bias -= learning_rate * (grad_b / denom)
        for index in range(len(weights)):
            grad = (grad_w[index] / denom) + (l2 * weights[index])
            weights[index] -= learning_rate * grad

    scores: dict[tuple[str, str], float] = {}
    for row in examples:
        features = vector(row)
        z = bias + sum(weight * value for weight, value in zip(weights, features))
        scores[(str(row["query_id"]), str(row["candidate_episode_id"]))] = sigmoid(z)

    coefficients = [
        {
            "feature": field,
            "coefficient": round(weights[index], 6),
            "train_mean": round(means[index], 6),
            "train_std": round(stds[index], 6),
        }
        for index, field in enumerate(feature_fields)
    ]
    coefficients.sort(key=lambda row: abs(float(row["coefficient"])), reverse=True)
    return {
        "scores": scores,
        "model": {
            "type": "standardized_batch_logistic_regression",
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2": l2,
            "positive_weight": round(positive_weight, 6),
            "bias": round(bias, 6),
            "coefficients": coefficients,
        },
    }


def write_report(path: Path, benchmark: dict[str, Any], candidate_rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append(f"# Global Pipeline Benchmark {benchmark['benchmark_id']}")
    lines.append("")
    lines.append(f"- Generated at: {benchmark['generated_at']}")
    lines.append(f"- Builder version: {benchmark['builder']['version']}")
    lines.append(f"- Global dataset: {benchmark['global_dataset_id']}")
    lines.append(f"- Query count: {benchmark['summary']['query_count']}")
    lines.append(f"- Candidate episodes: {benchmark['summary']['candidate_episode_count']}")
    lines.append(f"- Pair rows: {benchmark['summary']['example_count']}")
    lines.append("")
    lines.append("## Overall Metrics")
    lines.append("")
    lines.append("| Pipeline | Family | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for pipeline in benchmark["pipelines"]:
        metrics = pipeline["overall_metrics"]
        lines.append(
            f"| {pipeline['pipeline_id']} | {pipeline['family']} | {metrics['mrr']} | {metrics['recall_at_1']} | {metrics['recall_at_3']} | {metrics['f1_at_1']} | {metrics['f1_at_3']} | {metrics['ndcg_at_3']} |"
        )
    lines.append("")
    lines.append("## Split Metrics")
    lines.append("")
    lines.append("| Pipeline | Split | Queries | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for pipeline in benchmark["pipelines"]:
        for split_name, metrics in pipeline["split_metrics"].items():
            lines.append(
                f"| {pipeline['pipeline_id']} | {split_name} | {metrics['query_count']} | {metrics['mrr']} | {metrics['recall_at_1']} | {metrics['recall_at_3']} | {metrics['f1_at_1']} | {metrics['f1_at_3']} | {metrics['ndcg_at_3']} |"
            )
    lines.append("")
    lines.append("## Top Test Candidates")
    lines.append("")
    lines.append("| Pipeline | Query | Rank | Candidate scenario | Label | Score |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: |")
    for row in candidate_rows:
        if row.get("split") != "test" or int(row.get("rank", 999999)) > 3:
            continue
        lines.append(
            f"| {row['pipeline_id']} | {row['query_id']} | {row['rank']} | {row['candidate_scenario_id']} | {row['label']} | {row['score']} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- The logistic baseline is intentionally simple and dependency-free. It is a contract test for classical ML pipelines, not a final model.")
    lines.append("- Neural and language-model pipelines should reuse the same dataset files, splits, and metrics.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    global_root = (
        Path(args.global_root).resolve()
        if args.global_root
        else repo_root / "data" / "derived" / "global" / args.global_dataset_id
    )
    if not global_root.exists():
        raise FileNotFoundError(f"Global dataset root does not exist: {global_root}")

    benchmark_id = args.benchmark_id or "current"
    output_root = (
        Path(args.output_root).resolve()
        if args.output_root
        else global_root / "benchmarks" / benchmark_id
    )
    if output_root.exists() and args.force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    examples, queries, candidates, schema, split = load_global_dataset(global_root)
    feature_fields = list(schema.get("recommended_numeric_feature_fields", []))
    if not feature_fields:
        raise ValueError("pipeline-input-schema.json does not define recommended_numeric_feature_fields.")

    raw_scores = raw_telemetry_scores(examples)
    lexical_scores = lexical_bm25_scores(examples, queries, candidates)
    hybrid = hybrid_scores(examples, lexical_scores, raw_scores)
    logistic = train_numeric_logistic(examples, feature_fields)

    pipeline_specs = [
        {
            "pipeline_id": "raw_telemetry_existing",
            "family": "heuristic",
            "description": "Existing deterministic production-facing raw telemetry score.",
            "scores": raw_scores,
            "model": None,
        },
        {
            "pipeline_id": "bm25_raw_evidence",
            "family": "lexical",
            "description": "BM25 between Jira query text and candidate raw telemetry evidence text.",
            "scores": lexical_scores,
            "model": None,
        },
        {
            "pipeline_id": "hybrid_bm25_raw_telemetry",
            "family": "hybrid",
            "description": "Weighted score fusion: 55% BM25 raw evidence and 45% existing raw telemetry score.",
            "scores": hybrid,
            "model": {"weights": {"bm25_raw_evidence": 0.55, "raw_telemetry_existing": 0.45}},
        },
        {
            "pipeline_id": "logistic_numeric_features",
            "family": "classical_ml",
            "description": "Dependency-free logistic regression over production-safe numeric telemetry features.",
            "scores": logistic["scores"],
            "model": logistic["model"],
        },
    ]

    pipelines: list[dict[str, Any]] = []
    all_candidate_rows: list[dict[str, Any]] = []
    for spec in pipeline_specs:
        overall_metrics, rows = metrics_for_scores(examples, spec["scores"])
        for row in rows:
            row["pipeline_id"] = spec["pipeline_id"]
            row["family"] = spec["family"]
        all_candidate_rows.extend(rows)
        pipelines.append(
            {
                "pipeline_id": spec["pipeline_id"],
                "family": spec["family"],
                "description": spec["description"],
                "overall_metrics": overall_metrics,
                "split_metrics": split_metrics(examples, spec["scores"]),
                "model": spec["model"],
            }
        )

    benchmark = {
        "benchmark_id": benchmark_id,
        "global_dataset_id": args.global_dataset_id,
        "generated_at": utc_now(),
        "builder": {
            "name": "run_global_pipeline_benchmark.py",
            "version": SCRIPT_VERSION,
        },
        "global_root": str(global_root),
        "output_root": str(output_root),
        "split_manifest": split,
        "summary": {
            "query_count": len({str(row["query_id"]) for row in examples}),
            "candidate_episode_count": len(candidates),
            "example_count": len(examples),
            "positive_example_count": sum(int(row.get("label", 0)) for row in examples),
        },
        "pipelines": pipelines,
    }

    write_json(output_root / "benchmark-report.json", benchmark)
    write_report(output_root / "benchmark-report.md", benchmark, all_candidate_rows)
    write_csv(output_root / "benchmark-candidate-scores.csv", all_candidate_rows)
    write_json(output_root / "logistic-numeric-model.json", logistic["model"])

    return {
        "benchmark_id": benchmark_id,
        "output_root": str(output_root),
        "global_dataset_id": args.global_dataset_id,
        "pipelines": [
            {
                "pipeline_id": pipeline["pipeline_id"],
                "family": pipeline["family"],
                "overall_metrics": pipeline["overall_metrics"],
                "test_metrics": pipeline["split_metrics"].get("test", {}),
            }
            for pipeline in pipelines
        ],
        "files_written": [
            "benchmark-report.json",
            "benchmark-report.md",
            "benchmark-candidate-scores.csv",
            "logistic-numeric-model.json",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-dataset-id", default="current")
    parser.add_argument("--benchmark-id", default="current")
    parser.add_argument("--global-root")
    parser.add_argument("--repo-root")
    parser.add_argument("--output-root")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
