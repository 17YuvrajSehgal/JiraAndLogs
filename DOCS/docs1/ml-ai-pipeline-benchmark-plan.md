# ML And AI Pipeline Benchmark Plan

This document defines how we will compare lexical, classical ML, neural,
language-model, and hybrid pipelines on the Jira-aware observability dataset.

The goal is not to make one demo model look good. The goal is to create a
repeatable benchmark where different approaches rank the same Jira queries
against the same telemetry candidates using the same split rules and metrics.

## Two Tracks

This benchmark plan covers two parallel tasks.

| Track | Task | Status | Contract |
| --- | --- | --- | --- |
| **Triage** | Per-window: should this telemetry deserve a Jira ticket? | Primary product task | `docs/triage-task-contract.md` |
| **Ranking** | Per-query: given a Jira ticket, find the matching telemetry episode. | Secondary benchmark, retrospective use | This document, sections below |

Sections from "Current Benchmark Dataset" through "Optional Embedding And
Neural Benchmark" define the **ranking** benchmark. The **triage** benchmark
is defined in the final section of this document and in
`docs/triage-task-contract.md`.

When new pipelines are added, they should report on whichever task is
relevant to the approach. Lexical and embedding pipelines naturally apply to
both; classical feature pipelines tend to favor triage; LM rerankers apply to
both but with different prompts.

## Benchmark Dataset (Pending Collection)

The first benchmark dataset under the new product framing will be Dataset
v4, collected per `docs/dataset-v4-plan.md`. No collected dataset exists
yet; the earlier v3 dataset and its derived files were removed during the
Jira-as-memory pivot. The shape below is what the build pipeline must
produce.

Global dataset location once collected:

```text
data/derived/global/<GLOBAL_DATASET_ID>/
```

## Build Command

Build the global ranking dataset (secondary task) from a collected corpus:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-hard-negative-dataset.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force
```

Build the global triage dataset (primary task) from the same corpus — see
the Triage Benchmark section below for the parallel commands.

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

The ranking benchmark splits by query run, not by individual pair rows. The
specific train/validation/test runs are defined in the dataset's
`split-manifest.json` once collection completes; until then the contract
below applies.

The candidate pool is global: every query ranks against all selected
candidate episodes across all runs. This is intentional because a real
system compares a new Jira issue against many possible telemetry episodes,
not only episodes from the same collection run.

Note: the triage benchmark (primary task) uses a stricter split — scenario
families, not runs. See the Triage Benchmark section.

Leakage rules:

- Do not randomly split pair rows.
- Do not train on test queries.
- Production-facing pipelines must not use candidate severity, incident type,
  root-cause category, scenario id, or lab labels as features.
- Label-aware scores are allowed only as sanity checks.
- If a model uses candidate text, use `candidate-episodes.raw_evidence_text`,
  not scenario labels or generated ground-truth labels.

## Global Baselines

No collected baseline numbers yet. The first ranking baselines will be
produced from Dataset v4. Until then this section captures the pipeline
catalog and report shape only.

## Pipeline Benchmark

Run the ranking benchmark on a collected global dataset:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-global-pipeline-benchmark.ps1 `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -BenchmarkId "ranking-baseline-v1" `
  -Force
```

Outputs:

```text
data/derived/global/<GLOBAL_DATASET_ID>/benchmarks/<BENCHMARK_ID>/
```

Report files:

| File | Purpose |
| --- | --- |
| `benchmark-report.json` | Machine-readable metrics, split metrics, fold metrics, and model metadata. |
| `benchmark-report.md` | Human-readable benchmark report. |
| `benchmark-candidate-scores.csv` | Per-pipeline score and rank for every query-candidate pair. |
| `leave-one-query-run-out-metrics.csv` | Fold-level metrics where each query dataset run is held out once. |
| `top1-misses.csv` / `top1-misses.json` | Top-1 failure analysis rows for each pipeline. |
| `logistic-numeric-model.json` | Learned numeric logistic coefficients. |
| `logistic-text-numeric-model.json` | Learned numeric plus lexical logistic coefficients. |
| `pairwise-perceptron-text-numeric-model.json` | Learned pairwise linear ranker coefficients. |

Expanded pipelines:

| Pipeline | Family | Description |
| --- | --- | --- |
| `raw_telemetry_existing` | heuristic | Existing deterministic raw telemetry score. |
| `bm25_raw_evidence` | lexical | BM25 over Jira query text and raw telemetry evidence text. |
| `tfidf_raw_evidence` | lexical | TF-IDF cosine similarity over Jira query text and raw telemetry evidence text. |
| `hybrid_bm25_raw_telemetry` | hybrid | Weighted BM25 plus raw telemetry score. |
| `logistic_numeric_features` | classical ML | Logistic regression over production-safe numeric telemetry features. |
| `logistic_text_numeric_features` | classical ML | Logistic regression over numeric features plus raw/BM25/TF-IDF scores. |
| `pairwise_perceptron_text_numeric` | classical ML | Pairwise positive-vs-negative linear ranker. |
| `rrf_bm25_tfidf_raw_logistic` | hybrid | Reciprocal-rank fusion over raw telemetry, BM25, TF-IDF, and logistic ranking. |

Baseline numbers will be added once the v4 ranking benchmark is run. The
report contract requires:

- overall metrics across the global dataset,
- default held-out test split metrics,
- leave-one-query-run-out macro metrics (primary generalization signal),
- per-pipeline top-1 failure analysis,
- per-scenario-family stratified metrics.

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

1. Done: build the benchmark harness that loads the global dataset, applies the
   split contract, computes metrics, and writes reports.
2. Done: add lexical baselines: BM25 and TF-IDF.
3. Done: add classical ML baselines over production-safe numeric features.
4. Done: add hybrid lexical-plus-feature score fusion.
5. Done: add optional embedding retrieval and neural bi-encoder support.
6. Next: add language-model reranking over top-k candidates.
7. Later: add agentic workflows only after deterministic, neural, and
   language-model baselines are stable.

The optional embedding runner below implements step 5 without changing the
dependency-free smoke-test benchmark.

## Optional Embedding And Neural Benchmark

The embedding/neural runner is intentionally separate from
`run-global-pipeline-benchmark.ps1`. This keeps the dependency-free smoke test
stable while still letting us evaluate heavier embedding backends.

Run the local embedding benchmark:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-global-embedding-pipeline-benchmark.ps1 `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -BenchmarkId "embedding-v1-local" `
  -Force
```

Outputs:

```text
data/derived/global/<GLOBAL_DATASET_ID>/benchmarks/embedding-v1-local/
```

Files are the same shape as the main benchmark where possible:

| File | Purpose |
| --- | --- |
| `benchmark-report.json` | Machine-readable embedding/neural benchmark report. |
| `benchmark-report.md` | Human-readable report. |
| `benchmark-candidate-scores.csv` | Per-pipeline score and rank for every query-candidate pair. |
| `leave-one-query-run-out-metrics.csv` | Fold metrics using the same run-level fold contract. |
| `top1-misses.csv` / `top1-misses.json` | Top-1 miss rows for failure analysis. |
| `backend-status.json` | Which optional backends ran, were skipped, or failed to load. |
| `logistic-numeric-hashing-embedding-model.json` | Learned coefficients for the numeric plus hashing-embedding model. |

Local pipelines:

| Pipeline | Family | Description |
| --- | --- | --- |
| `hashing_embedding_raw_evidence` | embedding | Signed hashing embedding cosine over Jira query text and raw telemetry evidence text. |
| `hybrid_hashing_embedding_raw_telemetry` | hybrid | Weighted hashing embedding plus raw telemetry score. |
| `logistic_numeric_hashing_embedding` | classical ML | Logistic regression over numeric telemetry, raw telemetry score, and hashing embedding score. |

Embedding baseline numbers will be added once the v4 ranking benchmark is
run. Treat plain hashing retrieval as a floor, not a semantic model.

Optional neural bi-encoder (requires `sentence-transformers`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-global-embedding-pipeline-benchmark.ps1 `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -BenchmarkId "embedding-v1-sentence-transformers" `
  -IncludeSentenceTransformers `
  -SentenceTransformerModel "sentence-transformers/all-MiniLM-L6-v2" `
  -Force
```

## Triage Benchmark

The triage benchmark is the primary product benchmark. The full task contract,
label space, severity, components, hard-case flag, and operating-point rules
live in `docs/triage-task-contract.md`. This section defines the benchmark
shape — dataset paths, split rules, metrics, pipeline tracks, and report
contents — so that pipelines can compete on the same basis.

### Triage Dataset

The triage dataset is built from the same dataset runs as the ranking
dataset. Per-run derived files:

```text
data/derived/<DATASET_RUN_ID>/triage_examples.jsonl
data/derived/<DATASET_RUN_ID>/window_memory_matchings.jsonl
```

Global triage dataset:

```text
data/derived/global/<GLOBAL_DATASET_ID>/global-triage-examples.jsonl
data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-corpus.jsonl
data/derived/global/<GLOBAL_DATASET_ID>/window-memory-matchings.jsonl
```

For v4 the label source must be `human_adjudicated` for every `borderline`
and `is_hard_case` window. See `docs/dataset-v4-plan.md` for the adjudication
procedure and the time-ordered memory corpus rules.

### Build Commands

```powershell
# Per-run triage build
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-triage-dataset.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>" `
  -Force

# Per-run memory-match ground truth (after Jira corpus is built)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-window-memory-matchings.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force

# Jira memory corpus (across all runs in a prefix)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-jira-memory-corpus.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force

# Global triage build
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-triage-dataset.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force

# Benchmark (planned)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-triage-benchmark.ps1 `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -BenchmarkId "triage-baseline-v1" `
  -Force
```

### Triage Dataset Contract

Core files:

| File | Purpose |
| --- | --- |
| `global-triage-examples.jsonl` | One row per telemetry window with label, source, severity, components, hard-case flag, and numeric features. |
| `triage-windows.jsonl` | One row per window with the production-safe evidence text used as model input. |
| `triage-split-manifest.json` | Train/validation/test split definitions, plus leave-one-scenario-family-out fold definitions. |
| `triage-feature-columns.json` | Production-safe numeric features for classical ML. |
| `triage-pipeline-input-schema.json` | Stable input contract for all triage pipelines. |
| `triage-benchmark-report.md` | Human-readable benchmark report per benchmark id. |

Important fields in `global-triage-examples.jsonl`:

| Field | Meaning |
| --- | --- |
| `window_id` | Globally unique window id. |
| `dataset_run_id` | Run the window came from. |
| `scenario_family` | Family used for splits. |
| `triage_label` | `ticket_worthy`, `borderline`, or `noise`. Target. |
| `triage_severity` | Severity when ticket-worthy. Eval-only. |
| `triage_components` | Components when ticket-worthy. Eval-only for triage; target for the optional ticket-draft subtask. |
| `triage_reason_class` | Coarse reason when ticket-worthy. Eval-only for triage. |
| `is_hard_case` | True when intentionally designed to confuse simple models. Eval-only. |
| `source` | `scenario_authored` / `human_adjudicated` / `derived`. |
| `split` | Default split based on scenario-family holdout. |
| `triage_feature_*` | Production-facing numeric features. |
| `triage_evidence_text` | Production-facing text evidence. |

### Triage Split Rules

The triage benchmark must hold out scenario families, not runs.

A scenario family groups scenarios sharing fault mechanism and affected
service (e.g. `payment-outage`, `cart-redis`, `productcatalog-latency`,
`checkout-restart`). See `docs/triage-task-contract.md` for the canonical
family taxonomy.

Default split:

- train on at least three families,
- validation on one held-out family,
- test on one held-out family,
- additionally report leave-one-family-out macro metrics for every family.

Per-run holdout is insufficient for triage because fault signatures repeat
across runs of the same family. A model that has seen one
`payment-outage` run can memorize the signature.

Threshold selection must happen on the validation split only. Applying a
threshold tuned on test back to test is treated as a leak.

### Triage Metrics

Required:

| Metric | Why |
| --- | --- |
| Precision@FPR=1% | Headline. Models a low-alert-fatigue operating point. |
| Recall@FPR=1% | What fraction of real tickets we catch at the headline operating point. |
| Precision@FPR=5% | Secondary operating point. |
| PR-AUC | Threshold-free, robust to class imbalance. |
| ROC-AUC | Comparable across base rates. |
| Reliability curve + Expected Calibration Error | Required for probabilities to be usable downstream. |
| Cost-weighted F-beta (β=2) | Penalizes missed incidents more than false alarms. |

Borderline handling — both variants required, strict is headline:

| Variant | Treatment |
| --- | --- |
| Strict | Borderline counted as negative; precision computed against `ticket_worthy` only. |
| Inclusive | Borderline counted as positive; rewards models that surface human-interesting windows. |

Stratified metrics (recommended):

- by scenario family,
- by `is_hard_case`,
- by `triage_reason_class`,
- by affected service,
- by window type (active fault vs. recovery vs. baseline).

### Triage Pipeline Tracks

**Rule-based baseline.** Threshold on existing alert state and `should_alert`
heuristics. Establishes the floor a learned model must beat.

**Classical ML.** Logistic regression, gradient boosting, calibrated random
forest over `triage_feature_*` numeric features. Calibrate with Platt or
isotonic on the validation split.

**Lexical.** BM25 / TF-IDF over `triage_evidence_text` against a small set of
ticket-worthy and noise reference texts. Cheap, useful as a feature.

**Neural.** Bi-encoder embeddings of the window evidence text plus a learned
classification head. Cross-encoders over (window, ticket-worthy-reference)
pairs for harder cases.

**Language model.** Zero-shot or few-shot classification with rationale.
Calibration is the main risk — LMs are poorly calibrated by default;
temperature scaling on the validation set is required.

**Hybrid.** Classical features + LM-derived score fusion. Reciprocal-rank
fusion does not apply directly to classification; use stacking or weighted
log-odds blend instead.

### Triage Implementation Order

1. Build the v3 triage derived files using `source: derived` rules.
2. Implement rule baseline and classical logistic baselines.
3. Validate the split contract (scenario-family holdouts) on the compact corpus.
4. Add lexical and embedding pipelines.
5. Plan and collect dataset v4 with `human_adjudicated` borderline windows.
6. Add LM zero-shot and few-shot pipelines once v4 is available.
7. Add the optional ticket-draft subtask once classification metrics plateau.

### Acceptance Gates

A triage benchmark report is acceptance-ready when it meets the gates listed
in `docs/triage-task-contract.md#acceptance-gates-for-the-first-triage-benchmark`.
