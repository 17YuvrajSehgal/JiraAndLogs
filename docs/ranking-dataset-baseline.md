# Ranking Dataset And Baseline

This document defines the first derived dataset contract for the ranking MVP.
It starts from a validated raw research run under `data/runs/<DATASET_RUN_ID>`
and creates reproducible ranking artifacts under `data/derived/<DATASET_RUN_ID>`.

The raw run is the evidence source. Derived files can be deleted and rebuilt.

## Command

Build the derived dataset for the current final run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-ranking-dataset.ps1 `
  -DatasetRunId "2026-05-15-final-v2-production-001" `
  -Force
```

Equivalent Python command:

```powershell
python scripts\research-lab\build_ranking_dataset.py `
  --dataset-run-id "2026-05-15-final-v2-production-001" `
  --force
```

## Output Layout

Generated files:

```text
data/derived/<DATASET_RUN_ID>/
  README.md
  freeze-manifest.json
  episodes.csv
  episodes.jsonl
  windows.csv
  windows.jsonl
  issues.csv
  issues.jsonl
  episode_features.jsonl
  ranking_examples.csv
  ranking_examples.jsonl
  candidate_scores.csv
  label_aware_candidate_scores.csv
  raw_telemetry_candidate_scores.csv
  ablation-metrics.json
  ablation-metrics.csv
  ablation-candidate-scores.csv
  raw-telemetry-failure-analysis.json
  raw-telemetry-failure-analysis.csv
  baseline-ranking-report.json
  baseline-ranking-report.md
```

These generated files are ignored by Git through `data/derived/`.

## Freeze Manifest

`freeze-manifest.json` is the reproducibility anchor. It records:

- dataset run id,
- builder version,
- raw run path,
- derived output path,
- raw file count,
- raw byte count,
- SHA256 for every raw file,
- a combined raw tree SHA256,
- source manifest,
- source validation report,
- source record counts.

Use this file when citing a dataset version in experiments or papers. If the raw
tree SHA changes, the derived metrics should be considered a different dataset
version.

## Derived Tables

`episodes.csv` and `episodes.jsonl` contain one row per incident episode:

- scenario id,
- affected services,
- severity,
- incident type,
- root cause category,
- Jira-candidate flag,
- linked Jira key,
- window, alert, and trace counts.

`windows.csv` and `windows.jsonl` contain one row per telemetry window:

- service,
- window type,
- labels,
- log counts,
- trace counts,
- historical alert counts.

`issues.csv` and `issues.jsonl` contain one row per shadow Jira issue:

- Jira key,
- summary,
- issue type,
- priority,
- components,
- labels,
- linked window, alert, and trace counts,
- sanitized ranking query text.

## Episode Features

`episode_features.jsonl` is the candidate corpus for ranking. It aggregates each
episode into:

- affected services,
- raw telemetry-window services,
- severity, incident type, and root cause category,
- alert names,
- trace count,
- trace root service/name summaries,
- exact and contextual log counts,
- per-window exact log counts,
- per-service active-fault versus pre-fault log deltas,
- Kubernetes restart events, restart counters, rollout availability, and pod
  readiness signals when captured by v2.1 telemetry export,
- telemetry-shape signals for restart-like, outage-like, traffic-pressure, and
  latency-like evidence,
- recovery-completeness and service-local delta signals,
- sampled service log messages,
- sanitized evidence text.

The sampled log messages are used only as compact evidence text. The raw Loki
exports remain the authoritative source.

## Ranking Examples

`ranking_examples.jsonl` and `ranking_examples.csv` contain one Jira issue
paired with every candidate episode.

For the current final v2 production run:

- query issues: 5,
- candidate episodes: 10,
- ranking examples: 50,
- positive examples: 5,
- negative examples: 45.

The label is:

```text
1 when jira_shadow_issue.incident_episode_id == candidate_episode.incident_episode_id
0 otherwise
```

This creates a small but complete learning-to-rank contract. Future runs can be
appended by concatenating these files as long as the column contract remains
stable.

## Scoring Profiles

The first ranking step exports two deterministic profiles. Both are sanity
checks before we train or deploy a model, but they answer different questions.

`candidate_scores.csv` contains all profiles. `label_aware_candidate_scores.csv`
and `raw_telemetry_candidate_scores.csv` split the same rankings by profile.

### Label-Aware Baseline

`label_aware_baseline` can use lab labels. It verifies that the dataset joins
are correct and that each generated Jira issue points to the intended episode.

`baseline_score` uses:

- 55% BM25 text score between sanitized Jira query text and episode evidence text,
- 30% affected-service overlap,
- 10% Jira priority to episode severity match,
- 3% incident-type term match,
- 2% telemetry strength from log and trace volume.

This profile should not be treated as production-realistic because candidate
severity, incident type, root-cause category, scenario title, fault type, and
expected-impact labels are lab knowledge.

### Raw Telemetry Profile

`raw_telemetry` is the stricter production-facing profile. It does not score:

- candidate severity,
- candidate incident type,
- candidate root-cause category,
- scenario title,
- fault type,
- expected user impact,
- expected error rate,
- expected latency impact.

`raw_telemetry_score` uses:

- 34% BM25 text score between sanitized Jira query text and raw candidate evidence text,
- 26% service overlap from Jira components and telemetry-window service names,
- 12% activity signal from raw log, trace, and historical-alert volume,
- 4% alert-volume signal,
- 2% exact log-volume signal,
- 1% trace-volume signal,
- 16% telemetry-shape alignment from active-window deltas, restart-like alerts,
  outage-like logs, and query intent,
- 5% issue-service active-window delta signal,
- up to 10% penalty for common confusions, such as traffic-pressure near misses
  without service-local deltas or outage-like evidence for non-outage queries.

The raw profile still uses the generated shadow Jira issue text as the query,
because that is what the product will rank against. It only restricts candidate
features to evidence available from telemetry.

The raw profile remains production-facing: it still does not score candidate
severity, candidate incident type, candidate root-cause category, scenario
title, fault type, or expected impact labels. The v1 raw telemetry feature
policy adds behavior-derived features only.

Both profiles export component features and final scores. This lets us replace
the deterministic ranker later without changing the raw dataset.

## Ablation And Failure Analysis

The builder now exports first-pass ablation reports:

- `jira_text_only`,
- `service_overlap_only`,
- `raw_telemetry_text_only`,
- `volume_only`,
- `shape_features_only`,
- `full_raw_telemetry`.

These are intentionally simple. They show which evidence families carry signal
before we train a model.

The builder also exports raw telemetry top-1 misses in
`raw-telemetry-failure-analysis.csv` and
`raw-telemetry-failure-analysis.json`. Each row includes:

- query id,
- true candidate,
- true rank,
- rank-1 candidate,
- score components,
- alert names,
- sampled logs,
- service deltas,
- likely failure reason.

## Leakage Controls

The baseline avoids identity leakage in scoring text:

- dataset ids are removed,
- episode ids are removed,
- telemetry window ids are removed,
- Jira keys are removed,
- trace ids are removed,
- alert fingerprints are removed,
- synthetic scenario slug phrases are removed,
- dataset and scenario labels are excluded from Jira query text,
- generated root-cause and severity labels are excluded from Jira query text.

The builder still exports these audit-only columns:

- `provenance_alert_overlap_count`,
- `provenance_trace_overlap_count`.

They are useful to confirm that generated Jira links are correct, but they are
not used in either ranking score. This distinction matters for research
credibility.

## Metrics

`baseline-ranking-report.json` and `baseline-ranking-report.md` include metrics
for both profiles:

- MRR,
- Recall@1,
- Recall@3,
- F1@1,
- F1@3,
- nDCG@3,
- top ranked candidates per Jira issue,
- ablation metrics,
- raw telemetry failure analysis,
- scoring policy,
- leakage controls.

F1 is computed per Jira query with one relevant episode:

```text
Precision@k = 1/k if the true episode rank is <= k, else 0
Recall@k = 1 if the true episode rank is <= k, else 0
F1@k = harmonic mean of Precision@k and Recall@k
```

This means a successful top-1 query contributes `1.0` to F1@1, while a
successful top-3 query contributes `0.5` to F1@3.

For the current first run, metrics are only a smoke-test proof of the pipeline.
There are two positive Jira issues, so they should not be treated as a
statistically meaningful product claim.

## How To Change This Later

Make changes in this order:

1. Keep raw files immutable under `data/runs/<DATASET_RUN_ID>`.
2. Update `scripts/research-lab/build_ranking_dataset.py`.
3. Rebuild `data/derived/<DATASET_RUN_ID>`.
4. Compare `baseline-ranking-report.json` before and after the change.
5. Update this document if the feature contract, leakage policy, or metrics change.

The next practical improvement is to collect multiple additional runs with the
same contract, then aggregate the derived `ranking_examples.jsonl` files into a
cross-run evaluation set.

The aggregate workflow is documented in `docs/cross-run-evaluation.md` and
implemented by `scripts/research-lab/build-cross-run-evaluation.ps1`.
