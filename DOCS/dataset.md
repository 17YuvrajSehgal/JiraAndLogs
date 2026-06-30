# Dataset Collection Guide

This document explains the three datasets used in this project, how they were produced, and how a new researcher can reproduce or extend them.

---

## Table of Contents

1. [Overview](#overview)
2. [Infrastructure Setup](#infrastructure-setup)
3. [Application 1 — Online Boutique](#application-1--online-boutique)
4. [Application 2 — OpenTelemetry Demo](#application-2--opentelemetry-demo)
5. [Application 3 — World of Logs (WoL)](#application-3--world-of-logs-wol)
6. [Scenario System](#scenario-system)
7. [Data Collection Pipeline — Step by Step](#data-collection-pipeline--step-by-step)
8. [What Gets Stored and Where](#what-gets-stored-and-where)
9. [Published Datasets](#published-datasets)
10. [Key Numbers at a Glance](#key-numbers-at-a-glance)

---

## Overview

The project needs labelled telemetry data — logs, metrics, and distributed traces — paired with Jira-style incident tickets, so that a retrieval and triage system can learn to link new anomalies to past incidents. Because real production systems rarely come with clean ground-truth labels, the majority of the data is **synthetic but realistic**: two open-source microservice applications run in a local Kubernetes cluster, faults are injected under controlled conditions, and every window of telemetry is labelled with whether it should produce a Jira ticket.

The three datasets are:

| Dataset | Application | Fault injection | Windows | Memory tickets |
|---|---|---|---|---|
| **Online Boutique (OB)** | Google microservices demo (forked, see [Repository forks](#repository-forks)) | Kubernetes + Chaos Mesh | ~6,720 | ~347 |
| **OTel Demo** | OpenTelemetry Astronomy Shop | Kubernetes + Flagd + Chaos Mesh | ~1,643 | ~147 |
| **World of Logs (WoL) v3** | Real Apache projects, 24 projects (MSR 2026) | N/A — real data | 78,140 queries | 38,642 |

All three datasets are independently labelled and self-contained. The OB and OTel Demo datasets share the same collection infrastructure and data pipeline; WoL is a pre-existing archive plus our derived corpus.

**For a deep dive on the WoL dataset (project selection, filter choices, bucket taxonomy, KG extractions, reproducibility, limitations)** see the dedicated dataset card:
[`DOCS/WoL-v3-dataset.md`](WoL-v3-dataset.md).

---

## Infrastructure Setup

### Kubernetes Cluster

All synthetic data collection runs on a **Google Cloud Platform VM**, with a Kubernetes cluster brought up via either Docker Desktop (`docker-desktop` context) or `kind` (`deploy/research-lab/kind-config.yaml`: 1 control-plane node + 2 workers, host port 8080 → container port 30080). The cloud VM hosts everything — the Kubernetes cluster, the observability stack, the application workloads, the fault-injection orchestrators, and the data collection scripts.

Two different VM shapes were used for the two corpora:
- **Online Boutique corpus**: `e2-standard-8` (8 vCPUs / 32 GB RAM)
- **OTel Demo corpus**: `e2-standard-16` (16 vCPUs / 64 GB RAM) — the larger shape was needed to run all 18 OTel Demo services + Kafka + the observability stack simultaneously

Why a single GCP VM rather than a managed GKE cluster:
- Reproducibility: the entire pipeline boots from a fresh image with one `kind create cluster` invocation.
- Cost predictability: ~$0.50/hour while running; teardown is a `gcloud compute instances delete`.
- Isolation: no shared production-tier infrastructure to perturb.

For local development the same scripts run unchanged against Docker Desktop, but the published numbers in the paper come from the GCP-VM runs (the long-running corpus collection windows would be punishing on a laptop).

Two application namespaces are created (`deploy/research-lab/namespaces.yaml`):

- `online-boutique-research` — hosts the Online Boutique workload
- `otel-demo-research` — hosts the OTel Demo workload (privileged pod security policy, required by OTel Demo's hostPath volume for host metrics)

### Observability Stack

A shared observability stack lives in the `observability` namespace. It is installed once via:

```
scripts/research-lab/install-observability.ps1
```

This runs six Helm chart installs in order, with values files under `deploy/research-lab/observability/values/`:

| Component | Chart | Role |
|---|---|---|
| **kube-prometheus-stack** | `kube-prometheus-stack-values.yaml` | Prometheus metrics scraping (15 s interval, 15 d retention) + Alertmanager |
| **Tempo** | `tempo-values.yaml` | Distributed trace storage (7 d retention, receives OTLP) |
| **Loki** | `loki-values.yaml` | Log aggregation (7 d retention, TSDB v13 index; PVC defaults to 50 GiB but should be bumped to 120 GiB before a production corpus run) |
| **Grafana Alloy** | `alloy-values.yaml` | DaemonSet log collector — scrapes pods via Kubernetes API |
| **Grafana** | `grafana-values.yaml` | Dashboards (admin/admin; datasources: Prometheus, Loki, Tempo) |
| **OpenTelemetry Collector** | `opentelemetry-collector-values.yaml` | Central hub — receives OTLP from app pods, fans out to Tempo (traces) and Prometheus (metrics) |

#### How telemetry flows

```
App pods (OTLP gRPC :4317)
        │
        ▼
OpenTelemetry Collector (observability namespace, 2 replicas)
  ├── Traces  ──► Tempo
  └── Metrics ──► Prometheus exporter (scraped by Prometheus)

Pod stdout/stderr
        │
        ▼
Grafana Alloy (DaemonSet) ──► Loki
```

Logs are collected separately by Alloy rather than through the OTel Collector. Alloy discovers pods in `online-boutique-research`, `otel-demo-research`, `observability`, and `trainticket` namespaces. It extracts structured fields (`severity`, `message`, `trace_id`, `span_id`) from JSON log lines and promotes `severity` as a Loki label.

#### Prometheus alert rules

Three alert rules are baked into the `kube-prometheus-stack` values for the OB namespace (they fire during fault scenarios and get exported as part of the raw telemetry):

| Rule | Condition | Severity | `jira_candidate` |
|---|---|---|---|
| `OnlineBoutiqueDeploymentUnavailable` | Any deployment has unavailable replicas for > 2 min | major | true |
| `OnlineBoutiqueContainerRestarting` | Container restart count increases within 10 min window | major | — |
| `OnlineBoutiqueNearMissResourcePressure` | CPU throttle ratio > 25 % for > 10 min | minor | **false** (negative class) |

The `jira_candidate: "false"` label on the near-miss rule is intentional — it marks a family of alerts that should *not* generate tickets, providing negative-class signal for the triage classifier.

#### Label discipline

Research metadata is injected as low-cardinality Kubernetes labels and OTel resource attributes — never as application-level telemetry. This prevents label leakage into training signals.

- **Safe in Prometheus / OTel**: `deployment.environment`, `service.namespace`, `dataset.name`, `jira.mode`, `research.jira-telemetry/dataset`, `research.jira-telemetry/service-tier`, `app.id`
- **Banned from Prometheus labels** (kept in JSONL only): request IDs, session IDs, trace IDs, fault IDs, raw Jira keys

---

## Application 1 — Online Boutique

**Source repository**: `microservices-demo-google/` — a **fork** of the upstream Google Microservices Demo with research-specific source-level changes.

The fork adds:
- Structured JSON console logging across all services (enables Grafana Alloy to extract `severity`, `message`, `trace_id`, `span_id` as Loki labels).
- Per-service OTel resource attributes (`research.jira-telemetry/service-tier`) wired into application init.
- Host-metrics instrumentation hooks.
- Explicit OTLP exporter configuration that respects `COLLECTOR_SERVICE_ADDR`.

These changes are committed to the fork itself rather than applied through a Kustomize overlay because they touch service init code (the overlay can only inject env vars and swap images). The custom-built images (`v5.0.0-otel-pilot*`) are produced from this fork's source.

**Namespace**: `online-boutique-research`

### Why Online Boutique?

Online Boutique is a well-known 12-service e-commerce demo (Go, Python, Node.js, Java, .NET) with realistic inter-service dependencies. It provides a known, stable workload against which faults can be cleanly injected and labelled.

### How it is deployed

All research-specific changes are applied through a **Kustomize overlay** — the upstream source is never modified. The overlay is at `deploy/research-lab/online-boutique/` and is applied with:

```
scripts/research-lab/apply-online-boutique.ps1
```

The overlay does two things:

1. **Swaps service images** for custom-built variants tagged `v5.0.0-otel-pilot*` that add:
   - Structured JSON console logging (enables Alloy field extraction)
   - Host metrics instrumentation
   - Explicit OTLP export configuration

2. **Injects environment variables** via `patches/enable-otel-and-research-env.yaml`:
   - `ENABLE_TRACING=1`
   - `COLLECTOR_SERVICE_ADDR=opentelemetrycollector.observability.svc.cluster.local:4317`
   - `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`
   - `DATASET_RUN_ID`, `SCENARIO_ID`, `JIRA_MODE` (pulled from the per-run `research-run-config` ConfigMap)
   - Per-service `research.jira-telemetry/service-tier` label (edge / business / dependency / catalog / recommendation / traffic)

The load generator is configured with **25 users at spawn rate 3**, exercising the full checkout flow (`/`, `/product/{id}`, `/cart`, `/cart/checkout`, `/setCurrency`).

`loadgenerator` and `redis-cart` intentionally keep their upstream images (no custom build needed — they carry no application-level telemetry that needed changing).

### Services

12 services: `cartservice` (.NET), `checkoutservice` (Go), `currencyservice` (Node), `paymentservice` (Node), `productcatalogservice` (Go), `recommendationservice` (Python), `shippingservice` (Go), `emailservice` (Python), `adservice` (Java), `frontend` (Go), `redis-cart`, `loadgenerator`. Full catalog with criticality ratings is at `deploy/research-lab/service-catalogs/online-boutique.yaml`.

### Fault families (26 fault families + 1 no-fault baseline, ~6,720 windows)

Faults are grouped by mechanism:

| Family | Examples |
|---|---|
| Service outages (scale to 0) | `checkoutservice-unavailable-critical`, `paymentservice-unavailable-critical`, `productcatalog-unavailable-critical` |
| Degradation / latency | `productcatalog-latency-major`, `currency-partial-latency`, `cart-redis-degradation-critical` |
| Pod restarts | `cartservice-1-of-3-restart`, `frontend-pod-restart-major`, `redis-cart-restart-major` |
| Resource pressure | `cartservice-memory-leak-ticket-worthy`, `paymentservice-connection-leak-ticket-worthy`, `frontend-cpu-nearmiss` |
| Network chaos (Chaos Mesh) | `dns-block-cartservice-60s`, `network-partition-cart-redis`, `packet-loss-frontend-30pct-90s` |
| Deployment events | `deploy-canary-rollback-quick`, `deploy-rolling-cart-graceful` |
| Near-miss / noisy (negative class) | `loadgenerator-traffic-spike-nearmiss`, `frontend-cpu-nearmiss`, `recommendationservice-unavailable-nearmiss` |
| Orphan faults (fault without ticket) | 8 scenarios where a real fault occurs but `produces_jira_ticket: false` |
| Baselines (no fault) | `baseline-normal-traffic` |

---

## Application 2 — OpenTelemetry Demo

**Source repository**: `opentelemetry-demo/` (upstream OTel Demo Astronomy Shop v2.2.0, cloned as-is, **no source code changes**)

**Namespace**: `otel-demo-research`

### Why OTel Demo?

OTel Demo adds architectural distance relative to Online Boutique: 18 services across 10 programming languages, Kafka as a message bus with downstream consumers (`accounting`, `fraud-detection`), and first-class OpenTelemetry instrumentation. This tests whether the retrieval system can handle architecturally unfamiliar failure modes — particularly Kafka consumer lag and cascade failures through async pipelines — where Online Boutique has no analogue.

### How it is deployed

The OTel Demo is deployed via a single Helm install script:

```
deploy/otel-demo/helm-install.ps1
```

Chart version: `0.40.9` (image tag `2.2.0`). The Helm values at `deploy/otel-demo/helm-values.yaml`:

- Pin all images to `ghcr.io/open-telemetry/demo:2.2.0`
- **Disable** bundled Jaeger, Prometheus, Grafana, and OpenSearch (the shared observability stack is used instead)
- Increase memory limits for `ad` and `fraud-detection` to 600 Mi (JVM OOM at upstream defaults)
- Enable `flagd` without the sidecar UI (flags are controlled programmatically)
- Configure the in-namespace OTel Collector to forward all telemetry to `opentelemetrycollector.observability.svc.cluster.local:4317`

#### Two-hop telemetry routing

```
App pods (OTLP :4317/:4318)
        │
        ▼
otel-demo-otelcol (in-namespace, adds app.id=otel-demo label)
        │
        ▼
opentelemetrycollector.observability:4317  (shared stack)
        │
        ├── Traces ──► Tempo
        └── Metrics ──► Prometheus
```

This two-hop design keeps application-side configuration identical to upstream while routing all data into the shared research observability stack.

#### Feature flags (Flagd)

OTel Demo uses a feature flag system (`flagd`) to toggle failure modes without restarting pods. The baseline flag state is defined in `deploy/research-lab/scenarios/otel-demo/flagd-baseline.json` — all 16 flags default to `"off"`.

During a fault scenario, `Invoke-FlagdFlip.ps1` patches the `flagd-config` ConfigMap to activate a flag for the scenario duration, then restores the baseline. Example flags:

| Flag | Type | Variants |
|---|---|---|
| `productCatalogFailure` | boolean | on / off |
| `paymentFailure` | probability | off / 10% / 25% / 50% / 75% / 90% / 100% |
| `kafkaQueueProblems` | integer | 0 → 100 |
| `emailMemoryLeak` | multiplier | 0 / 1x / 10x / 100x / 1000x / 10000x |
| `intlShippingSlowdown` | duration | 0 / 5 sec / 10 sec |

### Services

18 application components: `frontend` (TypeScript), `frontend-proxy` (Nginx), `ad` (Java), `cart` (C#), `checkout` (Go), `currency` (C++), `email` (Ruby), `payment` (JavaScript), `product-catalog` (Go), `product-reviews` (Rust), `quote` (PHP), `recommendation` (Python), `shipping` (Rust), `llm` (Python), `image-provider` (Nginx), `accounting` (Kotlin/Kafka consumer), `fraud-detection` (Java/Kafka consumer), plus `kafka`, `flagd`, `valkey-cart`, `postgresql`. Full catalog at `deploy/research-lab/service-catalogs/otel-demo.yaml`.

### Fault families (52 fault scenarios + 1 no-fault baseline, ~1,643 windows)

Scenarios are structured in four complexity levels:

| Level | Type | Count | Example |
|---|---|---|---|
| **L1 single-fault** | One service affected | 29 | `payment-outage-critical`, `email-memory-leak-1000x`, `ad-high-cpu` |
| **L1 Kafka** | Kafka-specific (no OB analogue) | 5 | `kafka-broker-outage-critical`, `kafka-consumer-lag-major`, `kafka-dead-letter-spike-minor` |
| **L2 concurrent** | Two simultaneous faults | 5 | `concurrent-payment-cart-redis`, `concurrent-kafka-lag-payment-outage` |
| **L3 cascade** | Sequential faults with emergence window | 4 | `cascade-kafka-broker-checkout`, `cascade-valkey-cart-checkout` |
| **L4 compound** | Multi-mechanism (chaos-mesh required) | 1 | `compound-saturation-network-latency` |
| **Network chaos** | Chaos Mesh network faults | 4 | `network-partition-critical`, `dns-outage-critical` |
| **Baselines** | No fault | 1 | `baseline-normal-traffic` |

L3 cascade scenarios are orchestrated by `Invoke-MultiFaultOrchestration.ps1`, which reads a `components/*.json` sidecar file describing the injection sequence and inter-fault timing (`cascade_emergence_window_seconds: 30`).

---

## Application 3 — World of Logs (WoL)

**Source**: MSR 2026 World of Logs archive (external, pre-existing)
**Location**: `data/wol/` (raw archive) + `data/derived/global/2026-06-17-wol-real-v3-global/` (our derived v3 corpus)
**Dedicated dataset card**: [`DOCS/WoL-v3-dataset.md`](WoL-v3-dataset.md)

### What it is

The World of Logs dataset is a real-world Jira issue archive from Apache open-source projects, packaged for the MSR 2026 paper by Xiao et al. The full WoL archive (`WoL_v1.JIRA` collection) contains **360,778 Jira documents**. From those, we derive a research-ready corpus tailored to memory-augmented incident-triage retrieval.

The current derived corpus is **WoL v3** (locked 2026-06-20):

- **78,140 query rows** drawn from **24 Apache distributed-systems projects** (Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server, Hive, IMPALA, Geode, Infinispan, Hadoop HDFS/YARN/Common, Solr, Apache Drill, Beam, Mesos, ActiveMQ, Camel, CXF, Ignite, Derby, Apache Arrow).
- **Label breakdown**: 38,642 ticket_worthy + 25,619 borderline + 13,879 noise = 78,140 (trivial majority-class baseline accuracy: 0.495).
- **38,642 memory items** (Bug + resolution=Fixed) — the retrieval corpus.
- **Family-held-out splits**: train 21 families (60,916 rows) / validation Ambari (3,836 rows) / test Kafka + MariaDB-Server (13,388 rows).
- **Multi-ticket incident clusters** (2,456) extracted via Jira `is duplicate of` / `Cloners` / `Cause` link analysis.
- **KG entity extractions** (memory + window side) via OpenAI gpt-4o-mini (~$36 total; 55 of 38,642 memory items failed extraction, 99.86% success rate).

> **Note for paper readers (updated 2026-06-28)**: WoL **v3** is now the
> measured corpus (38,642 memory items / 13,388 test windows, 24 Apache
> projects). The complete, leak-free v3 results are in
> [`paper-results/`](../paper-results/README.md) — this is the source of truth.
> (The earlier `DOCS/docs8/PAPER-FINDINGS.md` reference is obsolete; that file is
> not part of this repository.)

Unlike the OB and OTel Demo datasets, WoL has no associated telemetry — it contributes the **memory corpus** side of the retrieval evaluation: given a new incident description, can the system find the most relevant past ticket? All `triage_feature_*` numeric columns are zero-filled in WoL.

WoL has gone through three dataset iterations (v1 → v2 → v3) with increasing scope. **For full provenance — what was included, what was rejected and why, filter changes, bucket taxonomy, reproducibility, and known limitations — see [`DOCS/WoL-v3-dataset.md`](WoL-v3-dataset.md).**

### Files

| File | Description |
|---|---|
| `data/wol/WoL_v1-2025-11-10.archive` | Raw archive (uncompressed) |
| `data/wol/WoL_v1-2025-11-10.archive.gz` | Compressed copy |
| `data/wol/TERMS_OF_USE.md` | License — read before redistribution |
| `data/wol/Xiaohui_MSR_2026.pdf` | Source paper describing the dataset |

### Role in the project

WoL provides a **held-out real-world test** for retrieval quality. The OB and OTel Demo datasets use synthetic Jira tickets generated during collection; WoL uses authentic engineer-written tickets, which test whether the system generalises beyond the synthetic distribution.

---

## Scenario System

A **scenario** is the atomic unit of data collection: one fault injection run with defined ground-truth labels. Every scenario is a YAML file with a fixed schema (`deploy/research-lab/scenarios/scenario-template.yaml`).

### Scenario YAML structure

```yaml
schema_version: "1.0"
scenario_id: "cartservice-memory-leak-ticket-worthy"
title: "Cart Service Memory Leak"
jira_candidate: true          # Should this produce a Jira ticket?
produces_jira_ticket: true    # false = orphan fault (no ticket written)

expected_jira:
  issue_type: Bug
  priority: P2
  summary_template: "Cart service memory growing unboundedly under load"

fault:
  fault_type: resource_leak
  affected_service: cartservice
  expected_duration_seconds: 600
  blast_radius:
    user_visible: true
    expected_error_rate: 0.15

execution:
  action: SetEnv          # How to inject the fault
  namespace: online-boutique-research
  target_name: cartservice

triage:                   # Ground-truth labels for each time window
  pre_fault_baseline:
    triage_label: noise
  active_fault:
    triage_label: ticket_worthy
    triage_severity: P2
    is_hard_case: false
  recovery_window:
    triage_label: borderline
```

### Fault injection actions

| Action | Mechanism |
|---|---|
| `RecordOnly` | No injection; records baseline telemetry only |
| `SetEnv` | `kubectl set env deployment/<name>` — changes env vars to simulate misconfiguration or resource limits |
| `RestartPods` | `kubectl delete pod -l <selector>` — forces pod restart events |
| `ScaleDeployment` | `kubectl scale deployment/<name> --replicas=N` — simulates outage (scale to 0) or overload (scale down) |
| `ChaosMeshChaos` | Applies a Chaos Mesh manifest (network partition, packet loss, DNS block, latency) |
| `Flagd` | Patches OTel Demo's `flagd-config` ConfigMap to activate a feature flag |
| `MultiFault` | Orchestrates L2/L3/L4 scenarios by sequencing multiple inject/restore steps |

### Triage labels

Every telemetry window in every scenario is labelled with one of three classes:

| Label | Meaning |
|---|---|
| `ticket_worthy` | Fault is active and significant — a real engineer would open a ticket |
| `borderline` | System is recovering or fault is marginal — a ticket is plausible but not certain |
| `noise` | Normal operation or near-miss — no ticket expected |

Orphan fault scenarios (`produces_jira_ticket: false`) inject a real fault but do not write a Jira ticket row. They test whether the retrieval system correctly returns no strong match — a needed negative case.

---

## Data Collection Pipeline — Step by Step

### Step 1: Install observability stack (once per cluster)

```powershell
.\scripts\research-lab\install-observability.ps1
```

Installs Prometheus, Tempo, Loki, Alloy, Grafana, and the OTel Collector into the `observability` namespace.

### Step 2: Deploy the application

**Online Boutique:**
```powershell
.\scripts\research-lab\apply-online-boutique.ps1
```

**OTel Demo:**
```powershell
.\deploy\otel-demo\helm-install.ps1
```

### Step 3: Run a corpus (full dataset collection)

```powershell
.\scripts\research-lab\collect-dataset-corpus.ps1 -CorpusFile deploy\research-lab\corpora\dataset-v5-large.json
```

or for OTel Demo:

```powershell
.\scripts\research-lab\collect-dataset-corpus.ps1 -CorpusFile deploy\research-lab\corpora\otel-demo-v1.json
```

The corpus script reads the manifest, generates run IDs, and calls `collect-dataset-plan.ps1` for each run. A corpus manifest specifies which run plans to execute and how many times each repeats.

#### Online Boutique corpus (`dataset-v5-large.json`): 100 runs total

| Run plan | Repeats | Content |
|---|---|---|
| `control-baseline-only.json` | 8 | Baseline-only; anchors false-positive rate |
| `dataset-v3-diverse-compact-a.json` | 14 | Latency, restart, Redis, near-miss |
| `dataset-v3-diverse-compact-b.json` | 14 | Service-diverse outages |
| `dataset-v5-new-families-a.json` | 11 | Post-deploy churn, recovered-in-window, single-pod-restart, third-party blip |
| `dataset-v5-new-families-b.json` | 11 | Scheduled-job spike, latency near-miss, flapping pod |
| `dataset-v5-long-running.json` | 8 | Memory leak, connection leak (600 s fault windows, ~30 min/run) |
| `dataset-v5-orphans.json` | 24 | 8 orphan fault families × 3 repeats + baselines |
| `dataset-v5-system-faults.json` | 10 | Chaos Mesh: DNS block, network partition, packet loss |

#### OTel Demo corpus (`otel-demo-v1.json`): 21 runs total

| Run plan | Repeats | Content |
|---|---|---|
| `otel-demo-baseline.json` | 8 | Negative class baselines |
| `otel-demo-l1-compact.json` | 3 | All 27 L1 + 2 LLM + 4 timing/recovery = single-fault coverage |
| `otel-demo-kafka.json` | 3 | 5 Kafka fault families |
| `otel-demo-multifault.json` | 4 | L2 concurrent (5) + L3 cascade (4) |
| `otel-demo-network.json` | 3 | 4 network chaos + L4 compound |

### Step 4: What happens inside a single scenario run

`collect-dataset-plan.ps1` calls `run-scenario.ps1` for each scenario in the plan. For each scenario:

1. **Pre-window** (300 s before injection): records baseline telemetry; creates `pre_fault_baseline` window
2. **Injection**: executes the fault action (scale, env change, chaos manifest, flagd flip)
3. **Active window** (scenario `active_duration_seconds`): fault is live; creates `active_fault` window
4. **Restore**: undoes the injection
5. **Recovery window** (180 s after restore): records recovery telemetry; creates `recovery_window` window
6. **Telemetry export** (`export-telemetry-window.ps1`): port-forwards to all four backends and fetches raw data
7. **Shadow Jira ticket** (`generate-shadow-jira-issues.ps1`): if `produces_jira_ticket: true`, writes a synthetic ticket to `jira_shadow_issues.jsonl`

Every window is recorded in `telemetry_windows.jsonl`; every scenario execution is recorded in `episodes.jsonl`.

### Step 5: Telemetry export (what gets fetched)

`export-telemetry-window.ps1` port-forwards to the observability stack and fetches the following for each window:

**Loki logs** → `raw/loki/<windowId>.json`
- Service-scoped logs for the exact window (limit 5,000 entries)
- Service-scoped logs with ±300 s padding (context view)
- Namespace-wide logs with ±300 s padding

**Prometheus metrics** → `raw/prometheus/<windowId>.json` (15 s step)
- Pod info (`kube_pod_info`)
- Container restart count (`kube_pod_container_status_restarts_total`)
- CPU usage (`container_cpu_usage_seconds_total`)
- Memory working set (`container_memory_working_set_bytes`)
- Active alerts (`ALERTS`)

**Kubernetes state** → `raw/kubernetes/<windowId>.json`
- `kubectl get events -n <namespace> -o json`
- `kubectl get pods -n <namespace> -l app=<service> -o json`
- `kubectl get deployment <service> -n <namespace> -o json`

**Tempo traces** → `raw/tempo/<windowId>.json`
- Trace search (limit 500 trace IDs)
- Full trace bodies for up to 200 traces

**Alertmanager** → snapshot of currently firing alerts

All requests use retry with exponential backoff (3 attempts, 180 s timeout per request). Export counts are back-patched into `telemetry_windows.jsonl` as feature fields.

---

## What Gets Stored and Where

### `data/runs/` — Online Boutique raw runs (~100 runs, ~35 GB raw telemetry)

```
data/runs/
└── 2026-05-25-dataset-v5-large-compact-a-r01/
    ├── manifest.json               # run metadata: run ID, plan, corpus, timestamps
    ├── episodes.jsonl              # one record per scenario execution
    ├── telemetry_windows.jsonl     # one record per window per service
    ├── jira_shadow_issues.jsonl    # synthetic Jira tickets
    ├── alerts.jsonl                # Prometheus + Alertmanager events
    ├── raw/
    │   ├── loki/                   # Loki JSON per window + run-level context
    │   ├── prometheus/             # Prometheus JSON per window
    │   ├── kubernetes/             # kubectl JSON snapshots per window
    │   ├── tempo/                  # Tempo trace search + trace bodies per window
    │   └── prometheus_supplement/  # supplemental metric queries
    └── summaries/
        ├── run-summary.md
        ├── validation-report.json
        ├── data-quality-report.json
        └── feature-distribution.md
```

Run naming: `2026-05-25-dataset-v5-large-<plan_alias>-r<NN>` where plan aliases are `compact-a`, `compact-b`, `control`, `long-running`, `new-families-a`, `new-families-b`, `orphans`, `system-faults`.

### `data/otel-demo-runs/` — OTel Demo raw runs (~21 runs, ~10–12 GB raw telemetry)

Same directory structure as `data/runs/`. Run naming: `2026-06-09-otel-demo-v1-<plan_alias>-r<NN>`.

Plan aliases: `baseline`, `l1-compact`, `kafka`, `multifault`, `network`.

### `data/wol/` — World of Logs archive (~18 GB)

Pre-existing archive files; not generated by the collection scripts.

### `data/derived/` — Processed outputs

After raw collection, build scripts compute derived representations:

- **`triage_examples.jsonl`**: per-window rows with 94 pre-computed numeric feature columns (`triage_feature_*`) plus `triage_evidence_text` and ground-truth labels. This is the primary input for classical ML models.
- **`triage_window_labels.jsonl`**: triage label assignments per window (aggregated from scenario YAML)
- **`window_memory_matchings.jsonl`**: gold mapping from each test window to matching memory tickets (coarse relation)

### `data/derived/global/` — Locked global datasets

Four locked aggregate datasets (not modified after the lock date):

| Dataset | Lock date | Windows / queries | Memory tickets |
|---|---|---|---|
| `2026-05-25-dataset-v5-large-global/` (OB) | 2026-05-25 | ~6,720 windows | ~347 |
| `2026-06-09-otel-demo-v1-global/` (OTel Demo) | 2026-06-09 | ~1,643 windows | ~147 |
| `2026-06-15-wol-real-v2-global/` (WoL v2 — retired) | 2026-06-16 | 9,341 query rows | 2,000 |
| **`2026-06-17-wol-real-v3-global/` (WoL v3 — active)** | **2026-06-20** | **78,140 query rows** | **38,642** |

Each global dataset directory contains:

| File | Content |
|---|---|
| `global-triage-examples.jsonl` | 94 `triage_feature_*` columns + evidence text + labels |
| `jira-memory-corpus.jsonl` | Memory tickets (retrieval corpus) |
| `jira-shadow-humanized-v2/` | Engineer-voice LLM-humanized ticket text |
| `v2_kg_extractions/all_extractions.jsonl` | LLM-extracted KG entities per memory ticket |
| `v2_kg_extractions_windows/all_extractions.jsonl` | LLM-extracted KG entities per test window |
| `window-memory-matchings.jsonl` | Gold window→memory mappings (coarse) |
| `triage-split-manifest-v2-resplit.json` (OB / OTel Demo) or `triage-split-manifest.json` (WoL) | OB + OTel Demo: 70/15/15 stratified split by fault family. WoL: family-held-out leave-one-domain-out split. |
| `triage-feature-columns.json` | Numeric feature column contract (94 columns) |
| `global-triage-build-manifest.json` | Build provenance: git SHA, seed, run counts |
| `README.md` | Dataset card: field schemas, ID linkage, citation |

---

## Published Datasets

Three self-contained zip archives are in `data/published/`, one per dataset. Each zip contains a README, field schemas, MANIFEST.sha256.json, and both a `simple_dataset` (text-only, lightweight) and `full_dataset` (includes raw telemetry JSON):

| Dataset | Simple zip | Full zip |
|---|---|---|
| `online-boutique/` | ~28 MB | ~4.4 GB |
| `otel-demo/` | ~4 MB | ~1.0 GB |
| `world-of-logs/` | ~7 MB | ~2.3 GB |

The simple dataset contains everything needed to train and evaluate the retrieval and triage systems: `global-triage-examples.jsonl`, `jira-memory-corpus.jsonl`, `window-memory-matchings.jsonl`, humanized tickets, KG extractions, and the split manifests. The full dataset additionally includes the per-window raw Loki, Prometheus, Tempo, and Kubernetes JSON files.

---

## Key Numbers at a Glance

| Metric | Online Boutique | OTel Demo | World of Logs (v3) |
|---|---|---|---|
| Raw collection runs | 100 | 21 | N/A (pre-existing archive) |
| Scenario families | 27 | 49 | 24 Apache projects |
| Total telemetry windows | ~6,720 | ~1,643 | 78,140 query rows (no telemetry) |
| Memory tickets | ~347 | ~147 | 38,642 |
| Services | 12 | 18 + Kafka | Real Apache distributed systems |
| Languages | 6 | 10 | — (project-mixed) |
| Fault injection methods | kubectl + Chaos Mesh | kubectl + Flagd + Chaos Mesh | — (real incidents) |
| GCP VM shape | e2-standard-8 (8 vCPU / 32 GB) | e2-standard-16 (16 vCPU / 64 GB) | N/A |
| Raw data size | ~35 GB raw telemetry | ~10–12 GB raw telemetry | ~18 GB (source archive) + ~1.3 GB (derived v3) |
| Pre-window duration | 300 s | 300 s | — |
| Post-window duration | 180 s | 180 s | — |
| Triage classes | ticket_worthy / borderline / noise | same | same (5 borderline sub-buckets in v3) |
| Numeric feature columns | 94 (`triage_feature_*`) | 94 | 94 (all zero-filled — no telemetry) |
| Train/val/test split | 70 / 15 / 15 % | 70 / 15 / 15 % | family-held-out (Kafka + MariaDB held out as test) |
| Split strategy | stratified by fault family | same | family-held-out leave-one-domain-out |
| Multi-ticket incident clusters | (via scenario chains) | (via L3 cascade scenarios) | 2,456 (via Jira `Duplicate`/`Cloners`/`Cause` links) |

---

The OTel Demo (`opentelemetry-demo/`) is used **as-is from the upstream** — research-specific routing is handled by Helm values, not by source changes. The WoL archive is read-only.

---
