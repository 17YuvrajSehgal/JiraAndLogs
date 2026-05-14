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
  -AggregateId "mvp-final-v1" `
  -DatasetRunId "2026-05-14-research-final-001,2026-05-14-mvp-eval-002,2026-05-14-mvp-eval-003" `
  -Force
```

The wrapper accepts repeated `-DatasetRunId` values or a comma-separated run-id
string.

## Output Layout

Aggregates are written under:

```text
data/derived/aggregate/<AGGREGATE_ID>/
  cross-run-evaluation.json
  cross-run-evaluation.md
  combined-ranking-examples.jsonl
  combined-ranking-examples.csv
  cross-run-candidate-scores.csv
```

These are generated artifacts and are ignored by Git through `data/derived/`.

## Query Identity

Jira issue keys are generated per run and can repeat. The aggregate evaluator
therefore uses this query identity:

```text
<DATASET_RUN_ID>::<JIRA_ISSUE_KEY>
```

This prevents `OBSRV-1001` from one run being mixed with `OBSRV-1001` from
another run.

## Metrics

The aggregate report recomputes metrics across all included query ids:

- MRR,
- Recall@1,
- Recall@3,
- nDCG@3.

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

The current final MVP aggregate is documented in:

```text
docs/mvp-evaluation-dataset.md
```

Use the aggregate as the main experiment input instead of reading individual run
folders directly.

## Expected Workflow

1. Collect a raw run with `collect-dataset-run.ps1`.
2. Validate the raw run.
3. Build the per-run derived dataset with `build-ranking-dataset.ps1`.
4. Rebuild the aggregate with `build-cross-run-evaluation.ps1`.
5. Use the aggregate report for cross-run research metrics.

Do not manually edit aggregate files. Rebuild them from the derived run folders.
