#!/usr/bin/env python3
"""
Run optional embedding and neural retrieval benchmarks on a global dataset.

This runner keeps the stable dependency-free benchmark intact. It reads the
same global hard-negative dataset contract and writes the same metric shape, but
adds embedding-style retrieval and optional neural bi-encoder scoring when the
requested backend is available.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from build_ranking_dataset import tokenize
from run_global_pipeline_benchmark import (
    METRIC_FIELDS,
    ScoreMap,
    leave_one_query_run_out_metrics,
    load_global_dataset,
    metrics_for_scores,
    min_max_normalize_by_query,
    pair_key,
    raw_telemetry_scores,
    repo_root_from_script,
    split_metrics,
    static_score_builder,
    top1_misses,
    train_logistic_model,
    utc_now,
    weighted_sum_scores,
    write_csv,
    write_json,
)


SCRIPT_VERSION = "0.1.0"
DEFAULT_HASH_DIMENSION = 768


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def write_csv_records(path: Path, records: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
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


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def hashed_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0 for _ in range(dimension)]
    counts = Counter(tokenize(text))
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    return normalize(vector)


def vector_to_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def score_from_vectors(
    examples: list[dict[str, Any]],
    query_vectors: dict[str, list[float]],
    candidate_vectors: dict[str, list[float]],
) -> ScoreMap:
    scores: ScoreMap = {}
    for row in examples:
        query_id, candidate_id = pair_key(row)
        scores[(query_id, candidate_id)] = dot(
            query_vectors.get(query_id, []),
            candidate_vectors.get(candidate_id, []),
        )
    return scores


def hashing_embedding_scores(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    dimension: int,
) -> ScoreMap:
    query_vectors = {
        str(row["query_id"]): hashed_embedding(str(row.get("query_text", "")), dimension)
        for row in queries
    }
    candidate_vectors = {
        str(row["candidate_episode_id"]): hashed_embedding(str(row.get("raw_evidence_text", "")), dimension)
        for row in candidates
    }
    return score_from_vectors(examples, query_vectors, candidate_vectors)


def sentence_transformer_scores(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    model_name: str,
    cache_folder: str | None,
    batch_size: int,
) -> tuple[ScoreMap | None, dict[str, Any]]:
    status: dict[str, Any] = {
        "pipeline_id": "sentence_transformers_biencoder",
        "backend": "sentence-transformers",
        "model_name": model_name,
        "available": False,
        "status": "skipped",
    }
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:
        status["reason"] = f"sentence-transformers import failed: {exc}"
        return None, status

    try:
        model_kwargs: dict[str, Any] = {}
        if cache_folder:
            model_kwargs["cache_folder"] = cache_folder
        model = SentenceTransformer(model_name, **model_kwargs)
        query_ids = [str(row["query_id"]) for row in queries]
        query_texts = [str(row.get("query_text", "")) for row in queries]
        candidate_ids = [str(row["candidate_episode_id"]) for row in candidates]
        candidate_texts = [str(row.get("raw_evidence_text", "")) for row in candidates]
        query_embeddings = model.encode(
            query_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        candidate_embeddings = model.encode(
            candidate_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        query_vectors = {
            query_id: vector_to_list(vector)
            for query_id, vector in zip(query_ids, query_embeddings)
        }
        candidate_vectors = {
            candidate_id: vector_to_list(vector)
            for candidate_id, vector in zip(candidate_ids, candidate_embeddings)
        }
        status["available"] = True
        status["status"] = "completed"
        status["embedding_dimension"] = len(next(iter(query_vectors.values()))) if query_vectors else 0
        return score_from_vectors(examples, query_vectors, candidate_vectors), status
    except Exception as exc:
        status["reason"] = f"sentence-transformers scoring failed: {exc}"
        return None, status


def write_report(
    path: Path,
    benchmark: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    miss_rows: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append(f"# Global Embedding Pipeline Benchmark {benchmark['benchmark_id']}")
    lines.append("")
    lines.append(f"- Generated at: {benchmark['generated_at']}")
    lines.append(f"- Builder version: {benchmark['builder']['version']}")
    lines.append(f"- Global dataset: {benchmark['global_dataset_id']}")
    lines.append(f"- Query count: {benchmark['summary']['query_count']}")
    lines.append(f"- Candidate episodes: {benchmark['summary']['candidate_episode_count']}")
    lines.append(f"- Pair rows: {benchmark['summary']['example_count']}")
    lines.append("")
    lines.append("## Backend Status")
    lines.append("")
    lines.append("| Backend | Model | Status | Reason |")
    lines.append("| --- | --- | --- | --- |")
    for status in benchmark["backend_status"]:
        reason = str(status.get("reason", "")).replace("|", "/")
        lines.append(
            f"| {status.get('backend', '')} | {status.get('model_name', '')} | {status.get('status', '')} | {reason} |"
        )
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
    lines.append("## Notes")
    lines.append("")
    lines.append("- `hashing_embedding_raw_evidence` is an always-available embedding-style baseline, not a neural model.")
    lines.append("- `sentence_transformers_biencoder` runs only when explicitly requested and the backend/model can load.")
    lines.append("- All text scoring uses production-safe `queries.query_text` and `candidate-episodes.raw_evidence_text`.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_pipeline_specs(
    examples: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    feature_fields: list[str],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    backend_status: list[dict[str, Any]] = []
    raw_scores = raw_telemetry_scores(examples)
    normalized_raw = min_max_normalize_by_query(examples, raw_scores)
    hashing_scores = hashing_embedding_scores(examples, queries, candidates, args.hash_dimension)
    normalized_hashing = min_max_normalize_by_query(examples, hashing_scores)
    auxiliary_scores = {
        "raw_telemetry_existing_score": normalized_raw,
        "hashing_embedding_raw_evidence_score": normalized_hashing,
    }
    hashing_feature_fields = feature_fields + list(auxiliary_scores)
    logistic_hashing = train_logistic_model(
        examples,
        hashing_feature_fields,
        auxiliary_scores=auxiliary_scores,
    )
    hybrid_hashing_raw = weighted_sum_scores(
        examples,
        [
            (0.55, normalized_hashing),
            (0.45, normalized_raw),
        ],
    )
    backend_status.append(
        {
            "pipeline_id": "hashing_embedding_raw_evidence",
            "backend": "standard-library",
            "model_name": f"signed_hashing_{args.hash_dimension}",
            "available": True,
            "status": "completed",
        }
    )

    def logistic_hashing_fold_builder(train_query_ids: set[str]) -> ScoreMap:
        return train_logistic_model(
            examples,
            hashing_feature_fields,
            auxiliary_scores=auxiliary_scores,
            train_query_ids=train_query_ids,
        )["scores"]

    pipeline_specs: list[dict[str, Any]] = [
        {
            "pipeline_id": "hashing_embedding_raw_evidence",
            "family": "embedding",
            "description": "Signed hashing embedding cosine over Jira query text and raw telemetry evidence text.",
            "scores": hashing_scores,
            "fold_score_builder": static_score_builder(hashing_scores),
            "model": {
                "type": "signed_hashing_embedding",
                "dimension": args.hash_dimension,
                "text_fields": {"query": "query_text", "candidate": "raw_evidence_text"},
            },
        },
        {
            "pipeline_id": "hybrid_hashing_embedding_raw_telemetry",
            "family": "hybrid",
            "description": "Weighted fusion: 55% hashing embedding score and 45% raw telemetry score.",
            "scores": hybrid_hashing_raw,
            "fold_score_builder": static_score_builder(hybrid_hashing_raw),
            "model": {"weights": {"hashing_embedding_raw_evidence": 0.55, "raw_telemetry_existing": 0.45}},
        },
        {
            "pipeline_id": "logistic_numeric_hashing_embedding",
            "family": "classical_ml",
            "description": "Logistic regression over numeric telemetry plus hashing embedding and raw scores.",
            "scores": logistic_hashing["scores"],
            "fold_score_builder": logistic_hashing_fold_builder,
            "model": logistic_hashing["model"],
        },
    ]
    model_outputs = {
        "logistic-numeric-hashing-embedding-model.json": logistic_hashing["model"],
    }

    if args.include_sentence_transformers:
        st_scores, st_status = sentence_transformer_scores(
            examples,
            queries,
            candidates,
            args.sentence_transformer_model,
            args.sentence_transformer_cache,
            args.batch_size,
        )
        backend_status.append(st_status)
        if st_scores is not None:
            normalized_st = min_max_normalize_by_query(examples, st_scores)
            hybrid_st_raw = weighted_sum_scores(
                examples,
                [
                    (0.6, normalized_st),
                    (0.4, normalized_raw),
                ],
            )
            pipeline_specs.extend(
                [
                    {
                        "pipeline_id": "sentence_transformers_biencoder",
                        "family": "neural_embedding",
                        "description": "Sentence-transformers bi-encoder cosine over Jira query and raw telemetry evidence text.",
                        "scores": st_scores,
                        "fold_score_builder": static_score_builder(st_scores),
                        "model": {
                            "type": "sentence_transformers_biencoder",
                            "model_name": args.sentence_transformer_model,
                            "text_fields": {"query": "query_text", "candidate": "raw_evidence_text"},
                        },
                    },
                    {
                        "pipeline_id": "hybrid_sentence_transformers_raw_telemetry",
                        "family": "hybrid",
                        "description": "Weighted fusion: 60% sentence-transformer score and 40% raw telemetry score.",
                        "scores": hybrid_st_raw,
                        "fold_score_builder": static_score_builder(hybrid_st_raw),
                        "model": {
                            "weights": {
                                "sentence_transformers_biencoder": 0.6,
                                "raw_telemetry_existing": 0.4,
                            }
                        },
                    },
                ]
            )
    else:
        backend_status.append(
            {
                "pipeline_id": "sentence_transformers_biencoder",
                "backend": "sentence-transformers",
                "model_name": args.sentence_transformer_model,
                "available": False,
                "status": "not_requested",
                "reason": "Pass --include-sentence-transformers to run the optional neural bi-encoder backend.",
            }
        )

    return pipeline_specs, backend_status, model_outputs


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    global_root = (
        Path(args.global_root).resolve()
        if args.global_root
        else repo_root / "data" / "derived" / "global" / args.global_dataset_id
    )
    if not global_root.exists():
        raise FileNotFoundError(f"Global dataset root does not exist: {global_root}")

    benchmark_id = args.benchmark_id or "embedding-v1"
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

    pipeline_specs, backend_status, model_outputs = build_pipeline_specs(examples, queries, candidates, feature_fields, args)

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
            "name": "run_global_embedding_pipeline_benchmark.py",
            "version": SCRIPT_VERSION,
        },
        "global_root": str(global_root),
        "output_root": str(output_root),
        "backend_status": backend_status,
        "split_manifest": split,
        "summary": {
            "query_count": len({str(row["query_id"]) for row in examples}),
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
    write_csv_records(output_root / "leave-one-query-run-out-metrics.csv", fold_csv_rows)
    write_json(output_root / "top1-misses.json", miss_rows)
    write_csv_records(output_root / "top1-misses.csv", miss_rows)
    write_json(output_root / "backend-status.json", backend_status)
    for filename, model in model_outputs.items():
        write_json(output_root / filename, model)

    files_written = [
        "benchmark-report.json",
        "benchmark-report.md",
        "benchmark-candidate-scores.csv",
        "leave-one-query-run-out-metrics.csv",
        "top1-misses.json",
        "top1-misses.csv",
        "backend-status.json",
        *sorted(model_outputs),
    ]

    return {
        "benchmark_id": benchmark_id,
        "output_root": str(output_root),
        "global_dataset_id": args.global_dataset_id,
        "backend_status": backend_status,
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
    parser.add_argument("--benchmark-id", default="embedding-v1")
    parser.add_argument("--global-root")
    parser.add_argument("--repo-root")
    parser.add_argument("--output-root")
    parser.add_argument("--hash-dimension", type=int, default=DEFAULT_HASH_DIMENSION)
    parser.add_argument("--include-sentence-transformers", action="store_true")
    parser.add_argument("--sentence-transformer-model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--sentence-transformer-cache")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
