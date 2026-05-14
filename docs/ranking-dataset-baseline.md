# Ranking Dataset And Baseline

This document defines the first derived dataset contract for the ranking MVP.
It starts from a validated raw research run under `data/runs/<DATASET_RUN_ID>`
and creates reproducible ranking artifacts under `data/derived/<DATASET_RUN_ID>`.

The raw run is the evidence source. Derived files can be deleted and rebuilt.

## Command

Build the derived dataset for the current final run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-ranking-dataset.ps1 `
  -DatasetRunId "2026-05-14-research-final-001" `
  -Force
```

Equivalent Python command:

```powershell
python scripts\research-lab\build_ranking_dataset.py `
  --dataset-run-id "2026-05-14-research-final-001" `
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
- severity, incident type, and root cause category,
- alert names,
- trace count,
- exact and contextual log counts,
- sampled service log messages,
- sanitized evidence text.

The sampled log messages are used only as compact evidence text. The raw Loki
exports remain the authoritative source.

## Ranking Examples

`ranking_examples.jsonl` and `ranking_examples.csv` contain one Jira issue
paired with every candidate episode.

For the first final run:

- query issues: 2,
- candidate episodes: 5,
- ranking examples: 10,
- positive examples: 2,
- negative examples: 8.

The label is:

```text
1 when jira_shadow_issue.incident_episode_id == candidate_episode.incident_episode_id
0 otherwise
```

This creates a small but complete learning-to-rank contract. Future runs can be
appended by concatenating these files as long as the column contract remains
stable.

## Baseline Scoring Policy

The first baseline is deterministic and intentionally simple. It is a sanity
check that the dataset joins are correct before we train or deploy a model.

`baseline_score` uses:

- 55% BM25 text score between sanitized Jira query text and episode evidence text,
- 30% affected-service overlap,
- 10% Jira priority to episode severity match,
- 3% incident-type term match,
- 2% telemetry strength from log and trace volume.

The baseline exports both the component features and the final score. This lets
us replace the ranker later without changing the raw dataset.

## Leakage Controls

The baseline avoids identity leakage in scoring text:

- dataset ids are removed,
- episode ids are removed,
- telemetry window ids are removed,
- Jira keys are removed,
- trace ids are removed,
- alert fingerprints are removed,
- synthetic scenario slug phrases are removed,
- dataset and scenario labels are excluded from Jira query text.
- generated root-cause and severity labels are excluded from Jira query text.

The builder still exports these audit-only columns:

- `provenance_alert_overlap_count`,
- `provenance_trace_overlap_count`.

They are useful to confirm that generated Jira links are correct, but they are
not used in `baseline_score`. This distinction matters for research credibility.

## Metrics

`baseline-ranking-report.json` and `baseline-ranking-report.md` include:

- MRR,
- Recall@1,
- Recall@3,
- nDCG@3,
- top ranked candidates per Jira issue,
- scoring policy,
- leakage controls.

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

The next practical improvement is to add a raw-only candidate feature profile
that does not use scenario labels such as severity or root-cause category. That
will move the ranking proof closer to a production setting where labels are
predicted rather than known.
