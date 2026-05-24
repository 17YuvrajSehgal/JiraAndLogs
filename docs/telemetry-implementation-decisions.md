# Telemetry Implementation Decisions (Phase M0)

**Created:** 2026-05-24
**Owner:** Yuvraj
**Source:** `microservice-changes-todo.md` Phase M0
**Scope:** durable decisions that govern the M1-M5 implementation work.

This file records the **cross-cutting decisions** that must be settled
before any code in `microservices-demo-google/` is changed. Each decision
ends with a binding statement so later phases don't relitigate.

---

## M0.1 — Interceptor placement

**Decision:** **Shared helper libraries per language**, under
`microservices-demo-google/src/_shared-<lang>/` in the fork.

| Language | Library path | Package name |
| --- | --- | --- |
| Go | `src/_shared-go/rpclog/` | `github.com/GoogleCloudPlatform/microservices-demo/src/_shared-go/rpclog` (vendored locally) |
| .NET | `src/_shared-dotnet/RpcLogging/` | `Hipstershop.RpcLogging` (project-reference, not a NuGet) |
| Node.js | `src/_shared-node/rpc-logging/` | `@hipstershop/rpc-logging` (npm workspace, not published) |
| Python | `src/_shared-python/rpc_logging/` | `hipstershop_rpc_logging` (sibling package, installed via `pip install -e ..`) |
| Java | shaded into `adservice/build.gradle` | `com.hipstershop.rpclogging` |

**Why shared not per-service:**
- The RPC log shape, status mapping, and label discipline are identical
  across all services. Inlining the same ~50 lines into each of 12 services
  invites drift — one service emitting `peer_service` while another emits
  `caller_service` and our retrieval index loses both as templates.
- M4 reuses the same interceptor to emit RED metrics. Sharing the
  interceptor guarantees the log fields and metric labels stay aligned.

**Why this is acceptable fork divergence:**
- The 5 helper directories live under `src/_shared-<lang>/`, which is a
  new top-level pattern not in upstream Google. Upstream rebase conflicts
  will be limited to per-service wiring changes (1-5 lines per service).

**Closed.**

---

## M0.2 — Upstream divergence policy

**Decision:** **Hard-fork**, branch `master-yuvraj-fork`.

- The user has already forked `microservices-demo-google/` into their own
  GitHub. All telemetry changes commit to that fork's `master-yuvraj-fork`
  branch.
- Upstream Google `main` is added as a remote (`upstream`) so we can
  `git fetch upstream` and cherry-pick selectively, but we do **not**
  attempt a continuous rebase.
- Cherry-pick cadence: **quarterly**, on a calendar reminder. Each
  cherry-pick is a separate PR against `master-yuvraj-fork` so we can
  measure the divergence cost in review time.

**Why not continuous rebase:**
- Our telemetry layer touches every service. A monthly rebase against
  active upstream development would constantly conflict on the same files.
- We do not depend on upstream feature velocity; Online Boutique is a
  stable demo. We mainly care about CVE-relevant updates, which a
  quarterly cadence catches.

**What we accept giving up:**
- New services Google adds in the meantime (in 2024 they added the
  shopping-assistant LLM service — that kind of change).
- Updated OTel library versions land via our own quarterly bump, not
  automatically.

**Closed.**

---

## M0.3 — Image registry

**Decision:** **kind-local registry for development; Google Artifact
Registry (AR) for cloud VM runs**.

### Development (local kind)

The current `scripts/research-lab/render-online-boutique.ps1` + `apply-online-boutique.ps1`
flow already loads images directly via `kind load docker-image`. No
registry needed for dev — `docker build && kind load docker-image cartservice:dev` is
the workflow.

### Cloud VM (v5 collection)

For the cloud collection runs documented in
`docs/gcp-production-dataset-vm-runbook.md`, use a Google **Artifact
Registry** Docker repo:

```
us-central1-docker.pkg.dev/<gcp-project>/jiraandlogs-research/
  ├─ cartservice:v5.0.0-otel
  ├─ adservice:v5.0.0-otel
  ├─ shippingservice:v5.0.0-otel
  └─ ... (other services unchanged → re-tagged from upstream Google images)
```

### Push workflow

A new script `scripts/research-lab/push-images-to-registry.ps1` will:
1. Read a target registry URL from `-Registry` parameter.
2. For each modified service: `docker build`, `docker tag`, `docker push`.
3. For unchanged services: `docker pull <upstream>; docker tag; docker push`.
4. Emit a `image-digests-<timestamp>.json` manifest pinning every digest
   (used by the reproducibility manifests under
   `data/runs/<id>/manifest.json`).

**Open:** the user needs to confirm the GCP project name. **Default assumed:** `jira-telemetry-research`. The push script will accept it as a parameter so wrong-default doesn't block anything.

**Closed (modulo GCP project name parameter).**

---

## M0.4 — OTel collector capacity headroom

**Inspected:** `deploy/research-lab/observability/values/opentelemetry-collector-values.yaml`.

Current config (line-by-line):
- `mode: deployment` (single replica by default)
- `memory_limiter`: 80% limit, 25% spike — fine for moderate load
- Processors: `[memory_limiter, k8sattributes, resource, batch]`
- Receivers: OTLP gRPC (4317) + HTTP (4318)
- Exporters: OTLP to Tempo, Prometheus on 8889
- **No resources limits/requests set explicitly** in the values file — relies on Helm chart defaults
- **No replica count set** — Helm chart default is 1

### Projected v5 load after M1-M4 land

Span volume estimate per service (very rough):
- Today: ~5-10 spans / request (one server span + N client spans for a fan-out call)
- After M3 (manual child spans for deps): ~15-25 spans / request

At v4-large load (~50-100 RPS sustained per service-pair during active_fault),
that's:
- Today: ~500 spans/sec at peak per service
- After M3: ~1500-2500 spans/sec at peak per service

Across ~6 services emitting traffic: **~9k-15k spans/sec at peak**.

A single OTel collector with the default Helm-chart resource limits
(typically 256Mi memory request, 512Mi limit) is **likely undersized** for
this. We've been getting away with it because v4-large is at ~500 spans/sec.

### Action

- [ ] **M0.4a (deferred to M5.2 pilot)** Bump collector resources in
      `opentelemetry-collector-values.yaml`:
      ```yaml
      resources:
        requests: {cpu: 500m, memory: 1Gi}
        limits: {cpu: 2, memory: 2Gi}
      replicaCount: 2
      ```
- [ ] **M0.4b** Also bump `batch` processor `send_batch_size: 8192` and
      `send_batch_max_size: 16384`. Default (1024) will bottleneck.

**Status:** sizing identified. Actual values applied during M5.2 pilot
to avoid disrupting current v4-large runs.

**Closed (decision recorded; bumps applied at M5.2 time).**

---

## M0.5 — Loki ingest sizing

**Inspected:** `deploy/research-lab/observability/values/loki-values.yaml`
not opened in this pass; following the M0.4 pattern of deferring actual
bumps to M5.2 but documenting the projected need.

### Projected log volume after M2 lands

- M2.1 (per-RPC structured request log): **multiplies log volume roughly 3-5×**
  at peak traffic. One log per RPC per direction (client + server) at
  ~50-100 RPS = ~10k log lines/sec across the fleet at peak.
- M2.2 (dep-boundary error logs): negligible at baseline, spikes during
  active_fault windows (where they matter most).
- M2.3 (business events): negligible (~10/sec total).

Estimated post-M2 log volume: **~30-50 GB/day** at sustained v5 traffic
(currently ~10 GB/day).

### Action

- [ ] **M0.5a** Bump Loki PVC size from current to **120 GB** for the
      cloud VM (gives 3 days retention at projected volume + headroom).
- [ ] **M0.5b** Confirm Loki chunk encoding stays at `snappy` (default);
      switch to `zstd` only if disk pressure becomes a real problem
      during the M5.2 pilot.
- [ ] **M0.5c** Update `docs/gcp-production-dataset-vm-runbook.md` to
      provision a 1 TB disk (was 500 GB for v4-large) — covers Loki + raw
      run exports + Tempo + Prometheus retention with headroom.

**Closed (decision recorded; actual bumps applied at M5.2 time).**

---

## M0.6 — Production fidelity disclosure (draft)

This section is a **first draft of the disclosure** that will land in the
v5 dataset README under a `## Production Fidelity` heading. It lists every
realism compromise we have not been able to fix and explains why.

> ### Production Fidelity
>
> This dataset is collected in a controlled lab. The following are known
> divergences from real production telemetry, recorded here so dataset
> consumers can calibrate their generalization expectations.
>
> 1. **Trace sampling is 100% (AlwaysSample).** Real production deployments
>    typically head-sample at 1-10% or tail-sample on errors/latency. Our
>    dataset density gain comes at the cost of trace distribution
>    realism — every span is captured, including spans a production
>    sampler would have dropped. Models trained on this dataset may
>    over-rely on span fan-out features that would be partially missing
>    under production sampling.
>
> 2. **Single-cluster, single-region.** All services run in one kind
>    cluster (development) or one GKE cluster in one region (cloud). No
>    cross-region failures, no inter-cluster network partitions, no
>    multi-AZ failover behavior. Cross-region scenarios are deferred to
>    Dataset v6.
>
> 3. **No real customer PII.** The loadgenerator emits synthetic users and
>    synthetic credit card numbers (paymentservice uses
>    `simple-card-validator` against `visa`/`mastercard` patterns). Real
>    production tickets often include user identifiers or session ids; ours
>    contain only synthetic equivalents.
>
> 4. **Synthetic traffic patterns.** Load is generated by `loadgenerator`
>    against a deterministic basket of routes. No diurnal pattern, no
>    weekly cycle, no business-hour effect. Phase D8 in
>    `dataset-todo.md` proposes adding these in v5.1 or v6.
>
> 5. **Single fault per run.** Each scenario injects one fault. Real
>    production incidents often have multiple correlated faults
>    (deploy-induced + DB slow + cache eviction firing within minutes).
>    Cascade scenarios in Phase D5 of `dataset-todo.md` partly address
>    this; full multi-fault correlation is out of scope for v5.
>
> 6. **Shadow Jira issues, not real engineer-authored Jira.** Every Jira
>    issue in the memory corpus is generated from a scenario YAML
>    template by `generate-shadow-jira-issues.ps1`. Real engineer-written
>    tickets carry inconsistencies, typos, and out-of-band signals
>    (Slack threads, postmortem links, manager pressure) that synthetic
>    issues do not capture.
>
> 7. **No alert-fatigue baseline.** Real on-call queues have a
>    background level of false positives from alerting systems that
>    pre-date the period of triage decision. Our baseline-normal-traffic
>    family emits zero alerts. v5 adds the `post-deploy-churn` family
>    (`dataset-todo.md` D1.1) to partly address this.
>
> 8. **No deploy event correlation in v4.** Phase D8 adds synthetic
>    deploy events with logs/metrics correlated to them. Until then,
>    every fault is independent of any deploy timeline.
>
> 9. **No GPU-served services.** Recommendation, ad-serving, fraud
>    detection in real e-commerce often use GPU-backed inference. Online
>    Boutique's recommendation service uses a Python sort-by-popularity
>    proxy. This affects what kinds of failures are realistic
>    (no CUDA OOM, no model-serving cold-start, no quota throttling).

**Closed.** Final wording lives in the v5 dataset README; this is the
binding draft.

---

## Summary of Phase M0 decisions

| Decision | Outcome | Action item |
| --- | --- | --- |
| M0.1 Interceptor placement | Shared per-language libs under `src/_shared-<lang>/` | Create skeletons in Phase M2.1 |
| M0.2 Upstream divergence | Hard-fork on `master-yuvraj-fork`; cherry-pick upstream quarterly | Add `upstream` remote when fork is created |
| M0.3 Image registry | kind-local for dev; Google Artifact Registry for cloud | `push-images-to-registry.ps1` script in Phase M5.2 |
| M0.4 Collector capacity | Bump to 2× replicas, 2Gi memory, 16k batch size at M5.2 time | M0.4a / M0.4b applied at M5.2 pilot |
| M0.5 Loki sizing | 120 GB PVC, 1 TB disk for cloud VM | M0.5a / M0.5b / M0.5c applied at M5.2 pilot |
| M0.6 Fidelity disclosure | Draft above is binding; lives in v5 dataset README | Inserted verbatim when v5 README is written |

Phase M0 status: **complete**.
