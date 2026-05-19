# Production Corpus Dataset Plan

This document describes the large Dataset v3 production corpus we will collect
before building more ML, NLP, AI, or agent pipelines.

The goal is simple: create a dataset that is hard enough that a weak pipeline
cannot look good by accident.

Dataset v2 final remains the locked MVP baseline:

```text
dataset-v2-final-production-v1
```

Dataset v3 is the next research corpus. It is meant for serious benchmark
development, not for replacing the locked MVP baseline until it has been
collected, validated, and reviewed.

## Why We Need A Bigger Corpus

Small observability datasets make ranking pipelines look better than they are.
They usually have too few services, too few near misses, and too few similar
incidents. That causes three problems:

- models learn scenario names instead of operational behavior,
- retrieval systems overfit to obvious service overlap,
- agent pipelines appear useful because the candidate set is too easy.

Dataset v3 intentionally adds repeated runs, service diversity, hard negatives,
restart-vs-outage confusion, noisy Jira text, and high-volume telemetry.

## What Dataset v3 Contains

The corpus is controlled by:

```text
deploy/research-lab/corpora/dataset-v3-production-corpus.json
```

It expands into four run-plan families:

| Plan | Purpose |
| --- | --- |
| `dataset-v3-corpus-foundation` | Broad mix of baseline, latency, outage, restart, degradation, and noisy near-miss cases. |
| `dataset-v3-corpus-outage-heavy` | Service-diverse outage coverage across checkout, catalog, payment, currency, shipping, recommendation, ad, and Redis. |
| `dataset-v3-corpus-restart-traffic` | Restart-heavy and traffic-heavy cases for restart, recovery, and near-miss separation. |
| `dataset-v3-corpus-latency-config` | Productcatalog latency, bad configuration, outage, and traffic cases that look similar but mean different things. |

The full corpus manifest currently targets:

| Item | Target |
| --- | ---: |
| Dataset runs | 40 |
| Incident or baseline episodes | 510 |
| Shadow Jira issues | 262 |
| Telemetry windows | 4000+ |
| Current per-run ranking pairs | 3000+ |
| Future global hard-negative pairs | 50000+ |

The current derived builder creates per-run ranking pairs. Later, without
recollecting telemetry, we can add a global hard-negative builder that pairs
each Jira issue against candidates from all corpus runs. That is how this same
raw corpus can support much larger ML and retrieval benchmarks.

## Scenario Coverage

Dataset v3 includes the existing v2.1 hard cases plus these additional
production-style variants:

| Scenario | Type | Jira issue |
| --- | --- | --- |
| `checkoutservice-unavailable-critical` | Checkout outage | Yes |
| `productcatalog-unavailable-critical` | Browse/catalog outage | Yes |
| `currencyservice-unavailable-major` | Checkout dependency outage | Yes |
| `shippingservice-unavailable-major` | Shipping quote outage | Yes |
| `recommendationservice-unavailable-major` | Browse path outage | Yes |
| `adservice-unavailable-nearmiss` | Noisy non-critical dependency outage | No |
| `frontend-pod-restart-major` | User-visible restart | Yes |
| `paymentservice-pod-restart-major` | Checkout dependency restart | Yes |
| `cartservice-pod-restart-nearmiss` | Restart near miss | No |
| `productcatalog-latency-nearmiss` | Small latency near miss | No |

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

Preview the first three planned corpus runs without collecting data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-16-dataset-v3-corpus" `
  -MaxRuns 3 `
  -PlanOnly
```

Run a one-run smoke test if the cluster was restarted:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-16-dataset-v3-corpus-smoke" `
  -MaxRuns 1 `
  -Quick `
  -ForceNewRun
```

Collect the first production batch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-16-dataset-v3-corpus" `
  -MaxRuns 3 `
  -ForceNewRun
```

Continue with the next batch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-16-dataset-v3-corpus" `
  -StartAt 4 `
  -MaxRuns 4 `
  -ForceNewRun
```

Collect the full remaining corpus only after early batches validate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "2026-05-16-dataset-v3-corpus" `
  -StartAt 8
```

The wrapper skips an existing run if its raw manifest already exists and
`-ForceNewRun` is not supplied. This lets us resume collection without
re-running completed runs.

## Current Collection Status

As of 2026-05-17, the first production batch completed:

| Item | Value |
| --- | --- |
| Corpus prefix | `2026-05-16-dataset-v3-corpus` |
| Completed runs | `foundation-r01`, `foundation-r02`, `foundation-r03` |
| Validation | 0 errors, 0 warnings on all three runs |
| Derived runs available | 3 |
| Aggregate id | `2026-05-16-dataset-v3-corpus-aggregate` |
| Holdout id | `2026-05-16-dataset-v3-corpus-holdout` |

First-batch aggregate size:

| Item | Count |
| --- | ---: |
| Dataset runs | 3 |
| Candidate episodes | 45 |
| Shadow Jira query issues | 24 |
| Ranking examples | 360 |
| Positive examples | 24 |
| Negative examples | 336 |

First-batch metrics:

| Profile | MRR | Recall@1 | Recall@3 | F1@1 | F1@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | 0.6875 | 0.458333 | 0.916667 | 0.458333 | 0.458333 | 0.731143 |
| `raw_telemetry` | 0.513194 | 0.291667 | 0.625 | 0.291667 | 0.3125 | 0.4747 |

These lower scores are expected for the v3 corpus foundation batch. The batch
is deliberately harder than the locked v2 MVP benchmark and should be treated
as a stress-test corpus, not as evidence that the product ranker is ready.

## Batch Strategy

Do not start with all 40 runs. Use this sequence:

1. Run `-PlanOnly` to confirm the selected run ids.
2. Run one quick smoke collection after any Docker or cluster restart.
3. Run the first 3 full production runs.
4. Inspect validation reports and derived metrics.
5. Continue in 4-run batches until the full corpus is complete.

This keeps the dataset large without making one failed step waste an entire
night.

## Outputs To Inspect After Each Batch

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

A batch is acceptable only if:

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
the locked v2 baseline because the candidate set is larger and harder.

Useful failures include:

- Redis restart confused with Redis outage,
- traffic near miss ranked above a latency incident,
- downstream checkout symptoms ranked above the true dependency,
- noisy Jira summary pointing to the wrong component,
- restart recovery window ranked above the active fault window.

These are exactly the cases that make the eventual product more credible.

## Promotion Rule

Dataset v3 should not become the new official benchmark just because it is
larger. Promote it only after:

- at least the first 12 full production runs validate cleanly,
- aggregate and holdout reports are reviewed,
- failure families are documented,
- known data-quality issues are separated from true ranking difficulty,
- the locked Dataset v2 final baseline remains reproducible.

Until then, Dataset v3 is the research corpus under construction.
