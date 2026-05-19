# Final Dataset v2 Production

This document is the reference for the current final dataset to use for MVP v1
development and evaluation.

It is final enough to unblock the application work. It is not yet final enough
for a publication claim because it has only four runs and one full-duration
production-style run.

Dataset v2.1 and the larger Dataset v3 production corpus are now research
stages. They must not replace this locked MVP baseline until new runs are
collected, validated, reviewed, and deliberately promoted.

## Dataset Identity

Named aggregate:

```text
data/derived/aggregate/dataset-v2-final-production-v1/
```

Moving aggregate pointer:

```text
data/derived/aggregate/current/
```

Named holdout evaluation:

```text
data/derived/holdout/dataset-v2-final-production-v1-holdout/
```

Moving holdout pointer:

```text
data/derived/holdout/current/
```

The MVP should load:

```text
data/derived/aggregate/current/combined-ranking-examples.jsonl
```

## Included Runs

| Run id | Type | Episodes | Windows | Shadow Jira issues | Validation |
| --- | --- | ---: | ---: | ---: | --- |
| `2026-05-15-dataset-v2-pilot-001` | quick pilot | 10 | 78 | 5 | 0 errors, 0 warnings |
| `2026-05-15-dataset-v2-pilot-002` | quick pilot | 10 | 78 | 5 | 0 errors, 0 warnings |
| `2026-05-15-dataset-v2-pilot-003` | quick pilot | 10 | 78 | 5 | 0 errors, 0 warnings |
| `2026-05-15-final-v2-production-001` | full-duration production run | 10 | 78 | 5 | 0 errors, 0 warnings |

Aggregate size:

| Item | Count |
| --- | ---: |
| Dataset runs | 4 |
| Episodes | 40 |
| Telemetry windows | 312 |
| Shadow Jira issues | 20 |
| Ranking examples | 200 |
| Positive examples | 20 |
| Negative examples | 180 |

## Production Run Details

The production run used the same v2 scenario plan without `-Quick`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-plan.ps1 `
  -DatasetRunId "2026-05-15-final-v2-production-001" `
  -PlanFile "deploy\research-lab\run-plans\dataset-v2-pilot.json" `
  -BuildDerived `
  -ForceNewRun
```

The full run used scenario durations from the scenario YAML files:

| Scenario | Duration seconds |
| --- | ---: |
| `baseline-normal-traffic` | 300 |
| `productcatalog-latency-major` | 900 |
| `loadgenerator-traffic-spike-nearmiss` | 300 |
| `paymentservice-unavailable-critical` | 600 |
| `recommendationservice-pod-restart-nearmiss` | 240 |
| `checkoutservice-pod-restart-major` | 300 |
| `redis-cart-restart-major` | 300 |
| `frontend-cpu-nearmiss` | 300 |
| `cart-redis-degradation-critical` | 600 |
| `baseline-normal-traffic` | 300 |

Production run raw tree SHA256:

```text
66d1758a196fdbdda369c5d20687f9a1d11eae0d5e6b4028b6a1b2b81a280c9b
```

Production run telemetry quality:

| Quality check | Count |
| --- | ---: |
| Windows with exact service logs | 71 / 78 |
| Windows with service log context | 75 / 78 |
| Windows with namespace log context | 78 / 78 |
| Windows with traces | 78 / 78 |
| Windows with historical alert events | 78 / 78 |

## Final Aggregate Metrics

Aggregate command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "dataset-v2-final-production-v1" `
  -DatasetRunId "2026-05-15-dataset-v2-pilot-001,2026-05-15-dataset-v2-pilot-002,2026-05-15-dataset-v2-pilot-003,2026-05-15-final-v2-production-001" `
  -Force
```

| Profile | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | 1.0 |
| `raw_telemetry` | 0.975 | 0.95 | 1.0 | 0.95 | 0.5 | 0.981546 |

F1 is computed per Jira query with one relevant episode. A top-k hit has
Precision@k = `1/k`, Recall@k = `1`, and F1@k is the harmonic mean. Because of
that definition, every successful F1@3 query contributes `0.5`.

The production-facing raw telemetry profile has one rank-1 miss:

| Query | Correct candidate | Correct rank | Rank-1 candidate |
| --- | --- | ---: | --- |
| `2026-05-15-final-v2-production-001::OBSRV-1004` | `redis-cart-restart-major` | 2 | `cart-redis-degradation-critical` |

This miss is useful. It captures a realistic dependency-restart versus
dependency-outage confusion that the MVP should explain and improve.

The miss is also exported with evidence in:

```text
data/derived/aggregate/current/raw-telemetry-failure-analysis.csv
data/derived/aggregate/current/raw-telemetry-failure-analysis.json
```

The current likely failure reason is `service_delta_signal_favored_rank1`: the
wrong cart/Redis degradation candidate has stronger raw text and service-delta
signals than the true Redis restart candidate.

The first ablation report is exported in:

```text
data/derived/aggregate/current/ablation-metrics.csv
data/derived/aggregate/current/ablation-metrics.json
```

Current raw telemetry ablations:

| Ablation | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `jira_text_only` | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | 1.0 |
| `service_overlap_only` | 0.75 | 0.6 | 0.8 | 0.6 | 0.4 | 0.726186 |
| `raw_telemetry_text_only` | 0.635 | 0.4 | 0.85 | 0.4 | 0.425 | 0.664279 |
| `volume_only` | 0.399345 | 0.2 | 0.45 | 0.2 | 0.225 | 0.338093 |
| `shape_features_only` | 0.654167 | 0.55 | 0.7 | 0.55 | 0.35 | 0.631546 |
| `full_raw_telemetry` | 0.975 | 0.95 | 1.0 | 0.95 | 0.5 | 0.981546 |

## Run-Aware Holdout Metrics

Holdout command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-run-aware-holdout-evaluation.ps1 `
  -EvaluationId "dataset-v2-final-production-v1-holdout" `
  -DatasetRunId "2026-05-15-dataset-v2-pilot-001,2026-05-15-dataset-v2-pilot-002,2026-05-15-dataset-v2-pilot-003,2026-05-15-final-v2-production-001" `
  -Force
```

Each fold holds out one dataset run. Train/test query overlap is zero in every
fold.

| Profile | Macro MRR | Macro Recall@1 | Macro Recall@3 | Macro F1@1 | Macro F1@3 | Macro nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | 1.0 |
| `raw_telemetry` | 0.975 | 0.95 | 1.0 | 0.95 | 0.5 | 0.981546 |

## Dataset v2.1 Status

Dataset v2.1 is implemented as the next research plan, not as the current MVP
baseline. It adds:

- Kubernetes event, pod restart, pod readiness, and deployment rollout snapshots
  to future telemetry exports.
- Additional Prometheus service queries for service latency, error, CPU,
  memory, and restart evidence.
- Derived restart-event, outage-versus-restart, recovery-completeness, and
  service-local delta features.
- Opt-in noisy Jira generation with delayed issue creation, human-style triage
  comments, initial versus corrected priority, and partially wrong components.
- A separate executable plan at
  `deploy/research-lab/run-plans/dataset-v2.1-production.json`.

The v2.1 design reference is:

```text
docs/dataset-v2.1-realism-plan.md
```

## How To Use This Dataset

Use this dataset for the next MVP tasks:

1. Build the product-facing ranking API or UI against
   `data/derived/aggregate/current/combined-ranking-examples.jsonl`.
2. Keep `raw_telemetry` as the deterministic baseline.
3. Train or tune any new ranker only with run-aware splits.
4. Preserve the Redis restart miss as a known hard case.
5. Report both pooled aggregate metrics and run-aware holdout metrics.

Do not manually edit files under `data/runs/`, `data/derived/aggregate/`, or
`data/derived/holdout/`. Rebuild them from scripts.
