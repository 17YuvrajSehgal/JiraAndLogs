# Research Project Onboarding Guide

This guide explains the project in plain language for a new team member.

The goal is to make the full research flow understandable without needing to
read every script first. After reading this file, a new person should understand
what we are building, what data we collect, how the data is created, where it is
stored, how models use it, and how we judge whether the product idea is working.

## Product Direction Update (2026-05-21)

The primary product task is now **triage**: given a telemetry window, decide
whether it is worth a Jira ticket, and if so, draft the ticket. The original
**retrospective ranking** task (given a Jira ticket, find the matching
telemetry) is kept as a secondary benchmark for postmortem tooling and as a
probe of representation quality.

The shift is motivated by where the value lies for large companies. Alerting
tools already surface anomalies; the bottleneck is the human decision "is this
worth filing." A triage product reduces that decision cost.

See `docs/triage-task-contract.md` for the full task definition, label space,
and metrics.

## The One Sentence Version

We run a realistic microservices application, create controlled production-like
incidents, collect logs, metrics, traces, alerts, and Kubernetes state, generate
Jira-shaped incident records, then train and evaluate systems on two tasks:
**triage** (decide whether a telemetry window deserves a Jira ticket — the
primary product task) and **retrospective ranking** (connect an existing Jira
ticket to its causing telemetry episode — kept as a secondary benchmark).

## What We Are Trying To Build

We are building a Jira-aware observability intelligence product.

In simple terms:

- Observability systems show what happened inside software systems.
- Jira issues show what engineers later decided was important.
- This project tries to connect those two worlds.

The current product framing has two tasks. **Triage** is the primary task and
the headline product capability. **Retrospective ranking** is kept as a
secondary benchmark.

Triage example:

1. The system observes a new telemetry window: payment service errors are
   climbing and checkout latency is rising.
2. The product decides the window is ticket-worthy and outputs a calibrated
   probability.
3. It drafts a ticket: summary, suspect service, severity, affected
   components, and the evidence links that drove the decision.
4. A human reviewer approves or rejects before any real Jira write.

Retrospective ranking example (secondary, for postmortems):

1. A Jira issue says checkout is failing because payment calls are unavailable.
2. The product searches recent telemetry episodes.
3. It ranks the most likely matching episode at the top.
4. It shows logs, alerts, service names, metrics, traces, and Kubernetes signals
   that explain why that episode was selected.

The first product version does not automatically create Jira issues. Human
approval and real Jira writing are later phases.

## Why We Need Our Own Dataset

The dataset is the hardest part of this research.

Public Jira datasets usually contain issue text, priority, comments, labels, and
metadata. They usually do not contain the exact logs, metrics, traces, and
alerts that caused the issue.

Public observability datasets often contain logs, metrics, or traces. They
usually do not contain the linked Jira issues written by engineers.

For this project, we need both sides:

| Side | What it contains | Why it matters |
| --- | --- | --- |
| Telemetry side | Logs, metrics, traces, alerts, Kubernetes events | Shows what really happened in the system |
| Jira side | Incident summary, priority, comments, components, labels | Shows how humans describe and track the problem |

Because we do not have a private company dataset with both sides linked, we
create a lab dataset where the ground truth is controlled and recorded.

## The System We Run

The application under test is Google's Online Boutique microservices demo.

It is useful because it behaves like a real distributed application:

- it has multiple services,
- services call each other,
- there is synthetic user traffic,
- incidents can affect upstream and downstream services,
- logs, metrics, and traces can be collected from real running containers.

The local Kubernetes lab uses two main namespaces:

| Namespace | Purpose |
| --- | --- |
| `online-boutique-research` | Online Boutique services and load generator |
| `observability` | Prometheus, Alertmanager, Loki, Tempo, Grafana, Alloy, OpenTelemetry Collector |

The observability stack gives us the evidence used by the dataset and later
models:

| Tool | Data type |
| --- | --- |
| Loki | Logs |
| Prometheus | Metrics |
| Alertmanager | Alerts |
| Tempo | Traces |
| Kubernetes API | Pods, restarts, events, deployment rollout state |

## The Triage Task (Primary Product Task)

The triage task is the headline product capability.

For every telemetry window in the system, the model must decide whether the
window deserves a Jira ticket and produce a calibrated probability and
evidence summary.

In plain terms:

```text
Input:
  One telemetry window
  (logs, metrics, traces, alerts, Kubernetes state)

Output:
  Triage label: ticket_worthy / borderline / noise
  Calibrated probability p_ticket_worthy in [0, 1]
  Ranked evidence references
  Optional: a draft Jira ticket (summary, components, severity)

Success:
  The product flags real incidents (high recall),
  rarely flags non-incidents (high precision at low FPR),
  is well calibrated (predicted probability matches observed rate),
  and reports its confidence honestly on borderline windows.
```

The full contract — label space, severity, components, hard cases, metrics,
splits, and production-safe field policy — lives in
`docs/triage-task-contract.md`. New benchmark, schema, and script work for the
triage task must conform to that contract.

Why triage matters more than ranking for the product. Alerting tools already
surface anomalies. The decision "would a senior engineer file this in Jira"
is the bottleneck that creates alert fatigue, missed incidents, and noisy
on-call. A model that gets that decision right is the product.

## The Retrospective Ranking Task (Secondary Benchmark)

The original task is a ranking problem. It remains a useful secondary
benchmark because it shares the same telemetry infrastructure, probes
representation quality, and supports postmortem tooling. The triage task above
is the primary product task; this section is kept for completeness.

For every Jira-like issue, we create a list of candidate telemetry episodes. The
model must put the true matching episode as high as possible.

In plain terms:

```text
Input:
  One Jira issue
  Many candidate telemetry episodes

Output:
  Ranked list of episodes

Success:
  The real matching episode is ranked near the top
```

This is the task our first MVP solved. See
`docs/ml-ai-pipeline-benchmark-plan.md` for the current ranking benchmark.

## Key Words Used In This Project

| Term | Simple meaning |
| --- | --- |
| Dataset run | One full execution of a dataset plan with one run id |
| Scenario | One controlled behavior, such as normal traffic or Redis outage |
| Scenario family | A group of scenarios sharing fault mechanism and affected service (e.g. payment-outage, cart-redis) — used for triage train/test holdouts |
| Incident episode | One labeled period of system behavior caused by a scenario |
| Telemetry window | A time window around an episode, such as before, during, or after the fault |
| Shadow Jira issue | A Jira-shaped issue record generated by the lab, not written to real Jira |
| Triage label | Per-window label for the triage task: ticket_worthy / borderline / noise |
| Ticket-worthy window | A window a senior engineer would file a Jira ticket on |
| Borderline window | A window where reasonable engineers would disagree about filing |
| Noise window | A window that should not become a ticket — baseline, near-miss, recovered transient |
| Hard case | A window intentionally designed to confuse simple models (e.g. restart vs outage). Analysis flag only, not a model input |
| Operating point | A decision threshold on the triage probability, usually chosen for a fixed false-positive rate (e.g. FPR=1%) |
| Ranking example | One Jira issue paired with one candidate telemetry episode |
| Positive example | The candidate episode is the true match for the Jira issue |
| Negative example | The candidate episode is not the true match |
| Hard negative | A wrong candidate that looks similar enough to confuse a model |
| Derived dataset | ML-ready files built from raw runs |
| Global dataset | Dataset where every query ranks against candidates across the whole corpus |

## How A Dataset Run Works

A dataset run follows this flow:

```text
1. Create a run folder and manifest
2. Run Online Boutique traffic
3. Execute one scenario at a time
4. Create telemetry windows for each scenario
5. Export logs, metrics, traces, alerts, and Kubernetes state
6. Generate shadow Jira issues for incident scenarios
7. Validate the raw run
8. Build derived ranking files
9. Build aggregate, holdout, or global benchmark files
```

The raw run is stored under:

```text
data/runs/<DATASET_RUN_ID>/
```

The derived run is stored under:

```text
data/derived/<DATASET_RUN_ID>/
```

Raw runs should be treated as evidence. We do not mutate them after collection
unless we are intentionally rerunning a run from scratch.

Derived files can be rebuilt from the raw runs.

## What Operations We Run On The Microservices

We use controlled operations to create realistic system behavior.

| Operation | What it does | Example use |
| --- | --- | --- |
| `RecordOnly` | Does not inject a fault, only records normal behavior | Baseline normal traffic |
| `SetEnv` | Changes an environment variable and rolls a deployment | Add latency or traffic pressure |
| `ScaleDeployment` | Scales a service down and back up | Simulate service outage |
| `RestartPods` | Deletes pods and waits for replacements | Simulate restart or recovery event |

Examples of scenario families:

| Scenario family | What it tests |
| --- | --- |
| Product catalog latency | Can the system identify latency degradation? |
| Payment unavailable | Can it find a checkout dependency outage? |
| Redis cart outage | Can it separate cart impact from Redis root cause? |
| Pod restart | Can it distinguish restart from full outage? |
| Bad configuration | Can it detect config-like failure patterns? |
| High traffic near miss | Can it avoid creating false incidents from noisy traffic? |
| Baseline normal traffic | Can it avoid matching normal periods as incidents? |

The point is not to create easy incidents. The point is to create realistic
confusion:

- root service versus downstream symptom service,
- outage versus restart,
- high traffic versus real incident,
- latency versus bad configuration,
- partial recovery versus complete recovery,
- incomplete Jira components versus actual telemetry evidence.

## What Data We Collect

For each telemetry window, we collect multiple evidence types.

| Data type | What we collect | Why it helps |
| --- | --- | --- |
| Logs | Exact service logs, service context logs, namespace context logs | Gives text evidence and error messages |
| Metrics | Error rate, latency, CPU, memory, restarts, request volume | Gives numeric behavior over time |
| Traces | Distributed trace evidence when available | Shows service-to-service call paths |
| Alerts | Alertmanager and Prometheus alert state | Shows what an operations team would see |
| Kubernetes events | Pod events and scheduling/restart information | Helps identify restarts and rollout problems |
| Deployment state | Rollout and readiness snapshots | Helps separate outage, restart, and recovery |

The raw exported files are usually under:

```text
data/runs/<DATASET_RUN_ID>/raw/
  loki/
  prometheus/
  tempo/
  kubernetes/
```

The run also records top-level JSONL files such as:

```text
data/runs/<DATASET_RUN_ID>/episodes.jsonl
data/runs/<DATASET_RUN_ID>/telemetry_windows.jsonl
data/runs/<DATASET_RUN_ID>/alerts.jsonl
data/runs/<DATASET_RUN_ID>/jira_shadow_issues.jsonl
```

## What A Telemetry Window Means

An incident is split into time windows so we can compare behavior before, during,
and after the fault.

Fault scenarios usually have:

| Window | Meaning |
| --- | --- |
| `pre_fault_baseline` | What the system looked like before the fault |
| `active_fault` | What the system looked like while the fault was active |
| `recovery_window` | What the system looked like after the fault was removed |

Normal baseline scenarios usually have:

| Window | Meaning |
| --- | --- |
| `observation_window` | Normal behavior without an injected fault |

These windows help the derived feature builder compute deltas, such as:

- active error rate compared to baseline,
- active latency compared to baseline,
- whether restart events appeared,
- whether recovery returned to normal,
- whether one service changed more than others.

## When We Create Jira Issues

We do not create a Jira issue for every scenario.

We create a shadow Jira issue only when the scenario is intended to represent a
real incident that an engineering team would plausibly track.

Examples that should create Jira issues:

- payment service unavailable,
- cart Redis outage,
- major product catalog latency,
- checkout service restart with user impact,
- bad configuration causing a customer-visible failure.

Examples that should not create Jira issues:

- normal baseline traffic,
- noisy high traffic that does not become an incident,
- small latency near miss,
- restart near miss with no meaningful user impact.

This distinction is important because production systems are noisy. A useful
product must not turn every strange telemetry pattern into a Jira issue.

## What Shadow Jira Issues Are

A shadow Jira issue is a Jira-like JSON record created by our lab.

It is called "shadow" because it is not written to real Jira. It exists only in
the dataset.

The generated issue tries to look like a real production issue. It can include:

- Jira key, such as `OBSRV-1001`,
- summary,
- description,
- priority,
- initial priority and updated priority,
- issue type,
- components,
- labels,
- comments,
- status history,
- affected service hints,
- timestamps,
- linked telemetry windows,
- linked alerts,
- linked traces or trace summaries,
- intentionally incomplete or noisy fields.

The project uses a real-looking sample issue as a guide:

```text
sample-jira-datasets/sample-jira-dataset.json
```

## How Shadow Jira Issues Are Created

Shadow Jira issues are generated from scenario metadata and run metadata.

At a high level:

```text
Scenario says:
  This is a Jira-worthy incident.
  The affected service is paymentservice.
  The severity is critical.
  The likely user impact is checkout failure.

The generator creates:
  A Jira-shaped issue with summary, priority, comments, labels, timestamps,
  components, and links back to telemetry windows.
```

The generator intentionally adds some realism:

- issue creation can be delayed after the incident starts,
- comments can be noisy or incomplete,
- components can be partially wrong,
- summaries may describe symptoms instead of the true root cause,
- priority can change as the incident becomes clearer.

This is intentional. Real Jira issues are not perfect labels written by a clean
machine. They are human operational records.

## Where Shadow Jira Issues Are Stored

Raw shadow Jira issues are stored in the raw run folder:

```text
data/runs/<DATASET_RUN_ID>/jira_shadow_issues.jsonl
```

Derived copies are stored in:

```text
data/derived/<DATASET_RUN_ID>/issues.jsonl
data/derived/<DATASET_RUN_ID>/issues.csv
```

In the global dataset, Jira queries are stored in:

```text
data/derived/global/<GLOBAL_DATASET_ID>/queries.jsonl
```

## What The Raw Data Looks Like

The raw data is evidence-oriented. It keeps what the system observed.

A simplified episode might look like this:

```json
{
  "dataset_run_id": "2026-05-19-dataset-v3-compact-compact-a-r01",
  "episode_id": "2026-05-19-dataset-v3-compact-compact-a-r01-paymentservice-unavailable-critical-...",
  "scenario_id": "paymentservice-unavailable-critical",
  "service": "paymentservice",
  "severity": "critical",
  "jira_candidate": true,
  "start_time": "2026-05-19T10:00:00Z",
  "end_time": "2026-05-19T10:10:00Z"
}
```

A simplified telemetry window might look like this:

```json
{
  "window_id": "paymentservice-unavailable-critical-active_fault-paymentservice",
  "episode_id": "2026-05-19-dataset-v3-compact-compact-a-r01-paymentservice-unavailable-critical-...",
  "window_type": "active_fault",
  "service": "paymentservice",
  "raw_paths": {
    "loki": "raw/loki/...",
    "prometheus": "raw/prometheus/...",
    "kubernetes": "raw/kubernetes/..."
  }
}
```

A simplified shadow Jira issue might look like this:

```json
{
  "key": "OBSRV-1002",
  "summary": "Checkout failures during payment authorization",
  "priority": "Critical",
  "components": ["checkout", "payments"],
  "labels": ["incident", "online-boutique", "checkout"],
  "linked_episode_id": "2026-05-19-dataset-v3-compact-compact-a-r01-paymentservice-unavailable-critical-...",
  "comments": [
    "Customers are reporting checkout failures.",
    "Payment calls look unhealthy; still checking dependency behavior."
  ]
}
```

The exact schema can evolve, but the important idea stays the same: every Jira
issue links back to the telemetry episode that caused it.

## What The Derived Data Looks Like

Derived data is model-oriented. It turns raw evidence into files that ranking
pipelines can read.

Per-run derived data is stored under:

```text
data/derived/<DATASET_RUN_ID>/
```

Important files:

| File | Meaning |
| --- | --- |
| `episodes.jsonl` and `episodes.csv` | One row per incident or baseline episode |
| `windows.jsonl` and `windows.csv` | One row per telemetry window |
| `issues.jsonl` and `issues.csv` | One row per shadow Jira issue |
| `episode_features.jsonl` | Derived numeric and text features per episode |
| `ranking_examples.jsonl` and `ranking_examples.csv` | Query-candidate pairs for ranking |
| `candidate_scores.csv` | Deterministic baseline scores |
| `raw_telemetry_candidate_scores.csv` | Scores from raw telemetry features |
| `ablation-metrics.csv` | Metrics when feature groups are removed |
| `raw-telemetry-failure-analysis.csv` | Why raw telemetry ranking missed top results |
| `baseline-ranking-report.md` | Human-readable per-run metrics |

The most important training file is usually:

```text
ranking_examples.jsonl
```

A triage example (the primary task) is one telemetry window with a label and
production-safe features. A ranking example (the secondary task) is one Jira
query paired with one candidate telemetry episode. Both forms are produced
by the dataset build pipeline; see `docs/dataset-v4-plan.md` for the file
inventory.

The first dataset collection following the new product framing is Dataset
v4. Earlier dataset versions (v1, v2, v2.1, v3) and their collected data have
been removed from the repository; their concepts are captured in
`docs/dataset-v4-plan.md` and `docs/triage-task-contract.md`. No collected
data exists yet — Phase A (scenario authoring) is in progress.

## Why The Global Dataset Matters

A global dataset lets every Jira query or telemetry window be evaluated
against the full corpus, not only data from its own collection run. For
triage, the global dataset is also where the Jira memory corpus lives — a
window queries past Jira issues from across all runs, time-ordered and
own-run-excluded.

This is much harder and closer to real product behavior. A production tool
will not only see one small run. It will see many possible incidents and
noisy near misses, plus a growing organizational Jira memory.

## How Models Use The Data

The model sees:

1. Query text from the Jira issue.
2. Candidate evidence from telemetry episodes.
3. Numeric features extracted from telemetry.
4. A label that says which candidate is the true match.

The model must learn to rank candidates.

Different model families can use different files:

| Model family | Typical inputs |
| --- | --- |
| Lexical retrieval | Jira text and raw telemetry evidence text |
| Classical ML | Numeric telemetry features from ranking examples |
| Neural models | Query text, candidate text, embeddings, numeric features |
| Language models | Condensed Jira text plus telemetry evidence summaries |
| Hybrid models | A combination of text retrieval, numeric features, and reranking |
| Agentic systems | Tools that inspect logs, metrics, traces, and candidate summaries before ranking |

The stable benchmark contract is documented in:

```text
docs/ml-ai-pipeline-benchmark-plan.md
```

Important rule: production-facing models must not use lab-only labels as input.

Do not train on:

- scenario id,
- known root-cause label,
- candidate severity label,
- generated ground-truth fields,
- any field that would not exist in production before human labeling.

Those fields can be used for analysis, debugging, and sanity checks, but not as
production model features.

## How We Split The Data For Models

We split by query dataset run, not by individual rows.

This matters because one Jira query creates many candidate rows. If we randomly
split rows, the same query can appear in train and test, which leaks information
and makes the model look better than it really is.

Correct idea:

```text
Train on some dataset runs.
Validate on a different dataset run.
Test on a different dataset run.
```

Wrong idea:

```text
Randomly split individual query-candidate rows.
```

The triage split (the primary task) goes further: it holds out whole
scenario families, not just runs, so the model cannot memorize fault
signatures across runs of the same family. See
`docs/triage-task-contract.md` for the split rules.

The global dataset contains a split manifest at:

```text
data/derived/global/<GLOBAL_DATASET_ID>/triage-split-manifest.json
```

## Metrics We Use

We use ranking metrics because the MVP returns a ranked list.

| Metric | Simple meaning |
| --- | --- |
| MRR | How high the first correct answer appears on average |
| Recall@1 | How often the true episode is ranked first |
| Recall@3 | How often the true episode is in the top 3 |
| F1@1 | F1 score for top-1 ranking quality |
| F1@3 | F1 score for top-3 triage quality |
| nDCG@3 | Rewards the true answer being near the top of the first 3 results |

For this project, each Jira query has one true episode.

For F1@k:

```text
If the true episode is ranked within top k:
  Precision@k = 1 / k
  Recall@k = 1
  F1@k = harmonic mean of Precision@k and Recall@k

If the true episode is not ranked within top k:
  Precision@k = 0
  Recall@k = 0
  F1@k = 0
```

Why F1@3 is useful:

- Recall@3 says whether the right answer is somewhere in the top 3.
- F1@3 also penalizes the fact that a human still has to inspect 3 candidates.

## How To Read Results

When reading a benchmark report, do not only look for the highest score.

Ask these questions:

1. Is the result measured on the global hard-negative dataset?
2. Is the test split separated by query run?
3. Does the model use only production-safe fields?
4. Are near misses included?
5. Are restarts and outages both included?
6. Does the failure analysis show understandable misses?

Low scores are not automatically bad in this project. A hard dataset should
expose weak pipelines.

The purpose is not to make a demo look perfect. The purpose is to avoid
overestimating product performance before testing on real company data.

## Current Baseline Results

No baseline results yet. Earlier dataset versions and their benchmark
results were removed during the move to the Jira-as-memory product
framing. The first triage benchmark and the first updated ranking benchmark
will be produced from the Dataset v4 collection. See
`docs/dataset-v4-plan.md` for the collection plan and
`docs/ml-ai-pipeline-benchmark-plan.md` for the benchmark contract.

## Main Output Folders

| Folder | What it contains |
| --- | --- |
| `data/runs/` | Raw collected dataset runs |
| `data/derived/` | Per-run derived model files |
| `data/derived/aggregate/` | Cross-run aggregate reports |
| `data/derived/holdout/` | Run-aware holdout reports |
| `data/derived/corpora/` | Corpus manifests and corpus-level bookkeeping |
| `data/derived/global/` | Global candidate-pool datasets and benchmark outputs |

Planned global paths for Dataset v4 (no collected data yet):

```text
data/derived/global/<GLOBAL_DATASET_ID>/global-triage-examples.jsonl
data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-corpus.jsonl
data/derived/global/<GLOBAL_DATASET_ID>/triage-split-manifest.json
data/derived/global/<GLOBAL_DATASET_ID>/benchmarks/triage-baseline-v1/
```

## How To Read The Project

Suggested reading order for a new team member:

1. Read this file first.
2. Read `docs/triage-task-contract.md` for the primary product task contract,
   including the Jira-as-memory architecture.
3. Read `docs/dataset-v4-plan.md` for the active dataset plan.
4. Read `README.md` for the full repository overview.
5. Read `docs/research-lab-deployment.md` if you need to rebuild Kubernetes.
6. Read `docs/dataset-acquisition-plan.md` to understand raw collection.
7. Read `docs/jira-shadow-issue-contract.md` to understand generated Jira records.
8. Read `docs/ml-ai-pipeline-benchmark-plan.md` before building triage or ranking models.
9. Read `docs/production-corpus-dataset-plan.md` only for historical collection
   mechanics; the v3 dataset itself has been removed.

Useful folders:

| Path | Purpose |
| --- | --- |
| `deploy/research-lab/` | Kubernetes overlays, observability config, scenarios, run plans, corpus plans |
| `scripts/research-lab/` | PowerShell and Python workflow scripts |
| `schemas/` | JSON schemas for run, episode, window, alert, and Jira records |
| `sample-jira-datasets/` | Example production-style Jira issue shape |
| `microservices-demo-google/` | Local Online Boutique repository |

## Important Scripts

Most workflow scripts live in:

```text
scripts/research-lab/
```

The main scripts are:

| Script | What it does |
| --- | --- |
| `check-prereqs.ps1` | Checks required local tools |
| `create-kind-cluster.ps1` | Creates the local Kubernetes cluster |
| `apply-online-boutique.ps1` | Deploys Online Boutique into the research namespace |
| `install-observability.ps1` | Installs Prometheus, Loki, Tempo, Grafana, Alloy, and collectors |
| `start-dataset-run.ps1` | Creates the initial raw run folder and manifest |
| `run-scenario.ps1` | Runs one scenario, applies the operation, exports windows, and restores the service |
| `export-telemetry-window.ps1` | Exports logs, metrics, traces, alerts, and Kubernetes evidence for a window |
| `generate-shadow-jira-issues.ps1` | Creates Jira-shaped records for Jira-worthy scenarios |
| `validate-dataset-run.ps1` | Validates the raw run structure and required files |
| `collect-dataset-run.ps1` | Runs the older simple dataset workflow |
| `collect-dataset-plan.ps1` | Runs a JSON run plan and optionally builds derived outputs |
| `collect-dataset-corpus.ps1` | Runs the compact corpus workflow across multiple dataset runs |
| `build-triage-dataset.ps1` | Builds per-run derived triage examples |
| `build-jira-memory-corpus.ps1` | Builds the time-ordered Jira memory corpus across runs |
| `build-window-memory-matchings.ps1` | Computes ground-truth memory-match labels per window |
| `build-global-triage-dataset.ps1` | Builds the global triage dataset with family-level splits |
| `build-ranking-dataset.ps1` | Builds per-run derived ranking files (secondary task) |
| `build-cross-run-evaluation.ps1` | Builds aggregate ranking metrics across derived runs (secondary task) |
| `build-run-aware-holdout-evaluation.ps1` | Builds ranking holdout reports where whole runs are held out (secondary task) |
| `build-global-hard-negative-dataset.ps1` | Builds the global candidate-pool ranking dataset (secondary task) |
| `run-global-pipeline-benchmark.ps1` | Runs baseline model and retrieval comparisons on the global ranking dataset (secondary task) |

Scenario definitions live under:

```text
deploy/research-lab/scenarios/
```

Run plans live under:

```text
deploy/research-lab/run-plans/
```

The corpus manifest lives at:

```text
deploy/research-lab/corpora/dataset-v3-production-corpus.json
```

## Common Commands

Set the repository root:

```powershell
Set-Location C:\workplace\JiraAndLogs
```

Preview a corpus plan (substitute the v4 prefix once chosen):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -PlanOnly
```

Collect a corpus from scratch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -ForceNewRun
```

Build the per-run triage dataset (one run at a time):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-triage-dataset.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>" `
  -Force
```

Build the Jira memory corpus across all runs in a prefix:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-jira-memory-corpus.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force
```

Build the global triage dataset:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-triage-dataset.ps1 `
  -DatasetRunPrefix "<DATASET_RUN_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force
```

## How To Inspect The Current Dataset

No collected dataset exists yet. After Phase A and Phase B
(`docs/dataset-v4-plan.md`), the global directory will contain a
`README.md`, the triage examples file, the Jira memory corpus, and the
split manifest. Inspect those paths first.

## What Good Progress Looks Like

Good progress is not only higher scores.

Good progress means:

- raw evidence is collected reliably,
- Jira issues are realistic enough to be messy,
- near misses are included,
- hard negatives are included,
- metrics are reported consistently,
- failure analysis explains why a pipeline missed,
- model splits avoid leakage,
- production-safe features are separated from lab-only labels,
- documentation stays current with scripts and dataset contracts.

## Current Known Limitations

Known limitations once the v4 dataset is collected:

- shadow Jira issues are generated, not written by real engineers,
- all incidents come from a controlled lab,
- Online Boutique is realistic but still smaller than a real company platform,
- some telemetry coverage depends on what each service emits,
- real Jira Cloud or Jira Data Center integration is still a later phase,
- the Jira memory corpus is synthetic; production memory will be noisier
  and may have weaker linkage between issues and telemetry timestamps.

These limitations are acceptable for the current research stage because the
immediate goal is to build a credible research benchmark and avoid
overestimating simple pipelines before transferring to real company data.

## What Comes Next

The next research steps should focus on model and benchmark quality:

1. Keep the global hard-negative dataset as the main comparison target.
2. Add more pipeline families: lexical, classical ML, neural, LLM, hybrid, and
   agentic approaches.
3. Use run-aware splits and leave-one-run-out evaluation.
4. Improve root-cause versus symptom-service separation.
5. Improve restart versus outage separation.
6. Add more diverse production-style incidents if future models start
   overfitting the compact corpus.
7. Preserve failure analysis so weak results teach us what to improve.

The product direction remains:

```text
Jira issue or incident query
  -> retrieve candidate telemetry episodes
  -> rank the most likely matches
  -> explain evidence
  -> later ask a human to approve actions
```

That is the core idea this repository is testing.
