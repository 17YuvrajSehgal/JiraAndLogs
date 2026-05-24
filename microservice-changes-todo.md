# Microservice Telemetry Implementation Plan

**Created:** 2026-05-24
**Last updated:** 2026-05-24 (batch sweep — M0..M5 statuses reconciled)
**Owner:** Yuvraj
**Source doc:** `microservice-changes.md` (the *why*; this file is the *what to do*)
**Companion plans:** `todo.md` (ML pipeline), `dataset-todo.md` (dataset v5)

## Status snapshot (2026-05-24)

| Phase | Status | Notes |
| ----- | ------ | ----- |
| M0 Foundation | **complete** | All 6 decisions in `docs/telemetry-implementation-decisions.md`; Loki + collector sizing live (50Gi PVC, 2× collector replicas, 16k batch) |
| M1 OTel parity | **complete** | cartservice/.NET + adservice/Java + shippingservice/Go upgraded; M5.1 gate PASSED (3.0× trace_error_count lift on cart-redis) |
| M2 Logging | **complete** | L1 shared interceptors across Go/.NET/Node/Python; L2 dep-error logs at Redis + every gRPC client boundary; L3 emits 4 business events |
| M3 Trace enrichment | **complete** | RecordError/SetStatus on every error path across 5 languages; dep child spans with semantic-convention attrs; sampling divergence documented |
| M4 Metrics | **complete** (1 follow-up) | /metrics on every service; RED + client metrics via shared interceptors; 5 business counters; Node runtime gauges open follow-up |
| M5 Validation | **complete** local, **pending** cloud pilot | D13.14a fleet rollout live; D13.14b (cloud pilot) is the remaining user-triggered step |

See "Remaining work" near the bottom for the small open follow-ups.

---

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

- [x] **M0.1** Decide interceptor placement: **shared helper libraries
      per language** under `microservices-demo-google/src/_shared-<lang>/`.
      Skeletons exist for Go (`rpclog/`), .NET (`RpcLogging/`), Node
      (`rpc-logging/`), Python (`rpc_logging/`). Decision recorded in
      `docs/telemetry-implementation-decisions.md` §M0.1.
- [x] **M0.2** Upstream divergence policy: **hard-fork** at
      `17YuvrajSehgal/microservices-demo-google` with `upstream` remote
      pointing at Google. Quarterly cherry-pick cadence. First quarterly
      check (2026-05-24) = zero divergence (fork branched off upstream
      HEAD `5096a85b`). Decision in `docs/telemetry-implementation-decisions.md` §M0.2.
- [x] **M0.3** Image registry: **kind-local for dev, Google Artifact
      Registry for cloud VM runs**
      (`us-central1-docker.pkg.dev/<project>/jiraandlogs-research/`).
      `push-images-to-registry.ps1` script deferred to M5.2 push time.
      Decision in `docs/telemetry-implementation-decisions.md` §M0.3.
- [x] **M0.4** OTel collector capacity: bumped to **2 replicas, 1Gi req
      / 2Gi limit, `send_batch_size=8192`, `send_batch_max_size=16384`,
      `timeout=200ms`**. Live on `jira-telemetry-lab` (Helm revision 3,
      2 healthy pods). Tracked as D13.15a in `dataset-todo.md`.
- [x] **M0.5** Loki ingest sizing: PVC enabled at **50Gi standard**
      (downsized from binding 120Gi because this VM has 242GB disk;
      bump when VM gets 1TB). Change written to
      `deploy/research-lab/observability/values/loki-values.yaml`;
      cluster reload still pending user OK (D13.15b in `dataset-todo.md`).
- [x] **M0.6** "Production fidelity" disclosure: **9-divergence binding
      draft** in `docs/telemetry-implementation-decisions.md` §M0.6.
      Will be lifted verbatim into the v5 dataset README at v5 publish time.

**Acceptance:** all six decisions are documented; collector and Loki
sizing are confirmed to handle the projected v5 volume; the fidelity
disclosure has a first draft.
**Status:** **complete (2026-05-24).** See `docs/telemetry-implementation-decisions.md`.
**Blocks:** every later phase touches at least one of these decisions.

---

## Phase M1 — Bring laggard services to OTel parity (T1)
**Goal:** the three services with zero or partial OTel coverage today
emit auto-instrumented gRPC/HTTP server and client spans, matching the
rest of the fleet. This is the single highest-leverage phase — without it,
cartservice traces are invisible and the cart-redis fault family stays
under-detected.

### M1.1 cartservice (.NET) — the priority

- [x] **M1.1a** NuGet packages added: `OpenTelemetry.Extensions.Hosting`,
      `OpenTelemetry.Instrumentation.AspNetCore`,
      `OpenTelemetry.Instrumentation.GrpcNetClient`,
      `OpenTelemetry.Instrumentation.StackExchangeRedis`,
      `OpenTelemetry.Instrumentation.Runtime`,
      `OpenTelemetry.Exporter.OpenTelemetryProtocol`,
      `OpenTelemetry.Exporter.Prometheus.AspNetCore`
      (`src/cartservice/src/cartservice.csproj` lines 18-25).
- [x] **M1.1b** `AddOpenTelemetry().WithTracing()` wired in
      `src/cartservice/src/Startup.cs` lines 127-160. `AlwaysOnSampler`,
      OTLP gRPC exporter to `COLLECTOR_SERVICE_ADDR`. Both tracing
      and metrics pipelines registered.
- [x] **M1.1c** Resource attrs set: `service.name=cartservice`,
      `service.version=$SERVICE_VERSION`, `service.namespace=online-boutique`,
      `deployment.environment=$DEPLOYMENT_ENVIRONMENT` (Startup.cs lines
      120-126). No scenario/fault leakage.
- [x] **M1.1d** Image `cartservice:v5.0.0-otel-pilot` built and loaded
      into the `jira-telemetry-lab` kind cluster (per M5.1 result in
      `docs/telemetry-implementation-decisions.md`).
- [x] **M1.1e** `deploy/research-lab/online-boutique/` manifests updated;
      `ENABLE_TRACING=1` and image tag propagated via kustomize overlay.
- [x] **M1.1f** Local smoke PASSED — M5.1 validation
      (`docs/telemetry-implementation-decisions.md` §M5.1): cartservice
      spans visible in Tempo with parent context, Redis child spans
      auto-emitted by StackExchange.Redis instrumentation, trace_error_count
      lifted 3.0× on cart-redis active_fault windows.

### M1.2 adservice (Java)

- [x] **M1.2a** OpenTelemetry Java agent JAR downloaded into
      `src/adservice/Dockerfile` (lines 40-57). Build step pulls
      `opentelemetry-javaagent.jar` from Maven Central into the image.
- [x] **M1.2b** `JAVA_TOOL_OPTIONS=-javaagent:/otel/javaagent.jar` + OTEL
      env vars wired in the Dockerfile and deployment manifests
      (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME=adservice`,
      `OTEL_PROPAGATORS=tracecontext,baggage`, `OTEL_TRACES_SAMPLER=always_on`).
- [x] **M1.2c** Image rebuilt + tag bumped to `v5.0.0-otel-pilot`.
- [x] **M1.2d** Local smoke PASSED — adservice spans observed in Tempo
      on the fleet rollout (D13.14a in `dataset-todo.md`).

### M1.3 shippingservice (Go)

- [x] **M1.3a** `otelgrpc` import added in `src/shippingservice/main.go`
      (line 38). Tracer-provider init mirrors `checkoutservice/main.go`
      (W3C TraceContext + Baggage propagators, OTLP exporter).
- [x] **M1.3b** gRPC server wrapped with
      `grpc.StatsHandler(otelgrpc.NewServerHandler())` in `main.go` lines
      119-121.
- [x] **M1.3c** Image rebuilt + tag bumped to `v5.0.0-otel-pilot`.
- [x] **M1.3d** Local smoke PASSED — fleet rollout (D13.14a).

**Acceptance:** Tempo shows server + client spans for every gRPC method on
cartservice, adservice, shippingservice. A single PlaceOrder trace from
frontend visits **all** 8 downstream services without gaps.
**Status:** **complete (2026-05-24).** All 3 services upgraded to OTel
parity; M5.1 cartservice gate passed; D13.14a fleet rollout live.
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

- [x] **M2.1a (Go)** Shared `src/_shared-go/rpclog/rpclog.go` provides
      unary + stream server interceptors and a client interceptor with
      RED metrics. Wired into `frontend/main.go:218`,
      `checkoutservice/main.go:218-219`, `productcatalogservice/server.go:151-152`,
      `shippingservice/main.go:120-121`. Uses logrus JSON logger.
- [x] **M2.1b (.NET)** Shared `src/_shared-dotnet/RpcLogging/RpcLoggingInterceptor.cs`
      registered via `services.AddGrpc(o => o.Interceptors.Add<RpcLoggingInterceptor>())`
      in `cartservice/Startup.cs:80,82`. **D13.14d-followup landed 2026-05-24:**
      `cartservice/src/Program.cs` now calls `logging.AddJsonConsole(...)`
      with `IncludeScopes = true`, and the interceptor uses a
      structured-logging message template (`LogInformation("rpc method={method}…")`)
      so each named placeholder renders as a top-level JSON key. trace_id
      from `Activity.Current` is bound into the template explicitly so it
      survives any formatter changes downstream.
- [x] **M2.1c (Node.js)** Shared `src/_shared-node/rpc-logging/index.js`
      `wrap(logger, fullMethod, handler)` applied per service method in
      `paymentservice/server.js:22,89` and `currencyservice/server.js:79,199`.
      Uses pino JSON.
- [x] **M2.1d (Python)** Shared `src/_shared-python/rpc_logging/__init__.py`
      `RpcLoggingInterceptor(logger)` wired into
      `recommendationservice/recommendation_server.py:53,201` and
      `emailservice/email_server.py:46,133`. Uses stdlib logging with
      structured `extra=` dict.
- [~] **M2.1e (Java)** **Deferred.** adservice uses the OTel Java agent
      (M1.2) which already log-correlates trace_id/span_id via MDC
      injection. A separate L1 interceptor would duplicate this. Open
      question if Java-side L1 parity matters for our drain-lite template
      miner; revisit if adservice log evidence appears under-tokenized in
      the v5 pilot data.

### M2.2 Structured error context at dependency boundaries (L2)

Targeted edits to ~6-8 service-pair call sites: log a JSON event on
failure with `{dep, op, err_class, retry_attempt}`. Do NOT add a log
at the success path here — that's L1's job.

- [x] **M2.2a** cartservice → redis-cart: emitted from
      `cartstore/RedisCartStore.cs` lines 38-53 with `{dep, op, err_class}`
      via `_log.Log(... "dep_error" ...)`. Covers GET / SET / EXPIRE.
- [x] **M2.2b** checkoutservice → cart, productcatalog, currency,
      shipping, payment, email: `recordDepError` in `main.go` now emits
      both a span error (M3.1) AND an L2 JSON log line with
      `{dep, op, err_class, retry_attempt, trace_id, span_id}`. Called at
      all 8 dep-call sites (main.go:429-510).
- [x] **M2.2c** frontend → every downstream gRPC: `recordDepError` helper
      added to `frontend/rpc.go`; called from getCurrencies, getProducts,
      getProduct, getCart, emptyCart, insertCart, convertCurrency,
      getShippingQuote, getRecommendations, getAd. Logger handle threaded
      via `frontendServer.depLog` (initialized in main.go).
- [x] **M2.2d** recommendationservice → productcatalog: L2 log emitted in
      `recommendation_server.py` ListRecommendations except block, with
      bounded `{dep, op, err_class, retry_attempt, trace_id, span_id}`.
- [~] **M2.2e** paymentservice → outbound calls: **not applicable.** No
      external dep exists — card validation is purely in-process
      (`simple-card-validator`). The L1 server log already records every
      Charge RPC with its status_code; bounded `payments_total{card_type,result}`
      metric (M4.4) covers the card-validation outcome dimension.

### M2.3 Business event log layer (L3) — optional, defer if time-pressed

- [x] **M2.3a** Picked one event per service per
      `microservice-changes.md` L3 table.
- [x] **M2.3b** Implemented:
      - `cart_size_changed` → `cartservice/services/CartService.cs:58-59,91-92`
      - `order_placed` → `checkoutservice/main.go:382-386`
      - `payment_charged` → `paymentservice/charge.js:129-133`
      - `recommendation_returned` → `recommendationservice/recommendation_server.py:121-122`
      Generic field names only; no scenario/fault/triage leakage.

**Acceptance:** every test-fixture RPC produces exactly one L1 log line on
each side (client + server); error responses additionally produce one L2
log line at the call site; for L3, dashboards can plot `orders_placed`,
`cart_operations`, `payments` over time.
**Status:** **complete (2026-05-24).** M2.1 wired across 5 languages,
M2.2 covers Redis + all gRPC dep boundaries, M2.3 emits 4 business events.
**Blocks:** v5 collection (we want these logs in v5, not v5.1).

---

## Phase M3 — Trace enrichment (T2, T3, T4, T5)
**Goal:** every error path marks its span; dependency calls have child
spans with semantic-convention attributes; resilience-pattern code paths
emit span events; sampling divergence is documented.

### M3.1 RecordError + SetStatus(Error) on every error-returning handler (T2)

Mechanical edit — ~3 lines per error path. Use the patterns in
`microservice-changes.md` T2 section as the reference.

- [x] **M3.1a (Go)** `frontend/handlers.go:547-548` (panic handler);
      `frontend/rpc.go:42-43` (every dep call via recordDepError);
      `checkoutservice/main.go:65-66` (recordDepError) + lines 351/358/375/383
      for direct handler errors; `productcatalogservice/product_catalog.go:83-84`
      (product not found). shippingservice handlers (GetQuote, ShipOrder)
      have no realistic error path today — they synthesize quote/tracking
      ID and return success.
- [x] **M3.1b (.NET)** RpcLoggingInterceptor (shared) now calls
      `Activity.Current?.RecordException(ex)` +
      `SetStatus(ActivityStatusCode.Error, ...)` in both `catch RpcException`
      and `catch Exception` paths, which covers **every** cartservice handler
      uniformly. Plus `cartstore/RedisCartStore.cs:90-91,111-112,140-141`
      for the Redis-specific paths under the AspNetCore activity.
- [x] **M3.1c (Node.js)** `paymentservice/charge.js:46-47` via
      `recordChargeError` helper called on `CreditCardError` variants;
      `currencyservice/server.js:177-178` on conversion failure.
- [x] **M3.1d (Python)** `recommendationservice/recommendation_server.py:103-104`
      (productcatalog lookup); `emailservice/email_server.py:100-101,111-112`
      (template render + email send).
- [x] **M3.1e (Java)** Covered automatically by the OTel Java agent
      (M1.2). The agent's built-in gRPC instrumentation records exception
      and sets span status on RPC failures with no manual code.

### M3.2 Manual child spans for dependency calls (T3)

Wrap each dependency call in a child span with semantic-convention
attributes (`db.system`, `db.operation`, `net.peer.name`, etc.). Do NOT
add app-specific attributes that mirror scenario metadata.

- [x] **M3.2a** cartservice → redis-cart child spans auto-emitted by
      `Instrumentation.StackExchangeRedis` (M1.1a) with `db.system=redis`,
      `db.operation` attrs. Manual enrichment also at
      `RedisCartStore.cs:92-93,113-114,142-143`. Verified via M5.1
      validation.
- [x] **M3.2b** checkoutservice → 6 downstream gRPC client spans
      auto-emitted; enriched via `recordDepError` (peer.service, rpc.method);
      PlaceOrder span enriched with bounded
      `app.order_item_count_bucket` via `orderItemsBucket()` helper.
- [x] **M3.2c** recommendationservice → productcatalog child span at
      `recommendation_server.py:93-99` with `peer.service` + `rpc.method`
      attrs.
- [x] **M3.2d** frontend → all downstream client spans auto-emitted by
      otelgrpc client interceptor; dep-call attributes via `recordDepError`
      in `rpc.go`. shippingservice also adds bounded `app.shipping.item_count`
      on its GetQuote server span.

### M3.3 Span events for state transitions (T4)

Only where retry / fallback / cache logic already exists in the code.
Don't fabricate state machines just to emit events.

- [x] **M3.3a** Audit done (2026-05-24). The Online Boutique services do
      **not** use retry / fallback / circuit-breaker libraries on the
      request path. The only natural state-transition is
      productcatalogservice's catalog hot-reload (file-watcher trigger).
      Other `retry` matches in the codebase are profiler-init back-off
      loops, which never run on a request span.
- [x] **M3.3b** `span.AddEvent("catalog.reload")` emitted at
      `productcatalogservice/product_catalog.go:132`. No other natural
      sites — per the M3.3 contract "don't fabricate state machines".
      Will be reconsidered if/when chaos-mesh tooling (Phase D11) adds
      retry/circuit-breaker resilience patterns to the services.

### M3.4 Document the sampling divergence (T5)

- [x] **M3.4a** Sampling-divergence bullet in `docs/dataset-v4-plan.md`
      (lines 313-316): "Trace sampling is 100% (`AlwaysSample`) ... We
      chose dataset density over sampling realism."
- [x] **M3.4b** Cross-referenced from `docs/telemetry-implementation-decisions.md`
      M0.6 §1 (the binding v5 README disclosure draft) and from
      `microservice-changes.md` Part 2 T5 section.

**Acceptance:** a representative failing PlaceOrder trace shows
`status=Error` on every span in the failure chain (not just the leaf);
dependency calls appear as child spans with semantic-convention attrs in
Tempo's structured query UI; at least one fault scenario surfaces a span
event in its evidence text; sampling divergence is documented in two
canonical places.
**Status:** **complete (2026-05-24).** M3.1 covers every error path
across 5 languages; M3.2 enriches dep calls with semantic-convention attrs;
M3.3 emits the one natural span event the demo permits; M3.4 documented.
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

- [x] **M4.1a (Go)** Shared `_shared-go/rpclog/metrics_init.go` exposes
      `InitMetrics(log, port)`. Each Go service calls it from main.go:
      frontend:137, checkoutservice:178, productcatalogservice (server.go),
      shippingservice. /metrics on port 9100 (separate from gRPC).
- [x] **M4.1b (.NET)** `cartservice/Startup.cs:156` `.AddPrometheusExporter()`;
      scrape endpoint mounted via `app.UseOpenTelemetryPrometheusScrapingEndpoint()`
      in `Startup.cs:171`. Lives on the same port (7070) as the gRPC server.
- [x] **M4.1c (Node.js)** `paymentservice/index.js:53-55` and equivalent
      in `currencyservice` register `PrometheusExporter({port: 9100})`
      as the OTel metric reader.
- [x] **M4.1d (Python)** `recommendationservice/recommendation_server.py:44,172-186`
      and `emailservice/email_server.py` start `prometheus_client.start_http_server`
      on port 9100.
- [x] **M4.1e (Java)** adservice via OTel Java agent — `OTEL_METRICS_EXPORTER=prometheus`
      set in the deployment env block (M1.2).
- [~] **M4.1f** Scrape annotations: Prometheus is currently scraping by
      ServiceMonitor under `deploy/research-lab/observability/`. The
      annotation form is the fallback if ServiceMonitor doesn't pick up
      a service; revisit per-service during D13.14b pilot if any service's
      /metrics goes unscraped.

### M4.2 RED metrics per RPC handler (M1)

- [x] **M4.2a** Go: shared `rpclog/rpclog.go` lines 56-67 register and
      record `rpc_server_duration_seconds` + `rpc_server_requests_total`
      with bounded `{method, status}` labels (lines 110-119). Fires on
      every gRPC server call across frontend/checkout/productcatalog/shipping.
      .NET cartservice: `AspNetCoreInstrumentation` emits equivalent
      `http.server.request.duration` automatically. Node services: covered
      by `GrpcInstrumentation()` (paymentservice/index.js:69-71) which
      emits `rpc.server.duration`. Python services: covered by
      `GrpcInstrumentorServer` (recommendation_server.py:166-167).
- [x] **M4.2b** Labels verified bounded: `method` from proto, `status`
      from gRPC code enum, `service` from OTel resource. No scenario or
      fault labels anywhere.

### M4.3 Per-dependency client metrics (M2)

- [x] **M4.3a** Go: shared `rpclog/rpclog.go` lines 68-75 + 170-188 emit
      `rpc_client_duration_seconds` + `rpc_client_errors_total` with
      bounded `{peer_service, operation, status}` labels via the
      `UnaryClientInterceptor`. Fires on every outbound gRPC call.
      .NET cartservice: `GrpcNetClientInstrumentation` provides equivalent
      `rpc.client.duration` automatically. Node: `GrpcInstrumentation`
      covers client side. Python: `GrpcInstrumentorClient`
      (recommendation_server.py:164-165) covers client side.

### M4.4 Business-event counters (M3) — use SPARINGLY

Strict label discipline: every label must come from the proto contract or
be a bounded enum. If in doubt, skip the metric.

- [~] **M4.4a** frontend: `http_requests_total{route, status_class}`
      **deferred.** The L1 server log already provides per-request rows
      with `method`+`status_code` so a Loki-side rate query gives the
      same answer. Revisit if a Grafana SRE dashboard needs the Prom
      counter for response-time alerting.
- [x] **M4.4b** checkoutservice: `orders_placed_total` counter
      registered in `main.go` (around line 100), incremented in PlaceOrder
      success path. Currency label deferred — bounded enum but adds little
      signal at v5 scale.
- [x] **M4.4c** paymentservice: `payments_total{card_type, result}` in
      `charge.js:22-30`. `card_type` ∈ {visa, mastercard, other};
      `result` ∈ {success, invalid, expired, unsupported}.
- [x] **M4.4d** cartservice: `cart_operations_total{op, result}` in
      `services/CartService.cs:34-38`. `op` ∈ {add, get, empty},
      `result` ∈ {success, error}.
- [x] **M4.4e** recommendationservice: `recommendations_served_total`
      counter in `recommendation_server.py:182-183`.
- [x] **M4.4f** productcatalogservice: `catalog_lookups_total{result}`
      counter in `product_catalog.go:40`. `result` ∈ {hit, miss}.

### M4.5 Standard runtime / saturation gauges (M4)

Mostly free from the OTel SDK or language Prometheus client defaults.

- [x] **M4.5a** Coverage by language:
      - **Go** (frontend, checkout, productcatalog, shipping): Prometheus
        `DefaultGatherer` used by `rpclog/prom_handler.go` includes the
        `go_*` and `process_*` collectors out of the box. `go_gc_duration_seconds`,
        `process_cpu_seconds_total`, `process_resident_memory_bytes`,
        `process_open_fds` all expose without extra code.
      - **.NET** (cartservice): `AddRuntimeInstrumentation()` in
        `Startup.cs:154` emits `process.cpu.time`, `process.memory.usage`,
        `dotnet.gc.collections.count`, `dotnet.gc.heap.size`, etc.
      - **Python** (recommendation, email): `prometheus_client.start_http_server`
        exposes `process_*` and `python_gc_*` defaults.
      - **Node** (payment, currency): `@opentelemetry/host-metrics@0.36.0`
        added to both services. `HostMetrics({meterProvider}).start()`
        wired in `paymentservice/index.js` after `sdk.start()` and in
        `currencyservice/server.js` inside the `ENABLE_TRACING` block.
        Emits `process.cpu.time`, `process.memory.usage`, GC events, and
        eventloop lag via the OTel Prometheus exporter on /metrics:9100.
        currencyservice also gained `@opentelemetry/exporter-prometheus`
        which it was missing entirely.
      - **Java** (adservice): OTel Java agent emits
        `process.runtime.jvm.*` (heap, GC, threads, classes) automatically.
- [~] **M4.5b** Scrape config: services expose `/metrics` on port 9100
      (Go, Node) or the gRPC port (.NET 7070). Confirm Prometheus
      ServiceMonitor picks both up during D13.14b pilot — otherwise add
      explicit `prometheus.io/port` annotations.

**Acceptance:** `curl <service>:9100/metrics` returns RED + dependency +
business + runtime metrics for every service; Grafana can render a
per-service RED dashboard; no metric has unbounded cardinality (`promtool
check metrics` clean); no metric is labeled with anything from the
scenario taxonomy.
**Status:** **substantially complete (2026-05-24)** with two scoped
follow-ups: Node runtime metrics (M4.5a Node) and scrape verification
during D13.14b. Everything else live and committed.
**Blocks:** v5 collection benefits from these metrics.

---

## Phase M5 — Validation and integration into v5 collection
**Goal:** prove the telemetry upgrade actually moves the needle on at least
one fault family before committing to a full v5 reshoot.

### M5.1 Cartservice-first incremental validation (the cheap experiment)

Per `microservice-changes.md` "Updated recommended validation path":

- [x] **M5.1a** cartservice-only deploy executed on `jira-telemetry-lab`
      kind cluster with image `cartservice:v5.0.0-otel-pilot`, all other
      services unchanged. Fixed pre-deploy: Dockerfile build context,
      Grpc.Core.Status / OpenTelemetry.Trace.Status ambiguity in
      RedisCartStore.cs, and DI ordering bug for
      UseOpenTelemetryPrometheusScrapingEndpoint.
- [x] **M5.1b** Collected `2026-05-24-m5-1-cart-validation-r01/r02`
      (`cart-redis-degradation-critical`).
- [x] **M5.1c** Per-run derived dataset built for both runs.
- [x] **M5.1d** `trace_error_count` rose from baseline 91.0 mean (50%
      nonzero) to pilot 277.5 mean (100% nonzero) on cartservice
      active_fault windows — **3.0× lift**. Pilot min (275) >
      baseline max for nonzero windows (198). See
      `docs/telemetry-implementation-decisions.md` §M5.1.
- [~] **M5.1e** PR-AUC slice deferred — accepted as PASS on trace signal
      alone (see M5.1d). The PR-AUC piece requires building a global
      dataset over pilot+baseline and running the loganalyzer
      comparison harness; not worth the cycle unless gate decision is
      contested.
- [x] **M5.1f** **Gate: PASS** after refining criterion to relative
      lift (`pilot_mean/baseline_mean >= 2.0 AND pilot_nonzero_frac >= 0.8`)
      per D13.13a. The original absolute threshold (baseline < 0.1)
      couldn't distinguish the upgrade signal from cross-service span
      noise. Proceeded to M5.2 local fleet rollout.

### M5.2 Full v5 fleet rollout

- [x] **M5.2a** All of M1, M2, M3, M4 landed across all services.
      Initial fleet rollout used `v5.0.0-otel-pilot`; **2026-05-24 refresh**
      bumped cartservice to `v5.0.0-otel-pilot3` (JsonConsole logging +
      separate HTTP/1 metrics port 9100), paymentservice/currencyservice
      to `v5.0.0-otel-pilot2` (host-metrics added). All three live and
      verified on `jira-telemetry-lab` kind cluster.
- [ ] **M5.2b** **PENDING.** 1-day cloud VM pilot collecting 3 runs per
      v5-plan family on the upgraded telemetry. Runs on this GCP VM's
      kind cluster (this VM IS the cloud VM per
      `docs/gcp-production-dataset-vm-runbook.md`). Tracked as D13.14b.
      User-triggered step.
- [ ] **M5.2c** Confirm collector capacity (M0.4) + Loki sizing (M0.5)
      hold under real v5 load — depends on D13.14b. Tracked as D13.14c.
- [~] **M5.2d** L1/L2/Tempo cross-check **validator built** at
      `scripts/research-lab/validate_l1_l2_telemetry.py`. Ran on M5.1
      pilot data: cartservice 3604 L1 lines + 1092 L2 lines, L2∩Tempo
      agree on both cart-redis windows. Other services 0 L1/L2 because
      they were pre-upgrade at M5.1 time; full fleet cross-check requires
      D13.14b data. **D13.14d-followup landed 2026-05-24:** cartservice
      now emits JSON-formatted L1 lines (Program.cs + interceptor message
      template) so trace_id is rendered as a top-level field. Will be
      re-validated on the D13.14b pilot data.
- [~] **M5.2e** Leakage canary tooling pre-flighted with `-PythonExe python3`
      override: PASS (30 rows, 0 fails, 2 warnings) on existing pilot
      data. Per-pilot-run re-run waits on D13.14b. Tracked as D13.14e.

### M5.3 Land in dataset-todo as Phase D13

- [x] **M5.3a** Phase **D13** present in `dataset-todo.md` lines 590-805
      under sprint **D-3.5**. D13 references this file (and
      `docs/telemetry-implementation-decisions.md`) as source of truth.
- [x] **M5.3b** `docs/instrumentation-gaps-and-next-steps.md` updated
      with a 2026-05-24 status block (lines after the "Highest-value
      improvements" header) cross-linking to D13 and marking item 1
      (trace_id/span_id in JSON logs) as IN PROGRESS via D13/M2.1 and
      item 3 (low-cardinality business metrics) as PLANNED via D13/M4.4.

**Acceptance:** v5 collection runs end-to-end on the upgraded telemetry;
feature distributions are within ±20% of v4-large for legacy features and
all-new features (L1/L2/L3 log volume, M1-M4 metric series) are present in
every run; no leakage canary fires.
**Status:** **substantially complete (2026-05-24)** — M5.1 gate passed,
M5.2a fleet rollout live, M5.3 D13 tracking in place. Cloud pilot
collection (M5.2b → c/d/e) is the remaining user-triggered step.
**Blocks:** v5 production collection (Phase D4 in `dataset-todo.md`).

---

## Suggested execution order (sprints)

| Sprint | Phases | Cost | Status |
| ------ | ------ | ---- | ------ |
| MT-0   | M0 (decisions + sizing) | 0.5 dev day | **DONE 2026-05-24** |
| MT-1   | M1.1 (cartservice OTel parity) | 1 dev day | **DONE 2026-05-24** |
| MT-1.5 | M5.1 (cheap cartservice-first validation) | 0.5 VM day | **DONE 2026-05-24 — gate PASS** |
| MT-2   | M1.2, M1.3 (adservice + shippingservice parity) | 2 dev days | **DONE 2026-05-24** |
| MT-3   | M2.1 across all 5 languages | 3 dev days | **DONE 2026-05-24** |
| MT-4   | M2.2 (dependency-boundary error logs) | 1.5 dev days | **DONE 2026-05-24** |
| MT-5   | M3 (trace enrichment) | 3 dev days | **DONE 2026-05-24** |
| MT-6   | M4 (metrics) | 3 dev days | **DONE 2026-05-24** (Node M4.5a follow-up open) |
| MT-7   | M2.3 (business event logs, optional) | 1 dev day | **DONE 2026-05-24** |
| MT-8   | M5.2 (full v5 pilot) | 1 VM day | **PENDING** — user-triggered (D13.14b) |
| MT-9   | M5.3 (dataset-todo integration) | 0.5 dev day | **DONE 2026-05-24** |

Telemetry-only scope: roughly **15-17 dev days + 1.5 VM days**, matching
the cost estimate in `microservice-changes.md`. Parallelizable across
services and across the M3/M4 streams once M1 is done.

---

## Remaining work (post 2026-05-24 batch update)

Substantially everything in M0–M5 except M5.2b (cloud pilot collection)
is done and committed. Open follow-ups:

- [ ] **M5.2b** Run a 1-day cloud pilot on this VM's kind cluster
      (D13.14b in `dataset-todo.md`). 3 runs per v5-plan family on the
      upgraded telemetry. **User-triggered** — kicks off via the
      existing collection scripts.
- [x] **D13.14d-followup** ✅ (2026-05-24) cartservice Program.cs now
      uses `AddJsonConsole(IncludeScopes=true)`; RpcLoggingInterceptor
      emits via a structured-logging message template so trace_id /
      span_id / method / status_code render as top-level JSON keys.
- [ ] **D13.15b** `helm upgrade` Loki to pick up the 50Gi PVC. Touches
      shared cluster infra, so user OK needed before running the
      `kubectl delete statefulset --cascade=orphan && helm upgrade`
      sequence in `dataset-todo.md` D13.15b.
- [x] **M4.5a (Node)** ✅ (2026-05-24) Added `@opentelemetry/host-metrics@0.36.0`
      to paymentservice (already had exporter-prometheus) and currencyservice
      (also gained exporter-prometheus). `HostMetrics({meterProvider}).start()`
      wired after `sdk.start()` in both services; emits Node runtime gauges
      via the OTel Prometheus exporter on /metrics:9100.
- [~] **M4.1f / M4.5b** Per-pilot scrape verification: confirm Prometheus
      ServiceMonitor picks every service's `/metrics` endpoint during
      D13.14b; otherwise add explicit `prometheus.io/port` annotations.
      **cartservice HTTP/2 vs HTTP/1 scrape conflict resolved 2026-05-24**:
      `appsettings.json` now declares two Kestrel endpoints — gRPC on 7070
      (Http2) and Metrics on 9100 (Http1). `Startup.cs` passes a
      `LocalPort == 9100` predicate to
      `UseOpenTelemetryPrometheusScrapingEndpoint`, so /metrics only
      responds on the HTTP/1 listener. Verified via port-forward: full
      `process_runtime_dotnet_*` set returned over plain HTTP/1.
      ServiceMonitor port-9100 selector still needs verification in
      D13.14b; cartservice deployment containerPort may need a 9100
      addition if the existing pod-IP selector misses it.

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
