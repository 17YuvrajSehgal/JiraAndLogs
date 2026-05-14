# Dataset Acquisition Plan

This document defines how the research dataset should be created, what each run
contains, and how telemetry windows become Jira-shaped records for the ranking
MVP.

The goal is not to create a toy demo dataset. The dataset must look like the
operational evidence a real company would produce: normal traffic, noisy
non-incidents, near misses, clear incidents, alerts, logs, metrics, traces, and
realistic Jira issue records linked by stable metadata.

## Primary Goal

The first MVP only ranks likely related Jira issues or incident candidates. Human
approval and real Jira writing are phase 2.

For the ranking MVP to be credible, every training and evaluation example must
be traceable to:

- one dataset run,
- one traffic profile,
- one scenario or baseline window,
- one telemetry time window,
- zero or more alert events,
- zero or one shadow Jira issue,
- raw logs, metrics, and traces exported from the observability stack.

## Dataset Run Directory

Each run should be written under:

```text
data/runs/<DATASET_RUN_ID>/
```

Expected structure:

```text
data/runs/<DATASET_RUN_ID>/
  manifest.json
  episodes.jsonl
  telemetry_windows.jsonl
  alerts.jsonl
  jira_shadow_issues.jsonl
  raw/
    loki/
      run-context.json
      episode-context-<episode_id>.json
      <window_id>.json
    prometheus/
      <window_id>.json
    tempo/
      <window_id>.json
  summaries/
    run-summary.md
    validation-report.md
    validation-report.json
```

The current schemas live in:

- `schemas/dataset_run.schema.json`
- `schemas/incident_episode.schema.json`
- `schemas/telemetry_window.schema.json`
- `schemas/alert_event.schema.json`
- `schemas/jira_shadow_issue.schema.json`

## Required Run Metadata

Every dataset run must include these stable fields:

```text
DATASET_RUN_ID
DATASET_NAME
DEPLOYMENT_ENVIRONMENT
TRAFFIC_PROFILE_ID
SCENARIO_ID
JIRA_MODE
started_at
ended_at
cluster_context
application_namespace
observability_namespace
online_boutique_version
```

Current Kubernetes metadata injection is configured through:

```text
deploy/research-lab/online-boutique/kustomization.yaml
```

The current shadow mode values are:

```yaml
DATASET_NAME: online-boutique-jira-telemetry
DATASET_RUN_ID: local-dev-run-001
DEPLOYMENT_ENVIRONMENT: research-local
JIRA_MODE: shadow
SCENARIO_ID: baseline-normal-traffic
TRAFFIC_PROFILE_ID: baseline-checkout-mix
```

Before each controlled run, `DATASET_RUN_ID`, `SCENARIO_ID`, and
`TRAFFIC_PROFILE_ID` should be changed to match the scenario being executed.

## Implemented Workflow

The current workflow is implemented in PowerShell under `scripts/research-lab`.
Run every script through `powershell -NoProfile -ExecutionPolicy Bypass` because
Windows execution policy may block local scripts or modules.

One-command first dataset workflow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001" `
  -Quick
```

Useful options:

- `-Quick`: uses shorter scenario durations for a smoke-quality dataset.
- `-ScenarioDurationSeconds <n>`: overrides all scenario active durations.
- `-PostWindowSeconds <n>`: overrides recovery observation duration.
- `-RecordOnly`: records windows without applying fault actions.
- `-NoTelemetryExport`: creates metadata only, useful for script testing.
- `-SkipJiraGeneration`: does not create shadow Jira issues.
- `-ForceNewRun`: recreates an existing run scaffold.

Fast script-only smoke test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "dry-run-001" `
  -RecordOnly `
  -NoTelemetryExport `
  -ScenarioDurationSeconds 1 `
  -PostWindowSeconds 0 `
  -ForceNewRun
```

Manual workflow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\start-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001"

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-scenario.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001" `
  -ScenarioFile deploy\research-lab\scenarios\baselines\baseline-normal-traffic.yaml

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-scenario.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001" `
  -ScenarioFile deploy\research-lab\scenarios\faults\productcatalog-latency-major.yaml

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\validate-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001"
```

## Dataset Creation Loop

### 1. Start A Dataset Run

Create a manifest before traffic or fault injection starts.

The manifest records:

- run id,
- operator or automation id,
- Git commit or workspace snapshot note,
- Kubernetes context,
- namespaces,
- active traffic profile,
- active scenario id,
- expected case type,
- expected affected services,
- timestamp source.

Implemented script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\start-dataset-run.ps1 `
  -DatasetRunId "2026-05-13-baseline-001" `
  -ScenarioId "baseline-normal-traffic" `
  -TrafficProfileId "baseline-checkout-mix"
```

### 2. Run Baseline Traffic

Start with a normal window before each incident scenario. This lets the ranking
system learn what healthy services look like under the same traffic profile.

Current traffic profile:

```text
deploy/research-lab/scenarios/traffic-profiles/baseline-checkout-mix.yaml
```

Traffic should include:

- browsing the homepage,
- viewing product pages,
- adding items to cart,
- viewing cart,
- checkout attempts,
- currency changes.

### 3. Execute One Controlled Scenario

Each scenario produces one or more incident episodes.

Current scenario files:

```text
deploy/research-lab/scenarios/baselines/baseline-normal-traffic.yaml
deploy/research-lab/scenarios/faults/productcatalog-latency-major.yaml
deploy/research-lab/scenarios/faults/cart-redis-degradation-critical.yaml
deploy/research-lab/scenarios/faults/frontend-cpu-nearmiss.yaml
```

The scenario runner currently supports these execution actions:

| Action | Behavior | Current Scenario |
| --- | --- | --- |
| `RecordOnly` | Waits for the scenario duration and records an observation window. | baseline normal traffic |
| `SetEnv` | Patches deployment environment variables, waits for rollout, then restores originals. | product catalog latency, frontend near miss |
| `ScaleDeployment` | Temporarily scales a deployment, then restores the original replica count. | Redis/cart degradation |
| `RestartPods` | Deletes pods matching a selector and waits for replacements to become ready. | available for future scenarios |

Current executable fault behavior:

- `productcatalog-latency-major`: sets `EXTRA_LATENCY=750ms` on `productcatalogservice`.
- `cart-redis-degradation-critical`: scales `redis-cart` to 0, then restores it to 1.
- `frontend-cpu-nearmiss`: temporarily increases `loadgenerator` to `USERS=60` and `RATE=8`.

For `SetEnv` scenarios, include `execution.target_container` whenever the
deployment has init containers or multiple containers. This keeps fault
injection and restore operations scoped to the intended runtime container.

Scenario metadata must record:

- `scenario_id`,
- `fault_id`,
- affected service,
- expected symptom,
- expected severity,
- expected user impact,
- whether it should produce a shadow Jira issue,
- fault start time,
- fault end time,
- recovery observation window.

### 4. Create Telemetry Windows

Each scenario should create multiple labeled windows:

```text
observation_window
pre_fault_baseline
active_fault
recovery_window
```

`observation_window` is used for record-only baseline scenarios. Fault scenarios
write `pre_fault_baseline`, `active_fault`, and `recovery_window`. More detailed
window types such as `fault_ramp_up` or `alerting_window` can be added later
without changing the JSONL contract.

Each window must be written to `telemetry_windows.jsonl` and linked back to the
run and episode:

```text
dataset_run_id
window_id
episode_id
scenario_id
start_time
end_time
window_type
expected_label
affected_services
```

## Telemetry Export

Telemetry export should happen after the window timestamps are known. Export raw
data first, then build compact features later. This preserves the evidence trail.

### Logs From Loki

Export logs for each window with the workflow script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\export-telemetry-window.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001"
```

The script starts temporary port-forwards to Loki, Prometheus, Tempo, and
Alertmanager unless `-NoPortForward` is supplied.

Manual Loki query shape:

```powershell
$query = '{namespace="online-boutique-research"}'
$encodedQuery = [uri]::EscapeDataString($query)
$uri = "http://127.0.0.1:3100/loki/api/v1/query_range?query=$encodedQuery&limit=5000"
Invoke-RestMethod -Uri $uri
```

Raw Loki exports should preserve:

- timestamp,
- namespace,
- pod,
- container,
- service name,
- severity,
- message,
- trace id or span id if present,
- research labels.

The exporter writes two levels of log evidence:

- `raw/loki/<window_id>.json` contains the exact service window, a padded
  service context query, and a padded namespace context query.
- `raw/loki/run-context.json` contains a continuous namespace-level log export
  across the whole dataset run, including padding before the first window and
  after the last window.

The run-level file is required for research use because some Online Boutique
services emit sparse logs. A window can be valid even when its service-specific
query has zero lines, but the run must still preserve enough namespace-level log
context to reconstruct what the application and Kubernetes workloads were doing.

### Metrics From Prometheus

Export metrics for application health, resource pressure, restarts, and alert
context.

Important metric families:

```text
kube_pod_info
kube_pod_container_status_restarts_total
kube_pod_container_resource_requests
kube_pod_container_resource_limits
container_cpu_usage_seconds_total
container_memory_working_set_bytes
up
ALERTS
```

Raw Prometheus exports should preserve:

- query,
- start time,
- end time,
- step,
- metric labels,
- values.

### Traces From Tempo

Export trace search results for each window and fetch full traces for candidate
trace ids.

Tempo search command shape:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:3200/api/search?limit=100'
```

Raw Tempo exports should preserve:

- trace id,
- root service,
- root span name,
- start time,
- duration,
- span service names,
- error status,
- relevant attributes.

## Alert Events

Alert events are not the same thing as Jira issues. Alerts may be noisy,
duplicated, delayed, or non-actionable.

Each alert event should include:

```text
alert_id
dataset_run_id
episode_id
alert_name
service
severity
starts_at
ends_at
status
labels
annotations
source
```

The current lab has Prometheus alert rules for:

- unavailable deployments,
- container restarts,
- near-miss resource pressure.

These should be exported to `alerts.jsonl`.

## Shadow Jira Issue Generation

Shadow Jira issues are generated records, not real Jira tickets. They should
match realistic Jira shape and use the sample Jira file as the style reference:

```text
sample-jira-datasets/sample-jira-dataset.json
```

Each generated issue should link back to:

```text
dataset_run_id
episode_id
scenario_id
fault_id
telemetry_window_ids
alert_ids
affected_services
trace_ids
```

The issue should include realistic production fields:

- summary,
- description,
- project,
- issue type,
- priority,
- severity,
- status,
- labels,
- components,
- reporter,
- assignee,
- comments,
- activity history,
- linked incidents or duplicated symptoms,
- deployment or environment metadata,
- timestamps for created, updated, resolved.

Do not generate a Jira issue for every alert. The dataset must include negative
and ambiguous examples.

Generate or regenerate issues for Jira-candidate episodes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\generate-shadow-jira-issues.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001"
```

## Case Types Required For Ranking

The ranking model needs several case types:

| Case Type | Jira Issue | Purpose |
| --- | --- | --- |
| Normal baseline | No | Teach healthy telemetry |
| Noisy non-incident | No | Teach noisy logs and harmless alerts |
| Near miss | Usually no | Teach risk signals that do not require Jira |
| Clear incident | Yes | Teach true issue linkage |
| Repeated incident | Yes or duplicate | Teach similarity across time |
| Cascading incident | Yes | Teach multi-service symptom spread |
| Misleading symptom | Maybe | Teach root cause versus symptom service |

This is critical. If every abnormal telemetry window becomes a Jira issue, the
ranking model will learn alert volume instead of operational relevance.

## First Small Dataset

The first usable dataset should be small but complete:

1. Baseline normal traffic.
2. Product catalog latency incident.
3. Cart or Redis degradation incident.
4. Frontend high-traffic near-miss case.
5. Post-recovery normal traffic.

`collect-dataset-run.ps1` now runs the normal baseline scenario at the beginning
and again at the end so each small dataset has both pre-incident and
post-recovery negative examples.

Minimum expected outputs:

```text
1 manifest.json
at least 5 incident or baseline episodes
at least 20 telemetry windows
alerts exported for every window
logs exported for every window
metrics exported for every window
traces exported for every window where traces exist
shadow Jira issues only for issue-worthy episodes
one validation report
```

## Implemented Scripts

Current scripts:

```text
scripts/research-lab/lib/ResearchLab.psm1
scripts/research-lab/start-dataset-run.ps1
scripts/research-lab/run-scenario.ps1
scripts/research-lab/export-telemetry-window.ps1
scripts/research-lab/generate-shadow-jira-issues.ps1
scripts/research-lab/validate-dataset-run.ps1
scripts/research-lab/collect-dataset-run.ps1
```

Responsibilities:

- `lib/ResearchLab.psm1`: shared path, JSONL, Git, Kubernetes, and scenario parsing helpers.
- `start-dataset-run.ps1`: creates the run folder and `manifest.json`.
- `run-scenario.ps1`: applies one scenario, restores the app, records exact timestamps, writes episodes and windows, and optionally exports telemetry and generates shadow Jira issues.
- `export-telemetry-window.ps1`: queries Loki, Prometheus, Tempo, and Alertmanager. It also supports `-RunLevelLokiOnly` to refresh the continuous run-level log corpus without re-exporting every window.
- `generate-shadow-jira-issues.ps1`: creates realistic Jira-shaped records.
- `validate-dataset-run.ps1`: verifies links, schemas, and required raw exports.
- `collect-dataset-run.ps1`: orchestrates the first small dataset workflow.

## Validation Rules

A dataset run is usable only if:

- every file is valid JSON or JSONL,
- every record has `dataset_run_id`,
- every episode has at least one telemetry window,
- every generated Jira issue links to an episode,
- every generated Jira issue links to at least one telemetry window,
- raw exports exist for every telemetry window,
- `raw/loki/run-context.json` contains namespace-level log context when raw exports are required,
- negative windows are present,
- severities are one of `none`, `minor`, `major`, or `critical`,
- episode and telemetry-window labels include `incident_type` and `root_cause_category`,
- timestamp ranges are non-overlapping where expected,
- the validation report states known gaps explicitly.

Validation command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\validate-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001"
```

For metadata-only script testing, use `-AllowMissingRawExports`.

## Research Proof Requirements

For paper-quality evidence and commercial trust, every dataset result must be
reproducible. A future reviewer should be able to answer:

- Which scenario created this issue?
- Which services were affected?
- What logs, metrics, and traces were visible at the time?
- Which alerts fired?
- Why was this episode converted into a Jira issue?
- Why were similar noisy windows not converted into Jira issues?
- Can the ranking result be traced back to raw evidence?

The dataset should favor provenance and reproducibility over volume in the early
MVP. More data can be generated later once the run loop is correct.
