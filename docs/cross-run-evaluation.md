# Cross-Run Evaluation

This document defines how derived ranking datasets are combined across dataset
runs.

The cross-run evaluator reads only derived files under:

```text
data/derived/<DATASET_RUN_ID>/
```

It does not read or mutate raw telemetry under `data/runs/`.

## Command

Build an aggregate for one explicit run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "current" `
  -DatasetRunId "2026-05-14-research-final-001" `
  -Force
```

Build an aggregate for every derived run currently available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "all-derived-runs" `
  -Force
```

Build the current final MVP aggregate explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "dataset-v2-final-production-v1" `
  -DatasetRunId "2026-05-15-dataset-v2-pilot-001,2026-05-15-dataset-v2-pilot-002,2026-05-15-dataset-v2-pilot-003,2026-05-15-final-v2-production-001" `
  -Force
```

The wrapper accepts repeated `-DatasetRunId` values or a comma-separated run-id
string.

## Run-Aware Holdout Command

Use the holdout evaluator when reporting research credibility. It creates one
fold per dataset run and holds out that full run as the test split:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-run-aware-holdout-evaluation.ps1 `
  -EvaluationId "dataset-v2-final-production-v1-holdout" `
  -DatasetRunId "2026-05-15-dataset-v2-pilot-001,2026-05-15-dataset-v2-pilot-002,2026-05-15-dataset-v2-pilot-003,2026-05-15-final-v2-production-001" `
  -Force
```

The current ranker is deterministic, so the script does not train a model. It
records train/test splits, evaluates frozen per-run scores on each held-out
run, and establishes the split contract for the later supervised ranker.

## Output Layout

Aggregates are written under:

```text
data/derived/aggregate/<AGGREGATE_ID>/
  cross-run-evaluation.json
  cross-run-evaluation.md
  combined-ranking-examples.jsonl
  combined-ranking-examples.csv
  cross-run-candidate-scores.csv
  ablation-metrics.json
  ablation-metrics.csv
  ablation-candidate-scores.csv
  raw-telemetry-failure-analysis.json
  raw-telemetry-failure-analysis.csv
```

These are generated artifacts and are ignored by Git through `data/derived/`.

Run-aware holdout outputs are written under:

```text
data/derived/holdout/<EVALUATION_ID>/
  run-aware-holdout-evaluation.json
  run-aware-holdout-evaluation.md
  split-manifest.json
  fold-metrics.csv
  holdout-candidate-scores.csv
```

## Query Identity

Jira issue keys are generated per run and can repeat. The aggregate evaluator
therefore uses this query identity:

```text
<DATASET_RUN_ID>::<JIRA_ISSUE_KEY>
```

This prevents `OBSRV-1001` from one run being mixed with `OBSRV-1001` from
another run.

In holdout mode, `split-manifest.json` must show zero train/test query overlap
for every fold. Repeated Jira keys across different runs are acceptable because
the full query id includes the dataset run id.

## Metrics

The aggregate report recomputes metrics across all included query ids:

- MRR,
- Recall@1,
- Recall@3,
- F1@1,
- F1@3,
- nDCG@3.

F1 is defined for the ranking task with one relevant episode per Jira query:

```text
Precision@k = 1/k if the true episode rank is <= k, else 0
Recall@k = 1 if the true episode rank is <= k, else 0
F1@k = harmonic mean of Precision@k and Recall@k
```

Under this definition, a successful top-3 query contributes `0.5` to F1@3.

Metrics are reported separately for:

- `label_aware_baseline`,
- `raw_telemetry`.

The `raw_telemetry` profile is the profile we should emphasize for product
claims because it does not score candidate severity, incident type, root-cause
category, scenario title, fault type, or expected-impact labels.

## Current Use

With one derived run, the aggregate is mostly a contract test. It proves that
derived runs can be combined safely and that query ids, labels, ranks, and
profile metrics survive the aggregation step.

The current final MVP v2 aggregate is documented in:

```text
docs/final-dataset-v2-production.md
```

Use the aggregate as the main experiment input instead of reading individual run
folders directly.

The current v2 final holdout report is:

```text
data/derived/holdout/dataset-v2-final-production-v1-holdout/
```

It contains four folds, one for each included run. On this final MVP v2 set,
`raw_telemetry` has pooled MRR `0.975`, Recall@1 `0.95`, Recall@3 `1.0`, F1@1
`0.95`, F1@3 `0.5`, and nDCG@3 `0.981546`.

The aggregate also exports:

- `ablation-metrics.csv`: Jira text only, service overlap only, raw telemetry
  text only, volume only, shape features only, and full raw telemetry.
- `raw-telemetry-failure-analysis.csv`: raw telemetry top-1 misses with true
  candidate, rank-1 candidate, score components, alerts, sampled logs, service
  deltas, and likely failure reason.

## Expected Workflow

1. Collect a raw run with `collect-dataset-run.ps1`.
2. Validate the raw run.
3. Build the per-run derived dataset with `build-ranking-dataset.ps1`.
4. Rebuild the aggregate with `build-cross-run-evaluation.ps1`.
5. Build a run-aware holdout report with
   `build-run-aware-holdout-evaluation.ps1`.
6. Use the aggregate report for pooled metrics and the holdout report for
   credibility claims.

Do not manually edit aggregate files. Rebuild them from the derived run folders.
