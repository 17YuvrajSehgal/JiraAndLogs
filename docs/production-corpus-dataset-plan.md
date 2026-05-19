# Production Corpus Dataset Plan

This document describes the compact Dataset v3 production corpus we collect
before building heavier ML, NLP, AI, or agent pipelines.

The goal is simple: create a dataset that is hard enough that a weak pipeline
cannot look good by accident, while keeping collection practical on the local
Kubernetes lab.

Dataset v2 final remains the locked MVP baseline:

```text
dataset-v2-final-production-v1
```

Dataset v3 is the next research corpus. It is meant for benchmark development,
not for replacing the locked MVP baseline until it has been collected,
validated, and reviewed.

## Why The Corpus Is Compact

The earlier 40-run corpus design was valid but too slow for the current local
workflow. Ten full foundation runs took more than 24 hours, so the default
corpus is now compacted to 6 balanced runs.

This is the tradeoff:

- keep service diversity,
- keep restart-vs-outage confusion,
- keep latency-vs-config confusion,
- keep noisy near misses,
- keep full telemetry export and realistic Jira noise,
- reduce repeated same-family runs,
- use shorter active and recovery windows.

The older large plan files remain in the repository as optional stress-test
material, but the default top-level corpus manifest now points to the compact
plans.

## Corpus Manifest

The active corpus is controlled by:

```text
deploy/research-lab/corpora/dataset-v3-production-corpus.json
```

It expands into two compact run-plan families:

| Plan | Purpose |
| --- | --- |
| `dataset-v3-diverse-compact-a` | Latency, dependency outage, restart, Redis degradation, bad configuration, and near-miss coverage. |
| `dataset-v3-diverse-compact-b` | Service-diverse outages, frontend and Redis restarts, intermittent Redis failure, and noisy traffic coverage. |

Target size:

| Item | Target |
| --- | ---: |
| Dataset runs | 6 |
| Incident or baseline episodes | 69 |
| Shadow Jira issues | 39 |
| Telemetry windows | 500+ |
| Current per-run ranking pairs | 450+ |
| Future global hard-negative pairs | 2500+ |

The current derived builder creates per-run ranking pairs. Later, without
recollecting telemetry, we can add a global hard-negative builder that pairs
each Jira issue against candidates from all corpus runs.

## Completed Compact Corpus

The first complete compact corpus run finished on 2026-05-19:

```text
2026-05-19-dataset-v3-compact
```

Corpus manifest:

```text
data/derived/corpora/2026-05-19-dataset-v3-compact/corpus-run-manifest.json
```

Completed size:

| Item | Count |
| --- | ---: |
| Dataset runs | 6 |
| Episodes | 69 |
| Shadow Jira issues | 39 |
| Telemetry windows | 576 |
| Ranking examples | 462 |
| Positive examples | 39 |
| Negative examples | 423 |

Every raw run validation report showed 0 errors and 0 warnings.

Aggregate and holdout reports:

```text
data/derived/aggregate/2026-05-19-dataset-v3-compact-aggregate/cross-run-evaluation.md
data/derived/holdout/2026-05-19-dataset-v3-compact-holdout/run-aware-holdout-evaluation.md
```

Pooled run-aware holdout metrics:

| Profile | Uses candidate labels | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | Yes | 0.805556 | 0.641026 | 0.974359 | 0.641026 | 0.487179 | 0.844621 |
| `raw_telemetry` | No | 0.572934 | 0.358974 | 0.74359 | 0.358974 | 0.371795 | 0.581497 |

The raw telemetry baseline is much weaker here than on Dataset v2. That is
expected and useful: v3 has more service-diverse incidents, more near misses,
and more cases where symptoms in one service compete with root evidence in
another service.

Main raw telemetry top-1 failure reasons:

| Failure reason | Count |
| --- | ---: |
| `service_delta_signal_favored_rank1` | 20 |
| `raw_text_overlap_favored_rank1` | 3 |
| `traffic_pressure_overweighted` | 2 |

This means the next product/research step should focus on better separating
root-cause services from downstream symptom services and high-traffic near
misses. The failure analysis is already exported in:

```text
data/derived/aggregate/2026-05-19-dataset-v3-compact-aggregate/raw-telemetry-failure-analysis.csv
```

## Global Hard-Negative Dataset

The compact corpus now has a global candidate-pool dataset for ML, neural,
language-model, lexical, and hybrid benchmarks:

```text
data/derived/global/2026-05-19-dataset-v3-compact-global/
```

Build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-hard-negative-dataset.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -GlobalDatasetId "2026-05-19-dataset-v3-compact-global" `
  -Force
```

Global dataset size:

| Item | Count |
| --- | ---: |
| Jira queries | 39 |
| Candidate episodes per query | 69 |
| Ranking examples | 2691 |
| Positive examples | 39 |
| Same-run negatives | 423 |
| Cross-run hard negatives | 2229 |

Global raw telemetry metrics:

| MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.194273 | 0.076923 | 0.153846 | 0.076923 | 0.076923 | 0.122099 |

This harder dataset should be the main comparison target for future pipeline
work because it tests ranking across the whole corpus rather than only within a
single run.

The first pipeline benchmark report is:

```text
data/derived/global/2026-05-19-dataset-v3-compact-global/benchmarks/baseline-v1/benchmark-report.md
```

It compares the existing raw telemetry heuristic, BM25 lexical retrieval, a
fixed hybrid, and a dependency-free logistic regression over numeric telemetry
features.

## Scenario Coverage

Dataset v3 includes these production-style variants:

| Scenario | Type | Jira issue |
| --- | --- | --- |
| `productcatalog-latency-major` | Latency degradation | Yes |
| `paymentservice-unavailable-critical` | Checkout dependency outage | Yes |
| `checkoutservice-pod-restart-major` | User-visible restart | Yes |
| `cart-redis-degradation-critical` | Cart/Redis outage | Yes |
| `productcatalog-bad-config-critical` | Configuration-style degradation | Yes |
| `productcatalog-latency-nearmiss` | Small latency near miss | No |
| `loadgenerator-noisy-high-traffic-nearmiss` | High traffic near miss | No |
| `checkoutservice-unavailable-critical` | Checkout outage | Yes |
| `productcatalog-unavailable-critical` | Browse/catalog outage | Yes |
| `currencyservice-unavailable-major` | Checkout dependency outage | Yes |
| `shippingservice-unavailable-major` | Shipping quote outage | Yes |
| `recommendationservice-unavailable-major` | Browse dependency outage | Yes |
| `adservice-unavailable-nearmiss` | Non-critical dependency near miss | No |
| `frontend-pod-restart-major` | Frontend restart | Yes |
| `redis-cart-restart-major` | Redis restart | Yes |
| `redis-cart-intermittent-failure-major` | Intermittent Redis failure | Yes |
| `cartservice-pod-restart-nearmiss` | Restart near miss | No |
| `loadgenerator-traffic-spike-nearmiss` | Traffic spike near miss | No |

The important point is not just adding more incidents. We are adding similar
but not identical incidents so the ranker must separate:

- restart vs outage,
- latency vs bad configuration,
- real incident vs high-traffic near miss,
- root service vs downstream symptom service,
- incomplete Jira components vs telemetry evidence,
- active fault vs recovery behavior.

## Evidence Captured Per Run

Each run records:

- logs from Loki,
- service context and namespace context logs,
- metrics from Prometheus,
- traces from Tempo,
- alerts from Alertmanager and Prometheus `ALERTS`,
- Kubernetes events,
- pod restart counts,
- deployment rollout and readiness state,
- shadow Jira issues with noisy production-style fields.

The raw run remains the source of truth:

```text
data/runs/<DATASET_RUN_ID>/
```

Derived ranking data is rebuilt from raw runs:

```text
data/derived/<DATASET_RUN_ID>/
```

Corpus-level bookkeeping is written to:

```text
data/derived/corpora/<DATASET_RUN_PREFIX>/corpus-run-manifest.json
```

## Collection Commands

Start from the repository root:

```powershell
Set-Location C:\workplace\JiraAndLogs
```

Preview the planned compact corpus without collecting data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -PlanOnly
```

Run a one-run smoke test if Docker or Kubernetes was restarted:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact-smoke" `
  -MaxRuns 1 `
  -Quick `
  -ForceNewRun
```

Collect the complete compact diverse corpus:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -ForceNewRun
```

If you want a smaller first batch, run two corpus runs first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -MaxRuns 2 `
  -ForceNewRun
```

Then continue:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-19-dataset-v3-compact" `
  -StartAt 3 `
  -ForceNewRun
```

The wrapper skips an existing run if its raw manifest and validation report
already exist and `-ForceNewRun` is not supplied. This lets us resume collection
without re-running completed runs.

## Batch Strategy

The compact corpus can be run end to end. Use this sequence:

1. Run `-PlanOnly` to confirm the selected run ids.
2. Run one quick smoke collection after any Docker or cluster restart.
3. Run the full compact corpus, or run the first 2 runs as a smaller batch.
4. Inspect validation reports and derived metrics.
5. Continue only if the first batch validates cleanly.

## Outputs To Inspect

For each raw run:

```text
data/runs/<DATASET_RUN_ID>/summaries/validation-report.json
data/runs/<DATASET_RUN_ID>/summaries/validation-report.md
data/runs/<DATASET_RUN_ID>/telemetry_windows.jsonl
data/runs/<DATASET_RUN_ID>/jira_shadow_issues.jsonl
```

For each derived run:

```text
data/derived/<DATASET_RUN_ID>/baseline-ranking-report.md
data/derived/<DATASET_RUN_ID>/ablation-metrics.csv
data/derived/<DATASET_RUN_ID>/raw-telemetry-failure-analysis.csv
```

For the corpus aggregate:

```text
data/derived/aggregate/<DATASET_RUN_PREFIX>-aggregate/
data/derived/holdout/<DATASET_RUN_PREFIX>-holdout/
```

## Acceptance Gates

A corpus run is acceptable only if:

- every selected run validates with 0 errors,
- raw logs, metrics, traces, alerts, and Kubernetes exports exist,
- every Jira-generating scenario produces exactly one linked shadow issue,
- near-miss scenarios do not create Jira issues,
- derived reports include MRR, Recall@1, Recall@3, F1@1, F1@3, and nDCG@3,
- failure-analysis files exist and list misses honestly,
- holdout reports are built from run-aware splits, not random row splits.

Warnings are allowed only when they are understood and documented.

## What Good Results Look Like

For Dataset v3, perfect scores are not the goal. We expect weaker metrics than
the locked v2 baseline because the candidate set is harder.

Useful failures include:

- Redis restart confused with Redis outage,
- traffic near miss ranked above a latency incident,
- downstream checkout symptoms ranked above the true dependency,
- noisy Jira summary pointing to the wrong component,
- restart recovery window ranked above the active fault window.

These are exactly the cases that make the eventual product more credible.

## Promotion Rule

Dataset v3 should not become the new official benchmark just because it is
larger or newer. Promote it only after:

- all compact corpus runs validate cleanly,
- aggregate and holdout reports are reviewed,
- failure families are documented,
- known data-quality issues are separated from true ranking difficulty,
- the locked Dataset v2 final baseline remains reproducible.

Until then, Dataset v3 is the research corpus under construction.
