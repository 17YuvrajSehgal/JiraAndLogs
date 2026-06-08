# OTel Demo Implementation — Status

**Last updated:** 2026-06-08
**Branch:** `otel-demo-cross-app` (cut from `master-final-models`)
**Parent plan:** `docs5/01-otel-demo-implementation-plan.md`

---

## Status overview

| Phase | Status | Commit | Summary |
|---|---|---|---|
| 0a — Deployment overlay | DONE | `18d86b4` | helm-values, collector config, namespace, install script, charter §17 |
| 0b — Namespace + chaos-mesh + ServiceMonitor | FOLDED INTO 0a | — | namespace included in 0a; chaos-mesh deferred per §10.3 resolution |
| 1a — Service catalog refactor | DONE | `863ccdd` | YAML catalogs + ServiceCatalog loader + extractor.py additive opt-in |
| 1b — New fault primitives | DONE | `44cc189` | `Flagd` primitive (network families deferred to chaos-mesh, PausePod dropped) |
| 1c — Multi-fault orchestration | DONE | `d818c9f` | Concurrent / cascade / compound; sidecar JSON components |
| 1d — Scenario YAMLs + run plans | **IN PROGRESS** | — | Representative subset (11 scenarios + 1 pilot plan + 1 corpus manifest); see below |
| 2 — Pilot | NOT STARTED | — | Requires running cluster |

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
