# Dataset v2 Realism Plan

This document defines the next dataset stage after the initial MVP benchmark.
The goal is to make the research more credible, acceptable, and realistic before
we invest heavily in a more complex model.

The current final MVP dataset proves that the pipeline works. Dataset v2 should
prove that the idea still works when the data is larger, noisier, more varied,
and closer to real operations.

## Why Dataset v2 Comes Before A Better Model

The current aggregate has:

- 3 dataset runs,
- 15 episodes,
- 90 telemetry windows,
- 6 shadow Jira issues,
- 30 ranking examples.

That is enough for an MVP contract test, but not enough for a strong research
claim. A more complex model trained on this small dataset could overfit to the
two incident families we already have.

Dataset v2 should improve the evidence base first:

- more runs,
- more failure modes,
- more negative examples,
- more noisy near misses,
- better holdout tests,
- better failure analysis.

## Research Goal

The Dataset v2 research question is:

```text
Can a Jira-aware ranker reliably identify the correct telemetry episode across
repeated runs, unseen run ids, varied fault types, and noisy non-incident
episodes?
```

The product goal is:

```text
Can the MVP ranker beat the production-facing raw telemetry baseline while
preserving high top-3 recall?
```

## Credibility Targets

Dataset v2 should move the project from a pipeline proof to a credible internal
research benchmark.

Target minimums:

| Item | MVP final dataset | Dataset v2 pilot target | Dataset v2 full target |
| --- | ---: | ---: | ---: |
| Dataset runs | 3 | 10 | 30-50 |
| Scenario episodes | 15 | 100 | 300-500 |
| Shadow Jira issues | 6 | about 50 | 150-250 |
| Ranking examples | 30 | about 1,000 | 10,000+ |
| Fault families | 2 | 5+ | 10+ |
| Negative episode types | 2 | 4+ | 6+ |

The pilot target is intentionally smaller than the full target. It is meant to
shake out collection issues before we spend hours collecting many runs.

## Executable Pilot Plan

The executable pilot plan is:

```text
deploy/research-lab/run-plans/dataset-v2-pilot.json
```

The generic collector is:

```text
scripts/research-lab/collect-dataset-plan.ps1
```

Dry-run verification completed:

| Date | Run id | Mode | Result |
| --- | --- | --- | --- |
| 2026-05-15 | `dry-run-v2-plan-001` | `-RecordOnly -NoTelemetryExport` | 10 episodes, 30 windows, 5 shadow Jira issues, 0 errors, 0 warnings |

This dry run validates the run-plan contract and shadow Jira generation. It does
not validate real telemetry export because `-NoTelemetryExport` was used.

First real telemetry pilot completed:

| Date | Run id | Aggregate id | Result |
| --- | --- | --- | --- |
| 2026-05-15 UTC | `2026-05-15-dataset-v2-pilot-001` | `dataset-v2-pilot-001` | 10 episodes, 78 windows, 606 alert events, 5 shadow Jira issues, 0 errors, 0 warnings |

Telemetry quality from the first real pilot:

| Quality check | Count |
| --- | ---: |
| Windows with exact service logs | 69 / 78 |
| Windows with service log context | 76 / 78 |
| Windows with namespace log context | 78 / 78 |
| Windows with traces | 78 / 78 |
| Windows with historical alert events | 78 / 78 |
| Run-level Loki namespace context entries | 5000 |

First real pilot ranking metrics:

| Profile | MRR | Recall@1 | Recall@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | 1.0 | 1.0 | 1.0 | 1.0 |
| `raw_telemetry` | 0.8 | 0.6 | 1.0 | 0.852372 |

The label-aware profile confirms the joins are correct. The raw telemetry
profile is weaker on this harder benchmark, which is useful for research because
it creates clear improvement targets.

Raw telemetry rank-1 misses in the first real pilot:

| Query | Correct scenario | Current rank | Incorrect rank-1 candidate |
| --- | --- | ---: | --- |
| `2026-05-15-dataset-v2-pilot-001::OBSRV-1001` | `productcatalog-latency-major` | 2 | `loadgenerator-traffic-spike-nearmiss` |
| `2026-05-15-dataset-v2-pilot-001::OBSRV-1004` | `redis-cart-restart-major` | 2 | `cart-redis-degradation-critical` |

Interpretation:

- The productcatalog latency issue is confused with a traffic spike near miss.
  This suggests the ranker needs active-fault deltas and better separation
  between service-local degradation and global traffic pressure.
- The Redis restart issue is confused with the Redis/cart outage scenario. This
  suggests the ranker needs better fault-shape features, such as restart event
  evidence, recovery timing, and pod lifecycle signals.

One pilot run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-plan.ps1 `
  -DatasetRunId "2026-05-14-dataset-v2-pilot-001" `
  -PlanFile "deploy\research-lab\run-plans\dataset-v2-pilot.json" `
  -Quick `
  -BuildDerived `
  -ForceNewRun
```

Ten pilot runs:

```powershell
for ($i = 1; $i -le 10; $i++) {
  $runId = "2026-05-14-dataset-v2-pilot-{0:D3}" -f $i
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-plan.ps1 `
    -DatasetRunId $runId `
    -PlanFile "deploy\research-lab\run-plans\dataset-v2-pilot.json" `
    -Quick `
    -BuildDerived `
    -ForceNewRun
}
```

Build a cross-run aggregate after collection:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "dataset-v2-pilot" `
  -Force
```

The command above includes all derived runs by default. Use explicit
`-DatasetRunId` values if the aggregate should contain only the v2 pilot runs.

## Pilot Scenario Mix

Each v2 pilot run currently contains ten scenario episodes:

| Order | Scenario | Role | Jira issue? |
| ---: | --- | --- | --- |
| 1 | `baseline-normal-traffic` | healthy baseline | No |
| 2 | `productcatalog-latency-major` | incident | Yes |
| 3 | `loadgenerator-traffic-spike-nearmiss` | noisy near miss | No |
| 4 | `paymentservice-unavailable-critical` | incident | Yes |
| 5 | `recommendationservice-pod-restart-nearmiss` | restart near miss | No |
| 6 | `checkoutservice-pod-restart-major` | incident | Yes |
| 7 | `redis-cart-restart-major` | incident | Yes |
| 8 | `frontend-cpu-nearmiss` | resource near miss | No |
| 9 | `cart-redis-degradation-critical` | incident | Yes |
| 10 | `baseline-normal-traffic` | restored baseline | No |

Expected per-run shape:

- 10 episodes,
- 5 Jira-positive incident episodes,
- 5 negative episodes,
- roughly 75 telemetry windows, depending on affected service fan-out.

This gives each Jira issue more false candidates than the current MVP dataset
and adds more realistic confusion cases.

## New Scenario Families Added

The first v2 executable scenarios add:

| Scenario | Action | Why it matters |
| --- | --- | --- |
| `paymentservice-unavailable-critical` | scale deployment to zero | checkout dependency outage |
| `checkoutservice-pod-restart-major` | restart pods | direct workload restart with user impact |
| `redis-cart-restart-major` | restart pods | transient dependency restart |
| `recommendationservice-pod-restart-nearmiss` | restart pods | recoverable non-Jira restart |
| `loadgenerator-traffic-spike-nearmiss` | raise loadgenerator users/rate | noisy traffic pressure negative |

These scenarios use the existing runner actions. They do not require Chaos Mesh
or privileged node-level operations.

## What Counts As Better

The current production-facing baseline is `raw_telemetry`:

| Metric | Current final MVP value |
| --- | ---: |
| MRR | 0.777778 |
| Recall@1 | 0.666667 |
| Recall@3 | 1.0 |
| nDCG@3 | 0.833333 |

Dataset v2 rankers should be compared against the same profile.

For the first v2 pilot, a useful improvement is:

- Recall@3 stays at or above 0.95,
- Recall@1 improves over the v2 `raw_telemetry` baseline,
- productcatalog latency no longer gets consistently outranked by healthy
  baseline windows,
- newly added payment and checkout faults rank correctly without hardcoded
  scenario labels.

For full Dataset v2, report:

- MRR,
- Recall@1,
- Recall@3,
- nDCG@3,
- metrics by fault family,
- metrics by affected service,
- metrics by severity,
- metrics for near-miss confusion cases,
- per-query failure analysis.

## Evaluation Protocol

Use run-aware splits. Do not randomly split rows, because ranking examples from
the same run share telemetry and labels.

Required splits:

| Split | Purpose |
| --- | --- |
| train runs | train or tune the ranker |
| validation runs | choose feature weights and thresholds |
| test runs | final held-out score |
| unseen fault-family holdout | test generalization to new scenario types |

The query id must remain:

```text
<DATASET_RUN_ID>::<JIRA_ISSUE_KEY>
```

This prevents repeated keys such as `OBSRV-1001` from different runs being
mixed together.

## Ablations To Run

Once v2 data exists, compare:

| Ablation | Question |
| --- | --- |
| Jira text only | Is issue text enough? |
| service overlap only | How far do components get us? |
| logs only | How much signal is in logs? |
| metrics only | Are golden signals enough? |
| traces only | Do traces improve dependency localization? |
| logs + metrics + traces | What does unified telemetry add? |
| no near misses | Are we overestimating performance by removing hard negatives? |
| no baseline windows | Are baselines causing useful or harmful confusion? |

## Feature Improvements To Build After Pilot Data

Do not add all of these before collecting pilot data. First collect the pilot,
then use failure cases to choose the most valuable features.

Highest-value feature improvements:

1. Pre-fault to active-fault deltas for logs, metrics, traces, and alerts.
2. Service-local latency features from Tempo spans.
3. Prometheus error-rate and restart deltas.
4. Baseline-window downweighting for active-incident queries.
5. Query expansion for service aliases such as product catalog and Redis cart.
6. A simple supervised ranker over exported component features.

## Future Scenario Backlog

These should come after the executable v2 pilot is stable:

- network latency and packet loss,
- CPU pressure on application pods,
- memory pressure and OOM restarts,
- bad deployment or bad configuration,
- cascading multi-service failure,
- partial availability with intermittent errors,
- low-traffic quiet periods,
- duplicate incident episodes,
- delayed Jira creation,
- incorrect initial Jira priority that gets corrected later.

Most of these require either deeper application instrumentation or a chaos tool
such as Chaos Mesh. They are intentionally kept out of the first executable v2
plan so the pilot can run with today's tooling.

## Documentation Rule

Every time the v2 plan changes, update:

- this document,
- `deploy/research-lab/run-plans/dataset-v2-pilot.json`,
- any new scenario file under `deploy/research-lab/scenarios/`,
- `docs/mvp-evaluation-dataset.md` if the current benchmark changes,
- `README.md` if the onboarding story changes.

Raw dataset folders under `data/runs/` should not be manually edited. Rebuild
derived files instead.
