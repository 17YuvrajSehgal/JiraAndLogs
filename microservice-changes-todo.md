# Microservice Telemetry Implementation Plan

**Created:** 2026-05-24
**Owner:** Yuvraj
**Source doc:** `microservice-changes.md` (the *why*; this file is the *what to do*)
**Companion plans:** `todo.md` (ML pipeline), `dataset-todo.md` (dataset v5)

This file is the actionable execution plan for the proposals in
`microservice-changes.md`. Each phase ends with an acceptance bar and lists
its dependencies. Production-realism discipline from the source doc applies
to every task — never add anything that names our scenarios, fault types,
or triage labels.

---

## Hard rules (review before EVERY task)

These come from `microservice-changes.md` "The trap to avoid" section. They
are non-negotiable.

- No span attribute, log field, or metric label may name our scenarios
  (`scenario.id`, `fault.injected`, `expected_severity`).
- No metric may be labeled by anything from
  `scripts/research-lab/triage_labels.py` (no `scenario_family`, `fault_type`).
- No trace baggage may propagate `dataset_run_id` through the app.
- No field listed in `docs/triage-task-contract.md` "Field Policy" as
  eval-only may appear in telemetry.
- Every change must answer YES to: *"would a real SaaS company in 2026 emit
  this without us telling them to?"*

---

## Phase M0 — Foundation and decisions
**Goal:** resolve the cross-cutting decisions before any code is written, so
later phases don't get blocked or have to be redone. None of these require
running anything in the cluster.

- [ ] **M0.1** Decide interceptor placement: per-service handwritten vs
      shared helper libraries under `microservices-demo-google/src/_shared-<lang>/`.
      Document the call in `microservice-changes.md` under "Open questions".
      Recommendation: shared per language (Go pkg, .NET nuget, Node pkg,
      Python module) — costs an extra setup hour per language, saves N×
      maintenance later.
- [ ] **M0.2** Decide upstream divergence policy: rebase-on-Google monthly
      vs hard-fork. Recommendation: hard-fork (`master-yuvraj-fork` branch
      on the user's repo of `microservices-demo-google`), cherry-pick
      upstream changes quarterly. Document on `microservices-demo-google/README.md`.
- [ ] **M0.3** Set up image registry for the fork. Local kind already has
      a registry; the cloud VM (`docs/gcp-production-dataset-vm-runbook.md`)
      needs either GCR or Artifact Registry. Create the registry, document
      the push command, add the auth secret to the v5 cluster manifests.
- [ ] **M0.4** Verify OTel collector capacity headroom. Read
      `deploy/research-lab/observability/` collector config; estimate 3-5×
      span throughput after T3 lands. Bump replica count or memory limits
      pre-emptively if margin is < 2×.
- [ ] **M0.5** Verify Loki ingest sizing. Per-RPC structured logs at p95
      traffic will multiply log volume substantially. Re-check Loki
      retention / disk sizing for the v5 cloud VM. Update
      `docs/gcp-production-dataset-vm-runbook.md` if needed.
- [ ] **M0.6** Author the "Production fidelity" disclosure section for the
      v5 dataset README. Lists every realism compromise (100% sampling,
      single-cluster, no real PII, no geo traffic). Even if the section
      is short, drafting it now forces honest tradeoff thinking before we
      start cutting telemetry corners.

**Acceptance:** all six decisions are documented; collector and Loki
sizing are confirmed to handle the projected v5 volume; the fidelity
disclosure has a first draft.
**Status:** not started.
**Blocks:** every later phase touches at least one of these decisions.

---

## Phase M1 — Bring laggard services to OTel parity (T1)
**Goal:** the three services with zero or partial OTel coverage today
emit auto-instrumented gRPC/HTTP server and client spans, matching the
rest of the fleet. This is the single highest-leverage phase — without it,
cartservice traces are invisible and the cart-redis fault family stays
under-detected.

### M1.1 cartservice (.NET) — the priority

- [ ] **M1.1a** Add NuGet packages: `OpenTelemetry.Extensions.Hosting`,
      `OpenTelemetry.Instrumentation.AspNetCore`,
      `OpenTelemetry.Instrumentation.GrpcNetClient`,
      `OpenTelemetry.Instrumentation.StackExchangeRedis`,
      `OpenTelemetry.Exporter.OpenTelemetryProtocol`.
- [ ] **M1.1b** Wire `AddOpenTelemetry().WithTracing()` in `Startup.cs` /
      `Program.cs` with W3C TraceContext propagator, OTLP gRPC exporter
      pointing to `COLLECTOR_SERVICE_ADDR`, `AlwaysOnSampler`.
- [ ] **M1.1c** Set resource attributes: `service.name=cartservice`,
      `service.version=<image-tag>`,
      `deployment.environment=<env var or "research-lab">`.
- [ ] **M1.1d** Rebuild the cartservice image, push to the registry from M0.3.
- [ ] **M1.1e** Update `deploy/research-lab/online-boutique/` manifests
      to use the new image tag for cartservice.
- [ ] **M1.1f** Local smoke: deploy, hit `/cart` via loadgenerator, confirm
      cartservice spans appear in Tempo with parent context from frontend
      and child spans for Redis ops.

### M1.2 adservice (Java)

- [ ] **M1.2a** Add OpenTelemetry Java agent JAR to `adservice/Dockerfile`
      (download from Maven Central into the image build step). Java agent
      is the production-standard approach — zero application code changes.
- [ ] **M1.2b** Set `JAVA_TOOL_OPTIONS=-javaagent:/otel/javaagent.jar` and
      `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME=adservice`,
      `OTEL_PROPAGATORS=tracecontext,baggage`,
      `OTEL_TRACES_SAMPLER=always_on` in the deployment manifest env block.
- [ ] **M1.2c** Rebuild + push, update manifest tag.
- [ ] **M1.2d** Local smoke: spans appear from `hipstershop.AdService/GetAds`.

### M1.3 shippingservice (Go)

- [ ] **M1.3a** Add `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc`
      to `go.mod`. Mirror the init pattern from `checkoutservice/main.go`
      (lines 38-43, 167-175): tracer provider, OTLP exporter, propagator
      set to W3C TraceContext + Baggage.
- [ ] **M1.3b** Wrap gRPC server with `grpc.StatsHandler(otelgrpc.NewServerHandler())`.
- [ ] **M1.3c** Rebuild + push, update manifest tag.
- [ ] **M1.3d** Local smoke.

**Acceptance:** Tempo shows server + client spans for every gRPC method on
cartservice, adservice, shippingservice. A single PlaceOrder trace from
frontend visits **all** 8 downstream services without gaps.
**Status:** not started.
**Blocks:** every later trace/metrics phase assumes these three services
emit OTel data.

---

## Phase M2 — Logging improvements (L1, L2, L3)
**Goal:** per-RPC structured request logs, dependency-boundary error
context, and a small business-event log layer. Implemented as shared
interceptor / middleware per language to keep service code clean.

### M2.1 Per-RPC structured request log (L1) — highest leverage

For each language, build a shared interceptor that logs one JSON object
per RPC with `{trace_id, span_id, method, peer_service, latency_ms,
status_code, err_class}`.

- [ ] **M2.1a (Go)** Shared package `src/_shared-go/rpclog/` with
      gRPC unary + stream server interceptors and a client interceptor.
      Wire into `frontend`, `checkoutservice`, `productcatalogservice`,
      `shippingservice`. Use existing `logrus` JSON logger.
- [ ] **M2.1b (.NET)** Shared package `src/_shared-dotnet/RpcLogging/`.
      Wire into `cartservice`. Use `Microsoft.Extensions.Logging` with
      JsonConsoleFormatter.
- [ ] **M2.1c (Node.js)** Shared package
      `src/_shared-node/rpc-logging/index.js`. Wire into
      `paymentservice`, `currencyservice`. Use `pino`.
- [ ] **M2.1d (Python)** Shared module
      `src/_shared-python/rpc_logging/__init__.py`. Wire into
      `recommendationservice`, `emailservice`. Use stdlib `logging`
      with `python-json-logger`.
- [ ] **M2.1e (Java)** Shared classpath JAR. Wire into `adservice`.
      Use Logback JSON encoder.

### M2.2 Structured error context at dependency boundaries (L2)

Targeted edits to ~6-8 service-pair call sites: log a JSON event on
failure with `{dep, op, err_class, retry_attempt}`. Do NOT add a log
at the success path here — that's L1's job.

- [ ] **M2.2a** cartservice → redis-cart: `GET`, `SET`, `DEL`, `EXPIRE`.
- [ ] **M2.2b** checkoutservice → each of cart, productcatalog,
      currency, shipping, payment, email — log on RPC error return.
- [ ] **M2.2c** frontend → each downstream gRPC — log on RPC error return.
- [ ] **M2.2d** recommendationservice → productcatalog lookup error.
- [ ] **M2.2e** paymentservice → outbound calls (currently synthetic;
      log card-validation failure paths).

### M2.3 Business event log layer (L3) — optional, defer if time-pressed

- [ ] **M2.3a** Pick ONE event per service from the table in
      `microservice-changes.md` L3 section.
- [ ] **M2.3b** Implement and emit at the natural code site.
      Keep field names generic (`order_id`, `cart_size`, `payment_amount`),
      NEVER include scenario/fault/triage names.

**Acceptance:** every test-fixture RPC produces exactly one L1 log line on
each side (client + server); error responses additionally produce one L2
log line at the call site; for L3, dashboards can plot `orders_placed`,
`cart_operations`, `payments` over time.
**Status:** not started.
**Blocks:** v5 collection (we want these logs in v5, not v5.1).

---

## Phase M3 — Trace enrichment (T2, T3, T4, T5)
**Goal:** every error path marks its span; dependency calls have child
spans with semantic-convention attributes; resilience-pattern code paths
emit span events; sampling divergence is documented.

### M3.1 RecordError + SetStatus(Error) on every error-returning handler (T2)

Mechanical edit — ~3 lines per error path. Use the patterns in
`microservice-changes.md` T2 section as the reference.

- [ ] **M3.1a (Go)** `frontend` handlers (handlers.go ~21 log call sites),
      `checkoutservice` (main.go ~20), `productcatalogservice`,
      `shippingservice`.
- [ ] **M3.1b (.NET)** `cartservice` Redis ops + service methods.
- [ ] **M3.1c (Node.js)** `paymentservice` charge.js, `currencyservice`.
- [ ] **M3.1d (Python)** `recommendationservice`, `emailservice`.
- [ ] **M3.1e (Java)** `adservice`.

### M3.2 Manual child spans for dependency calls (T3)

Wrap each dependency call in a child span with semantic-convention
attributes (`db.system`, `db.operation`, `net.peer.name`, etc.). Do NOT
add app-specific attributes that mirror scenario metadata.

- [ ] **M3.2a** cartservice → redis-cart child spans
      (mostly auto-emitted by `Instrumentation.StackExchangeRedis` from M1.1a;
      verify they appear with correct attributes; add manual spans only
      for code paths the library misses, e.g. batch ops).
- [ ] **M3.2b** checkoutservice → its 6 downstream gRPC client spans
      already exist; enrich with attributes like
      `app.order_item_count` (NEVER `app.order_subtotal_usd` if
      cardinality risk; use bucketed `app.order_item_count_bucket`).
- [ ] **M3.2c** recommendationservice → productcatalog lookup span.
- [ ] **M3.2d** frontend → 8 downstream + HTTP outbound enrichment.

### M3.3 Span events for state transitions (T4)

Only where retry / fallback / cache logic already exists in the code.
Don't fabricate state machines just to emit events.

- [ ] **M3.3a** Audit each service for existing retry / fallback / cache
      code paths. Inventory in a comment block on this task.
- [ ] **M3.3b** Add `span.AddEvent("cache.miss"|"cache.hit"|"retry.attempt"|
      "fallback.used"|"circuit_breaker.open", ...)` at those sites.

### M3.4 Document the sampling divergence (T5)

- [ ] **M3.4a** Add a "Current Limitations" bullet to
      `docs/dataset-v4-plan.md` noting 100% trace sampling vs typical
      production 1-10% head sampling.
- [ ] **M3.4b** Cross-reference from the v5 dataset README's
      "Production fidelity" section (M0.6).

**Acceptance:** a representative failing PlaceOrder trace shows
`status=Error` on every span in the failure chain (not just the leaf);
dependency calls appear as child spans with semantic-convention attrs in
Tempo's structured query UI; at least one fault scenario surfaces a span
event in its evidence text; sampling divergence is documented in two
canonical places.
**Status:** not started.
**Blocks:** none; runs in parallel with M2 if dev capacity allows.

---

## Phase M4 — Metrics emission (M1, M2, M3, M4)
**Goal:** every service exposes a `/metrics` Prometheus endpoint with
RED metrics per RPC, per-dependency client metrics, a handful of
carefully-labeled business counters, and standard runtime gauges.

### M4.1 OTel MeterProvider + Prometheus exporter init (M1, M4)

This is the foundation — once a service has a working MeterProvider and
`/metrics` endpoint, the rest of M4 is metric-by-metric registration.
~15 lines per service.

- [ ] **M4.1a (Go)** Add `go.opentelemetry.io/otel/exporters/prometheus`,
      `go.opentelemetry.io/otel/sdk/metric`. Init in `main.go`. Expose
      `/metrics` on a separate port (e.g. 9100) so it doesn't collide
      with the gRPC port.
- [ ] **M4.1b (.NET)** `OpenTelemetry.Exporter.Prometheus.AspNetCore`.
- [ ] **M4.1c (Node.js)** `@opentelemetry/exporter-prometheus`.
- [ ] **M4.1d (Python)** `opentelemetry-exporter-prometheus`.
- [ ] **M4.1e (Java)** OTel Java agent already supports Prometheus
      exporter via `OTEL_METRICS_EXPORTER=prometheus`.
- [ ] **M4.1f** Update each service's k8s manifest to add
      `prometheus.io/scrape=true`, `prometheus.io/port=9100` annotations
      (or equivalent ServiceMonitor under
      `deploy/research-lab/observability/`).

### M4.2 RED metrics per RPC handler (M1)

- [ ] **M4.2a** Per-language: register `rpc_server_duration_seconds`
      histogram and `rpc_server_requests_total` counter, labeled by
      `service`, `method`, `status`. Record from the same interceptor
      that emits L1 logs (consistency win).
- [ ] **M4.2b** Verify metric labels are bounded — `service` and `method`
      are bounded by the proto; `status` is the gRPC code enum.

### M4.3 Per-dependency client metrics (M2)

- [ ] **M4.3a** `rpc_client_duration_seconds`, `rpc_client_errors_total`
      labeled by `peer_service` and `operation`. Emitted from the client
      interceptor mirror of M4.2a.

### M4.4 Business-event counters (M3) — use SPARINGLY

Strict label discipline: every label must come from the proto contract or
be a bounded enum. If in doubt, skip the metric.

- [ ] **M4.4a** frontend: `http_requests_total{route, status_class}`.
      `route` from gorilla/mux route templates (bounded). `status_class`
      = `2xx|3xx|4xx|5xx` (bounded).
- [ ] **M4.4b** checkoutservice: `orders_placed_total{currency}` and
      `order_value_units_total{currency}` (sum-of-units counter, NOT a
      histogram per-order).
- [ ] **M4.4c** paymentservice: `payments_total{card_type, result}`.
      `card_type` ∈ {visa, mastercard, other}; `result` ∈ {success, invalid, expired, unsupported}.
- [ ] **M4.4d** cartservice: `cart_operations_total{op, result}`. `op` ∈ {add, get, empty}.
- [ ] **M4.4e** recommendationservice: `recommendations_served_total`.
- [ ] **M4.4f** productcatalogservice: `catalog_lookups_total{result}`.
      `result` ∈ {hit, miss}.

### M4.5 Standard runtime / saturation gauges (M4)

Mostly free from the OTel SDK or language Prometheus client defaults.

- [ ] **M4.5a** Verify each service exposes `process_cpu_seconds_total`,
      `process_resident_memory_bytes`, `process_open_fds`, GC metrics
      appropriate to the language.
- [ ] **M4.5b** Update Prometheus scrape config if any of these go to a
      separate port from M4.1f.

**Acceptance:** `curl <service>:9100/metrics` returns RED + dependency +
business + runtime metrics for every service; Grafana can render a
per-service RED dashboard; no metric has unbounded cardinality (`promtool
check metrics` clean); no metric is labeled with anything from the
scenario taxonomy.
**Status:** not started.
**Blocks:** v5 collection benefits from these metrics.

---

## Phase M5 — Validation and integration into v5 collection
**Goal:** prove the telemetry upgrade actually moves the needle on at least
one fault family before committing to a full v5 reshoot.

### M5.1 Cartservice-first incremental validation (the cheap experiment)

Per `microservice-changes.md` "Updated recommended validation path":

- [ ] **M5.1a** Deploy ONLY M1.1 (cartservice OTel parity) +
      M3.1b (RecordError in cartservice) to the local kind cluster.
      Everything else stays unchanged.
- [ ] **M5.1b** Collect 2 runs of `cart-redis-degradation-critical` on
      that cluster using the existing collection scripts.
- [ ] **M5.1c** Build the per-run derived dataset for those 2 runs.
- [ ] **M5.1d** Measure: does `trace_error_count` on cartservice
      `active_fault` windows go from ~0 (today) to a meaningful value?
- [ ] **M5.1e** Run the loganalyzer phase0.5 pipeline on just the
      cart-redis family slice from those 2 runs vs a sampled equivalent
      from v4-large. Report PR-AUC and recall@5 delta.
- [ ] **M5.1f** **Gate:** if the metrics move (PR-AUC up by >= 5pt on
      cart-redis family OR `trace_error_count` newly fires), proceed to
      M5.2. If not, revisit M1.1 wiring before continuing.

### M5.2 Full v5 fleet rollout

- [ ] **M5.2a** Land all of M1, M2, M3, M4 across all services.
- [ ] **M5.2b** Run a 1-day cloud VM pilot collecting 3 runs each from
      the v5 plan families (a small subset of the full v5 corpus).
- [ ] **M5.2c** Confirm collector capacity and Loki sizing assumptions
      from M0.4 + M0.5 hold under real v5 load.
- [ ] **M5.2d** Validate every L1 log includes `trace_id`, every error
      path has both an L2 log AND a `RecordError` span event (cross-check
      that the two paths agree).
- [ ] **M5.2e** Run feature distribution validation
      (`scripts/research-lab/validate-run-feature-distribution.ps1`) on
      the pilot runs; bias-check: confirm no new feature column is
      perfectly correlated with `scenario_id`, `scenario_family`, or
      `triage_label` (a leakage canary).

### M5.3 Land in dataset-todo as Phase D13

- [ ] **M5.3a** Open a PR adding Phase **D13** to `dataset-todo.md`
      under sprint **D-3.5**, with the source of truth being this file.
      D13's acceptance is M5.2's acceptance.
- [ ] **M5.3b** Update `docs/instrumentation-gaps-and-next-steps.md` to
      cross-link to this plan; mark the bullets it resolves as
      "in progress" once M1 lands.

**Acceptance:** v5 collection runs end-to-end on the upgraded telemetry;
feature distributions are within ±20% of v4-large for legacy features and
all-new features (L1/L2/L3 log volume, M1-M4 metric series) are present in
every run; no leakage canary fires.
**Status:** not started.
**Blocks:** v5 production collection (Phase D4 in `dataset-todo.md`).

---

## Suggested execution order (sprints)

| Sprint | Phases | Cost | Depends on |
| ------ | ------ | ---- | ---------- |
| MT-0   | M0 (decisions + sizing) | 0.5 dev day | nothing |
| MT-1   | M1.1 (cartservice OTel parity) | 1 dev day | M0 |
| MT-1.5 | M5.1 (cheap cartservice-first validation) | 0.5 VM day | MT-1 done |
| MT-2   | M1.2, M1.3 (adservice + shippingservice parity) | 2 dev days | MT-1.5 passes gate |
| MT-3   | M2.1 across all 5 languages | 3 dev days | M0.1 (shared interceptor decision) |
| MT-4   | M2.2 (dependency-boundary error logs) | 1.5 dev days | MT-3 |
| MT-5   | M3 (trace enrichment) | 3 dev days | MT-2, can overlap MT-3/MT-4 |
| MT-6   | M4 (metrics) | 3 dev days | MT-2, can overlap MT-5 |
| MT-7   | M2.3 (business event logs, optional) | 1 dev day | MT-3 |
| MT-8   | M5.2 (full v5 pilot) | 1 VM day | MT-2 .. MT-6 landed |
| MT-9   | M5.3 (dataset-todo integration) | 0.5 dev day | MT-8 |

Telemetry-only scope: roughly **15-17 dev days + 1.5 VM days**, matching
the cost estimate in `microservice-changes.md`. Parallelizable across
services and across the M3/M4 streams once M1 is done.

---

## Quick wins available right now (today)

- [ ] **M0.1 + M0.2** decisions (interceptor placement + upstream policy).
      Pure thinking + 30 min of writing.
- [ ] **M1.1a-c** cartservice OTel wiring (no rebuild yet) — fastest path
      to closing the single biggest blind spot in v4-large.
- [ ] **M3.4** documentation-only sampling-divergence note. Trivial.
- [ ] **M0.6** "Production fidelity" disclosure draft. Forces honest
      tradeoff documentation before any code change.

The cleanest first concrete step is the chain
**M0.1 → M0.2 → M1.1 → M5.1**: pick interceptor placement, pick fork policy,
wire cartservice tracing, validate it actually moves the cart-redis family
numbers. If that validation gate passes, commit the rest of the plan;
if it fails, we've spent ~1.5 days learning something instead of ~15.

---

## What this plan DOES NOT cover

- Other application repos (Sock Shop, TrainTicket, Hotel Reservation).
  Those are Phase D6 in `dataset-todo.md`; we'd re-do this exercise per
  app there.
- Real production deployment of the upgraded Online Boutique outside
  research. Out of scope — same as in `microservice-changes.md`.
- Sampling reconfiguration. Stays at AlwaysSample for research; the
  divergence is documented (M3.4), not fixed.
- Distributed transaction tracing across cluster boundaries. Single
  cluster only; cross-cluster is v6.
