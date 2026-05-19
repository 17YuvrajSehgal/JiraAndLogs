# Dataset v2.1 Realism Plan

Dataset v2.1 is the next research benchmark stage after the locked MVP dataset
`dataset-v2-final-production-v1`.

The current v2 dataset remains the MVP baseline. V2.1 adds realism and evidence
capture for future runs; it should be promoted only after collection,
validation, and review.

After the first v2.1 production run, the dataset-first expansion path moves to
Dataset v3 production corpus:

```text
docs/production-corpus-dataset-plan.md
deploy/research-lab/corpora/dataset-v3-production-corpus.json
```

Dataset v3 keeps the v2.1 realism goals but scales them across many more runs,
services, outage families, restart cases, and near misses.

## Goals

Dataset v2.1 should make the benchmark harder and closer to real operations:

- richer telemetry evidence,
- noisier Jira records,
- more confusing near misses,
- explicit failure analysis,
- first ablation reports,
- F1 metrics alongside MRR, Recall, and nDCG.

UI work is out of scope. The immediate output is a better research dataset and
more honest evaluation artifacts.

## Locked Baseline

The locked MVP baseline is:

```text
data/derived/aggregate/dataset-v2-final-production-v1/
data/derived/aggregate/current/
data/derived/holdout/dataset-v2-final-production-v1-holdout/
data/derived/holdout/current/
```

Current raw telemetry metrics:

| Metric | Value |
| --- | ---: |
| MRR | 0.975 |
| Recall@1 | 0.95 |
| Recall@3 | 1.0 |
| F1@1 | 0.95 |
| F1@3 | 0.5 |
| nDCG@3 | 0.981546 |

The known hard case remains:

```text
2026-05-15-final-v2-production-001::OBSRV-1004
```

The true candidate is `redis-cart-restart-major` at rank 2. The rank-1
candidate is `cart-redis-degradation-critical`.

## F1 Definition

This project uses per-query F1@k for ranking with one relevant episode:

```text
Precision@k = 1/k if the true episode rank is <= k, else 0
Recall@k = 1 if the true episode rank is <= k, else 0
F1@k = harmonic mean of Precision@k and Recall@k
```

Implications:

- a correct top-1 result contributes `1.0` to F1@1,
- a correct top-3 result contributes `0.5` to F1@3,
- a miss outside top-k contributes `0.0`.

## Implemented v2.1 Changes

### Future Telemetry Capture

`scripts/research-lab/export-telemetry-window.ps1` now captures additional
evidence for future runs:

- Kubernetes events around each telemetry window,
- pod readiness and restart counters,
- deployment rollout state,
- Prometheus pod restart, CPU, and memory metrics,
- Prometheus service latency and error metric queries for HTTP/RPC services.

Kubernetes snapshots are written under:

```text
data/runs/<DATASET_RUN_ID>/raw/kubernetes/<TELEMETRY_WINDOW_ID>.json
```

Window feature summaries are attached under:

```text
features.kubernetes
```

### Derived Features

`scripts/research-lab/build_ranking_dataset.py` now derives additional
research features when the raw evidence is available:

- restart-event signal,
- rollout-unavailable signal,
- outage-versus-restart separation inputs,
- recovery-complete and recovery-incomplete signals,
- service-local active-fault versus pre-fault deltas.

These features are exported in `episode_features.jsonl` and
`ranking_examples.jsonl`. They do not mutate raw runs.

### Jira Shadow Issue Realism

Shadow Jira generation now has an opt-in v2.1 noisy mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\generate-shadow-jira-issues.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>" `
  -IncidentEpisodeId "<INCIDENT_EPISODE_ID>" `
  -RealisticNoise
```

When enabled through the v2.1 run plan, generated Jira issues include:

- delayed issue creation timestamps,
- human-style triage comments,
- initial priority and corrected final priority,
- incomplete or partially wrong components,
- less direct summaries,
- component correction history.

The deterministic Jira generator remains available for reproducible baseline
runs.

### Evaluation Outputs

Per-run, aggregate, and holdout reports now include:

- MRR,
- Recall@1,
- Recall@3,
- F1@1,
- F1@3,
- nDCG@3.

Per-run and aggregate reports also export:

```text
ablation-metrics.csv
ablation-metrics.json
ablation-candidate-scores.csv
raw-telemetry-failure-analysis.csv
raw-telemetry-failure-analysis.json
```

The first ablation profiles are:

- Jira text only,
- service overlap only,
- raw telemetry text only,
- volume only,
- shape features only,
- full raw telemetry.

## Executable v2.1 Plan

The v2.1 run plan is:

```text
deploy/research-lab/run-plans/dataset-v2.1-production.json
```

It keeps the v2 scenario families and adds:

- intermittent Redis failures,
- bad deployment/configuration,
- partial checkout degradation,
- noisy high-traffic non-incident,
- restart near miss with no Jira issue.

The plan enables realistic Jira noise:

```json
"realistic_jira_noise": true
```

Recommended first v2.1 collection command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-plan.ps1 `
  -DatasetRunId "2026-05-15-dataset-v2.1-production-001" `
  -PlanFile "deploy\research-lab\run-plans\dataset-v2.1-production.json" `
  -BuildDerived `
  -ForceNewRun
```

Use `-Quick` only for smoke tests. Do not promote a quick v2.1 run as the
research benchmark.

## Validation Checklist

Before promoting any v2.1 run:

1. Validate the raw run with `validate-dataset-run.ps1`.
2. Build derived data with `build-ranking-dataset.ps1`.
3. Rebuild aggregate and holdout reports.
4. Confirm F1 fields exist in all JSON reports.
5. Review `raw-telemetry-failure-analysis.csv`.
6. Review `ablation-metrics.csv`.
7. Confirm no raw files under `data/runs/` were manually edited.
8. Compare results against `dataset-v2-final-production-v1`.

Promotion should update `docs/final-dataset-v2-production.md` only after the
team decides v2.1 is ready to replace the current MVP baseline.
