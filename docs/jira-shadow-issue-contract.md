# Jira Shadow Issue Contract

The sample production-style issue in `sample-jira-datasets/sample-jira-dataset.json` shows that useful Jira data is much richer than a title and severity. Our generated Jira shadow issues should preserve that richness from the first dataset run.

## Required shape

A shadow Jira issue must include:

- stable `jira_shadow_issue_id`,
- nullable real `jira_issue_key`,
- linked `dataset_run_id`,
- linked `incident_episode_id`,
- Jira-like `metadata`,
- `telemetry_links`,
- `history`,
- `activity`.

The schema is defined in `schemas/jira_shadow_issue.schema.json`.

The current generator is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\generate-shadow-jira-issues.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>"
```

It reads `episodes.jsonl`, `telemetry_windows.jsonl`, and `alerts.jsonl`, then
writes `jira_shadow_issues.jsonl` for episodes where `jira_candidate=true`.

## Production-like fields to preserve

The sample issue includes these useful signals:

- `metadata.summary`
- `metadata.project_key`
- `metadata.project_name`
- `metadata.issue_type`
- `metadata.status`
- `metadata.priority`
- `metadata.components`
- `metadata.labels`
- `metadata.resolution`
- `metadata.fix_versions`
- `metadata.description`
- `metadata.assignee`
- `metadata.reporter`
- `metadata.watcher_count`
- `metadata.created_at`
- `metadata.updated_at`
- `metadata.resolved_at`
- `metadata.development`
- `metadata.related_issues`
- `metadata.comments_id`
- `metadata.comments_body`
- `history`
- `activity`
- `worklog`
- `submissions`

## Mapping telemetry to Jira-like fields

| Telemetry/scenario source | Shadow Jira field |
| --- | --- |
| `scenario_id` | label and description |
| `incident_episode_id` | telemetry link and description |
| affected service | component |
| severity | priority |
| fault type | label and root-cause text |
| alert fingerprints | telemetry links and first comment |
| trace ids | telemetry links |
| log query | description and telemetry links |
| metric query | description and telemetry links |
| remediation template | comment and resolution note |

## Suggested synthetic workflow

Use a realistic lifecycle instead of creating issues as immediately resolved:

1. `Needs Triage`
2. `Open`
3. `In Progress`
4. `Resolved`

For non-Jira near misses, create an `incident_episode` and telemetry windows but do not create a shadow Jira issue. Those cases are essential negative examples for the ranking MVP.

## Privacy

Generated lab issues should not include real names, internal URLs, private hostnames, customer identifiers, secrets, or credentials. Use deterministic synthetic users and fake internal URLs.
