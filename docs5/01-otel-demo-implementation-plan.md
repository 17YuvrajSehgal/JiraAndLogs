# OTel Demo — Implementation Plan (File-Level)

**Status:** PLAN, ready to execute on approval.
**Parent:** `docs5/00-otel-demo-cross-app-plan.md` (strategy + scenarios)
**This document:** every new file to create + every existing file to parameterize + hard isolation guarantees against the OB v5-large pipeline.
**Branch:** to be created — `otel-demo-cross-app` from `master-final-models`.
**OTel Demo source:** `opentelemetry-demo/` (cloned at repo root; vendored as-is, never edited).

---

## Table of contents

1. [Hard isolation contract — what can and cannot change](#1-hard-isolation-contract--what-can-and-cannot-change)
2. [Repo findings — what we discovered about OTel Demo](#2-repo-findings--what-we-discovered-about-otel-demo)
3. [Decision matrix — deployment, observability, fault primitives](#3-decision-matrix--deployment-observability-fault-primitives)
4. [File map — everything we create](#4-file-map--everything-we-create)
5. [File map — everything we parameterize (additive, no breakage)](#5-file-map--everything-we-parameterize-additive-no-breakage)
6. [File map — everything we DO NOT touch](#6-file-map--everything-we-do-not-touch)
7. [Scenario YAML inventory (42 scenarios)](#7-scenario-yaml-inventory-42-scenarios)
8. [Implementation phases — what gets built when](#8-implementation-phases--what-gets-built-when)
9. [Smoke and validation checklist](#9-smoke-and-validation-checklist)
10. [Open implementation decisions](#10-open-implementation-decisions)

---

## 1. Hard isolation contract — what can and cannot change

The OB v5-large dataset, the locked TCH cascade, and every script under the existing `scripts/research-lab/` directory must continue to work **bit-identically** after this implementation. Three rules enforce that:

### Rule R1 — output paths

Every new file written by OTel Demo collection lives under a path that does NOT collide with OB. Specifically:

| Asset | OB path (READ-ONLY) | OTel Demo path (NEW) |
|---|---|---|
| Raw runs | `data/runs/2026-05-25-dataset-v5-large-*/` | `data/runs/2026-XX-XX-otel-demo-v1-*/` |
| Derived | `data/derived/2026-05-25-dataset-v5-large-*/` | `data/derived/2026-XX-XX-otel-demo-v1-*/` |
| Global dataset | `data/derived/global/2026-05-25-dataset-v5-large-global/` | `data/derived/global/2026-XX-XX-otel-demo-v1-global/` |
| Comparison / cascade outputs | `.../comparison/v2g-final-models/final/` (OB) | `.../comparison/otel-demo/zero-shot/` and `.../l1-retrained/` |
| Scenario YAMLs | `deploy/research-lab/scenarios/{baselines,faults}/` | `deploy/research-lab/scenarios/otel-demo/{baselines,faults,multifault}/` |
| Corpus manifest | `deploy/research-lab/corpora/dataset-v5-large.json` | `deploy/research-lab/corpora/otel-demo-v1.json` |
| Run plans | `deploy/research-lab/run-plans/dataset-v5-*.json` | `deploy/research-lab/run-plans/otel-demo-*.json` |
| Service catalog | `deploy/research-lab/service-catalogs/online-boutique.yaml` (NEW — to extract) | `deploy/research-lab/service-catalogs/otel-demo.yaml` (NEW) |
| Deployment overlay | `deploy/research-lab/online-boutique/` | `deploy/otel-demo/` |

### Rule R2 — script behavior

Existing PowerShell + Python scripts under `scripts/research-lab/` may be **parameterized but never rewritten**. The contract:

- All current OB invocations (without new flags) must continue to produce identical output.
- New behavior is gated behind explicit flags (`--service-catalog`, `--app-profile otel-demo`, etc.).
- Default values of any new flag must reproduce existing OB behavior.

If a parameterization cannot be additive (e.g., a hardcoded service name list that must change), the file is **forked** under `scripts/research-lab/otel-demo/<name>.ps1`. OB always reads the original; OTel Demo reads the fork. No conditionals in shared code.

### Rule R3 — cascade and humanizer

- The locked TCH cascade artifacts (`comparison/v2g-final-models/final/*.pkl`, `*.jsonl`) are **read-only** during all OTel Demo work.
- The cascade builder (`src/v2_advanced/tch/build_cascade.py`) runs unchanged; we pass it OTel Demo inputs via existing CLI flags.
- The V2 humanizer (`scripts/research-lab/humanize_v5_large_bulk.py`) is parameterized to read service catalog from a CLI flag instead of the hardcoded list. Default behavior unchanged.
- The Jira shadow generator (`scripts/research-lab/generate-shadow-jira-issues.ps1`) gets a `-ServiceCatalogFile` parameter. Default reads OB's catalog.

### Rule R4 — kubernetes namespace

OTel Demo runs in `otel-demo-research` namespace. OB v5-large runs in `online-boutique-research`. Never both on the same cluster simultaneously without explicit operator confirmation (the namespaces are independent but cluster-level resources like Loki PVCs are shared and can be saturated).

### Rule R5 — Git branch

All OTel Demo work happens on branch `otel-demo-cross-app` cut from `master-final-models`. The branch is merged to `master` only after the cross-app section is locked. While on the branch, the locked TCH artifacts and `master-final-models`'s `comparison/v2g-final-models/final/` directory are not deleted, moved, or modified.

---

## 2. Repo findings — what we discovered about OTel Demo

### 2.1 Service inventory (18 application services)

| Service | Language | Type | Critical path for checkout? | Fault flags |
|---|---|---|---|---|
| `frontend` | TypeScript / Next.js | Web UI | yes | — |
| `frontend-proxy` | Envoy | Edge proxy | yes | — |
| `ad` | Java | Display ads | no | `adFailure`, `adManualGc`, `adHighCpu` |
| `cart` | .NET | Cart, backed by Valkey | yes | `cartFailure`, `failedReadinessProbe` |
| `checkout` | Go | Order placement + Kafka producer | yes | — |
| `currency` | C++ | FX conversion | yes | — |
| `email` | Ruby | Order confirmation | medium | `emailMemoryLeak` (5 intensity levels) |
| `payment` | Node.js | Card processing | yes | `paymentFailure` (6 variants), `paymentUnreachable` |
| `product-catalog` | Go | Catalog + search | yes | `productCatalogFailure` |
| `product-reviews` | (new) | Reviews | medium | — |
| `quote` | PHP | Shipping cost estimate | yes | — |
| `recommendation` | Python | Product recs | medium | `recommendationCacheFailure` |
| `shipping` | Rust | Shipping quote + label | yes | `intlShippingSlowdown` (5sec/10sec) |
| `accounting` | .NET | Kafka CONSUMER (orders ledger) | async downstream | — |
| `fraud-detection` | Kotlin | Kafka CONSUMER (fraud check) | async downstream | — |
| `image-provider` | Nginx | Image serving | no | `imageSlowLoad` (5sec/10sec) |
| `load-generator` | Python / Locust | Synthetic traffic | driver | `loadGeneratorFloodHomepage` |
| `llm` | Python (mock) | LLM-backed product summaries | medium | `llmInaccurateResponse`, `llmRateLimitError` |

Dependent infrastructure: `kafka` (broker), `valkey-cart` (Redis-compatible), `astronomy-db` (PostgreSQL), `flagd` (feature flag service), `flagd-ui`.

### 2.2 Flagd fault-flag inventory (16 flags)

Total **16 flags** in `src/flagd/demo.flagd.json`:

| Flag | Service | Failure type | Intensity |
|---|---|---|---|
| `adFailure` | ad | Service-level failure | binary |
| `adManualGc` | ad | JVM GC pressure | binary |
| `adHighCpu` | ad | CPU saturation | binary |
| `cartFailure` | cart | Service-level failure | binary |
| `paymentFailure` | payment | Charge request failure | 10/25/50/75/90/100% |
| `paymentUnreachable` | payment | Network unavailability | binary |
| `productCatalogFailure` | product-catalog | Per-product failure (targeted at `OLJCESPC7Z`) | binary, targeted |
| `recommendationCacheFailure` | recommendation | Cache-layer failure | binary |
| `kafkaQueueProblems` | kafka | Producer overload + consumer delay (causes lag) | binary (100% rate) |
| `loadGeneratorFloodHomepage` | load-generator | Synthetic load spike | binary (100% rate) |
| `imageSlowLoad` | image-provider | Slow image responses | 5sec / 10sec |
| `failedReadinessProbe` | cart | Kubernetes readiness probe failure | binary |
| `emailMemoryLeak` | email | Memory leak | 1x / 10x / 100x / 1000x / 10000x |
| `intlShippingSlowdown` | shipping | International shipping latency | 5sec / 10sec |
| `llmInaccurateResponse` | llm | Wrong product summary | binary |
| `llmRateLimitError` | llm | Intermittent rate limit | binary |

This is richer than OB's binary fault primitives. **Intensity-variant flags give us a built-in severity-gradient axis** that we can use for sub-claim 3 robustness experiments (severity sweep within a single fault family).

### 2.3 OTel Collector capabilities

Their collector receives OTLP gRPC on `:4317` and HTTP on `:4318`. Built-in scrapers:
- `redis` against `valkey-cart:6379`
- `postgresql` against `astronomy-db:5432`
- `docker_stats`
- `host_metrics` (CPU, memory, disk, network, paging, processes)
- `nginx` against `image-provider`
- `prometheus/ad` (scrapes ad's Prometheus client metrics)
- `http_check/frontend-proxy`

This is structurally similar to our M0-M5 setup. **No application-code instrumentation work needed.**

### 2.4 Deployment options

| Path | Available in repo? | Compatible with our pipeline? |
|---|---|---|
| Docker Compose (`compose.yaml`) | YES | NO — our scripts assume kubectl |
| Kubernetes via Helm chart | NO — external `open-telemetry/opentelemetry-helm-charts` repo | YES |
| Kubernetes via raw manifests | NO | N/A |

**Decision: use the upstream Helm chart**, not the repo's docker-compose. The chart is at `https://open-telemetry.github.io/opentelemetry-helm-charts` and the package is `open-telemetry/opentelemetry-demo`.

### 2.5 Critical telemetry routing decision

Two choices for telemetry export:

| Option | Description | Verdict |
|---|---|---|
| **Use OTel Demo's bundled stack** (Jaeger, Prometheus, OpenSearch, Grafana) | Charts ship with their own backends | NO — incompatible with our `export-telemetry-window.ps1` which queries Loki/Tempo/Prometheus by URL |
| **Reuse our existing observability stack** (Loki, Tempo, our Prometheus, our Grafana, our Alloy) | Override the helm chart's OTel collector config to export OTLP to OUR collector | **YES** — zero changes to our export pipeline |

Implementation: pass a custom collector config via the chart's `opentelemetry-collector.config` values key. Our config replaces theirs and exports to our cluster's existing collector endpoints. We never edit `src/otel-collector/otelcol-config.yml` in the OTel Demo repo.

---

## 3. Decision matrix — deployment, observability, fault primitives

### 3.1 Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Deployment | Helm chart from `open-telemetry/opentelemetry-helm-charts`, pinned version | k8s-native, compatible with existing scripts |
| Namespace | `otel-demo-research` | Mirrors `online-boutique-research`; isolates from OB |
| Observability | Reuse existing Loki + Tempo + Prometheus + Alloy in `observability` namespace | Zero changes to `export-telemetry-window.ps1` |
| OTel Collector | Override helm chart config to export to our observability stack | Non-invasive (no code/config edit in OTel Demo repo) |
| Bundled Jaeger / OpenSearch / Grafana / Prometheus | DISABLED in helm values | Avoid cluster bloat; we have our own |
| Fault primitive — flagd | Use as the primary mechanism where a flag exists | Built-in, reversible, OTel Demo-native |
| Fault primitive — kubectl scale / restart | Use where no flag exists or where we want infrastructure-level fault | Same as OB |
| Fault primitive — chaos-mesh NetworkChaos | Use for network families | Same as OB |
| Multi-fault orchestration | New `run-scenario` extension supports `composition_type` field | Builds on existing PowerShell harness |
| Image registry | Use upstream `ghcr.io/open-telemetry/demo:2.2.0` images | No image-building work needed |
| Image pin | `2.2.0` (current latest stable, will pin exact tag at Phase 0 start) | Reproducibility |

### 3.2 New fault primitives we have to implement

In `scripts/research-lab/otel-demo/Invoke-Scenario-Primitive.ps1` (NEW, forked from `run-scenario.ps1`):

| Primitive | Implementation | Reversibility |
|---|---|---|
| `Flagd` | HTTP PATCH to `flagd-ui:4000/api/flags/<flag>` setting `defaultVariant` to `on` (or named variant); restore to `off` after fault duration | idempotent |
| `FlagdVariant` | Same but for multi-variant flags (e.g., `paymentFailure: 50%`, `emailMemoryLeak: 100x`) — supports the intensity-gradient axis | idempotent |
| `ChaosMeshNetwork` | `kubectl apply -f` a NetworkChaos CR; `kubectl delete` after fault duration | bounded by CR lifetime |
| `PausePod` | `kubectl exec` to send SIGSTOP to the consumer process; SIGCONT to restore | needs care — see §10 open question |
| `KafkaTopic` | `kubectl exec` into kafka pod, use `kafka-topics.sh` to delete topic / pause partitions | direct broker manipulation |

The existing primitives (`SetEnv`, `ScaleDeployment`, `RestartPods`, `RecordOnly`) reused unchanged.

---

## 4. File map — everything we create

All new files. None of these exist today. Total: **~75 new files** (most are scenario YAMLs).

### 4.1 Deployment overlay — `deploy/otel-demo/` (NEW)

```
deploy/otel-demo/
├── README.md                              # how to deploy + tear down
├── helm-values.yaml                       # CORE FILE — overrides upstream chart
├── helm-version.txt                       # pinned chart version (e.g. 0.36.0)
├── otel-collector-config.yaml             # custom collector config (exports to our stack)
├── namespace.yaml                         # otel-demo-research namespace + research labels
├── flagd-baseline.json                    # all flags set to defaultVariant=off, snapshot for restore
├── chaos-mesh/
│   ├── network-latency-template.yaml      # NetworkChaos template (parametrized)
│   ├── network-packetloss-template.yaml
│   └── network-partition-template.yaml
└── helm-install.ps1                       # one-shot deploy script
```

**`helm-values.yaml` highlights:**
- `observability.enabled: false` (disables their bundled Grafana/Jaeger/Prometheus/OpenSearch)
- `opentelemetry-collector.config`: our exporters pointing at `loki.observability.svc.cluster.local`, `tempo.observability.svc.cluster.local`, etc.
- `default.envOverrides`: research-injection labels at namespace level (`DATASET_RUN_ID`, `SCENARIO_ID`, `TRAFFIC_PROFILE_ID`, `JIRA_MODE`)
- `default.image.repository: ghcr.io/open-telemetry/demo` (pinned tag)

### 4.2 Scenario YAMLs — `deploy/research-lab/scenarios/otel-demo/` (NEW)

```
deploy/research-lab/scenarios/otel-demo/
├── baselines/
│   └── baseline-normal-traffic.yaml
├── faults/                                # 32 L1 single-fault scenarios
│   ├── payment-outage-major.yaml
│   ├── payment-failure-50pct-major.yaml   # uses paymentFailure: 50% variant
│   ├── payment-failure-100pct-critical.yaml
│   ├── checkout-outage-critical.yaml
│   ├── cart-redis-degradation-critical.yaml
│   ├── currency-outage-major.yaml
│   ├── shipping-outage-major.yaml
│   ├── shipping-slowdown-5sec-minor.yaml   # uses intlShippingSlowdown: 5sec
│   ├── shipping-slowdown-10sec-major.yaml
│   ├── recommendation-outage-major.yaml
│   ├── recommendation-cache-failure-minor.yaml
│   ├── ad-outage-major.yaml
│   ├── ad-high-cpu-major.yaml             # uses adHighCpu flag
│   ├── ad-gc-pressure-minor.yaml           # uses adManualGc
│   ├── productcatalog-outage-major.yaml
│   ├── productcatalog-targeted-failure-minor.yaml
│   ├── productcatalog-latency-major.yaml
│   ├── email-outage-minor.yaml
│   ├── email-memory-leak-100x-major.yaml
│   ├── email-memory-leak-1000x-critical.yaml
│   ├── checkout-restart-minor.yaml
│   ├── frontend-restart-minor.yaml
│   ├── single-pod-restart-cart-minor.yaml
│   ├── flapping-pod-cart-major.yaml
│   ├── post-deploy-churn-rolling-minor.yaml
│   ├── frontend-traffic-pressure-major.yaml
│   ├── scheduled-job-spike-minor.yaml
│   ├── resource-saturation-major.yaml
│   ├── slow-leak-saturation-major.yaml
│   ├── latency-near-miss-partial-recovery-minor.yaml
│   ├── recovered-in-window-minor.yaml
│   ├── third-party-image-slow-minor.yaml   # uses imageSlowLoad
│   ├── network-latency-major.yaml          # uses chaos-mesh
│   ├── network-packet-loss-major.yaml
│   ├── network-partition-critical.yaml
│   ├── dns-outage-critical.yaml
│   └── llm-rate-limit-minor.yaml           # NEW — LLM-specific failure
│   └── llm-inaccurate-minor.yaml           # NEW
├── kafka/                                 # 5 new Kafka-family scenarios
│   ├── kafka-broker-outage-critical.yaml
│   ├── kafka-consumer-lag-major.yaml      # uses kafkaQueueProblems
│   ├── kafka-consumer-crash-major.yaml    # scales fraud-detection to 0
│   ├── kafka-partition-rebalance-minor.yaml
│   └── kafka-dead-letter-spike-minor.yaml
└── multifault/                             # 10 multi-fault scenarios per docs5/00 §5.5
    ├── concurrent/
    │   ├── concurrent-payment-cart-redis.yaml
    │   ├── concurrent-currency-shipping.yaml
    │   ├── concurrent-ad-recommendation.yaml
    │   ├── concurrent-productcatalog-latency-flapping-pod.yaml
    │   └── concurrent-kafka-lag-payment-outage.yaml
    ├── cascade/
    │   ├── cascade-kafka-broker-checkout.yaml
    │   ├── cascade-productcatalog-latency-recommendation-timeout.yaml
    │   ├── cascade-valkey-cart-checkout.yaml
    │   └── cascade-currency-frontend-errors.yaml
    └── compound/
        └── compound-saturation-network-latency.yaml
```

**Total: 1 baseline + 36 L1 (32 transferred + LLM bonus + 5 Kafka) + 10 multi-fault = 47 YAMLs.** A few more than the planned 42 because the LLM service gives us 2 free bonus scenarios.

Each YAML extends the existing schema with the additive multi-fault fields from `docs5/00 §5.5.3`.

### 4.3 Corpus and run plans — `deploy/research-lab/corpora/` and `run-plans/` (NEW files)

```
deploy/research-lab/corpora/
└── otel-demo-v1.json                     # 100-run L1 + 40-run multi-fault corpus manifest

deploy/research-lab/run-plans/
├── otel-demo-baseline.json                # baselines × 8 runs
├── otel-demo-compact-a.json               # 16 high-volume L1 × ~3 runs
├── otel-demo-compact-b.json               # 16 medium L1 × ~3 runs
├── otel-demo-llm.json                     # 2 LLM scenarios × 2 runs  (small bonus)
├── otel-demo-kafka.json                   # 5 Kafka × 4 runs
├── otel-demo-multifault-concurrent.json   # 5 × 4 runs
├── otel-demo-multifault-cascade.json      # 4 × 4 runs
├── otel-demo-multifault-compound.json     # 1 × 4 runs
└── otel-demo-long-running.json            # slow-leak / memory-leak × 4 runs
```

### 4.4 Service catalogs — `deploy/research-lab/service-catalogs/` (NEW directory)

```
deploy/research-lab/service-catalogs/
├── _schema.yaml                           # documents the catalog format
├── online-boutique.yaml                   # OB services (extracted from existing hardcoded list — sourced FROM existing scripts, BACKWARDS-COMPATIBLE)
└── otel-demo.yaml                         # 18 OTel Demo services + dependencies
```

`otel-demo.yaml` shape:

```yaml
app_id: otel-demo
namespace: otel-demo-research
canonical_services:
  - name: cart
    language: dotnet
    role: cart
    criticality: high
  - name: checkout
    language: go
    role: order-placement
    criticality: critical
  # ... 18 total ...
infra_components:
  - name: kafka
    role: message-broker
  - name: valkey-cart
    role: cache
  - name: astronomy-db
    role: database
service_catalog_for_humanizer:
  # what the humanizer should reference when generating engineer-voice Jira
  - cart
  - checkout
  - ...
```

The schema doc `_schema.yaml` is what reviewers / future contributors read; the OB file extracts what is currently hardcoded in `generate-shadow-jira-issues.ps1` and `humanize_v5_large_bulk.py`. **Default behavior of those scripts (no flag = OB catalog) is preserved.**

### 4.5 OTel Demo-specific scripts — `scripts/research-lab/otel-demo/` (NEW directory)

```
scripts/research-lab/otel-demo/
├── Install-OtelDemo.ps1                   # helm install + ServiceMonitor + namespace labels
├── Uninstall-OtelDemo.ps1                 # helm uninstall + namespace delete
├── Invoke-FlagdFlip.ps1                   # HTTP PATCH to flagd-ui to flip a flag
├── Invoke-ChaosMeshNetwork.ps1            # apply / delete NetworkChaos CR
├── Invoke-PausePod.ps1                    # SIGSTOP / SIGCONT a consumer
├── Invoke-Scenario-Primitive.ps1          # NEW primitive dispatcher; called by run-scenario when scenario uses one of the new primitives
├── Invoke-MultiFaultOrchestration.ps1     # NEW — handles composition_type ∈ {concurrent, cascade, compound_primitive}
├── Export-PropagationEvidence.ps1         # NEW — computes the propagation_evidence block per window
├── validate_otel_demo_telemetry.py        # OTel Demo-specific smoke validation (mirrors validate_l1_l2_telemetry.py)
└── README.md                              # how the scripts compose
```

These scripts are **forked, not shared.** OB never calls them; OTel Demo never depends on the OB equivalents existing.

### 4.6 New cascade evaluation runners — `src/v2_advanced/tch/otel_demo/` (NEW)

```
src/v2_advanced/tch/otel_demo/
├── __init__.py
├── zero_shot_eval.py                      # loads OB-locked cascade artifacts, runs on OTel Demo test split, no retraining
├── l1_retrain_eval.py                     # refits ONLY the L1 stacker on OTel train split
├── multifault_metrics.py                  # AllGold@K, PrimaryGold@K, Recall@K (avg over golds)
├── propagation_stratify.py                # per-cascade-depth stratification
└── consolidate_cross_app_headline.py      # produces headline-cross-app.json
```

These are NEW modules that import the existing cascade builder (`src/v2_advanced/tch/build_cascade.py`) and reuse its logic. **No edits to `build_cascade.py` itself.**

### 4.7 docs5 additions

```
docs5/
├── 00-otel-demo-cross-app-plan.md         # already exists — strategy + scenarios
├── 01-otel-demo-implementation-plan.md    # THIS FILE
└── 02-otel-demo-runbook.md                # to be authored at Phase 0 start — operator runbook for the GCP collection
```

---

## 5. File map — everything we parameterize (additive, no breakage)

These existing files get a new flag or argument. Default values reproduce existing OB behavior bit-identically. The implementation rule: if a parameterization can't be made non-breaking, fork the file instead.

| File | New behavior | Default (OB)? |
|---|---|---|
| `scripts/research-lab/generate-shadow-jira-issues.ps1` | Add `-ServiceCatalogFile <path>` parameter | Defaults to `deploy/research-lab/service-catalogs/online-boutique.yaml` (extracted from current hardcode) |
| `scripts/research-lab/humanize_v5_large_bulk.py` | Add `--service-catalog <path>` argument | Same default |
| `scripts/research-lab/build_global_triage_dataset.py` | Add `--app-id <id>` to tag the global manifest with the source app | Defaults to `online-boutique` |
| `scripts/research-lab/build_jira_memory_corpus.py` | Add `--service-catalog <path>` argument | Same default |
| `scripts/research-lab/mint_v2_distractors.py` | (no change needed — reused with OB distractors per §5.6 of docs5/00) | n/a |
| `scripts/research-lab/run-scenario.ps1` | Add dispatch for new primitive types (`Flagd`, `ChaosMeshNetwork`, `PausePod`, `KafkaTopic`) when scenario YAML uses them | Existing primitives (`SetEnv`, `ScaleDeployment`, `RestartPods`, `RecordOnly`) unchanged |
| `scripts/research-lab/run-scenario.ps1` | Add `composition_type` handling — dispatch to multifault orchestrator when present | Absence = single fault, unchanged |
| `scripts/research-lab/collect-dataset-corpus.ps1` | Accept new corpus manifest path (no flag change; it already takes a `-CorpusFile`) | OB corpus → unchanged path → unchanged behavior |
| `scripts/research-lab/export-telemetry-window.ps1` | Add optional `--include-propagation-evidence` flag | Off by default; only OTel Demo runs turn it on |
| `scripts/research-lab/validate-dataset-run.ps1` | Accept service catalog parameter for service-name validation | Defaults to OB catalog |
| `scripts/research-lab/build_triage_dataset.py` | (no change — already operates on per-window raw evidence, app-agnostic) | n/a |
| `src/v2_advanced/proposal_d_knowledge_graph/extractor.py` | Read canonical services list from service-catalog YAML instead of hardcoded list | Hardcoded list extracted into `service-catalogs/online-boutique.yaml`; default behavior preserved |
| `src/jira_humanizer/personas.py`, `symptom_map.py` | Accept service-catalog as input; new Kafka-symptom templates appended (do NOT replace existing) | Same default |

**Each parameterization is tested for OB-equivalence before merging.** The smoke test is: re-run the regression check `python -m v2_advanced.tch.check_cascade --cascade-dir ...v2g-final-models/final` and confirm headline metrics unchanged.

---

## 6. File map — everything we DO NOT touch

The following are **read-only** for the entire OTel Demo work. No edits, no parameterizations, no renames.

### 6.1 Locked OB artifacts

- `data/derived/global/2026-05-25-dataset-v5-large-global/**` — read-only
- `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/**` — the locked TCH cascade output, including `headline-final.json`, `tch_metrics.json`, `stacker.pkl`, `bootstrap-cis.json`, `per-window-predictions.jsonl`
- `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2f-tch-phase1/**` — the locked v2f regression baseline
- `data/runs/2026-05-25-dataset-v5-large-*/**` — raw OB runs
- `data/derived/2026-05-25-dataset-v5-large-*/**` — per-run derived

### 6.2 Cloned OTel Demo repository

- `opentelemetry-demo/**` — **vendored, never edited.** If we need to alter their config we override at the helm-values level. If we need an upstream change it's a separate PR to upstream OTel.

### 6.3 Core cascade code

- `src/v2_advanced/tch/build_cascade.py` — no edits; we import and call its functions from new modules
- `src/v2_advanced/tch/novelty_calibration.py` — G7 logic; read-only
- `src/comparison/runner.py::KNOWN_PIPELINES` — no new pipelines added; we reuse the 6 existing pipelines exactly
- Locked git commits referenced in the technical paper (b3bf12f / c27a54c / 56e53bf / a79ba5d / b7557c4 / e485149) — never amended

### 6.4 Charter

- `RESEARCH-CHARTER.md` §1–§16 — unchanged; we add a new §17 per `docs5/00 §16` rather than editing existing sections.

### 6.5 Technical paper sections

- `technical-paper/sections/01..11.tex` — unchanged until the cross-app section `08-cross-app.tex` is ready to be inserted. The insertion is additive.

---

## 7. Scenario YAML inventory (42 scenarios planned, 47 authored due to LLM bonus)

Consolidated count by family and difficulty:

| Tier | Family / scenario | Realization | New / transferred |
|---|---|---|---|
| L1 | baseline-normal-traffic | RecordOnly | transferred (1 scenario) |
| L1 | payment-outage / -failure variants | flagd `paymentFailure` 50%/100% + ScaleDeployment | transferred (3 scenarios) |
| L1 | cart-redis | ScaleDeployment on `valkey-cart` | transferred (1) |
| L1 | checkout-outage | ScaleDeployment | transferred (1) |
| L1 | currency-outage | ScaleDeployment | transferred (1) |
| L1 | shipping-outage + slowdown variants | ScaleDeployment + flagd `intlShippingSlowdown` | transferred + intensity (3) |
| L1 | recommendation-outage + cache-failure | ScaleDeployment + flagd `recommendationCacheFailure` | transferred (2) |
| L1 | ad-outage + high-cpu + gc-pressure | flagd `adFailure` / `adHighCpu` / `adManualGc` | transferred + intensity (3) |
| L1 | productcatalog-outage + latency + targeted | ScaleDeployment + SetEnv + flagd targeted | transferred + new variant (3) |
| L1 | email-outage + memory-leak intensity variants | ScaleDeployment + flagd `emailMemoryLeak` 100x/1000x | transferred + intensity (3) |
| L1 | pod-restart families (checkout / frontend / single-pod / flapping / post-deploy-churn) | RestartPods | transferred (5) |
| L1 | traffic / saturation / leak families | flagd `loadGeneratorFloodHomepage`, SetEnv, scheduled spike | transferred (4) |
| L1 | near-miss / recovered / third-party-image-slow | brief faults + flagd `imageSlowLoad` | transferred (3) |
| L1 | network families (latency / packet-loss / partition / dns) | chaos-mesh + DNS pod restart | transferred (4) |
| L1 | **llm-rate-limit / llm-inaccurate** | flagd `llmRateLimitError` / `llmInaccurateResponse` | **NEW — bonus from LLM service** (2) |
| L1 | **kafka-broker-outage / kafka-consumer-lag / kafka-consumer-crash / kafka-partition-rebalance / kafka-dead-letter-spike** | ScaleDeployment kafka + flagd `kafkaQueueProblems` + ScaleDeployment consumers + RestartPods kafka | **NEW — architectural-distance evidence** (5) |
| L2 | concurrent dual-fault (5 scenarios) | composed primitives, parallel | NEW |
| L3 | cascading dual-fault (4 scenarios) | primary primitive + emergent secondary observation | NEW |
| L4 | compound primitives (1 scenario) | mixed primitive types | NEW |

**L1 total: 36 scenarios.** (32 originally planned + 2 LLM bonus + 2 extra variants from intensity flags)
**Multi-fault total: 10 scenarios.**
**Grand total: 47 scenario YAMLs.** Runs target ~135 (within budget).

---

## 8. Implementation phases — what gets built when

The implementation breaks into **5 sub-phases of Phase 0–2** (the local prep work before any collection). Maps to docs5/00 §13 execution order.

### Phase 0a — Deployment overlay (1 day)
1. Clone helm chart values; write `deploy/otel-demo/helm-values.yaml` overriding observability + research labels.
2. Write `deploy/otel-demo/otel-collector-config.yaml` exporting to our existing Loki/Tempo/Prometheus.
3. Write `deploy/otel-demo/helm-install.ps1` (one-shot deploy script).
4. **Local kind smoke test:** deploy chart with our values; verify pods come up; verify logs land in our Loki, traces in our Tempo, metrics in our Prometheus.

### Phase 0b — Namespace + ServiceMonitor + chaos-mesh templates (½ day)
1. `namespace.yaml` with research labels.
2. ServiceMonitor entries for OTel Demo's `/metrics` endpoints (if any aren't already covered via the collector's prometheus receiver).
3. Verify chaos-mesh is installed on the cluster (skip network families if not).

### Phase 1a — Service catalog refactor (½ day)
1. Extract OB's hardcoded service list into `deploy/research-lab/service-catalogs/online-boutique.yaml`.
2. Author `deploy/research-lab/service-catalogs/otel-demo.yaml` with all 18 services + infra.
3. Parameterize `generate-shadow-jira-issues.ps1`, `humanize_v5_large_bulk.py`, `build_jira_memory_corpus.py`, `personas.py`, `symptom_map.py`, `extractor.py` to accept a catalog path with OB as default.
4. **Regression check:** run the OB humanizer end-to-end with the new flag pointing at the OB catalog; diff output against the existing v2 humanized corpus. Must be bit-identical.

### Phase 1b — New fault primitives in the harness (1 day)
1. Author `scripts/research-lab/otel-demo/Invoke-FlagdFlip.ps1`, `Invoke-ChaosMeshNetwork.ps1`, `Invoke-PausePod.ps1`.
2. Parameterize `run-scenario.ps1` to dispatch to the new primitives when scenario YAML specifies them. **Default code path for existing OB primitives is unchanged.**
3. **OB-equivalence regression:** re-run one OB scenario end-to-end and confirm output is bit-identical to a recent recorded run.

### Phase 1c — Multi-fault orchestration (½ day)
1. Author `Invoke-MultiFaultOrchestration.ps1` with three composition modes (concurrent / cascade / compound).
2. Add `composition_type` field handling in `run-scenario.ps1`.
3. Smoke-test concurrent and cascade modes on the local kind cluster.

### Phase 1d — Scenario YAMLs (1.5 days)
1. Author 47 YAMLs under `deploy/research-lab/scenarios/otel-demo/`.
2. Author the 9 run plans + 1 corpus manifest.
3. Lint check (consistent schema, no typos, every referenced flag exists in `demo.flagd.json`).

### Phase 2 — Pilot run (1 day)
1. Run 5–10 sample scenarios via `collect-dataset-plan.ps1` pointing at one of the OTel Demo run plans.
2. **Feature-column compatibility check** (CRITICAL — docs5/00 risk #1): run `build_triage_dataset.py` on a pilot run, confirm 94 `triage_feature_*` columns are produced with sensible values. Document any mismatches.
3. **L3 cascade-validity check** (docs5/00 §5.5.7): for each L3 cascade scenario, verify the secondary failure actually manifests with the expected propagation depth.
4. **Go / no-go** decision point.

After Phase 2 → kick off the GCP VM Phase 4 (full collection) per docs5/00.

### What Phases 3–11 look like after that (already in docs5/00)
- Phase 4: full GCP collection (4–5 days unattended)
- Phase 4b: multi-fault collection (1.5 days)
- Phases 5–11: humanize, extract, run pipelines, run agent, build cascade, evaluate, write up

---

## 9. Smoke and validation checklist

Before declaring each phase complete, run these checks:

### Phase 0a complete when:
- [ ] Helm chart deploys cleanly on local kind
- [ ] All ~18 application pods are Ready
- [ ] One synthetic checkout request from load-generator shows up in our Tempo as a multi-span trace
- [ ] Same request emits logs in our Loki tagged with the research labels
- [ ] Same request emits RED metrics in our Prometheus

### Phase 0b complete when:
- [ ] `otel-demo-research` namespace has all four research labels at the namespace level
- [ ] Application telemetry does NOT have any scenario-labeled span/log/metric fields (bias-avoidance discipline)
- [ ] chaos-mesh is installed and `NetworkChaos` CRDs exist (or skip-network-families flag is set)

### Phase 1a complete when:
- [ ] `generate-shadow-jira-issues.ps1` with no flags produces output identical to before this change (regression diff)
- [ ] Same for the humanizer with no flags
- [ ] `otel-demo.yaml` covers all 18 services with criticality + role + language
- [ ] Adding `-ServiceCatalogFile otel-demo.yaml` to a shadow-jira invocation produces tickets referencing OTel Demo service names (no leakage of OB service names)

### Phase 1b complete when:
- [ ] `Invoke-FlagdFlip.ps1` can flip a flag on, wait N seconds, flip off — and the flag state is observable via flagd-ui's API before and after
- [ ] An OB scenario (e.g., `cart-redis-degradation-critical`) re-runs end-to-end and produces bit-identical output to a saved reference run
- [ ] A new OTel Demo scenario using flagd (e.g., `payment-failure-100pct-critical`) runs end-to-end and produces a valid telemetry window

### Phase 1c complete when:
- [ ] A concurrent dual-fault scenario fires both primitives within ~1s of each other and restores both
- [ ] A cascade scenario fires the primary, waits the cascade-emergence window, and confirms the secondary signal manifests (per §5.5.7)

### Phase 1d complete when:
- [ ] 47 YAMLs lint-clean against the scenario schema
- [ ] Every flagd reference in a YAML matches a flag in `src/flagd/demo.flagd.json`
- [ ] Every multi-fault YAML references two valid single-fault primitives

### Phase 2 complete when:
- [ ] Pilot produces 10 valid telemetry windows
- [ ] 94 `triage_feature_*` columns are emitted; ≤5 columns have unexpected all-zero values (documented if so)
- [ ] L3 cascade pilots show observable secondary failure with measurable propagation depth
- [ ] OB regression check still passes: `python -m v2_advanced.tch.check_cascade --cascade-dir ...v2g-final-models/final`

---

## 10. Open implementation decisions

Listed for explicit resolution before / during Phase 0. **Recommend resolving 1–4 before Phase 0 starts; 5–8 can be resolved in-flight.**

1. **Helm chart version pin.** Resolve by checking `https://github.com/open-telemetry/opentelemetry-helm-charts/releases` for the latest version compatible with `IMAGE_VERSION=2.2.0`. Recommend pinning at Phase 0 start and not bumping mid-collection.
2. **Bundled observability disablement.** Helm chart values key for disabling Grafana / Jaeger / OpenSearch / Prometheus — verify the exact key names in the chart's `values.yaml`. Recommend test-deploying locally first to confirm.
3. **chaos-mesh on the lab cluster.** Confirm whether chaos-mesh is already installed. If not, install before Phase 0b; otherwise skip the 4 network scenarios in v1 and add as future work.
4. **PausePod realism.** SIGSTOP on the consumer process is a heavy-handed simulation of a consumer pause. Alternative: scale the consumer to zero replicas. Recommend scaling to zero for consistency with OB primitives — drop PausePod.
5. **LLM service collection burden.** The mock LLM may emit large response payloads; verify token / size constraints don't bloat the Loki index. If so, exclude LLM scenarios from v1.
6. **`failedReadinessProbe` flag semantics.** Need to verify whether triggering this flag actually causes the pod to be marked NotReady (and thus to lose traffic from the service) or just changes the probe response without triggering eviction. Skip the scenario if behavior is ambiguous.
7. **`paymentFailure` partial-rate variants.** Use these to populate intensity-gradient sub-scenarios (10%, 25%, 50%, 75%, 90%, 100%), or only use the binary 0%/100%? Recommend keeping the gradient — gives us a free severity axis.
8. **Charter §17 timing.** Author `RESEARCH-CHARTER.md` §17 amendment now (locks scope) or after Phase 2 pilot succeeds (defers commitment until validation)? Recommend now — small risk, clearer scope discipline.

---

## 11. What happens after this plan is approved

Once you say "go," the implementation order is:

1. **Charter §17** authored and committed (~5 min) — locks scope.
2. **Phase 0a** (deployment overlay) — 1 day local work. Smoke-tests against local kind. Single commit at end.
3. **Phase 0b** (namespace + chaos-mesh) — ½ day. Single commit.
4. **Phase 1a** (service catalog refactor + parameterization) — ½ day. Commit with OB regression diff in commit message.
5. **Phase 1b** (new fault primitives) — 1 day. Commit with OB regression confirmation.
6. **Phase 1c** (multi-fault orchestration) — ½ day. Commit with concurrent + cascade smoke test logs.
7. **Phase 1d** (47 scenario YAMLs + run plans + corpus manifest) — 1.5 days. Single commit.
8. **Phase 2** (pilot) — 1 day. Go/no-go decision point. Either proceed to GCP collection or iterate.

**Total local work before GCP collection kicks off: ~5–6 working days.**

I'll commit after each sub-phase so you can review at natural pause points. Each commit message will include the relevant regression-check output to demonstrate Rule R2 compliance.

---

## 12. Memory pointers

- [[project-research-charter-locked]] — scope and non-claims
- [[project-tch-cascade-design]] — what the cascade we're transferring does
- [[project-g-series-outcomes]] — which G-phases we run on OTel (G4, G6, G8)
- [[reference-code-layout]] — where the existing code lives
- [[reference-final-artifacts]] — locked OB output paths (read-only during this work)
- [[reference-per-run-artifacts]] — per-run JSONL schema we must match
- [[reference-derived-feature-columns]] — the 94 numeric columns we must reproduce on OTel
- `docs5/00-otel-demo-cross-app-plan.md` — the strategic plan this implementation realizes

---

*Last updated 2026-06-08. Authored after exploring `opentelemetry-demo/` (cloned 2026-06-08).*
