# ML And AI Pipeline Benchmark Plan

This document defines how we will compare lexical, classical ML, neural,
language-model, and hybrid pipelines on the Jira-aware observability dataset.

The goal is not to make one demo model look good. The goal is to create a
repeatable benchmark where different approaches rank the same Jira queries
against the same telemetry candidates using the same split rules and metrics.

## Current Benchmark Dataset

Use the completed compact Dataset v3 global hard-negative dataset:

```text
data/derived/global/2026-05-19-dataset-v3-compact-global/
```

It was built from:

```text
2026-05-19-dataset-v3-compact
```

Current size:

| Item | Count |
| --- | ---: |
| Source dataset runs | 6 |
| Jira queries | 39 |
| Candidate episodes | 69 |
| Pairwise ranking examples | 2691 |
| Positive examples | 39 |
| Same-run negatives | 423 |
| Cross-run hard negatives | 2229 |

Every Jira query has exactly one positive candidate and 68 negatives.

## Build Command

Rebuild the global dataset from the compact corpus:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-hard-negative-dataset.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -GlobalDatasetId "2026-05-19-dataset-v3-compact-global" `
  -Force
```

This reads raw and derived run data but writes only derived outputs under:

```text
data/derived/global/2026-05-19-dataset-v3-compact-global/
```

## Dataset Contract

Core files:

| File | Purpose |
| --- | --- |
| `global-ranking-examples.jsonl` | Pairwise query-candidate rows with labels, split, ranks, and numeric features. |
| `queries.jsonl` | One row per Jira query, including query text and original Jira key. |
| `candidate-episodes.jsonl` | One row per candidate episode, including raw telemetry evidence text. |
| `split-manifest.json` | Train, validation, test, and leave-one-query-run-out split definitions. |
| `pipeline-input-schema.json` | Stable contract for all pipeline families. |
| `feature-columns.json` | Production-safe numeric features for classical ML. |
| `global-ranking-report.md` | Current deterministic baseline metrics and failure analysis. |

Important fields in `global-ranking-examples.jsonl`:

| Field | Meaning |
| --- | --- |
| `query_id` | Globally unique query id: `<DATASET_RUN_ID>::<JIRA_KEY>`. |
| `query_dataset_run_id` | Dataset run where the Jira query came from. Use this for splits. |
| `candidate_episode_id` | Candidate telemetry episode id. |
| `candidate_dataset_run_id` | Dataset run where the candidate episode came from. |
| `label` | `1` only for the true query-episode pair. |
| `candidate_scope` | `positive`, `same_run_negative`, or `cross_run_hard_negative`. |
| `split` | Default split based on query run: `train`, `validation`, or `test`. |
| `raw_telemetry_*` | Production-facing numeric features. |

## Split Rules

The benchmark must split by query run, not by individual pair rows.

Default split:

| Split | Query dataset runs |
| --- | --- |
| Train | `compact-a-r01`, `compact-a-r02`, `compact-a-r03`, `compact-b-r01` |
| Validation | `compact-b-r02` |
| Test | `compact-b-r03` |

The candidate pool is global: every query ranks against all 69 selected
candidate episodes. This is intentional because a real triage system compares a
new Jira issue against many possible telemetry episodes, not only episodes from
the same collection run.

Leakage rules:

- Do not randomly split pair rows.
- Do not train on test queries.
- Production-facing pipelines must not use candidate severity, incident type,
  root-cause category, scenario id, or lab labels as features.
- Label-aware scores are allowed only as sanity checks.
- If a model uses candidate text, use `candidate-episodes.raw_evidence_text`,
  not scenario labels or generated ground-truth labels.

## Current Global Baselines

Global candidate-pool metrics:

| Profile | Uses candidate labels | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | Yes | 0.398346 | 0.179487 | 0.512821 | 0.179487 | 0.25641 | 0.369654 |
| `raw_telemetry` | No | 0.194273 | 0.076923 | 0.153846 | 0.076923 | 0.076923 | 0.122099 |

These scores are lower than the per-run corpus because the global candidate
pool is much harder. That is the point: it gives us enough headroom to compare
real pipeline improvements.

Main raw telemetry top-1 failure reasons:

| Reason | Count |
| --- | ---: |
| `service_delta_signal_favored_rank1` | 25 |
| `raw_text_overlap_favored_rank1` | 7 |
| `redis_restart_vs_redis_outage_confusion` | 3 |
| `score_component_overlap` | 1 |

## First Pipeline Benchmark

The first benchmark harness is dependency-free and runs immediately on the
global dataset:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-global-pipeline-benchmark.ps1 `
  -GlobalDatasetId "2026-05-19-dataset-v3-compact-global" `
  -BenchmarkId "baseline-v1" `
  -Force
```

Outputs:

```text
data/derived/global/2026-05-19-dataset-v3-compact-global/benchmarks/baseline-v1/
```

The initial benchmark runs:

| Pipeline | Family | Description |
| --- | --- | --- |
| `raw_telemetry_existing` | heuristic | Existing deterministic raw telemetry score. |
| `bm25_raw_evidence` | lexical | BM25 over Jira query text and raw telemetry evidence text. |
| `hybrid_bm25_raw_telemetry` | hybrid | Fixed 55% BM25 plus 45% raw telemetry score. |
| `logistic_numeric_features` | classical ML | Standardized logistic regression over production-safe numeric telemetry features. |

Initial overall metrics:

| Pipeline | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `raw_telemetry_existing` | 0.194273 | 0.076923 | 0.153846 | 0.076923 | 0.076923 | 0.122099 |
| `bm25_raw_evidence` | 0.134792 | 0.051282 | 0.076923 | 0.051282 | 0.038462 | 0.064103 |
| `hybrid_bm25_raw_telemetry` | 0.173442 | 0.076923 | 0.102564 | 0.076923 | 0.051282 | 0.089744 |
| `logistic_numeric_features` | 0.373998 | 0.153846 | 0.538462 | 0.153846 | 0.269231 | 0.369654 |

Initial held-out test metrics on `compact-b-r03`:

| Pipeline | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `raw_telemetry_existing` | 0.240221 | 0.125 | 0.25 | 0.125 | 0.125 | 0.203866 |
| `bm25_raw_evidence` | 0.304579 | 0.25 | 0.25 | 0.25 | 0.125 | 0.25 |
| `hybrid_bm25_raw_telemetry` | 0.300369 | 0.25 | 0.25 | 0.25 | 0.125 | 0.25 |
| `logistic_numeric_features` | 0.391033 | 0.25 | 0.375 | 0.25 | 0.1875 | 0.328866 |

The logistic baseline is a useful first signal, but it is not a final model. It
is trained on only 23 query groups, so the next benchmark work must add
leave-one-run-out reporting and more robust model comparisons before making a
product claim.

## Pipeline Tracks

### Lexical

Purpose: establish strong non-ML retrieval baselines.

Candidate approaches:

- BM25 over Jira query text and raw telemetry evidence text.
- TF-IDF cosine similarity.
- Field-weighted lexical retrieval over alerts, services, logs, and traces.

Expected files:

- `queries.jsonl`
- `candidate-episodes.jsonl`
- `global-ranking-examples.jsonl`

### Classical ML

Purpose: test whether engineered telemetry features can improve ranking.

Candidate approaches:

- logistic regression,
- linear SVM,
- random forest,
- gradient boosting,
- calibrated pairwise ranker.

Expected files:

- `global-ranking-examples.jsonl`
- `feature-columns.json`
- `split-manifest.json`

### Neural

Purpose: test learned text and feature representations.

Candidate approaches:

- bi-encoder embeddings for query and telemetry evidence,
- cross-encoder reranker over query-candidate text pairs,
- MLP over engineered features,
- feature-plus-embedding reranker.

Expected files:

- `queries.jsonl`
- `candidate-episodes.jsonl`
- `global-ranking-examples.jsonl`

### Language Models

Purpose: test whether instruction-following models can reason over Jira text and
telemetry evidence.

Candidate approaches:

- zero-shot top-k reranking,
- pairwise comparison reranking,
- rationale-then-score reranking,
- LLM reranking only over top-k candidates returned by a cheaper retriever.

Language model tests should start with top-k candidate subsets to control cost.
The full 69-candidate pool should be used only after we know the prompt and
scoring contract are stable.

### Hybrids

Purpose: combine cheap retrieval, engineered features, and expensive reasoning.

Candidate approaches:

- BM25 top-k plus classical feature ranker,
- embedding top-k plus learned reranker,
- raw telemetry ranker plus LLM reranker,
- lexical and telemetry-feature score fusion.

## Required Metrics

Every pipeline must report:

- MRR,
- Recall@1,
- Recall@3,
- F1@1,
- F1@3,
- nDCG@3.

Optional but useful:

- metrics by scenario family,
- metrics by affected service,
- metrics by candidate scope,
- failure analysis for top-1 misses,
- latency and cost per query.

## Implementation Order

1. Build the benchmark harness that loads the global dataset, applies the split
   contract, computes metrics, and writes reports.
2. Add lexical baselines: BM25 and TF-IDF.
3. Add classical ML baselines over production-safe numeric features.
4. Add hybrid lexical-plus-feature score fusion.
5. Add embedding retrieval and neural reranking.
6. Add language-model reranking over top-k candidates.
7. Add agentic workflows only after deterministic baselines are stable.

The next implementation step is the benchmark harness plus lexical and
classical ML baselines. That gives us a cheap, repeatable comparison foundation
before adding neural or language-model costs.
