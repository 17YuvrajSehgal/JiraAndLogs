# Cross-App Generalization Plan — OpenTelemetry Demo (Astronomy Shop)

**Status:** PLAN, not yet executing.
**Owner:** Yuvraj Sehgal
**Branch:** to be created — `otel-demo-cross-app`
**Created:** 2026-06-08
**Parent:** Extends RESEARCH-CHARTER §10/§14 with a re-charter entry for cross-app validation.

---

## Table of contents

1. [Goal and headline claim](#1-goal-and-headline-claim)
2. [Why OTel Demo (vs the alternatives)](#2-why-otel-demo-vs-the-alternatives)
3. [What we will collect — the data contract](#3-what-we-will-collect--the-data-contract)
4. [OTel Demo architecture overview](#4-otel-demo-architecture-overview)
5. [Scenario taxonomy — 27 transferred + 5 new Kafka families](#5-scenario-taxonomy--27-transferred--5-new-kafka-families)
6. [Telemetry plumbing — what we plug into our existing pipeline](#6-telemetry-plumbing--what-we-plug-into-our-existing-pipeline)
7. [Fault-injection strategy](#7-fault-injection-strategy)
8. [Humanized Jira corpus generation](#8-humanized-jira-corpus-generation)
9. [Dataset structure — paths, IDs, splits](#9-dataset-structure--paths-ids-splits)
10. [Cascade evaluation protocol](#10-cascade-evaluation-protocol)
11. [Reporting — what lands in the paper](#11-reporting--what-lands-in-the-paper)
12. [Time and resource budget](#12-time-and-resource-budget)
13. [Execution order](#13-execution-order)
14. [Risk register](#14-risk-register)
15. [Go / no-go checklist](#15-go--no-go-checklist)
16. [Charter delta](#16-charter-delta)
17. [Open questions](#17-open-questions)

---

## 1. Goal and headline claim

**Goal.** Demonstrate that the locked TCH cascade (G1+G4+G7, commit `b7557c4`) transfers to a structurally different microservice application without modification, producing meaningfully comparable retrieval / triage / novelty metrics. This is the cross-app external-validity test called for in `technical-paper/sections/10-future-work.tex` and `RESEARCH-CHARTER.md` §15.

**Headline claim we are trying to support:**

> The TCH cascade, trained and locked on the 10-service Online Boutique corpus, transfers without architectural modification to the 15-service OpenTelemetry Demo (a polyglot Kafka-based e-commerce application). On the OTel Demo test set, Hit@5 = X, novel-recall = Y at preserved precision, with no L1 stacker retraining. With L1 retrained on the OTel train split, the cascade matches its Online Boutique numbers within Z%.

The claim is structured as two columns in the headline table:

| Setting | What's locked | What's reported |
|---|---|---|
| **Zero-shot transfer** | Entire cascade (L1 stacker, L2 fusion weights, L3 novelty model) | Strict external-validity number |
| **L1 retrained** | L2 fusion + L3 novelty + all pipeline architectures | Apples-to-apples retrieval/novelty number |

Both columns are reported. Zero-shot is the harder claim; L1-retrained is the more useful operating number.

---

## 2. Why OTel Demo (vs the alternatives)

Decided 2026-06-08 (see prior session reasoning). Briefly:

| Candidate | Decision | Reason |
|---|---|---|
| **OTel Demo (Astronomy Shop)** | **CHOSEN** | OTel-native (zero re-instrumentation); Kafka async genuine architectural diversity; built-in fault injection via flagd; 15+ services in 12+ languages; CNCF provenance |
| Train-Ticket (47 services) | Deferred | Local scaffolding exists but full M0–M5 redo would be ~3 weeks; pure-microservice angle is less valuable than Kafka angle |
| ThingsBoard / ThingsBoard-k8s | Rejected | IoT domain pivot, not architecture pivot; scenario taxonomy doesn't transfer; full M0–M5 redo required; better as future-paper material |

---

## 3. What we will collect — the data contract

The OTel Demo dataset must be **schema-compatible** with the locked Online Boutique v5-large dataset so the existing cascade builder and feature pipeline run unchanged. The contract:

| Artifact | Schema match required? | Source |
|---|---|---|
| `data/runs/<run_id>/manifest.json` | YES — same fields | `start-dataset-run.ps1` |
| `data/runs/<run_id>/episodes.jsonl` | YES — same fields including `scenario_family` | `run-scenario.ps1` |
| `data/runs/<run_id>/telemetry_windows.jsonl` | YES — same window types | `run-scenario.ps1` |
| `data/runs/<run_id>/raw/loki/*.json` | YES — Loki JSON format | `export-telemetry-window.ps1` |
| `data/runs/<run_id>/raw/tempo/*.json` | YES — Tempo JSON format | `export-telemetry-window.ps1` |
| `data/runs/<run_id>/raw/prometheus/*.json` | YES — Prometheus query JSON | `export-telemetry-window.ps1` |
| `data/runs/<run_id>/raw/kubernetes/*.json` | YES — k8s events JSON | `export-telemetry-window.ps1` |
| `data/runs/<run_id>/jira_shadow_issues.jsonl` | YES — same Jira-shadow contract | `generate-shadow-jira-issues.ps1` |
| `data/derived/<run_id>/triage_examples.jsonl` | YES — 94 numeric features | `build_triage_dataset.py` |
| `data/derived/<run_id>/window_memory_matchings.jsonl` | YES — same gold-linking format | `build_window_memory_matchings.py` |
| `data/derived/global/<global_id>/global-triage-examples.jsonl` | YES | `build_global_triage_dataset.py` |
| `data/derived/global/<global_id>/jira-memory-corpus.jsonl` | YES | `build_jira_memory_corpus.py` |
| `data/derived/global/<global_id>/jira-shadow-humanized-v2/` | YES — engineer-voice timelines | `humanize_v5_large_bulk.py` |

**Implication:** all of the existing PowerShell + Python collection / build pipeline runs on OTel Demo data unchanged. We only need to (a) deploy OTel Demo with our observability stack pointed at it, (b) author OTel Demo scenario YAMLs that match our `scenarios/*.yaml` schema, and (c) author an OTel Demo corpus manifest.

**Scenario family field policy.** `scenario_family` strings will be reused exactly where the semantics match (`cart-redis`, `payment-outage`, `checkout-outage`, etc.) and **new** for the Kafka families. This preserves the family-stratification logic in `build_global_triage_dataset.py`.

---

## 4. OTel Demo architecture overview

Quick reference — what we're working with. (For authoritative details, defer to upstream <https://opentelemetry.io/docs/demo/>.)

### Services (15+)

| Service | Language | Role | Failure-mode family |
|---|---|---|---|
| `frontend` | TypeScript / React | Web UI | Pod restart, traffic pressure |
| `frontend-proxy` | Envoy | Edge proxy | (untouched in initial scope) |
| `cart-service` | .NET | Cart, backed by Valkey/Redis | cart-redis (transferable from OB) |
| `checkout-service` | Go | Order placement, produces to Kafka | checkout-outage + **kafka-producer** new family |
| `payment-service` | JavaScript / Node | Card processing | payment-outage |
| `currency-service` | C++ | FX conversion | currency-outage |
| `shipping-service` | Rust | Shipping quote + label | shipping-outage |
| `email-service` | Ruby | Order confirmation | email-outage |
| `product-catalog-service` | Go | Catalog + search | productcatalog-outage / latency |
| `recommendation-service` | Python | Product recs | recommendation-outage |
| `ad-service` | Java | Display ads | ad-outage |
| `quote-service` | PHP | Shipping cost estimate | (new — quote-outage) |
| `accounting-service` | .NET | Kafka consumer for orders | **kafka-consumer** new family |
| `fraud-detection` | Kotlin | Kafka consumer for fraud check | **kafka-consumer** new family |
| `kafka` | — | Message broker | **kafka-broker** new family |
| `valkey-cart` | — | Cart cache (Redis-compatible) | backs cart-redis |
| `flagd` | Go | Feature-flag service | (used as fault-injection plane) |
| `load-generator` | Python / Locust | Synthetic traffic | (driver, not a scenario target) |

### Telemetry baseline (what the demo already emits)

- **Logs** — every service emits structured logs to stdout in OTLP-friendly format; OTel Collector receives + forwards.
- **Traces** — full OTel SDK in every service; spans on every RPC, RecordError on every failure path, semantic-convention attributes.
- **Metrics** — RED metrics per service via OTel SDK; runtime metrics from each language's default exporters.
- **Logs / metrics / traces all flow through a single OTel Collector** by design.

This is what we manually built as M1–M5 on Online Boutique. **We get it for free.**

### What we add (and what we deliberately do NOT add)

- **DO add**: research-injection labels at the **namespace level** (`DATASET_RUN_ID`, `SCENARIO_ID`, `TRAFFIC_PROFILE_ID`, `JIRA_MODE`) — same firewall as OB. These never appear in application-level telemetry, only in collector exemplar / sidecar context.
- **DO add**: ServiceMonitor for application `/metrics` scrape (some OTel Demo services expose Prometheus directly; verify each).
- **DO add**: dataset-export sidecar pattern from `scripts/research-lab/` — same as v5-large.
- **DO NOT add**: any application-level field naming our scenarios or fault types. The bias-avoidance discipline from `microservice-changes.md` applies unchanged.
- **DO NOT modify** application code unless something is genuinely missing (no current evidence of gaps — OTel Demo is the reference impl of what we built).

---

## 5. Scenario taxonomy — 27 transferred + 5 new Kafka families

Total: **32 families** for OTel Demo (vs 27 for OB). The 5 new families are the architectural-distance evidence and are the headline justification for choosing OTel Demo over Train-Ticket.

### 5.1 Transferred from OB (semantic match)

| OB family | OTel Demo realization | Fault primitive |
|---|---|---|
| `payment-outage` | `payment-service` scaled to zero / paymentServiceUnreachable flag | ScaleDeployment OR flagd flip |
| `checkout-outage` | `checkout-service` scaled to zero | ScaleDeployment |
| `currency-outage` | `currency-service` scaled to zero | ScaleDeployment |
| `shipping-outage` | `shipping-service` scaled to zero | ScaleDeployment |
| `recommendation-outage` | `recommendation-service` scaled to zero OR recommendationServiceCacheFailure flag | ScaleDeployment OR flagd |
| `ad-outage` | adServiceFailure flag OR scaled to zero | flagd OR ScaleDeployment |
| `productcatalog-outage` | productCatalogFailure flag OR scaled to zero | flagd OR ScaleDeployment |
| `email-outage` | `email-service` scaled to zero | ScaleDeployment |
| `cart-redis` | `valkey-cart` scaled to zero | ScaleDeployment |
| `productcatalog-latency` | inject latency env var on product-catalog | SetEnv |
| `checkout-restart` | `kubectl rollout restart checkout-service` | RestartPods |
| `frontend-restart` | `kubectl rollout restart frontend` | RestartPods |
| `single-pod-restart-healthy-replication` | kill 1 pod of N replicas | RestartPods (selective) |
| `flapping-pod` | repeated single-pod restart (3× within window) | RestartPods loop |
| `post-deploy-churn` | rolling update on cart-service | image bump |
| `frontend-traffic-pressure` | loadgeneratorFloodHomepage flag | flagd |
| `scheduled-job-spike` | periodic locust spike via load-generator config | SetEnv on load-generator |
| `resource-saturation` | adServiceHighCpu flag | flagd |
| `slow-leak-saturation` | ad-service manual GC pressure (adServiceManualGc) | flagd |
| `latency-near-miss-partial-recovery` | brief latency injection that recovers mid-window | SetEnv timed |
| `recovered-in-window` | brief outage < 60s mid-window | ScaleDeployment timed |
| `third-party-blip` | imageInvalidLink or imageSlowLoad flag | flagd |
| `network-latency` | chaos-mesh NetworkChaos delay | chaos-mesh |
| `network-packet-loss` | chaos-mesh NetworkChaos loss | chaos-mesh |
| `network-partition` | chaos-mesh NetworkChaos partition | chaos-mesh |
| `dns-outage` | kill CoreDNS pod | RestartPods (kube-system) |
| `baseline-normal` | no fault | RecordOnly |

### 5.2 New Kafka families (architectural-distance evidence)

These are the families that exist in OTel Demo but cannot exist in OB. They are the publishable architectural-distance evidence.

| Family | Realization | Fault primitive | Why it matters |
|---|---|---|---|
| `kafka-broker-outage` | scale `kafka` to zero replicas | ScaleDeployment | Tests cascade behavior when a non-RPC dependency dies — symptoms manifest as Kafka producer errors in `checkout-service` and silence in downstream consumers. |
| `kafka-consumer-lag` | kafkaQueueProblems flag OR pause `fraud-detection` | flagd OR PausePod | Tests detection of accumulating consumer-lag pattern. Failure mode is "queue grows, fraud-detection falls behind" — no RPC error spike. |
| `kafka-consumer-crash` | scale `fraud-detection` to zero (orders pile up; checkout continues OK) | ScaleDeployment | One consumer down, others healthy. Tests downstream-consumer outage detection. |
| `kafka-partition-rebalance` | restart all kafka brokers within window | RestartPods | Tests transient rebalance noise — recoverable. |
| `kafka-dead-letter-spike` | flagd flip causing one consumer to throw and DLQ | flagd | Tests detection via dead-letter queue depth, an OTel Demo–specific signal. |

### 5.3 Total counts (single-fault baseline)

- 27 transferred + 5 new Kafka = **32 single-fault (L1) scenario families**
- Target windows per family: median ~50, minimum 20 (matches OB v5-large stratification)
- L1 target: ~6,500–7,500 windows across ~95 runs (matches OB v5-large)
- **L2/L3/L4 multi-fault adds another ~10 scenarios and ~40 runs — see §5.5.**
- **Grand total: ~42 scenarios, ~135 runs, ~9,300 windows.**

### 5.4 Severity labeling

Each scenario YAML carries a `severity` field in `{none, minor, major, critical}`, matching the OB convention. Kafka families default to `major` for outage / crash, `minor` for lag / rebalance.

### 5.5 Graded difficulty — multi-fault and compound anomalies

The OB v5-large corpus is **single-fault-per-run by construction** — §09-limitations.tex lists this explicitly as a known divergence from real production. The OTel Demo collection is the natural place to turn that limitation into a contribution by deliberately running scenarios at **three escalating difficulty levels** plus the existing single-fault baseline.

This is the most valuable single addition to the cross-app plan: it makes the OTel Demo dataset *strictly richer* than the OB dataset along a dimension reviewers will recognize as production-realistic, and gives the paper a clean graded-difficulty axis to report on.

#### 5.5.1 The four difficulty levels

| Level | Name | Definition | Example |
|---|---|---|---|
| L1 | **Single fault** | One fault primitive on one target. Matches the OB v5-large regime. | `payment-outage` alone |
| L2 | **Concurrent dual-fault** | Two faults injected simultaneously on different services, no causal link between them. Models "incident clusters" — multiple unrelated things break at once (deploy-induced, regional pressure, etc.) | `payment-outage` + `cart-redis` injected in parallel, same window |
| L3 | **Cascading dual-fault** | Two faults with a causal relationship: a primary fault triggers a secondary observable failure on a downstream / dependent service, with directionality. Models real incident cascades. | `kafka-broker-outage` → `checkout-outage` (broker dies, checkout's Kafka producer errors out, cascading errors observed) |
| L4 | **Compound primitives** | Two different fault *primitives* on the same or different targets. Mixes mechanisms (e.g., resource saturation + network latency). Models heterogeneous incidents. | `adServiceHighCpu` (flagd) + `network-latency` on shipping-service (chaos-mesh) |

Levels L1–L3 are the headline graded series. L4 is optional — useful as a stress test if collection budget allows.

#### 5.5.2 Concrete multi-fault scenario list

Total: **10 multi-fault scenarios** spanning L2–L4. Each combines two families from §5.1 / §5.2.

**L2 — Concurrent (5 scenarios)**

| ID | Composition | Why this pair |
|---|---|---|
| `concurrent-payment-cart-redis` | payment-outage + cart-redis | Two independent critical services down together; common deploy-correlated pattern |
| `concurrent-currency-shipping` | currency-outage + shipping-outage | Both downstream of checkout; tests whether retrieval can return two non-overlapping golds |
| `concurrent-ad-recommendation` | ad-outage + recommendation-outage | Both ML-adjacent / personalization layer; tests semantic clustering of golds |
| `concurrent-productcatalog-latency-flapping-pod` | productcatalog-latency + flapping-pod (frontend) | Mixes severity tiers; one critical + one noisy |
| `concurrent-kafka-lag-payment-outage` | kafka-consumer-lag + payment-outage | New-family × OB-family combination; tests whether the Kafka novelty path interacts with a familiar RPC path |

**L3 — Cascading (4 scenarios, directionality matters)**

| ID | Composition (primary → secondary) | Causal mechanism |
|---|---|---|
| `cascade-kafka-broker-checkout` | kafka-broker-outage → checkout-service errors | Broker dies, checkout's Kafka producer fails, checkout returns errors to frontend |
| `cascade-productcatalog-latency-recommendation-timeout` | productcatalog-latency → recommendation-service timeout | Slow upstream produces timeouts in dependent service |
| `cascade-valkey-cart-checkout` | cart-redis (valkey) → checkout-service errors | Cart unavailable → checkout can't read cart → checkout fails |
| `cascade-currency-frontend-errors` | currency-outage → frontend display errors | Currency missing → price formatting fails → frontend shows errors |

**L4 — Compound primitives (1 scenario, sentinel)**

| ID | Composition |
|---|---|
| `compound-saturation-network-latency` | adServiceHighCpu (flagd, resource) + network-latency on shipping (chaos-mesh, network) |

#### 5.5.3 Episode + window labeling changes

The single-fault `episodes.jsonl` schema needs three additive fields. The default values keep the schema backward-compatible with OB:

```json
{
  // ... existing fields ...
  "difficulty_level": "L1",                          // L1 | L2 | L3 | L4
  "fault_composition_type": "single",                // single | concurrent | cascade | compound_primitive
  "fault_components": [                              // ordered list; cascade direction = order
    {
      "scenario_family": "payment-outage",
      "fault_primitive": "ScaleDeployment",
      "target": "paymentservice",
      "is_primary_cause": true                       // true for L1 single; primary for L3 cascade; both true for L2 concurrent
    }
    // ... second component for L2/L3/L4 ...
  ]
}
```

`telemetry_windows.jsonl` is unchanged. `jira_shadow_issues.jsonl` carries one shadow ticket **per fault component** (so an L2 / L3 / L4 episode produces two shadow tickets), each linked back to the same episode via `episode_id` and carrying a `causal_role: "primary" | "secondary"` field.

#### 5.5.4 Multi-gold retrieval — metric semantics

In multi-fault episodes, a window may correctly match **multiple gold tickets** (one per component). The metric definitions adapt as follows:

- **Hit@K (binary, primary metric)** — 1 if **any** gold is in top-K, else 0. Unchanged from OB. The cleanest cross-app number.
- **AllGold@K (new, secondary metric)** — 1 if **all** golds are in top-K, else 0. New metric for L2/L3/L4 episodes only. Measures comprehensive retrieval.
- **PrimaryGold@K (new, L3-only)** — 1 if the **primary-cause** gold is in top-K, else 0. Reported only for L3 cascade scenarios; tests root-cause prioritization.
- **MRR** — uses rank of the **first** gold encountered. Unchanged.
- **Recall@K (averaged)** — fraction of gold tickets recovered. `recall@K = |gold ∩ top-K| / |gold|`. Useful aggregate for L2/L3 reporting.

Stratification axis added: `difficulty_level ∈ {L1, L2, L3, L4}`. Headline tables report Hit@5 per level. **A monotone degradation curve L1 → L2 → L3 is the expected result; reporting it honestly is publishable either way.**

#### 5.5.5 Per-difficulty run targets

| Difficulty | Scenarios | Runs per scenario | Total runs | Total windows (≈) |
|---|---:|---:|---:|---:|
| L1 — single fault | 32 (§5.1+§5.2) | ~3 | ~95 (matches OB v5-large) | ~6,500 |
| L2 — concurrent dual | 5 | 4 | 20 | ~1,400 |
| L3 — cascading dual | 4 | 4 | 16 | ~1,100 |
| L4 — compound primitives | 1 | 4 | 4 | ~280 |
| **TOTAL** | **42** | — | **~135 runs** | **~9,300 windows** |

This is ~30% more collection work than the original single-level plan but yields a strictly richer dataset and a publishable graded-difficulty section. Updated budget in §12.

#### 5.5.6 Harness work needed

`scripts/research-lab/run-scenario.ps1` currently dispatches one fault primitive per scenario. For L2/L3/L4 we need a small extension:

- **L2 concurrent** — issue both fault primitives in parallel (start both before `active_fault` window begins; restore both after).
- **L3 cascade** — issue the primary fault first, wait ~30s for the secondary to manifest organically (it should — the cascade is causal, not orchestrated), then begin the `active_fault` window. The secondary fault is *not* directly injected; we observe it as an emergent effect. **This is the key validity property of L3 scenarios.**
- **L4 compound primitives** — same as L2 but with mixed primitive types (e.g., `ScaleDeployment` + `ChaosMeshNetwork` together).

Concretely: add a `composition_type` field to scenario YAMLs, and a small dispatcher in `run-scenario.ps1` that handles each composition. Estimate ~1 day of harness work (slight extension of the §6.4 / §7 work already planned).

#### 5.5.7 Cascade-validity check (Phase 3 pilot must verify)

L3 only works if the *secondary* fault genuinely manifests as a downstream observable. For each L3 scenario, the pilot must show:

- The secondary service's error rate / latency moves measurably during the active-fault window.
- The secondary's signal is distinguishable from baseline traffic.
- The two faults are temporally separable in the telemetry (primary errors → ~10–30s lag → secondary errors).

If a cascade scenario doesn't actually cascade (e.g., the dependent service has aggressive retries that mask the failure), drop it from the corpus rather than running it under false-pretense L3 labeling. Better to ship 2 valid L3 scenarios than 4 mislabeled ones.

#### 5.5.8 Why this matters for ICSE

1. **Closes a stated limitation.** The paper currently says "single fault per run is a known divergence from production." OTel Demo with multi-fault closes that gap on the second dataset, weakening the limitation without invalidating the primary OB claim.
2. **Graded-difficulty results are reviewer-credible.** A monotone L1 → L2 → L3 degradation curve, reported with bootstrap CIs, is the kind of result ICSE reviewers expect from an empirical systems paper. It's hard to wave away.
3. **Multi-gold retrieval is a new claim axis** that the OB experiments cannot make. The paper section §6.5 (cross-app) becomes meaningfully different from §5 (anchor experiment) and §6 (G-series), not just "same experiments on a different app."
4. **Cascade scenarios are root-cause attribution evidence.** Even if we don't claim "TCH does root-cause attribution," reporting `PrimaryGold@5` on L3 scenarios shows whether the cascade naturally prioritizes upstream causes over downstream symptoms — a property that is highly relevant to real on-call workflows.

---

## 6. Telemetry plumbing — what we plug into our existing pipeline

The existing collection pipeline is dataset-agnostic. We need to do exactly four pieces of new work:

### 6.1 Deployment manifests (kustomize overlay)

Create `deploy/otel-demo/` mirroring `deploy/research-lab/online-boutique/`:

```
deploy/otel-demo/
├── README.md
├── kustomization.yaml                         # pins to specific OTel Demo upstream tag
├── namespace.yaml                             # otel-demo-research namespace
├── flagd/
│   └── flagd-config.yaml                      # feature flags incl. our fault flags
├── observability/
│   ├── servicemonitor.yaml                    # /metrics scrape for OTel Demo services
│   └── loki-namespace-relabeling.yaml         # tag logs with our 4 research labels
├── chaos-mesh/
│   └── network-chaos-templates.yaml           # template NetworkChaos for net families
└── upstream/                                  # vendored or submodule'd upstream demo
```

**Decision:** vendor the upstream demo manifests at a pinned tag (e.g. `v2.0.0`) rather than git-submodule. Simpler reproducibility, smaller blast radius for upstream changes mid-collection.

### 6.2 Scenario YAMLs

Author 32 YAMLs under `deploy/research-lab/scenarios/otel-demo/` mirroring the existing schema:

```
deploy/research-lab/scenarios/otel-demo/
├── baselines/
│   └── baseline-normal-traffic.yaml
├── faults/
│   ├── payment-outage-major.yaml
│   ├── cart-redis-degradation-critical.yaml
│   ├── kafka-broker-outage-major.yaml          # NEW
│   ├── kafka-consumer-lag-minor.yaml           # NEW
│   ├── ...
```

Each YAML follows the existing schema: `scenario_id`, `scenario_family`, `severity`, `fault_primitive` (`SetEnv` / `ScaleDeployment` / `RestartPods` / `RecordOnly` / `Flagd` / `ChaosMeshNetwork`), `active_fault_duration_seconds`, `pre_fault_baseline_seconds`, `recovery_window_seconds`.

**New fault primitives needed:**
- `Flagd` — flip a feature flag for the active fault duration, flip back after.
- `ChaosMeshNetwork` — apply a NetworkChaos CR for the active fault duration, delete after.
- `PausePod` — pause a pod (`kubectl drain` style) without scaling — used for `kafka-consumer-lag`.

These three are new and require small additions to `scripts/research-lab/run-scenario.ps1`. Estimate ~1 day of harness work.

### 6.3 Corpus manifest + run plans

```
deploy/research-lab/corpora/
└── otel-demo-v1.json                          # 100-run corpus manifest

deploy/research-lab/run-plans/
├── otel-demo-control-baseline.json            # baselines × 8 runs
├── otel-demo-compact-a.json                   # 12 high-volume families × 30 runs
├── otel-demo-compact-b.json                   # 14 medium families × 30 runs
├── otel-demo-new-kafka.json                   # 5 Kafka families × 12 runs
└── otel-demo-long-running.json                # slow-leak / saturation × 8 runs
```

Total: **100 runs**, structured to match OB v5-large stratification.

### 6.4 Service-name mapping for Jira shadow templates

The Jira-shadow generator hardcodes the OB service names. We need a per-app service catalog. Make this configurable:

- Add `deploy/research-lab/service-catalogs/online-boutique.yaml` (existing 10 services).
- Add `deploy/research-lab/service-catalogs/otel-demo.yaml` (15+ services).
- `generate-shadow-jira-issues.ps1` reads the catalog based on the corpus manifest's `service_catalog` field.

This is the single piece of cross-app refactoring needed. Estimate ~½ day.

---

## 7. Fault-injection strategy

Three orthogonal injection mechanisms, mapped to scenario primitives:

| Mechanism | When to use | Pros | Cons |
|---|---|---|---|
| **kubectl** (`ScaleDeployment`, `RestartPods`, `SetEnv`) | Service-down, restart, env-config | Same as OB; harness already exists | No fine control over which RPCs fail |
| **flagd** (feature flags) | Application-level fault simulation | Fast, reversible, OTel Demo-native; one of the few apps with this built in | Fault is a code path the app intentionally exposes — slight realism trade-off |
| **chaos-mesh** (NetworkChaos) | Network families | Realistic L3/L4 faults | New harness dependency; verify it's compatible with the lab cluster |

### 7.1 Fault-realism note

`flagd`-driven faults are application-aware — the service knows it's been told to fail. This is slightly different from OB's `ScaleDeployment` faults where the service is actually gone. For symmetry, **default to ScaleDeployment / RestartPods where possible** and only use flagd where the flag exposes a fault mode that can't easily be reproduced otherwise (e.g., `adServiceHighCpu`, `recommendationServiceCacheFailure`, `kafkaQueueProblems`).

Document this trade-off in the limitations section: ~15% of scenarios use flagd-driven faults; the rest use deployment-level primitives matching OB.

### 7.2 Recovery semantics

For all primitives, the active-fault window ends with a deterministic restore step:
- `ScaleDeployment` → restore replicas
- `RestartPods` → wait for ready
- `SetEnv` → revert env, wait for rollout
- `Flagd` → flip flag back, optional 30s settle
- `ChaosMeshNetwork` → delete the NetworkChaos CR

All restores are idempotent and recoverable from harness re-runs.

---

## 8. Humanized Jira corpus generation

### 8.1 Approach

Reuse the V2 humanizer (`humanize_v5_large_bulk.py`) with two changes:

1. **Service catalog substitution.** The humanizer's per-persona prompts reference OB service names (e.g., "cartservice"). Update the prompt templates to read from the corpus's `service_catalog` field, so OTel Demo's `cart-service` / `valkey-cart` / `quote-service` etc. appear naturally in generated tickets.

2. **Kafka-specific symptoms.** The humanizer's `symptom_map.py` does not currently cover Kafka failure modes. Add ~10–15 new symptom templates for: producer error spikes, consumer-lag growth, partition rebalance noise, dead-letter accumulation, broker connectivity drops. These should match the language style validated against TAWOS in [[project-jira-humanizer-redesign-tawos]].

3. **Architecture-aware engineer voice.** The "engineer-voice" prompts can stay; OTel Demo engineers in 2026 sound like OB engineers in 2026. No persona changes needed.

### 8.2 Corpus size target

- Target: **~350 humanized tickets** (matching OB V2 corpus size) plus **~20 Kafka-specific tickets** to ensure each new family has 4+ tickets in memory.
- 90% should carry `description_code` blocks (matching OB V2's 90.2%).
- Sanitizer-clean per §14.11 of the charter.

### 8.3 Distractor pool

**Do not re-mint a distractor pool for OTel Demo.** Reuse the existing 110-ticket OB distractor pool (60 TAWOS + 25 in-arch OB + 25 cross-arch) for the OTel Demo distractor sweep. This keeps the noise distribution identical across both datasets and makes the cross-app G6-equivalent result directly comparable.

---

## 9. Dataset structure — paths, IDs, splits

### 9.1 Naming

- Run prefix: `2026-XX-XX-otel-demo-v1` (where XX-XX is collection start date)
- Global ID: `2026-XX-XX-otel-demo-v1-global`
- Branch: `otel-demo-cross-app`

### 9.2 Output structure

```
data/runs/2026-XX-XX-otel-demo-v1-*/             # ~100 directories
data/derived/2026-XX-XX-otel-demo-v1-*/          # ~100 directories
data/derived/global/2026-XX-XX-otel-demo-v1-global/
├── global-triage-examples.jsonl                 # ~7,000 windows
├── triage-feature-columns.json                  # MUST equal OB's 94 columns
├── triage-split-manifest.json                   # family-disjoint (OOD eval)
├── triage-split-manifest-v2-resplit.json        # in-distribution (primary)
├── jira-memory-corpus.jsonl                     # ~350-370 raw shadow tickets
├── jira-shadow-humanized-v2/bulk-otel-v1/
│   └── timeline.jsonl                           # humanized
├── v2_kg_extractions/all_extractions.jsonl      # LLM extraction over humanized
├── v2_kg_extractions_rules/all_extractions.jsonl
└── comparison/
    ├── v2a-resplit-otel/                        # HGB + bi_encoder + memorygraph
    ├── v2b-logseq2vec-otel/
    ├── v2c-hybrid-otel/
    ├── v2c-hybrid-llm-otel/
    ├── v2d-kg-rulebased-otel/
    ├── v2e-agent-llm-otel/
    └── v2g-final-models/
        ├── zero-shot/                           # cascade as-is, no retraining
        ├── l1-retrained/                        # L1 stacker refit on OTel train
        └── headline-cross-app.json              # consolidated paper-ready
```

### 9.3 Splits

Two splits, both via `make_resplit.py` (with the same `random_state=42` recipe):

- **In-distribution v2-resplit**: ~70/15/15 by run within family. Primary headline.
- **OOD family-disjoint**: original split by family. Used for the cross-app analogue of G8.

Verify both manifests have ≥20 windows per family in the test set before proceeding.

### 9.4 Feature-column compatibility check

**Critical pre-flight check.** Run `build_triage_dataset.py` on one pilot OTel Demo run and verify it emits exactly the same 94 `triage_feature_*` columns as OB. If any column is missing or has unexpected zeros, investigate before scaling collection.

Most likely places for mismatch:
- `m05_rpc_server_*` — OTel Demo uses `otel.span.duration` not `rpc_server_duration` directly. Verify the recording rule.
- `m05_svc_*` — depends on the OTel Demo's metric naming conventions.
- `m05_*_business_event_*` — OTel Demo has different business events (e.g., no `order_placed` per se, but `recommendations.counter`). Decide whether to map or accept these as zero.

A one-day pilot collection (10–20 windows) catches these issues before the 100-run commitment.

---

## 10. Cascade evaluation protocol

### 10.1 Two evaluation columns

**Column A — Zero-shot transfer (PRIMARY)**

- Load locked TCH artifacts from OB: L1 stacker (`v2g-final-models/final/stacker.pkl`), L2 fusion config, L3 learned-novelty classifier (`g7-learned-novelty/novelty_classifier.pkl`).
- Run the 6 underlying pipelines on the OTel Demo test split:
  - HGB — predict using the OB-trained model directly (no refit). HGB sees raw 94-feature vectors; if OTel feature distributions differ enough, this will show.
  - bi_encoder — use the OB-trained encoder (G1 fine-tuned) to embed OTel windows and the OTel humanized memory. **No re-fine-tune.**
  - hybrid_rrf rule + LLM — same pipelines, OTel Neo4j graph loaded (re-extract over OTel humanized memory).
  - logseq2vec — use OB-trained transformer to encode OTel log sequences. **No retrain.**
  - kg_retrieval — Cypher over OTel-extracted Neo4j graph.
- DiagnosisAgent — re-run on OTel test windows (LLM doesn't retrain; the prompts work on any service catalog).
- Assemble the cascade. Compute Hit@1, Hit@5, MRR, PR-AUC strict + inclusive, novel precision, novel recall. Bootstrap CIs as per OB.

**Column B — L1 retrained (SECONDARY)**

- Same pipelines, but refit the L1 stacker on the OTel train split (5-fold CV, class-balanced, same recipe as OB).
- All other components unchanged.
- This isolates "is the L1 stacker's HGB-coefficient-dominated structure transferring, or does HGB itself transfer?" If A and B match closely, the cascade transfers cleanly. If B >> A, the L1 stacker needs per-app calibration but the rest of the cascade is portable.

**Column C — L1 + G7 retrained (TERTIARY, optional)**

- Same as B but also refit the G7 learned-novelty LogReg on the OTel train split. Use only if column B novel-recall comes out much lower than OB and we want to know whether G7's family-one-hot features are the issue.

### 10.2 Reported metrics

**Headline table (L1 single-fault windows only, for clean OB comparison):**

| Metric | OB locked | OTel zero-shot | OTel L1 retrained | Δ rel vs OB |
|---|---:|---:|---:|---:|
| Hit@1 | 0.7221 | ? | ? | ? |
| Hit@5 | 0.9124 | ? | ? | ? |
| MRR | 0.7937 | ? | ? | ? |
| PR-AUC strict | 0.9998 | ? | ? | ? |
| PR-AUC inclusive | 0.8562 | ? | ? | ? |
| Novel precision | 0.9405 | ? | ? | ? |
| Novel recall | 0.7932 | ? | ? | ? |

**Graded-difficulty table (L1 / L2 / L3 / L4, new — has no OB counterpart):**

| Metric | L1 (single) | L2 (concurrent) | L3 (cascade) | L4 (compound) |
|---|---:|---:|---:|---:|
| Hit@5 | ? | ? | ? | ? |
| AllGold@5 | — | ? | ? | ? |
| PrimaryGold@5 | — | — | ? | — |
| Recall@5 (avg over golds) | — | ? | ? | ? |
| MRR | ? | ? | ? | ? |

Plus the standard stratified breakdowns: per scenario family, per service, per window-type, per `n_prior_family_tickets` (depth curve), and now **per `difficulty_level`**.

### 10.3 Statistical envelope

Same as OB: paired bootstrap, 1000 resamples, seed=42, 95% CIs. The bootstrap pairs are within the OTel test set, not across OB and OTel (those datasets are not paired).

### 10.4 What "success" looks like

The paper survives if:

- **L1 zero-shot Hit@5 ≥ 0.75** — at least 82% of OB's number, showing meaningful transfer. (If it falls below 0.5, the cascade is more OB-specific than we think and the framing has to change.)
- **L1 retrained Hit@5 within 5% rel of OB's 0.912.** This is the "apples-to-apples with stacker refit" claim.
- **L1 novel-recall ≥ 0.60 in either column.** Lower than OB's 0.79 is fine; novelty was always going to be the more brittle channel.
- **Kafka families have non-trivial Hit@5.** At least 0.50 on the 5 new Kafka L1 families combined. Even 0.50 is publishable as "the cascade transfers to a new failure-mode family it has never seen" since G8 already established LOFO behavior.
- **L2 Hit@5 ≥ 0.65** — concurrent dual-fault windows should still retrieve at least one of the two golds the majority of the time.
- **L3 PrimaryGold@5 ≥ 0.50** — for cascade scenarios, the primary cause should be in the top-5 at least half the time. This is the most demanding threshold and the one most likely to miss; below it, frame as "cascade scenarios reveal a root-cause-attribution gap" — still publishable.
- **Monotone graded-difficulty curve** — Hit@5(L1) ≥ Hit@5(L2) ≥ Hit@5(L3). If non-monotone (e.g., L3 > L2), investigate before reporting; could indicate cascade scenarios accidentally have stronger gold signal than concurrent ones.

If any of these thresholds is missed by a wide margin, **report honestly and reframe.** The integrity of the negative finding is more valuable than a forced positive — same charter discipline as the rest of the project.

### 10.5 Cross-app analogues of the G-series

Run the cheap ones; skip the expensive ones:

| G-phase | Cross-app version | Run? |
|---|---|---|
| G1 | BiEncoder G1 on OTel | NO — defeats zero-shot claim. (Maybe as a side experiment.) |
| G2 | Cross-encoder reranker on OTel | NO — already failed on OB; uninformative. |
| G3 | Symmetric LLM extraction on OTel | NO — already failed on OB; would re-fail. |
| G4 | Agent on OTel test windows | YES — already in the pipeline since the agent is per-window. |
| G5 | LLM judge on OTel | NO — already failed. |
| **G6** | **Distractor sweep on OTel (reuse 110 OB distractors)** | **YES — cheap, ~1 hr.** |
| G7 | Learned-novelty on OTel | YES — column C. |
| **G8** | **LOFO on OTel** | **YES — uses the OOD split.** |

So: G4 (free), G6 (~1 hr), G8 (~2 hrs). Skip the rest. Document in the paper which were skipped and why.

---

## 11. Reporting — what lands in the paper

A new section (call it `08-cross-app.tex` between `07-results.tex` and `08-discussion.tex`) covering:

1. **Setup** — OTel Demo overview, scenario taxonomy delta (32 single + 10 multi-fault), dataset stats table.
2. **Headline cross-app table (L1 single-fault)** — columns A / B / C as in §10.2.
3. **Kafka-family results** — separate sub-table showing per-family Hit@5 on the 5 new Kafka families.
4. **Graded-difficulty results (L1 / L2 / L3 / L4)** — the second headline. New table per §10.2. This is the section that does NOT have an OB analogue; it's pure new contribution.
5. **Per-stratum delta** — does the cascade lose more on certain families / window types / difficulty levels?
6. **Cross-app robustness** — G6 distractor sweep on OTel, G8 LOFO on OTel.
7. **Discussion** — what transferred, what didn't, what this tells us about the cascade's structural assumptions; how cascade-difficulty degradation interacts with the cascade's L2 fusion design.

Also update:

- `09-limitations.tex` — add a single bullet that the synthetic-Jira humanizer ran on OTel too, so the synthetic-corpus limitation applies to both datasets.
- `10-future-work.tex` — remove "cross-app generalization" from the future-work list (it's now done) and add "domain generalization (IoT, ThingsBoard)" as the new ambition.
- `B-reproducibility.tex` — append the OTel Demo collection instructions and the new branch/commit references.

---

## 12. Time and resource budget

### 12.1 Wall-clock budget

| Phase | Wall-clock | Notes |
|---|---:|---|
| Phase 0 — Infrastructure setup (deploy/otel-demo/) | 1 day | Vendor upstream manifests at pinned tag; kustomize overlay; observability scrape config |
| Phase 1 — Scenario YAMLs + harness primitives | 2 days | 32 YAMLs + Flagd/ChaosMeshNetwork/PausePod fault primitives in run-scenario.ps1 |
| Phase 2 — Service catalog refactor | ½ day | `generate-shadow-jira-issues.ps1` + humanizer prompt template parameterization |
| Phase 3 — Pilot collection (5–10 runs) | 1 day | Validate feature-column compatibility; catch schema drift early |
| Phase 4 — Full corpus collection (GCP VM) — L1 single-fault | **4–5 days** | ~95 runs; same as OB v5-large; unattended on e2-standard-16 |
| Phase 4b — Multi-fault collection (L2/L3/L4) | **~1.5 days** | ~40 runs; cascade scenarios need ~30s warmup-to-cascade so per-run time is slightly higher than L1 |
| Phase 5 — Humanized Jira corpus | 1 day | ~5 hrs LM Studio; Kafka symptom-map additions; ~20 Kafka-specific tickets |
| Phase 6 — LLM extraction (Neo4j) | 1 day | ~80 min LLM extraction + Neo4j load + verification |
| Phase 7 — 6 pipeline pre-runs | ~1 day | Embed both corpora; SPLADE index; KG retrieval; logseq2vec |
| Phase 8 — Agent on OTel test (1008 windows) | ~6 hrs LLM | Same throughput as G4 on OB |
| Phase 9 — Cascade A/B/(C) evaluation | ½ day | build_cascade + analyze_cascade; bootstrap CIs |
| Phase 10 — G6 + G8 cross-app robustness | ~½ day | Simulate distractor sweep; run LOFO novelty |
| Phase 11 — Section 08-cross-app.tex write-up | 1 day | New paper section + table updates |
| **TOTAL** | **~16 working days** | **~3 weeks calendar, with overnight LLM/collection runs.** |

### 12.2 GPU / LLM budget

- LM Studio with Qwen 3.6 35B-A3B loaded: ~12 hours total (humanizer ~5 hrs + extraction ~1.5 hrs + agent ~6 hrs).
- No new fine-tunes by default (zero-shot is the claim). If we run column C with G7 retrained, add ~30 min CPU.

### 12.3 GCP cost

- e2-standard-16 VM, ~5 days uptime ≈ ~$70 at on-demand rates.
- ~50 GB egress for data exports (free under standard quota).
- No new persistent storage beyond what OB v5-large used.

### 12.4 Disk

- Raw OTel Demo telemetry: ~10–12 GB compressed (similar to OB v5-large, possibly larger due to extra services).
- Derived + comparison outputs: ~5 GB.
- Confirm ~20 GB headroom under `data/` before starting.

---

## 13. Execution order

```
Phase 0 (1d)  ──→ Phase 1 (2d)  ──→ Phase 2 (½d)
                                          │
                                          ▼
                                  Phase 3 Pilot (1d)
                                          │
                                  go / no-go decision
                                          │
                                          ▼
                                  Phase 4 Full collection (4-5d, GCP)
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                   Phase 5 Humanize  Phase 6 LLM extract  Phase 7 Pipelines
                       (1d)             (1d)                 (1d)
                          └───────────────┼───────────────┘
                                          ▼
                                  Phase 8 Agent (6 hrs)
                                          │
                                          ▼
                                  Phase 9 Cascade A/B (½d)
                                          │
                                          ▼
                                  Phase 10 G6 + G8 (½d)
                                          │
                                          ▼
                                  Phase 11 Write-up (1d)
                                          │
                                          ▼
                                  Section 08-cross-app.tex
```

Phases 5/6/7 can parallelize after collection completes — they share no GPU dependency with each other (humanizer = LLM, extraction = LLM, pipelines = mostly CPU + small encoder GPU).

---

## 14. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | OTel Demo's feature columns don't 1:1 match OB's 94 (different metric names, different business events) | **HIGH** | Medium — derails feature pipeline | Phase 3 pilot catches this before scaling. Plan: map where possible (`otel.rpc.server.duration` → `m05_rpc_server_duration`); zero-out where not (no business event); document in paper limitations. |
| 2 | Zero-shot cascade collapses (Hit@5 ≪ 0.5) | Medium | High — narrative breaks | If A column collapses, B column (L1-retrained) becomes primary. Frame honestly: "L1 stacker requires per-app calibration; everything else transfers." Still publishable. |
| 3 | flagd-driven faults are unrealistic enough that reviewers object | Medium | Low | We default to ScaleDeployment/RestartPods; flagd only where unavoidable. Document the ~15% flagd share explicitly. |
| 4 | Kafka families produce no useful signal (consumers can't distinguish broker outage from consumer crash from local stub) | Medium | Medium | Pilot one Kafka scenario first; verify trace_error_count + consumer-lag metric move. If they don't, the Kafka families don't make the paper, but the OTel Demo overall still does. |
| 5 | OTel Demo's redis is Valkey, not Redis — instrumentation may differ enough that cart-redis windows look different | Low | Low | Verify in pilot; Valkey is Redis-compatible at the protocol level so OTel instrumentation should be identical. |
| 6 | Chaos-mesh not available in the lab cluster | Low | Low | Network families are 4/32 scenarios; can skip them in v1 and add later. |
| 7 | GCP VM cost overrun | Low | Low | Hard ceiling at 6 days; resume-on-failure is built into collect-dataset-corpus.ps1. |
| 8 | Humanizer drifts off-style on Kafka content (no TAWOS Kafka examples to anchor) | Medium | Low | TAWOS has Kafka-related issues in MULE / SERVER projects; sample a few during the symptom-map authoring to anchor the new templates. |
| 9 | LLM extraction over Kafka tickets confuses the canonical-services list | Low | Low | Update the canonical-services list to include all 15 OTel Demo services + `kafka` + `valkey-cart`. |
| 10 | Schema drift in upstream OTel Demo between pin time and collection | Low | Low | Vendor (not submodule) at pinned tag. Lock once and don't update mid-collection. |
| 11 | Reviewer pushback: "same domain — e-commerce on both sides" | Medium | Medium | The Kafka async axis is the genuine architectural-distance evidence. Spell it out in §1 of the cross-app section. |
| 12 | L3 cascade scenario doesn't actually cascade (secondary service has aggressive retries that hide the failure) | **HIGH** | Medium | Phase 3 pilot validates cascade signal per §5.5.7. Drop any L3 scenario that doesn't show the temporal lag → secondary error pattern. Better to ship 2 valid L3s than 4 mislabeled ones. |
| 13 | L2/L3 multi-gold metric definitions are contested by a reviewer | Low | Low | All three metrics (Hit@K / AllGold@K / PrimaryGold@K) are standard IR variants. Define them precisely in §3 of the cross-app section with citations. |
| 14 | Graded-difficulty curve is NOT monotone (e.g., L2 < L3 unexpectedly) | Medium | Low | This is informative either way. Investigate the violation; if real, report it as a finding about which compositions stress the cascade more than expected. Don't force monotonicity by cherry-picking scenarios. |
| 15 | Multi-fault scenario coverage in memory is sparse (few past tickets describe two-fault incidents) | **HIGH** | Medium | By construction, the V2 humanizer generates one ticket per fault component. So a two-fault episode contributes TWO tickets to memory, each describing one fault. This means the multi-gold retrieval task is well-defined; risk is mostly about whether reviewers consider this a fair test. Document the construction clearly. |

---

## 15. Go / no-go checklist

Before kicking off Phase 4 (full collection), confirm:

```
[ ] Phase 0-2 infrastructure complete and reviewed
[ ] Phase 3 pilot ran; feature-column compatibility check passed (or known deltas documented)
[ ] GCP VM provisioned (e2-standard-16) with sufficient quota
[ ] ~20 GB free under data/ on the VM
[ ] Qwen 3.6 35B-A3B in LM Studio ready for post-collection humanize + extract + agent
[ ] Neo4j running and accessible from the VM
[ ] Charter §17 change-log entry locking cross-app scope (see §16 below)
[ ] Existing OB v5-large dataset and locked cascade artifacts NOT modified (read-only during cross-app work)
[ ] Branch `otel-demo-cross-app` created from `master-final-models` (or `master`)
[ ] Stale comparison directories under archive/ where appropriate
```

Once approved:

1. Phase 0–3 (local, ~4 days).
2. Pilot go/no-go check.
3. Phase 4–11 (GCP + local, ~10 days).
4. Updated paper draft → review → submit.

---

## 16. Charter delta

`RESEARCH-CHARTER.md` §14 currently lists "Real-Jira ingestion (vs TAWOS reference)" as out of scope, and §15 risk row mentions cross-app generalization only in passing. We need a small, explicit re-charter entry locking the cross-app scope. Append to `RESEARCH-CHARTER.md`:

```markdown
## 17. Cross-app validation (added 2026-06-08)

**Scope addition:** Cross-app evaluation on the OpenTelemetry Demo
(Astronomy Shop) is in scope as a single external-validity test, per the
plan in `docs5/00-otel-demo-cross-app-plan.md`.

**What this changes:**
- §5 (system) — unchanged; cascade is dataset-agnostic.
- §7 (datasets) — adds a second locked corpus on the OTel Demo. The OB v5-large corpus remains frozen and primary.
- §8 (panel) — unchanged; same locked pipelines run on the second dataset.
- §9 (metrics) — unchanged.
- §13 (paper outline) — adds §6.5 "Cross-app generalization" between current §6 and §7.
- §14 (non-claims) — IoT / ThingsBoard generalization is still out of scope.

**What is NOT changing:** the headline claim, the three sub-claims, the
locked OB cascade, or the locked OB dataset.

**Exit criterion:** the cross-app section (§6.5) reports Hit@1 / Hit@5 /
MRR / PR-AUC / novel-precision / novel-recall on the OTel Demo test
split under both zero-shot and L1-retrained settings, with bootstrap
CIs and per-stratum breakdowns.
```

This re-charter is non-destructive and reversible — if the cross-app result is too weak to support the claim, the OTel Demo work simply doesn't make the paper, and the original charter stands.

---

## 17. Open questions

These are decisions to make before / during execution. Listed here so they don't get lost.

1. **Vendor at which OTel Demo tag?** Latest stable is fine, but pin it explicitly in `kustomization.yaml`. Verify the tag includes the flagd fault flags we depend on.
2. **Do we use OTel Demo's bundled Jaeger / Grafana / OpenSearch, or run our existing Loki + Tempo + Prometheus stack against OTel Demo's services?** Recommend: **our existing stack.** OTel Demo can emit OTLP to any collector, and reusing our Loki/Tempo/Prom stack means no changes to `export-telemetry-window.ps1`.
3. **Are the existing 110 OB distractors still appropriate for OTel Demo's G6-equivalent?** The TAWOS-derived 60 are cross-architecture by design. The 25 in-arch and 25 cross-arch are OB-shaped. Document this and accept; alternative is minting OTel-shaped distractors, which violates §8.3.
4. **Decision on chaos-mesh installation in the lab.** If it's not already running on the GCP VM, decide whether to install it now (4 scenarios use it) or skip network families in v1.
5. **Does the humanizer need a "Kafka engineer voice" tweak, or does the existing engineer voice work?** Resolve during Phase 5 authoring of the Kafka symptom map.
6. **Do we run the cascade with the OTel test windows mixed into the OB memory (single combined corpus), separately (two independent evaluations), or both?** Recommend: **separately** for the cleanest cross-app claim. A combined-corpus experiment is a possible follow-up but isn't the primary deliverable.
7. **Branch strategy.** Cut from `master-final-models` (which has the locked TCH) to preserve the regression baseline. Alternatively, cut from `master` and pull in the G-series. Decide before Phase 0.

---

## 18. Memory pointers

- [[project-research-charter-locked]] — the binding scope
- [[project-tch-cascade-design]] — the cascade we're transferring
- [[project-g-series-outcomes]] — which G-phases we're skipping vs running on OTel
- [[reference-code-layout]] — where collection / humanizer / cascade code lives
- [[reference-final-artifacts]] — locked OB outputs (read-only during cross-app work)
- [[reference-per-run-artifacts]] — per-run JSONL schema we must match
- [[reference-derived-feature-columns]] — the 94 numeric columns we must reproduce
- [[project-trainticket-cross-app]] — the deferred Train-Ticket alternative
- [[project-jira-humanizer-redesign-tawos]] — humanizer voice / length targets we apply to OTel too
- [[reference-tawos-mysql]] — source of the 60 cross-arch distractors we reuse
- [[reference-docs-map]] — docs navigation

---

*Last updated 2026-06-08. This plan is for review only — once approved via §15 go/no-go, execution starts at Phase 0.*
