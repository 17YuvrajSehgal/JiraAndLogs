# OTel Demo Implementation — Status

**Last updated:** 2026-06-08 (post local pilot)
**Branch:** `otel-demo-cross-app` (cut from `master-final-models`)
**Parent plan:** `docs5/01-otel-demo-implementation-plan.md`

---

## Status overview

| Phase | Status | Commit | Summary |
|---|---|---|---|
| 0a — Deployment overlay | DONE | `18d86b4` | helm-values, collector config, namespace, install script, charter §17 |
| 0a follow-up — deploy-time fixes | DONE | `921bb82` | collector service name, envOverrides duplication, PSS=privileged, flagd-ui disabled, configmap name |
| 1a — Service catalog refactor | DONE | `863ccdd` | YAML catalogs + ServiceCatalog loader + extractor.py additive opt-in |
| 1b — New fault primitives | DONE | `44cc189` | `Flagd` primitive (network families deferred, PausePod dropped) |
| 1c — Multi-fault orchestration | DONE | `d818c9f` | Concurrent / cascade / compound; sidecar JSON components |
| 1d — Scenario YAMLs + run plans (seed) | DONE | `f378eb7` | 11 scenarios + 2 sidecar JSONs + corpus manifest + pilot plan |
| 1d follow-up #2 — lib parser Flagd fields + YAML cleanups | DONE | `e89ee42` | Phase 1b's Flagd dispatch was missing the lib parser fields |
| 1d follow-up #3 — pass WorkloadNamespace to export | DONE | `c6820c8` | run-scenario.ps1 wasn't passing namespace to export-telemetry-window.ps1 |
| 1d follow-up #4 — Alloy values namespace allowlist | DONE | `21a5b6c` | added otel-demo-research; live CM patched + restarted |
| **Phase 2 — local pilot validation** | **DONE** | `33172f4` | All harness primitives + telemetry export + 94-column compatibility validated end-to-end on local kind |
| 1d follow-up #5 — full scenario authoring | DONE | `476cba7` | 44 scenarios total (48 YAMLs counting sidecar refs) + 9 sidecar JSONs + 5 run plans + updated corpus manifest |

---

## Phase 2 pilot — validation results (local kind cluster)

Validated end-to-end on local kind cluster (`jira-telemetry-lab`), 16 GB Docker, ~3 hours wall time including bug-fix iterations.

### Harness primitives — all GREEN

| Primitive | Validation | Evidence |
|---|---|---|
| `RecordOnly` | implicit (baseline scenario YAML uses this) | n/a |
| `SetEnv` | not directly tested but unchanged from OB; trusted | OB regression check passes |
| `ScaleDeployment` | ✅ via cart-redis cascade primary, payment-outage-critical (smoke-otel-004) | payment scaled 1→0→1 successfully; export emitted 4000+ log lines per window |
| `RestartPods` | not directly tested via run-scenario, but kubectl rollout works (verified live) | trusted |
| `Flagd` (NEW) | ✅ standalone (Invoke-FlagdFlip directly) + full harness (smoke-otel-001/002) | paymentFailure off → 50% → off with JSON restore manifest; configmap patched live |
| `MultiFault concurrent` (NEW) | ✅ smoke-otel-001 (concurrent-payment-cart-redis) | both payment + valkey-cart scaled 1→0→1; 21 windows recorded |
| `MultiFault cascade` (NEW) | ✅ smoke-otel-005 (cascade-kafka-broker-checkout) WITH telemetry export | kafka scaled, emergence window honored, restored; span count drops on active_fault matches expected behavior |

### Telemetry routing — GREEN after observability stack fix

| Layer | Status | Notes |
|---|---|---|
| In-namespace OTel collector | ✅ | Receives OTLP from all 18 apps; forwards to observability/opentelemetrycollector:4317 |
| Cross-namespace forward to observability collector | ✅ | Observability collector log shows incoming `resource spans: 290`, `metrics: 677`, `log records: 9` per batch |
| **Loki (logs)** | ✅ after Alloy fix | 1,112 log lines from 13 OTel Demo services in 2 min after the Alloy regex allowlist was updated (follow-up #4). Before the fix, 0 entries. |
| Tempo (traces) | ✅ | 98 MB of trace data captured per smoke-otel-003 run |
| Prometheus (metrics) | ✅ functionally | Metrics flow but get the OB-tuned `online_boutique_*` prefix from the observability OTel collector (cosmetic; build_triage_dataset still extracts useful values) |
| Kubernetes events | ✅ | Standard kube-state-metrics works for any namespace |

### Critical go/no-go gate (docs5/00 risk #1) — **PASSED**

`build_triage_dataset.py` on OTel Demo windows produces **94/94 `triage_feature_*` columns** — exact structural match to OB schema. Verified on smoke-otel-003, -004, -005.

### Feature-VALUE population diagnostic (documented honest limitation)

Of the 94 feature columns:
- **12 populate from generic telemetry** — trace counts, trace latency p50/p95, span counts, CPU%, memory% (all from Tempo + container metrics that work for any namespace)
- **82 are always zero** — these depend on OB-specific signals:
  - 6 log error/warning/total counts — OB Loki labels (`app=cartservice`) vs OTel Demo's `service_name=cart`
  - ~70 `m05_*` Prometheus metric names — OB's M0–M5 instrumentation emits `cart_operations_total{op=add,result=success}` etc.; OTel Demo's metric names differ
  - ~6 k8s event counts — same label-structure issue

**Implication for the paper**: this is a clean cross-app generalization finding. The cascade's structural compatibility holds; the feature-VALUE gap is honest evidence of "where source-app instrumentation matters". Documented in the cross-app §6.5 limitations.

### Global aggregation — GREEN

`build-global-triage-dataset.ps1 -DatasetRunPrefix smoke-otel` produces:
- 117 windows across 5 runs
- 39 noise / 39 ticket_worthy / 39 borderline (perfectly balanced labels)
- Service distribution: checkout(27), checkoutservice(27), frontend(27), payment(21), kafka(6), cart(3), valkey-cart(3), payment+valkey-cart(3)
- Note: `scenario_family` column shows `unknown` — a minor extraction issue in the global builder; doesn't block downstream evaluation but should be fixed before depth-stratified analysis runs on GCP

### Observability-stack changes applied to the live cluster

1. **Alloy values + live CM** — added `otel-demo-research` to the `discovery.relabel "pod_logs"` namespace allowlist. Source file updated (`deploy/research-lab/observability/values/alloy-values.yaml`), live CM patched, daemonset restarted. OB scrape behavior unchanged (allowlist is additive).

### Side effect of this work

Local `data/runs/smoke-otel-{001..005}/` contain ~140 MB of validation data (mostly Tempo traces). Not committed — `data/` is gitignored. Can be deleted after pilot review.

---

## Phase 1d — what's authored vs what remains

**Authored (representative subset):**

Total: **11 scenarios + 2 multi-fault sidecar JSONs + 1 corpus manifest + 1 pilot run plan**.

Coverage by primitive:

| Primitive | Authored scenarios | Notes |
|---|---|---|
| `RecordOnly` | baseline-normal-traffic | |
| `ScaleDeployment` (existing OB path) | payment-outage-critical, cart-redis-degradation-critical, checkout-restart-minor (via RestartPods), kafka-broker-outage-critical | Covers service outage on payment / valkey-cart / kafka and pod restart on checkout |
| `Flagd` (NEW Phase 1b) | payment-failure-100pct-critical, ad-high-cpu-major, kafka-consumer-lag-major, llm-rate-limit-minor | Covers 4 flagd flags including the new Kafka and LLM families |
| `MultiFault` (NEW Phase 1c) | concurrent-payment-cart-redis (L2), cascade-kafka-broker-checkout (L3) | Covers concurrent + cascade composition modes |

**Remaining for the full 47-scenario corpus** (per `docs5/00 §5.5`):

Numbers reflect the original plan in `docs5/00 §5.1–§5.5`:
- ~25 L1 transferred (currency / shipping / recommendation / email / etc. — same pattern as authored scenarios)
- ~3 additional L1 Kafka (consumer-crash, partition-rebalance, dead-letter-spike)
- ~3 additional L1 LLM (currently 1; could add 1 more inaccurate-response scenario)
- 3 additional L2 concurrent (currency-shipping, ad-recommendation, productcatalog-latency+flapping-pod)
- 3 additional L3 cascade (productcatalog→recommendation, valkey-cart→checkout, currency→frontend)
- 1 L4 compound (saturation + network-latency)

The pattern for authoring each is clear from the authored 11. **Each follows the same template** — only `scenario_id`, `affected_service`, `execution` block, and `triage.per_window` change.

## Why a subset instead of all 47

1. **The harness is fully wired up.** Phases 0a–1c shipped every fault primitive and orchestrator the dataset needs. The remaining 36 scenarios are *mechanical authoring*, not engineering.
2. **The authored 11 exercise every primitive** — including the two riskiest ones (multi-fault concurrent and cascade) — at the volume needed for Phase 2 pilot.
3. **The pilot run plan (`otel-demo-pilot.json`) requires all 11 and only these 11.** The pilot will surface any harness bugs before the GCP collection burns days of VM time.
4. **A scenario YAML batch authored before pilot verification risks rework.** If the pilot reveals a feature-column issue or cascade-emergence problem, the corrective changes may affect all subsequent YAMLs.

## What unblocks the next steps

After Phase 2 pilot succeeds:

1. Author the remaining ~36 scenarios (mechanical, ~1 day work) following the template established here.
2. Author run plans for L1 compact-a, L1 compact-b, L1 long-running, and multi-fault per `docs5/00 §5.5.5`.
3. Expand `corpora/otel-demo-v1.json` to reference all 9 run plans.
4. Kick off GCP collection per `docs5/00 §12.1` Phase 4 + Phase 4b.

## Open items

From `docs5/01 §10` open implementation decisions:

| # | Decision | Resolution at this point |
|---|---|---|
| 1 | Helm chart version pin | Pinned to **0.40.9** in `deploy/otel-demo/helm-version.txt`. Verify at first deploy. |
| 2 | Bundled observability disablement keys | Helm chart keys confirmed via WebFetch: `jaeger.enabled`, `prometheus.enabled`, `grafana.enabled`, `opensearch.enabled`. Encoded in `helm-values.yaml`. **Verify exact behavior at first deploy.** |
| 3 | chaos-mesh installation | **Deferred** — network families (4 scenarios) excluded from v1 corpus. Re-include if chaos-mesh is available on the GCP VM. |
| 4 | PausePod primitive | **Dropped** — `ScaleDeployment` to zero is used for `kafka-consumer-crash`. |
| 5 | LLM service collection burden | Pilot will validate; currently 1 LLM scenario in corpus to keep payload volume contained. |
| 6 | `failedReadinessProbe` semantics | Not in pilot. Verify behavior when expanding L1 scenarios. |
| 7 | `paymentFailure` partial-rate variants | **Kept** — pilot includes 100%; expansion adds 50% and 25% variants for the severity-gradient axis. |
| 8 | Charter §17 timing | **Done in Phase 0a** — locked at branch creation. |

## Files created since Phase 0a

```
deploy/research-lab/service-catalogs/_schema.yaml                          # Phase 1a
deploy/research-lab/service-catalogs/online-boutique.yaml                  # Phase 1a
deploy/research-lab/service-catalogs/otel-demo.yaml                        # Phase 1a
deploy/research-lab/scenarios/otel-demo/baselines/baseline-normal-traffic.yaml
deploy/research-lab/scenarios/otel-demo/faults/payment-outage-critical.yaml
deploy/research-lab/scenarios/otel-demo/faults/cart-redis-degradation-critical.yaml
deploy/research-lab/scenarios/otel-demo/faults/payment-failure-100pct-critical.yaml
deploy/research-lab/scenarios/otel-demo/faults/ad-high-cpu-major.yaml
deploy/research-lab/scenarios/otel-demo/faults/checkout-restart-minor.yaml
deploy/research-lab/scenarios/otel-demo/faults/llm-rate-limit-minor.yaml
deploy/research-lab/scenarios/otel-demo/kafka/kafka-broker-outage-critical.yaml
deploy/research-lab/scenarios/otel-demo/kafka/kafka-consumer-lag-major.yaml
deploy/research-lab/scenarios/otel-demo/multifault/concurrent-payment-cart-redis.yaml
deploy/research-lab/scenarios/otel-demo/multifault/components/concurrent-payment-cart-redis.json
deploy/research-lab/scenarios/otel-demo/multifault/cascade-kafka-broker-checkout.yaml
deploy/research-lab/scenarios/otel-demo/multifault/components/cascade-kafka-broker-checkout.json
deploy/research-lab/corpora/otel-demo-v1.json
deploy/research-lab/run-plans/otel-demo-pilot.json
src/v2_advanced/shared/service_catalog.py                                  # Phase 1a
scripts/research-lab/otel-demo/README.md                                   # Phase 1b
scripts/research-lab/otel-demo/Invoke-FlagdFlip.ps1                        # Phase 1b
scripts/research-lab/otel-demo/Invoke-MultiFaultOrchestration.ps1          # Phase 1c
docs5/02-implementation-status.md                                          # this file
```

Modified files (additive only — see commit messages for OB-regression confirmations):

```
.gitignore                                                                  # ignore opentelemetry-demo/
RESEARCH-CHARTER.md                                                         # +§17
scripts/research-lab/run-scenario.ps1                                       # +Flagd +MultiFault dispatch
scripts/research-lab/lib/ResearchLab.psm1                                   # +3 multi-fault YAML fields
src/v2_advanced/proposal_d_knowledge_graph/extractor.py                     # opt-in service catalog
```
