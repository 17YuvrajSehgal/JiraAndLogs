# TrainTicket Migration Plan

**Created:** 2026-05-23
**Owner:** Yuvraj
**Status doc:** sibling of `dataset-todo.md`. Where that doc grows the
Online Boutique dataset, this one stands up the same kind of dataset
on TrainTicket so the project has cross-app generalization evidence.
**Source repo:** `train-ticket/` (cloned 2026-05-23 from
FudanSELab/train-ticket).

---

## Why TrainTicket, and what we're keeping vs replacing

TrainTicket is the most-cited microservice benchmark in fault-injection
and AIOps research. It buys us:

- **47 services** (vs Boutique's 11) — much richer dependency graph.
- **4 languages** (Java/Spring Boot + Node/Express + Python/Django +
  Go/Webgo) — log shapes, log levels, stack-trace formats differ per
  service. Real generalization test for the log-template miner.
- **2 databases** (MySQL clusters + MongoDB) plus Redis and Nacos service
  discovery — Boutique only stresses Redis.
- **Pre-built Istio fault injection** (`deployment/fault-inject-deployment/`)
  — we don't need to install chaos-mesh urgently to get going on
  TrainTicket; can iterate from there.

What we **keep from the existing project**:

| Asset                                       | Reuse strategy                                            |
| ------------------------------------------- | --------------------------------------------------------- |
| `src/loganalyzer`, `src/logsense`, `src/jira_features`, `src/comparison` | Completely app-agnostic. Zero changes. |
| The pipeline scripts in `scripts/research-lab/` (`start-dataset-run`, `run-scenario`, `export-telemetry-window`, `collect-dataset-corpus`, `validate-*`, `build_*_dataset`) | Mostly app-agnostic. Need only the LoQL/Tempo queries and scenario-file paths re-pointed at TrainTicket. |
| Triage contract + global dataset schema     | Identical - `global-triage-examples.jsonl`, `jira-memory-corpus.jsonl`, `window-memory-matchings.jsonl`, `triage-feature-columns.json`. |
| The 28 production-safe `triage_feature_*` columns | Same definitions; the EXTRACTION re-reads new service / span / log shapes but the column list does not change. |

What we **replace for TrainTicket**:

| Asset                                       | TrainTicket version                                       |
| ------------------------------------------- | --------------------------------------------------------- |
| Online Boutique helm overlay                | TrainTicket's `make deploy` + a new Helm overlay we author |
| `SCENARIO_FAMILIES`, `FAULT_TYPE_COMPATIBILITY` in `triage_labels.py` | Rewritten for the train-booking domain |
| 24 scenario YAMLs in `deploy/research-lab/scenarios/faults/` | Re-authored against TrainTicket service names |
| Shadow Jira templates (e-commerce summaries) | Train-booking domain templates                            |
| Loadgenerator (Boutique's Locust-style) | Adapted from TrainTicket's existing `script/` and Locust scripts in the wiki |
| The 13 scenario families                    | New TrainTicket-shaped taxonomy (booking-flow, payment, search, etc.) |

---

## Cluster sizing (the realistic constraint)

The 47 services + MySQL + MongoDB + Nacos + observability overlay
**do not fit on the same e2-standard-8 (32GB) that ran v4-large for
Boutique**. Quick math from
`deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample`:

| Component                   | Memory request | Memory limit |
| --------------------------- | -------------: | -----------: |
| Single ts-* service          |          300Mi |        2000Mi |
| 47 services                  |        ~14 GiB |       ~94 GiB |
| MySQL all-in-one             |        ~1-2 GiB |       ~4 GiB  |
| MongoDB                      |        ~500 Mi |        ~2 GiB  |
| Nacos                        |        ~1 GiB  |       ~2 GiB  |
| Redis                        |        ~200 Mi |       ~500 Mi |
| Observability (Loki+Tempo+Prom+Alloy+Grafana) | ~2-3 GiB | ~6 GiB |
| **Realistic floor**         |     **~19 GiB requests** |   **~110 GiB limits** |

Recommendation: **e2-standard-16 (64GB) + 1TB pd-balanced** for
TrainTicket collection. Locally, a workstation with **≥48GB RAM**
is the minimum for an interactive smoke test.

If we want all 47 services with `--independent-db` (each service gets its
own MySQL StatefulSet), the floor doubles. **For the dataset collection
we use `make deploy` (all-in-one MySQL)**, not `--independent-db`.

---

## Risks worth calling out before committing

1. **TrainTicket image freshness.** The `codewisdom/ts-*` Docker images on
   Docker Hub are unmaintained on some forks. May need to `make package`
   + `make build-image` ourselves (47 Java services × ~30-90s each ≈
   30-90 min cold build).
2. **Java service startup time.** Each Spring Boot pod takes 60-120s to
   become ready. Cold-start of the whole cluster is ~5-10 min, vs
   ~1 min for Boutique. The collection pipeline's window
   timestamps need readiness gates accounting for this.
3. **SkyWalking vs OTel.** The shipped tracing is SkyWalking, but our
   builders consume OTel/Tempo. Two options - either swap in the Spring
   Boot OTel auto-instrumentation agent (clean, ~1 dev day per language)
   or bridge SkyWalking → OTel via the SkyWalking OAP receiver (less
   clean, faster).
4. **Nacos coupling.** Service discovery via Nacos means restarting a
   service requires the Nacos registry to expire the old endpoint. The
   `pod-restart` fault has different observable timing than on Boutique.
5. **Istio dependency for built-in fault injection.** The shipped
   virtual-services-fault.yaml requires Istio. If we don't want Istio
   we re-implement those faults via chaos-mesh (which we'll need
   anyway for Phase D11 from `dataset-todo.md`).

---

## Phase T0 - Feasibility spike (2-3 days, before committing)
**Goal:** prove TrainTicket can run end-to-end on a kind cluster with
our observability overlay, and we can pull a single useful telemetry
window from it. Do this BEFORE committing to T4-T8 multi-week work.

- [x] **T0.1** Kind cluster stood up locally with the existing
      `deploy/research-lab/kind-config.yaml` (3 nodes). Docker Desktop
      memory ceiling: 15GiB (not enough for all 47 services locally;
      sized for cloud VM only - see VM runbook).
- [ ] **T0.2** Build TrainTicket from source. Run
      `make package && make build-image Repo=local Tag=v1` and time
      how long the 47-service Maven + Docker build takes on our laptop.
      (Deferred: prebuilt `codewisdom/ts-*:1.0.0/1.0.1` images verified
      to pull cleanly from Docker Hub. Source build only needed if those
      images go away.)
- [~] **T0.3** Deploy: `scripts/research-lab/apply-trainticket.ps1`
      authored. Locally the radondb-mysql HA chart from the bundled
      train-ticket repo crashloops on Docker Desktop kind (xenon
      coordinator needs Linux storage features); `-LocalSmokeTest` and
      `-SkipMysql` flags added as workarounds, and the script is
      expected to work end-to-end on the GCP Ubuntu VM. Full 47-pod
      Ready test deferred to the VM run.
- [ ] **T0.4** Curl the UI at `http://[node-ip]:32677`. Do one end-to-end
      booking flow manually. Confirm at least one booking succeeds.
      (Deferred to VM smoke.)
- [x] **T0.5** Observability overlay installed and verified. Alloy
      `namespace-allowlist` regex extended to include `trainticket`
      (commit modifies `deploy/research-lab/observability/values/alloy-values.yaml`).
- [x] **T0.6** End-to-end `export-telemetry-window.ps1` against the
      trainticket namespace verified. A stub `ts-loglines-test`
      deployment emitting JSON logs produced 15 entries in the exact
      window query, 179 entries in the service-context query, with
      labels `{namespace=trainticket, app=ts-loglines-test, container,
      pod, ...}` exactly matching what the boutique pipeline expects.
      `validate-dataset-run.ps1` returned 0 errors. The query shape
      `{namespace=, app=}` is fully reusable for train-ticket without
      code changes; only the alloy allowlist needed extending.
- [ ] **T0.7** Try one fault on a real train-ticket service (e.g.
      `kubectl scale deploy/ts-auth-service --replicas=0`). Deferred to
      VM, since the radondb-mysql + Java services don't all fit on the
      16GB Docker Desktop ceiling.

**Acceptance:** all 47 pods Ready; one booking succeeds; we have at
least one telemetry window from TrainTicket that our existing
`build_triage_dataset.py` can ingest without crashing. If T0.7 doesn't
produce a clear fault signature, T1-T8 aren't worth doing.

**Status:** the pipeline-side scaffolding is done (T0.1, T0.5, T0.6).
The application-side smoke (T0.2-T0.4, T0.7) needs the GCP VM because
of laptop memory + Docker Desktop storage constraints. See
`docs/gcp-trainticket-vm-runbook.md`.
**Blocks:** every other Phase T.

### Quick reference - what's now wired up

| Asset | Path | Notes |
| --- | --- | --- |
| Namespace | `deploy/research-lab/namespaces.yaml` | adds `trainticket` |
| Alloy allowlist | `deploy/research-lab/observability/values/alloy-values.yaml` | `online-boutique-research\|observability\|trainticket` |
| Deploy script | `scripts/research-lab/apply-trainticket.ps1` | helm install of mysql / nacos / rabbitmq / ts-mysql + secret generation + svc/deploy apply |
| Collection wrapper | `scripts/research-lab/collect-trainticket-run.ps1` | runs the 6-scenario sequence end-to-end |
| Starter scenarios | `deploy/research-lab/scenarios/trainticket/` | 9 baseline + fault YAMLs |
| Traffic profile | `deploy/research-lab/scenarios/trainticket/traffic-profiles/trainticket-booking-mix.yaml` | |
| Run plans | `deploy/research-lab/run-plans/trainticket-{control-baseline-only,compact-a,compact-b}.json` | 3 plans |
| Corpus | `deploy/research-lab/corpora/dataset-trainticket-pilot.json` | 6 runs, ~270 windows |
| Triage families | `scripts/research-lab/triage_labels.py` | 9 new `tt-*` family entries; scenario YAML lookup walks the trainticket/ subtree |
| VM runbook | `docs/gcp-trainticket-vm-runbook.md` | end-to-end recipe for `e2-standard-16` Ubuntu VM |

---

## Phase T1 - Observability overlay (3-5 days)
**Goal:** unify TrainTicket's telemetry into the same Loki / Tempo /
Prometheus pipeline our builders read from. TrainTicket ships an
alternative stack (SkyWalking, EFK, Grafana) - we replace it.

- [ ] **T1.1** Add an OTel agent to every Java service via the Spring
      Boot OTel auto-instrumentation agent. Pin
      `opentelemetry-javaagent.jar` 1.x in a base image overlay, set
      `OTEL_EXPORTER_OTLP_ENDPOINT` to Alloy. Document in
      `docs/trainticket-instrumentation.md`.
- [ ] **T1.2** For Python (`ts-avatar-service`, ...): add the OTel
      Python distro and `opentelemetry-instrument` wrapper.
- [ ] **T1.3** For Node (`ts-ui-dashboard`, ...): add the
      `@opentelemetry/auto-instrumentations-node` package.
- [ ] **T1.4** For Go (`ts-voucher-service`): add otelhttp +
      otelgrpc and link in main.
- [ ] **T1.5** Switch every service's logger to JSON output where
      possible. Spring Boot: add `logstash-logback-encoder`. Python:
      `python-json-logger`. Node: `pino` JSON output. This makes our
      JSON-aware template miner work without changing code in
      `src/logsense/templates/miner.py`.
- [ ] **T1.6** Loki + Tempo pipeline test: a synthetic booking call
      should appear as one trace with N spans, and Loki should index
      the logs from each span's service. Verify trace_id is in the log
      lines.
- [ ] **T1.7** Prometheus scrape config for TrainTicket's existing
      `/actuator/prometheus` endpoints on every Spring Boot service.
      Adds dozens of per-service business metrics without code changes.

**Acceptance:** for an end-to-end booking, we can pull the full trace
from Tempo, all logs from Loki filtered by trace_id, and per-service
HTTP / JVM metrics from Prometheus.

**Status:** not started.
**Blocks:** T4 (scenarios), T6 (Jira).

---

## Phase T2 - Service inventory + family taxonomy (1-2 days)
**Goal:** the equivalent of Boutique's
`scripts/research-lab/triage_labels.py` `SCENARIO_FAMILIES` constant
for the 47 TrainTicket services. Without this, every later phase has
to invent ad-hoc service groupings.

- [ ] **T2.1** Walk the TrainTicket service graph (`docs/trainticket-service-map.md`
      - we write this). Cluster services by domain:
      - **booking-flow:** `ts-preserve-service`, `ts-preserve-other-service`,
        `ts-travel-service`, `ts-travel-plan-service`, `ts-travel2-service`,
        `ts-order-service`, `ts-order-other-service`
      - **search-flow:** `ts-station-service`, `ts-route-service`,
        `ts-route-plan-service`, `ts-train-service`, `ts-basic-service`
      - **payment-flow:** `ts-payment-service`,
        `ts-inside-payment-service`, `ts-price-service`,
        `ts-consign-price-service`
      - **user-auth:** `ts-auth-service`, `ts-user-service`,
        `ts-security-service`, `ts-verification-code-service`
      - **admin-tools:** all `ts-admin-*-service`
      - **food-delivery:** `ts-food-service`, `ts-food-delivery-service`,
        `ts-station-food-service`, `ts-train-food-service`
      - **post-booking:** `ts-cancel-service`, `ts-rebook-service`,
        `ts-execute-service`, `ts-consign-service`, `ts-delivery-service`,
        `ts-assurance-service`
      - **notification + voucher:** `ts-notification-service`,
        `ts-news-service`, `ts-voucher-service`, `ts-contacts-service`
      - **front-tier:** `ts-gateway-service`, `ts-ui-dashboard`
      - **support:** `ts-config-service`, `ts-avatar-service`,
        `ts-ticket-office-service`, `ts-seat-service`, `ts-common`
- [ ] **T2.2** Author the new `SCENARIO_FAMILIES` table for TrainTicket
      in `triage_labels.py` (or behind an `--app trainticket` flag so
      Boutique and TrainTicket can coexist in the codebase). Target:
      9-10 family slots, mapping the clusters above.
- [ ] **T2.3** `FAULT_TYPE_COMPATIBILITY` updates - mostly the same fault
      taxonomy applies; just confirm cross-service compatibility classes
      stay sensible for the new taxonomy.

**Acceptance:** every TrainTicket service is in exactly one family. The
family list is documented and matches the application's actual
booking flow.

**Status:** not started.
**Blocks:** T4 (scenarios).

---

## Phase T3 - Loadgenerator + traffic profile (2-3 days)
**Goal:** TrainTicket needs realistic continuous traffic for the
collection windows to mean anything. Boutique ships a Locust
loadgenerator. TrainTicket has Locust scripts in
`old-docs/wiki-files/Loadgen` but they're not packaged for k8s.

- [ ] **T3.1** Package the existing TrainTicket Locust scripts as a
      `ts-loadgenerator` k8s deployment. Drives end-to-end booking
      flows continuously. Target: 5-10 RPS sustained.
- [ ] **T3.2** Author a `baseline-trainticket-mix` traffic profile in
      `deploy/research-lab/scenarios/traffic-profiles/`, mirroring
      Boutique's `baseline-checkout-mix.yaml`. Defines weighted
      mix: 50% search, 30% booking, 10% admin, 10% cancel/rebook.
- [ ] **T3.3** Confirm under sustained load the cluster is stable
      for 10+ minutes without OOMKills.

**Acceptance:** a 10-min baseline run produces >= 800 traces in Tempo
with >= 95% success rate. Cluster does not OOMKill any pod.

**Status:** not started.
**Blocks:** T4 (faults need a stable baseline to perturb).

---

## Phase T4 - Scenario catalog (4-5 days, the bulk of the porting work)
**Goal:** port Boutique's 24 scenario YAMLs + the 8 deferred v4 families
+ Phase D11 (system) + Phase D12 (orphan) to TrainTicket service names
and fault mechanisms.

For each family in the new TrainTicket taxonomy (Phase T2), author 2-3
scenarios. Reuse the Boutique scenario template at
`deploy/research-lab/scenarios/scenario-template.yaml`.

- [ ] **T4.1** Port direct equivalents:
      - `ts-auth-service-unavailable-critical` (≈ paymentservice-unavailable)
      - `ts-mysql-degradation-critical` (≈ cart-redis-degradation)
      - `ts-order-service-pod-restart-major`
      - `ts-station-service-bad-config-critical`
      - `ts-travel-service-latency-major`
      - `ts-preserve-service-unavailable-critical`
      - `ts-payment-service-flake-recovers`
      - `ts-gateway-service-cpu-nearmiss`
      - `ts-ui-dashboard-pod-restart-major`
- [ ] **T4.2** TrainTicket-specific scenarios that have no Boutique
      analog:
      - `ts-mongodb-slow-saturation` (TT uses MongoDB; Boutique doesn't)
      - `ts-nacos-registry-blip-major` (service discovery fault)
      - `ts-multi-mysql-replica-lag` (only available in `--independent-db`
        mode; defer to v5.2)
      - `ts-cancel-rebook-deadlock-major` (cross-service transaction
        fault unique to TT's booking domain)
- [ ] **T4.3** Port the 8 v4-deferred families from `dataset-todo.md`
      Phase D1: `post-deploy-churn`, `recovered-in-window`,
      `single-pod-restart-healthy-replication`, `third-party-blip`,
      `scheduled-job-spike`, `latency-near-miss-partial-recovery`,
      `flapping-pod`, `slow-leak-saturation`. TrainTicket's larger
      service surface gives us much more room to author these.
- [ ] **T4.4** Port system-level faults from `dataset-todo.md` Phase
      D11 (network / disk / time / pod-kill / kubelet / etcd). Use
      Istio's built-in fault injection where natural; chaos-mesh for
      the rest.
- [ ] **T4.5** Author orphan-fault scenarios from `dataset-todo.md`
      Phase D12 - same `produces_jira_ticket: false` mechanism, applied
      to TT scenarios. Particularly easy on TT because the 47-service
      surface gives many "this service has never been ticketed" picks.
- [ ] **T4.6** Each scenario YAML carries a filled `triage` block per
      v4 schema (`triage_label`, `severity`, `components`,
      `reason_class`, `is_hard_case` markers).

**Acceptance:** at least 30 TrainTicket scenarios authored, every
SCENARIO_FAMILIES family covered by >= 2 scenarios, every scenario
passes the v4 triage-block schema validator.

**Status:** not started.

---

## Phase T5 - Pipeline integration (2-3 days)
**Goal:** the existing PowerShell scripts in `scripts/research-lab/`
work on TrainTicket without forking.

- [ ] **T5.1** Add an `-App` parameter (default `online-boutique`) to
      `start-dataset-run.ps1`, `run-scenario.ps1`,
      `export-telemetry-window.ps1`, `collect-dataset-corpus.ps1`.
      When `-App trainticket`, scripts read from
      `deploy/research-lab/scenarios/trainticket/` instead of the
      Boutique path and target the TrainTicket namespace.
- [ ] **T5.2** Loki queries in `export-telemetry-window.ps1` change
      `app=` label selectors to TrainTicket's actual label scheme.
      Confirm the existing query shape still works.
- [ ] **T5.3** Tempo trace search queries: TrainTicket's span attributes
      may not include the same keys as Boutique. Audit the queries in
      `export-telemetry-window.ps1` and parametrize per app.
- [ ] **T5.4** Prometheus metric names: `/actuator/prometheus` exposes
      Spring-Micrometer names like `http_server_requests_seconds_count`
      instead of Boutique's `rpc_*` style. Update the
      `numeric_features_from_raw` extractor to accept either source -
      OR live with the existing dead-Prometheus-query handling that
      already gracefully zeroes-out missing metrics.
- [ ] **T5.5** Smoke test: run one scenario end-to-end. Confirm
      `validate-dataset-run.ps1` passes and
      `validate-run-feature-distribution.py` produces a sane report.

**Acceptance:** `collect-dataset-corpus.ps1 -App trainticket -CorpusFile
... -Quick` runs at least 3 scenarios end-to-end with zero failures.

**Status:** not started.
**Blocks:** T7 (collection).

---

## Phase T6 - Shadow Jira templates for the train-booking domain (1-2 days)
**Goal:** the Boutique shadow-Jira generator produces e-commerce-flavoured
incident reports ("Customer checkout path seeing elevated failures").
TrainTicket needs domain-appropriate variants ("Ticket purchase failing
for high-speed routes").

- [ ] **T6.1** Author 4-5 train-booking summary / description templates
      in `scenario-template.yaml`-style files under
      `deploy/research-lab/scenarios/trainticket/`. Cover: booking
      failures, payment failures, search failures, admin-tool errors,
      post-booking (rebook/cancel) failures.
- [ ] **T6.2** Resolution-notes variants - "Rolled back v2.3.1 deploy"
      / "Restored MongoDB primary" / "Cleared Nacos cache". Realism
      matters for the retrieval research.
- [ ] **T6.3** Hook into `generate-shadow-jira-issues.ps1` by
      template-set name (`-TemplateSet trainticket-booking`).

**Acceptance:** sampling 10 generated Jira issues looks plausible to
a researcher seeing the domain for the first time.

**Status:** not started.

---

## Phase T7 - Pilot collection (1 VM day)
**Goal:** the equivalent of v4-pilot for TrainTicket. Catch the
TrainTicket-specific pipeline bugs before committing to a multi-day
full collection.

- [ ] **T7.1** Author
      `deploy/research-lab/corpora/dataset-trainticket-pilot.json` -
      6 runs: 1 control + 2 booking-flow scenarios + 2 search-flow +
      1 admin-tool.
- [ ] **T7.2** Provision a fresh GCP VM (e2-standard-16 + 1TB disk).
      Update the runbook at `docs/gcp-trainticket-vm-runbook.md`
      (we author this).
- [ ] **T7.3** Run the pilot corpus collection.
- [ ] **T7.4** Run the full Phase 0 + Phase 0.5 comparison reports on
      the pilot. Confirm headline metrics make sense (PR-AUC > rule
      baseline, retrieval recall > 0).

**Acceptance:** 6 TrainTicket runs collected with zero failures,
~~~80 windows, ~~6 Jira issues. Headline metrics roughly mirror
Boutique-v4-pilot proportions.

**Status:** not started.
**Blocks:** T8 (full collection).

---

## Phase T8 - Full TrainTicket collection (4-5 VM days)
**Goal:** dataset large enough for ML/AI training (the actual
deliverable analogous to v4-large on Boutique).

- [ ] **T8.1** Author
      `deploy/research-lab/corpora/dataset-trainticket-large.json` -
      60 runs: 8 control + 22 booking + 14 search + 6 payment + 6 admin
      + 4 system-level fault + 4 orphan-fault. Sized for ~5000 windows
      and ~300 Jira issues.
- [ ] **T8.2** Launch the full collection on the same e2-standard-16 VM.
- [ ] **T8.3** Re-run the Phase 0, Phase 0.5, and (when available)
      Phase 1+ comparison reports against TrainTicket-large.
- [ ] **T8.4** Cross-app evaluation: train every pipeline on
      v5-Boutique-large, test on TrainTicket-large WITHOUT retraining.
      Report the PR-AUC / recall@5 drop. This is the headline number
      that justifies the entire T-track.

**Acceptance:** >= 5000 windows, >= 300 Jira issues, all 9-10 families
covered, validation reports clean.
Cross-app PR-AUC drop reported with paired-bootstrap CIs.

**Status:** not started.

---

## Phase T9 - Cross-app analysis (1-2 days after T8)
**Goal:** turn the cross-app numbers into a paper-grade artifact.

- [ ] **T9.1** Stratified comparison table: per-family PR-AUC on
      Boutique-test vs TrainTicket-test, for every pipeline.
- [ ] **T9.2** Which families generalize best? Which collapse? Which
      services dominate the failure modes?
- [ ] **T9.3** Failure case study set: 5 windows the Boutique-trained
      model gets wrong on TrainTicket, with full evidence text + top
      Jira hits + analyst commentary.
- [ ] **T9.4** Document the result in
      `docs/cross-app-generalization-report.md`.

**Acceptance:** a 2-3 page write-up of cross-app numbers with CIs and
case studies, suitable to drop into a paper as a generalization
section.

---

## Total effort estimate

| Phase | Description                            | Effort                |
| ----- | -------------------------------------- | --------------------- |
| T0    | Feasibility spike                      | 2-3 dev days          |
| T1    | Observability overlay (OTel everywhere) | 3-5 dev days         |
| T2    | Service inventory + taxonomy           | 1-2 dev days          |
| T3    | Loadgen + traffic profile              | 2-3 dev days          |
| T4    | Scenario catalog (30+ scenarios)       | 4-5 author days       |
| T5    | Pipeline integration (-App flag)       | 2-3 dev days          |
| T6    | Shadow Jira templates                  | 1-2 author days       |
| T7    | Pilot collection                       | 1 VM day              |
| T8    | Full TrainTicket collection            | 4-5 VM days           |
| T9    | Cross-app analysis report              | 1-2 dev days          |
| **Total** | **~21-30 dev/author days + ~6 VM days** | |

This **is more expensive than the dataset-todo.md D6 estimate (8-10 dev
days)** because we're authoring all 30+ scenarios from scratch rather
than porting a curated subset. If the goal is purely a cross-app test,
T4 can be cut to 12-15 scenarios (~2 author days) and the total drops
to ~15-20 dev days.

GCP cost estimate: ~$150-200 for e2-standard-16 + 1TB over 6 VM days
(pilot + full collection).

---

## Decision points before starting

1. **OTel vs SkyWalking** (T1). Replacing the shipped SkyWalking with
   OTel is more work but keeps the pipeline single-stack. SkyWalking
   bridge is faster but means our builders learn a second trace format.
   **Recommend OTel - one-time cost amortizes across v5+.**
2. **`make deploy` vs `make deploy DeployArgs="--independent-db"`**.
   The independent-db mode is more production-like but doubles the
   memory floor. **Recommend all-in-one for v5; revisit for v6 if the
   research story needs DB-cluster fault scenarios.**
3. **Istio yes/no**. Istio enables the shipped Virtual Service fault
   injection AND TrainTicket's mesh-level metrics, but adds 1-2GB of
   memory overhead and configuration complexity. **Recommend no
   Istio for v5; do faults via chaos-mesh per `dataset-todo.md` D11.**
4. **Scope of T4**. Full port (30+ scenarios) for a stand-alone TT
   dataset, OR minimal port (12-15 scenarios) for cross-app eval only?
   **Recommend minimal port first; expand if cross-app numbers are
   interesting.**

---

## Realistic recommendation

Given the project state today (v4-large just landed, Phase 1 ML work
not yet started), the right move is:

1. **T0 only this week** - 2-3 day feasibility spike. Confirm
   TrainTicket runs on our infra. Decide go / no-go based on whether
   the smoke test produces clean fault signatures.
2. **If T0 passes**, queue T1+T2+T5 (~6-10 dev days) in parallel with
   `todo.md` Phase 1 (real embeddings) - they share no critical path.
3. **Then T3+T4-minimal+T7+T8 with reduced T4 scope** - target a
   modest TrainTicket-pilot (~1000 windows) as a held-out cross-app
   test set rather than a full retraining corpus. Saves ~10 days vs
   the full plan above.
4. **T9 cross-app report** as the headline TrainTicket deliverable for
   the paper.

If at any point the smoke test reveals fundamental incompatibility
(image rot, Java OTel agent conflicts with TrainTicket's classloader,
MySQL data layer not exposing useful business metrics), abandon T-track
and keep TrainTicket as a future-work mention only.

---

## What this does NOT solve

- **Multi-cluster TrainTicket.** v4's deferred-to-v6 note stays in
  effect. TT is single-cluster.
- **TrainTicket source modifications.** Where TT services have weak
  logging or no metrics, we *do not* fix them in source. The dataset
  reflects whatever telemetry the upstream emits. (Mention as
  limitation in any paper.)
- **Industrial credibility.** TT is academic, not production. Pairing
  TT with `dataset-todo.md` D9 (public postmortems anchoring) is
  still desirable.

---

## Quick wins available right now (today)

These do not require running TrainTicket:

- [ ] T0.2 dry-run: time-budget the Maven build by reading the
      `pom.xml`. If it's >2h on our laptop, batch-build on a beefier
      machine first.
- [ ] T2.1 service inventory: walk the directory listing of 47 services
      and propose family groupings. Pure-thinking work.
- [ ] T6.1 shadow-Jira templates: author the 4-5 train-booking
      templates as text now; wire them up later.

The cleanest first commit is **T0 (the feasibility spike)**. Until we
know TrainTicket boots on our infra and produces parseable telemetry,
every later phase is speculative.
