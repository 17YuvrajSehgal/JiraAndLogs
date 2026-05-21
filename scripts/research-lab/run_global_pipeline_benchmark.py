#!/usr/bin/env python3
"""
Run pipeline benchmarks on a global hard-negative dataset.

This benchmark harness compares heuristic, lexical, classical ML, pairwise
ranking, and hybrid approaches against the same query-candidate pool and split
contract. It intentionally uses only the Python standard library so it can run
on the VM while the large dataset collection is in progress. Neural and LLM
pipelines can be added later behind the same dataset and metric contract.
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


SCRIPT_VERSION = "0.2.0"
METRIC_FIELDS = ("mrr", "recall_at_1", "recall_at_3", "f1_at_1", "f1_at_3", "ndcg_at_3")
TEXT_SCORE_FIELDS = (
    "raw_telemetry_existing_score",
    "bm25_raw_evidence_score",
    "tfidf_raw_evidence_score",
)

ScoreMap = dict[tuple[str, str], float]


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


def pair_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["query_id"]), str(row["candidate_episode_id"])


def row_query_id(row: dict[str, Any]) -> str:
    return str(row["query_id"])


def load_global_dataset(
    global_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    examples = read_jsonl(global_root / "global-ranking-examples.jsonl")
    queries = read_jsonl(global_root / "queries.jsonl")
    candidates = read_jsonl(global_root / "candidate-episodes.jsonl")
    schema = read_json(global_root / "pipeline-input-schema.json")
    split = read_json(global_root / "split-manifest.json")
    return examples, queries, candidates, schema, split


def examples_by_query(examples: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped[row_query_id(example)].append(example)
    return grouped


def subset_by_query_ids(examples: list[dict[str, Any]], query_ids: set[str]) -> list[dict[str, Any]]:
    return [row for row in examples if row_query_id(row) in query_ids]


def metrics_for_scores(examples: list[dict[str, Any]], score_by_pair: ScoreMap) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped = examples_by_query(examples)
    ranks_by_query: dict[str, int | None] = {}
    rows: list[dict[str, Any]] = []
    for query_id, query_examples in grouped.items():
        ranked = sorted(
            query_examples,
            key=lambda row: (
                -score_by_pair.get(pair_key(row), 0.0),
                str(row["candidate_episode_id"]),
            ),
        )
        true_rank: int | None = None
        for rank, row in enumerate(ranked, start=1):
            score = round(score_by_pair.get(pair_key(row), 0.0), 6)
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


def split_metrics(examples: list[dict[str, Any]], score_by_pair: ScoreMap) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for split_name in ("train", "validation", "test"):
        split_examples = [row for row in examples if row.get("split") == split_name]
        if split_examples:
            result[split_name], _ = metrics_for_scores(split_examples, score_by_pair)
    return result


def macro_average_metrics(fold_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not fold_rows:
        return {"fold_count": 0}
    result: dict[str, Any] = {
        "fold_count": len(fold_rows),
        "query_count": sum(int(row.get("query_count", 0)) for row in fold_rows),
        "example_count": sum(int(row.get("example_count", 0)) for row in fold_rows),
        "positive_example_count": sum(int(row.get("positive_example_count", 0)) for row in fold_rows),
    }
    result["negative_example_count"] = result["example_count"] - result["positive_example_count"]
    for field in METRIC_FIELDS:
        result[field] = round(sum(safe_float(row.get(field)) for row in fold_rows) / len(fold_rows), 6)
    return result


def leave_one_query_run_out_metrics(
    examples: list[dict[str, Any]],
    split_manifest: dict[str, Any],
    score_builder: Any,
) -> dict[str, Any]:
    fold_metric_rows: list[dict[str, Any]] = []
    for fold in split_manifest.get("leave_one_query_run_out_folds", []):
        train_query_ids = {str(value) for value in fold.get("train_query_ids", [])}
        test_query_ids = {str(value) for value in fold.get("test_query_ids", [])}
        if not train_query_ids or not test_query_ids:
            continue
        fold_scores = score_builder(train_query_ids)
        test_examples = subset_by_query_ids(examples, test_query_ids)
        metrics, _ = metrics_for_scores(test_examples, fold_scores)
        fold_metric_rows.append(
            {
                "fold_id": fold.get("fold_id"),
                "test_query_dataset_run_id": fold.get("test_query_dataset_run_id"),
                **{field: metrics.get(field) for field in ("query_count", "example_count", "positive_example_count", "negative_example_count")},
                **{field: metrics.get(field) for field in METRIC_FIELDS},
            }
        )
    return {
        "macro_metrics": macro_average_metrics(fold_metric_rows),
        "folds": fold_metric_rows,
    }


def raw_telemetry_scores(examples: list[dict[str, Any]]) -> ScoreMap:
    return {pair_key(row): safe_float(row.get("raw_telemetry_score")) for row in examples}


def lexical_bm25_scores(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> ScoreMap:
    query_by_id = {str(row["query_id"]): str(row.get("query_text", "")) for row in queries}
    documents = {
        str(row["candidate_episode_id"]): tokenize(str(row.get("raw_evidence_text", "")))
        for row in candidates
    }
    scores: ScoreMap = {}
    candidate_ids = list(documents)
    for query_id, query_text in query_by_id.items():
        raw_scores = bm25_scores(documents, tokenize(query_text))
        max_score = max(raw_scores.values()) if raw_scores else 0.0
        for candidate_id in candidate_ids:
            normalized = raw_scores.get(candidate_id, 0.0) / max_score if max_score > 0 else 0.0
            scores[(query_id, candidate_id)] = normalized
    pair_keys = {pair_key(row) for row in examples}
    return {key: score for key, score in scores.items() if key in pair_keys}


def tfidf_cosine_scores(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> ScoreMap:
    query_by_id = {str(row["query_id"]): tokenize(str(row.get("query_text", ""))) for row in queries}
    document_tokens = {
        str(row["candidate_episode_id"]): tokenize(str(row.get("raw_evidence_text", "")))
        for row in candidates
    }
    doc_count = max(1, len(document_tokens))
    document_frequency: Counter[str] = Counter()
    for tokens in document_tokens.values():
        document_frequency.update(set(tokens))

    def idf(token: str) -> float:
        return math.log((1.0 + doc_count) / (1.0 + document_frequency.get(token, 0))) + 1.0

    def vector(tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        return {
            token: (1.0 + math.log(count)) * idf(token)
            for token, count in counts.items()
            if count > 0
        }

    def cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        numerator = sum(value * right.get(token, 0.0) for token, value in left.items())
        if numerator <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    document_vectors = {candidate_id: vector(tokens) for candidate_id, tokens in document_tokens.items()}
    scores: ScoreMap = {}
    pair_keys = {pair_key(row) for row in examples}
    for query_id, tokens in query_by_id.items():
        query_vector = vector(tokens)
        for candidate_id, document_vector in document_vectors.items():
            key = (query_id, candidate_id)
            if key in pair_keys:
                scores[key] = cosine(query_vector, document_vector)
    return scores


def min_max_normalize_by_query(examples: list[dict[str, Any]], score_by_pair: ScoreMap) -> ScoreMap:
    normalized: ScoreMap = {}
    for _, query_examples in examples_by_query(examples).items():
        keys = [pair_key(row) for row in query_examples]
        values = [score_by_pair.get(key, 0.0) for key in keys]
        low = min(values) if values else 0.0
        high = max(values) if values else 0.0
        spread = high - low
        for key in keys:
            normalized[key] = (score_by_pair.get(key, 0.0) - low) / spread if spread > 0 else 0.0
    return normalized


def weighted_sum_scores(
    examples: list[dict[str, Any]],
    weighted_maps: list[tuple[float, ScoreMap]],
) -> ScoreMap:
    scores: ScoreMap = {}
    for row in examples:
        key = pair_key(row)
        scores[key] = sum(weight * score_map.get(key, 0.0) for weight, score_map in weighted_maps)
    return scores


def ranks_for_score_map(examples: list[dict[str, Any]], score_by_pair: ScoreMap) -> dict[tuple[str, str], int]:
    ranks: dict[tuple[str, str], int] = {}
    for _, query_examples in examples_by_query(examples).items():
        ranked = sorted(
            query_examples,
            key=lambda row: (
                -score_by_pair.get(pair_key(row), 0.0),
                str(row["candidate_episode_id"]),
            ),
        )
        for rank, row in enumerate(ranked, start=1):
            ranks[pair_key(row)] = rank
    return ranks


def reciprocal_rank_fusion_scores(
    examples: list[dict[str, Any]],
    weighted_maps: list[tuple[str, float, ScoreMap]],
    rank_k: int = 60,
) -> ScoreMap:
    rank_maps = [
        (name, weight, ranks_for_score_map(examples, score_map))
        for name, weight, score_map in weighted_maps
    ]
    scores: ScoreMap = {}
    for row in examples:
        key = pair_key(row)
        score = 0.0
        for _, weight, rank_map in rank_maps:
            rank = rank_map.get(key)
            if rank is not None:
                score += weight / (rank_k + rank)
        scores[key] = score
    return scores


def feature_value(row: dict[str, Any], field: str, auxiliary_scores: dict[str, ScoreMap]) -> float:
    if field in auxiliary_scores:
        return auxiliary_scores[field].get(pair_key(row), 0.0)
    return safe_float(row.get(field))


def training_rows_for_queries(
    examples: list[dict[str, Any]],
    train_query_ids: set[str] | None,
) -> list[dict[str, Any]]:
    if train_query_ids is not None:
        return [row for row in examples if row_query_id(row) in train_query_ids]
    return [row for row in examples if row.get("split") == "train"]


def standardization(
    train_rows: list[dict[str, Any]],
    feature_fields: list[str],
    auxiliary_scores: dict[str, ScoreMap],
) -> tuple[list[float], list[float]]:
    means: list[float] = []
    stds: list[float] = []
    for field in feature_fields:
        values = [feature_value(row, field, auxiliary_scores) for row in train_rows]
        mean = sum(values) / max(1, len(values))
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
        std = math.sqrt(variance) or 1.0
        means.append(mean)
        stds.append(std)
    return means, stds


def standardized_vector(
    row: dict[str, Any],
    feature_fields: list[str],
    auxiliary_scores: dict[str, ScoreMap],
    means: list[float],
    stds: list[float],
) -> list[float]:
    return [
        (feature_value(row, field, auxiliary_scores) - means[index]) / stds[index]
        for index, field in enumerate(feature_fields)
    ]


def coefficient_rows(
    feature_fields: list[str],
    weights: list[float],
    means: list[float],
    stds: list[float],
) -> list[dict[str, Any]]:
    rows = [
        {
            "feature": field,
            "coefficient": round(weights[index], 6),
            "train_mean": round(means[index], 6),
            "train_std": round(stds[index], 6),
        }
        for index, field in enumerate(feature_fields)
    ]
    rows.sort(key=lambda row: abs(float(row["coefficient"])), reverse=True)
    return rows


def train_logistic_model(
    examples: list[dict[str, Any]],
    feature_fields: list[str],
    auxiliary_scores: dict[str, ScoreMap] | None = None,
    train_query_ids: set[str] | None = None,
    epochs: int = 600,
    learning_rate: float = 0.25,
    l2: float = 0.001,
) -> dict[str, Any]:
    auxiliary_scores = auxiliary_scores or {}
    train_rows = training_rows_for_queries(examples, train_query_ids)
    if not train_rows:
        raise ValueError("Cannot train logistic baseline: no train rows found.")

    means, stds = standardization(train_rows, feature_fields, auxiliary_scores)
    x_train = [
        standardized_vector(row, feature_fields, auxiliary_scores, means, stds)
        for row in train_rows
    ]
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

    scores: ScoreMap = {}
    for row in examples:
        features = standardized_vector(row, feature_fields, auxiliary_scores, means, stds)
        z = bias + sum(weight * value for weight, value in zip(weights, features))
        scores[pair_key(row)] = sigmoid(z)

    return {
        "scores": scores,
        "model": {
            "type": "standardized_batch_logistic_regression",
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2": l2,
            "positive_weight": round(positive_weight, 6),
            "bias": round(bias, 6),
            "train_query_count": len({row_query_id(row) for row in train_rows}),
            "train_pair_count": len(train_rows),
            "feature_fields": feature_fields,
            "auxiliary_score_fields": sorted(auxiliary_scores),
            "coefficients": coefficient_rows(feature_fields, weights, means, stds),
        },
    }


def train_pairwise_perceptron(
    examples: list[dict[str, Any]],
    feature_fields: list[str],
    auxiliary_scores: dict[str, ScoreMap] | None = None,
    train_query_ids: set[str] | None = None,
    epochs: int = 70,
    learning_rate: float = 0.03,
    l2: float = 0.0005,
    margin: float = 1.0,
) -> dict[str, Any]:
    auxiliary_scores = auxiliary_scores or {}
    train_rows = training_rows_for_queries(examples, train_query_ids)
    if not train_rows:
        raise ValueError("Cannot train pairwise perceptron: no train rows found.")

    means, stds = standardization(train_rows, feature_fields, auxiliary_scores)

    def vector(row: dict[str, Any]) -> list[float]:
        return standardized_vector(row, feature_fields, auxiliary_scores, means, stds)

    grouped = examples_by_query(train_rows)
    query_pairs: list[tuple[list[float], list[list[float]]]] = []
    for query_examples in grouped.values():
        positives = [row for row in query_examples if int(row.get("label", 0)) == 1]
        negatives = [row for row in query_examples if int(row.get("label", 0)) == 0]
        if not positives or not negatives:
            continue
        query_pairs.append((vector(positives[0]), [vector(row) for row in negatives]))

    weights = [0.0 for _ in feature_fields]
    updates = 0
    comparisons = 0
    for _ in range(epochs):
        for positive_vector, negative_vectors in query_pairs:
            positive_score = sum(weight * value for weight, value in zip(weights, positive_vector))
            for negative_vector in negative_vectors:
                negative_score = sum(weight * value for weight, value in zip(weights, negative_vector))
                comparisons += 1
                if positive_score - negative_score <= margin:
                    for index in range(len(weights)):
                        weights[index] *= 1.0 - (learning_rate * l2)
                        weights[index] += learning_rate * (positive_vector[index] - negative_vector[index])
                    updates += 1
                    positive_score = sum(weight * value for weight, value in zip(weights, positive_vector))

    scores: ScoreMap = {}
    for row in examples:
        features = vector(row)
        scores[pair_key(row)] = sum(weight * value for weight, value in zip(weights, features))

    return {
        "scores": scores,
        "model": {
            "type": "standardized_pairwise_perceptron_ranker",
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2": l2,
            "margin": margin,
            "updates": updates,
            "comparisons": comparisons,
            "train_query_count": len(query_pairs),
            "train_pair_count": len(train_rows),
            "feature_fields": feature_fields,
            "auxiliary_score_fields": sorted(auxiliary_scores),
            "coefficients": coefficient_rows(feature_fields, weights, means, stds),
        },
    }


def static_score_builder(scores: ScoreMap) -> Any:
    def build_for_fold(_: set[str]) -> ScoreMap:
        return scores

    return build_for_fold


def top1_misses(
    candidate_rows: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    query_by_id = {str(row["query_id"]): row for row in queries}
    candidate_by_id = {str(row["candidate_episode_id"]): row for row in candidates}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        grouped[(str(row["pipeline_id"]), str(row["query_id"]))].append(row)

    misses: list[dict[str, Any]] = []
    for (pipeline_id, query_id), rows in grouped.items():
        rows.sort(key=lambda row: int(row.get("rank", 999999)))
        rank1 = rows[0] if rows else None
        true_rows = [row for row in rows if int(row.get("label", 0)) == 1]
        if not rank1 or not true_rows:
            continue
        true_row = true_rows[0]
        true_rank = int(true_row.get("rank", 999999))
        if true_rank == 1:
            continue
        query = query_by_id.get(query_id, {})
        rank1_candidate = candidate_by_id.get(str(rank1.get("candidate_episode_id")), {})
        true_candidate = candidate_by_id.get(str(true_row.get("candidate_episode_id")), {})
        misses.append(
            {
                "pipeline_id": pipeline_id,
                "family": rank1.get("family"),
                "query_id": query_id,
                "jira_issue_key": query.get("jira_issue_key"),
                "split": rank1.get("split"),
                "priority": query.get("priority"),
                "query_summary": query.get("summary"),
                "true_rank": true_rank,
                "rank1_candidate_episode_id": rank1.get("candidate_episode_id"),
                "rank1_candidate_scenario_id": rank1.get("candidate_scenario_id"),
                "rank1_candidate_services": rank1_candidate.get("affected_services"),
                "rank1_score": rank1.get("score"),
                "true_candidate_episode_id": true_row.get("candidate_episode_id"),
                "true_candidate_scenario_id": true_row.get("candidate_scenario_id"),
                "true_candidate_services": true_candidate.get("affected_services"),
                "true_score": true_row.get("score"),
            }
        )
    misses.sort(key=lambda row: (str(row["pipeline_id"]), str(row.get("split")), int(row["true_rank"]), str(row["query_id"])))
    return misses


def write_report(
    path: Path,
    benchmark: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    miss_rows: list[dict[str, Any]],
) -> None:
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
    lines.append("## Leave-One-Query-Run-Out Macro Metrics")
    lines.append("")
    lines.append("| Pipeline | Folds | Queries | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for pipeline in benchmark["pipelines"]:
        metrics = pipeline["leave_one_query_run_out"]["macro_metrics"]
        lines.append(
            f"| {pipeline['pipeline_id']} | {metrics.get('fold_count', 0)} | {metrics.get('query_count', 0)} | {metrics.get('mrr', 0)} | {metrics.get('recall_at_1', 0)} | {metrics.get('recall_at_3', 0)} | {metrics.get('f1_at_1', 0)} | {metrics.get('f1_at_3', 0)} | {metrics.get('ndcg_at_3', 0)} |"
        )
    lines.append("")
    lines.append("## Test Top-1 Miss Counts")
    lines.append("")
    lines.append("| Pipeline | Test top-1 misses |")
    lines.append("| --- | ---: |")
    miss_counter = Counter(row["pipeline_id"] for row in miss_rows if row.get("split") == "test")
    for pipeline in benchmark["pipelines"]:
        lines.append(f"| {pipeline['pipeline_id']} | {miss_counter.get(pipeline['pipeline_id'], 0)} |")
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
    lines.append("- Overall metrics include train, validation, and test query groups. Use split metrics and leave-one-query-run-out metrics for held-out evidence.")
    lines.append("- All production-facing text pipelines use `queries.query_text` and `candidate-episodes.raw_evidence_text` only.")
    lines.append("- Neural and language-model pipelines should reuse these same dataset files, split rules, and metric names.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_pipeline_specs(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    feature_fields: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_scores = raw_telemetry_scores(examples)
    bm25_scores_by_pair = lexical_bm25_scores(examples, queries, candidates)
    tfidf_scores_by_pair = tfidf_cosine_scores(examples, queries, candidates)

    normalized_raw = min_max_normalize_by_query(examples, raw_scores)
    normalized_bm25 = min_max_normalize_by_query(examples, bm25_scores_by_pair)
    normalized_tfidf = min_max_normalize_by_query(examples, tfidf_scores_by_pair)

    auxiliary_scores = {
        "raw_telemetry_existing_score": normalized_raw,
        "bm25_raw_evidence_score": normalized_bm25,
        "tfidf_raw_evidence_score": normalized_tfidf,
    }
    text_numeric_fields = feature_fields + list(TEXT_SCORE_FIELDS)

    hybrid_bm25_raw = weighted_sum_scores(
        examples,
        [
            (0.55, normalized_bm25),
            (0.45, normalized_raw),
        ],
    )
    logistic_numeric = train_logistic_model(examples, feature_fields)
    logistic_text_numeric = train_logistic_model(examples, text_numeric_fields, auxiliary_scores=auxiliary_scores)
    pairwise_text_numeric = train_pairwise_perceptron(examples, text_numeric_fields, auxiliary_scores=auxiliary_scores)
    rrf_hybrid = reciprocal_rank_fusion_scores(
        examples,
        [
            ("raw_telemetry_existing", 1.0, raw_scores),
            ("bm25_raw_evidence", 1.0, bm25_scores_by_pair),
            ("tfidf_raw_evidence", 1.0, tfidf_scores_by_pair),
            ("logistic_text_numeric_features", 1.5, logistic_text_numeric["scores"]),
        ],
    )

    def logistic_numeric_fold_builder(train_query_ids: set[str]) -> ScoreMap:
        return train_logistic_model(examples, feature_fields, train_query_ids=train_query_ids)["scores"]

    def logistic_text_numeric_fold_builder(train_query_ids: set[str]) -> ScoreMap:
        return train_logistic_model(
            examples,
            text_numeric_fields,
            auxiliary_scores=auxiliary_scores,
            train_query_ids=train_query_ids,
        )["scores"]

    def pairwise_fold_builder(train_query_ids: set[str]) -> ScoreMap:
        return train_pairwise_perceptron(
            examples,
            text_numeric_fields,
            auxiliary_scores=auxiliary_scores,
            train_query_ids=train_query_ids,
        )["scores"]

    def rrf_fold_builder(train_query_ids: set[str]) -> ScoreMap:
        fold_logistic = train_logistic_model(
            examples,
            text_numeric_fields,
            auxiliary_scores=auxiliary_scores,
            train_query_ids=train_query_ids,
        )["scores"]
        return reciprocal_rank_fusion_scores(
            examples,
            [
                ("raw_telemetry_existing", 1.0, raw_scores),
                ("bm25_raw_evidence", 1.0, bm25_scores_by_pair),
                ("tfidf_raw_evidence", 1.0, tfidf_scores_by_pair),
                ("logistic_text_numeric_features", 1.5, fold_logistic),
            ],
        )

    pipeline_specs = [
        {
            "pipeline_id": "raw_telemetry_existing",
            "family": "heuristic",
            "description": "Existing deterministic production-facing raw telemetry score.",
            "scores": raw_scores,
            "fold_score_builder": static_score_builder(raw_scores),
            "model": None,
        },
        {
            "pipeline_id": "bm25_raw_evidence",
            "family": "lexical",
            "description": "BM25 between Jira query text and candidate raw telemetry evidence text.",
            "scores": bm25_scores_by_pair,
            "fold_score_builder": static_score_builder(bm25_scores_by_pair),
            "model": None,
        },
        {
            "pipeline_id": "tfidf_raw_evidence",
            "family": "lexical",
            "description": "TF-IDF cosine similarity over Jira query text and raw telemetry evidence text.",
            "scores": tfidf_scores_by_pair,
            "fold_score_builder": static_score_builder(tfidf_scores_by_pair),
            "model": {"type": "tfidf_cosine", "text_fields": {"query": "query_text", "candidate": "raw_evidence_text"}},
        },
        {
            "pipeline_id": "hybrid_bm25_raw_telemetry",
            "family": "hybrid",
            "description": "Weighted score fusion: 55% BM25 raw evidence and 45% existing raw telemetry score.",
            "scores": hybrid_bm25_raw,
            "fold_score_builder": static_score_builder(hybrid_bm25_raw),
            "model": {"weights": {"bm25_raw_evidence": 0.55, "raw_telemetry_existing": 0.45}},
        },
        {
            "pipeline_id": "logistic_numeric_features",
            "family": "classical_ml",
            "description": "Dependency-free logistic regression over production-safe numeric telemetry features.",
            "scores": logistic_numeric["scores"],
            "fold_score_builder": logistic_numeric_fold_builder,
            "model": logistic_numeric["model"],
        },
        {
            "pipeline_id": "logistic_text_numeric_features",
            "family": "classical_ml",
            "description": "Logistic regression over production-safe numeric telemetry plus lexical/raw score features.",
            "scores": logistic_text_numeric["scores"],
            "fold_score_builder": logistic_text_numeric_fold_builder,
            "model": logistic_text_numeric["model"],
        },
        {
            "pipeline_id": "pairwise_perceptron_text_numeric",
            "family": "classical_ml",
            "description": "Pairwise linear ranker trained from positive-vs-negative query groups.",
            "scores": pairwise_text_numeric["scores"],
            "fold_score_builder": pairwise_fold_builder,
            "model": pairwise_text_numeric["model"],
        },
        {
            "pipeline_id": "rrf_bm25_tfidf_raw_logistic",
            "family": "hybrid",
            "description": "Reciprocal-rank fusion over BM25, TF-IDF, raw telemetry, and text+numeric logistic scores.",
            "scores": rrf_hybrid,
            "fold_score_builder": rrf_fold_builder,
            "model": {
                "type": "reciprocal_rank_fusion",
                "rank_k": 60,
                "weights": {
                    "raw_telemetry_existing": 1.0,
                    "bm25_raw_evidence": 1.0,
                    "tfidf_raw_evidence": 1.0,
                    "logistic_text_numeric_features": 1.5,
                },
            },
        },
    ]
    model_outputs = {
        "logistic-numeric-model.json": logistic_numeric["model"],
        "logistic-text-numeric-model.json": logistic_text_numeric["model"],
        "pairwise-perceptron-text-numeric-model.json": pairwise_text_numeric["model"],
    }
    return pipeline_specs, model_outputs


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

    pipeline_specs, model_outputs = build_pipeline_specs(examples, queries, candidates, feature_fields)

    pipelines: list[dict[str, Any]] = []
    all_candidate_rows: list[dict[str, Any]] = []
    fold_csv_rows: list[dict[str, Any]] = []
    for spec in pipeline_specs:
        overall_metrics, rows = metrics_for_scores(examples, spec["scores"])
        for row in rows:
            row["pipeline_id"] = spec["pipeline_id"]
            row["family"] = spec["family"]
        all_candidate_rows.extend(rows)

        fold_metrics = leave_one_query_run_out_metrics(examples, split, spec["fold_score_builder"])
        for fold_row in fold_metrics["folds"]:
            fold_csv_rows.append(
                {
                    "pipeline_id": spec["pipeline_id"],
                    "family": spec["family"],
                    **fold_row,
                }
            )

        pipelines.append(
            {
                "pipeline_id": spec["pipeline_id"],
                "family": spec["family"],
                "description": spec["description"],
                "overall_metrics": overall_metrics,
                "split_metrics": split_metrics(examples, spec["scores"]),
                "leave_one_query_run_out": fold_metrics,
                "model": spec["model"],
            }
        )

    miss_rows = top1_misses(all_candidate_rows, queries, candidates)
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
            "query_count": len({row_query_id(row) for row in examples}),
            "candidate_episode_count": len(candidates),
            "example_count": len(examples),
            "positive_example_count": sum(int(row.get("label", 0)) for row in examples),
            "pipeline_count": len(pipelines),
        },
        "pipelines": pipelines,
    }

    write_json(output_root / "benchmark-report.json", benchmark)
    write_report(output_root / "benchmark-report.md", benchmark, all_candidate_rows, miss_rows)
    write_csv(output_root / "benchmark-candidate-scores.csv", all_candidate_rows)
    write_csv(output_root / "leave-one-query-run-out-metrics.csv", fold_csv_rows)
    write_json(output_root / "top1-misses.json", miss_rows)
    write_csv(output_root / "top1-misses.csv", miss_rows)
    for filename, model in model_outputs.items():
        write_json(output_root / filename, model)

    files_written = [
        "benchmark-report.json",
        "benchmark-report.md",
        "benchmark-candidate-scores.csv",
        "leave-one-query-run-out-metrics.csv",
        "top1-misses.json",
        "top1-misses.csv",
        *sorted(model_outputs),
    ]

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
                "leave_one_query_run_out_macro_metrics": pipeline["leave_one_query_run_out"]["macro_metrics"],
            }
            for pipeline in pipelines
        ],
        "files_written": files_written,
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
