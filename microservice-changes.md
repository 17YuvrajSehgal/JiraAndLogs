# Microservice Telemetry Improvements (Online Boutique)

**Created:** 2026-05-24
**Last updated:** 2026-05-24 (added trace/metrics section)
**Status:** proposal / future reference
**Related:** `dataset-todo.md` (suggested as new Phase D13),
`docs/instrumentation-gaps-and-next-steps.md` (existing repo-side gap list),
`src/logsense/README.md` (why logsense underperforms loganalyzer on v4-large)

This file captures concrete proposals to improve **logs, traces, and metrics**
emitted by the Online Boutique microservices, so the dataset we collect is
closer to what a real production observability stack would see.

**Hard constraint (read this first):** every change here must be something a
real production microservice would emit anyway. The goal is **realism, not
favouring our product**. Anything that effectively leaks the injected fault
into the telemetry stream is rejected, because it would inflate our model
scores without representing real on-call conditions. If we wouldn't see it at
a typical SaaS company in 2026, we don't add it.

The user's fork of `microservices-demo-google/` is what we'd patch and
redeploy from; the upstream Google repo stays untouched conceptually so we
can rebase later if needed.

---

## Why this matters for our pipeline

Two consumers care about logs differently:

| Consumer | What it uses | Why richer logs help |
| --- | --- | --- |
| `src/logsense` | Raw Loki bodies → Drain-lite template miner → per-window template counts + anomalous-template surfacing | More distinct, well-structured log events = more templates = more learnable signal. Logsense is currently much weaker than loganalyzer (PR-AUC **0.49** vs **0.72** on v4-large), and sparse logging is a major reason. |
| `src/loganalyzer` | Aggregate columns `log_error_count`, `log_warning_count`, `log_total_count` | Consistent severity tagging directly raises signal-to-noise on these features. |
| `src/jira_features` | BM25 over evidence text against time-ordered Jira memory | Richer log text that matches the wording in past Jira tickets lifts retrieval recall@k and MRR. |

## Current state of logging in each service

`microservices-demo-google/` is a real clone of Google's repo (its own `.git`,
full source). Workflow to redeploy is already wired: edit source → rebuild
image → load into kind via `apply-online-boutique.ps1`. Logs flow stdout →
Alloy → Loki → `data/runs/<id>/raw/loki/`.

| Language | Services | Logger today | Quality |
| --- | --- | --- | --- |
| Go | `frontend`, `checkoutservice`, `productcatalogservice`, `shippingservice` | `logrus` JSON (timestamp/severity/message keys) | decent shape, but mostly init + ad-hoc info; few structured fields per request |
| C#/.NET | `cartservice` | `Microsoft.Extensions.Logging` | barely used; almost silent outside exceptions |
| Node.js | `paymentservice`, `currencyservice` | `pino` JSON with severity formatter | decent shape, sparse content |
| Python | `recommendationservice`, `emailservice`, `loadgenerator`, `shoppingassistantservice` | stdlib `logger` | basic; mostly startup messages |
| Java | `adservice` | (likely SLF4J/logback; not inspected) | — |

## The trap to avoid (research integrity)

The entire research story depends on **lab-vs-production fidelity**. If we log
things real microservices don't, we artificially inflate our own scores.

- **Don't** add anything that effectively leaks the fault label
  (e.g., `"REDIS UNAVAILABLE — this is a ticket-worthy event"`).
- **Don't** add per-scenario tags, scenario ids, or anything tied to the
  injected fault.
- **Do** add only what real production services already emit.

This rule is non-negotiable — it's what separates "honest dataset improvement"
from "I made my benchmark go up."

## Three concrete, high-leverage changes (priority order)

### 1. Per-RPC structured request log (highest leverage)

Wire a gRPC/HTTP interceptor in each language that emits **one structured log
per RPC**:

```json
{
  "trace_id": "...",
  "method": "hipstershop.CartService/AddItem",
  "peer_service": "frontend",
  "latency_ms": 42,
  "status_code": "OK",
  "err_class": null
}
```

Why: this is what real production services emit anyway, it's pipeline-agnostic,
and it gives `logsense` per-request template diversity across every service for
~50 lines of code per language. Also aligns log evidence with the trace
features `loganalyzer` already uses (`trace_error_rate`, `trace_latency_p95_ms`).

### 2. Structured error context at dependency boundaries

Where cartservice calls Redis, where checkout calls payment, etc., log on
failure:

```json
{
  "dep": "redis-cart",
  "op": "GET",
  "err_class": "ConnectTimeoutException",
  "retry_attempt": 2
}
```

Why: this is exactly what humans grep postmortems for, and it makes the
Drain-lite templates discriminative for the right reason — the *shape* of the
failure, not the fault name. Directly raises template-level discriminative
power for the cart-redis, payment-outage, checkout-outage families.

### 3. Business event log layer

Emit semantic events: `cart_size_changed`, `order_placed`, `payment_charged`,
`recommendation_returned_n_items`, `currency_conversion_completed`.

Why: gives logsense's anomaly model real "shape" to anchor against baselines.
A drop in `order_placed` count during active_fault is a strong, label-free
signal.

# Part 2: Trace and metric improvements

This section covers the **distributed trace** and **application metrics**
side. Same hard constraint applies — every change must be production-realistic
and not encode the injected fault label.

## Current trace state, per service

| Service | Lang | OTel SDK? | Auto gRPC/HTTP server spans? | Auto client spans? | Manual spans? | Span attrs / events? | Records errors on span? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `frontend` | Go | yes | yes (`otelhttp`) | yes (`otelgrpc`) | no | no | no |
| `checkoutservice` | Go | yes | yes (`otelgrpc`) | yes (`otelgrpc`) | no | no | no |
| `productcatalogservice` | Go | yes | yes | yes | no | no | no |
| `shippingservice` | Go | partial — listed as gap in `docs/instrumentation-gaps-and-next-steps.md` | — | — | no | no | no |
| `paymentservice` | Node.js | yes (`@opentelemetry/sdk-node` + `GrpcInstrumentation`) | yes | yes | no | no | no |
| `currencyservice` | Node.js | yes | yes | yes | no | no | no |
| `recommendationservice` | Python | yes (`GrpcInstrumentorServer/Client`) | yes | yes | no | no | no |
| `emailservice` | Python | yes | yes | yes | no | no | no |
| `adservice` | Java | partial — listed as gap | — | — | no | no | no |
| `cartservice` | C#/.NET | **NONE** — zero OTel imports | **NO** | **NO** | no | no | no |
| `loadgenerator` | Python | partial | client-side only | — | no | no | no |

Sampling everywhere is `AlwaysSample()`. Propagator is W3C `TraceContext` +
`Baggage` everywhere it's wired.

### What this means

We get one server span and one client span per RPC, and that's it. Every
trace is a flat "fan-out" of RPC calls with **no internal structure** — no
"cache lookup" sub-span, no "validate credit card", no "currency conversion",
no "DB query". When something goes wrong, the trace shows *that* an RPC
returned an error code but never *what* part of the handler failed.

The most damaging single gap is **cartservice has no tracing at all**.
Cartservice is the service touching Redis in our cart-redis fault family —
the most-collected family in v4-large (720 windows). Every cartservice
trace is effectively invisible, which is why trace-derived features under-fire
for that family.

## Why richer traces are realistic (and why our pipeline benefits as a side-effect)

These are things production services routinely have:

| Production-realistic addition | Why real services do it | Side-benefit for our pipeline |
| --- | --- | --- |
| `RecordError(err)` + `SetStatus(Error)` on the span when handler returns an error | Standard OTel idiom; auto-instrumentation only marks the RPC envelope, not internal failures | `loganalyzer.trace_error_count` becomes more accurate; today some errors are silent on the span |
| Manual child spans for dependency calls (Redis, SQL, Memcached, outbound HTTP) | Every production trace-instrumented service does this — it's the whole point of OTel | More trace structure → trace-shape features (root-service, span fan-out) become discriminative; also exposes the Redis dependency that's currently invisible in cartservice |
| Semantic-convention span attributes: `db.system`, `db.statement` (parameterized!), `net.peer.name`, `http.status_code`, `rpc.grpc.status_code`, `messaging.destination` | OTel semantic conventions — every modern instrumentation library emits these | Gives Tempo the structured fields that on-call dashboards (and our raw evidence text) actually query against |
| Span events for state transitions: `cache.miss`, `cache.hit`, `retry.attempt`, `circuit_breaker.open`, `fallback.used` | Common in production resilience libraries (Hystrix, Resilience4j, Polly) | Span events end up in the Tempo body text that flows into our BM25 retriever and into logsense's evidence text |
| `service.version` and `deployment.environment` resource attributes | OTel resource semantic conventions, required for any production deployment tracker | Lets us link traces to deploy events (relevant for `post-deploy-churn` family in v5) |
| Log↔trace correlation: every log line includes `trace_id` and `span_id` | This is **the** single most-cited production observability best-practice; every doc from Datadog, New Relic, Honeycomb, Grafana, etc. opens with it | Already in `docs/instrumentation-gaps-and-next-steps.md` as gap #1. Lets the retriever join logs and traces at the request level. |

None of these encode "a fault was injected" or "this scenario is X". They
encode *what the service was doing*, which is exactly what a real production
trace records.

## Concrete trace changes (priority order)

### T1. Add baseline OTel tracing to the missing services

- **cartservice (.NET):** wire up `OpenTelemetry.Extensions.Hosting`,
  `OpenTelemetry.Instrumentation.AspNetCore`, `OpenTelemetry.Instrumentation.GrpcNetClient`,
  `OpenTelemetry.Instrumentation.StackExchangeRedis`. **This last package is
  the highest-leverage single change in this entire document** — it gives us
  per-Redis-operation spans automatically, which the cart-redis fault family
  needs to be visible.
- **adservice (Java):** add OpenTelemetry Java agent or the manual SDK with
  `opentelemetry-instrumentation-grpc-1.6`. Java agent is the standard
  production approach — zero code changes, drop-in JAR.
- **shippingservice (Go):** add the same `otelgrpc` server+client interceptors
  that the other Go services already use.

This is pure parity work — bringing the laggards up to where the rest of the
fleet already is. No "research bias" risk.

### T2. Add `RecordError` + `SetStatus(Error)` to every error-returning handler

Pattern (Go):

```go
span := trace.SpanFromContext(ctx)
if err != nil {
    span.RecordError(err)
    span.SetStatus(codes.Error, err.Error())
    return nil, err
}
```

Equivalent in C#, Java, Node, Python. This is the OTel idiomatic pattern and
costs ~3 lines per error path. Today many handlers return errors that the
auto-instrumentation does mark on the RPC envelope, but internal handler
errors and panics are silent.

### T3. Manual child spans for dependency calls

In every service that calls Redis / a DB / an external HTTP API, wrap that
call in a child span with semantic-convention attributes:

```go
ctx, span := tracer.Start(ctx, "redis.GET cart",
    trace.WithAttributes(
        attribute.String("db.system", "redis"),
        attribute.String("db.operation", "GET"),
        attribute.String("net.peer.name", redisAddr),
    ),
)
defer span.End()
```

Specifically:

- `cartservice` → `redis-cart` (already covered by T1's `Instrumentation.StackExchangeRedis`)
- `checkoutservice` → each of `cart`, `productcatalog`, `currency`, `shipping`, `payment`, `email`
  (these are already gRPC client spans, but they should have attributes like
  `app.order_subtotal_currency`, `app.order_item_count`)
- `recommendationservice` → `productcatalog` lookup
- `frontend` → all 8 downstream gRPC services + any HTTP outbound

### T4. Span events for state transitions

In code paths with retries, fallbacks, circuit breakers, cache lookups,
add `span.AddEvent("cache.miss", attrs...)` style events. Production
resilience libraries (Resilience4j, Polly, gobreaker) emit these natively —
the Online Boutique services just don't use those libraries today.

For us, these events end up in the Tempo span body that our exporter
includes in evidence text, so they become tokens for both BM25 retrieval
and the Drain-lite template miner.

### T5. Sampling configuration: leave at AlwaysSample for research, document the gap

Production traces are typically head-sampled at 1-10% or tail-sampled on
errors/latency. We use `AlwaysSample` because we want every span for
dataset density. **This is a known divergence from production** and should
be called out in any paper — models trained on 100%-sampled traces may
not transfer directly to 1%-sampled production environments.

We do **not** change this for v5. But we should note it in
`docs/dataset-v4-plan.md` "Current Limitations" so it's transparent.

## Concrete metric changes (priority order)

Right now the only metrics we have are:

- cAdvisor: per-container CPU and memory
- kube-state-metrics: replica counts, restart counts, rollout state
- OTel-collector-derived spanmetrics: rate/error/duration from spans

Zero application-level metrics are emitted by any service. That's not a
research bias issue — it's just a coverage gap. Production services
typically expose a handful of business + dependency metrics on a `/metrics`
endpoint scraped by Prometheus.

### M1. RED metrics per RPC handler (rate / errors / duration)

Today derived from spans. That works but loses fidelity at high traffic
(spanmetrics aggregates lossily). Production services typically also expose
direct Prometheus counters/histograms per handler:

```
rpc_server_duration_seconds_bucket{service="checkoutservice", method="PlaceOrder", status="OK"} ...
rpc_server_requests_total{service="checkoutservice", method="PlaceOrder", status="OK"} ...
```

These are exactly what the OTel `MeterProvider` + Prometheus exporter give
for free if we add ~15 lines of init code per service.

### M2. Dependency call metrics

Per outbound dependency call: `rpc_client_duration_seconds`, `rpc_client_errors_total`,
labeled by `peer_service` and `operation`. Lets Prometheus answer "is the
cart→redis dependency degraded?" directly, instead of inferring from span
counts.

### M3. Business-event counters (use SPARINGLY)

A small handful of high-value counters that any real e-commerce service
would emit:

| Service | Metric | Why real services emit it |
| --- | --- | --- |
| `frontend` | `http_requests_total{route, status}` | basic SRE dashboard |
| `checkoutservice` | `orders_placed_total{currency}`, `order_value_usd_sum` | revenue dashboard, finance ops |
| `paymentservice` | `payments_total{card_type, result}` | fraud detection, billing recon |
| `cartservice` | `cart_operations_total{op, result}` | UX team, A/B test infra |
| `recommendationservice` | `recommendations_served_total{model_version}` | ML team, experimentation |
| `productcatalogservice` | `catalog_lookups_total{result}` | catalog team |

These are NOT a research bias because any real e-commerce platform tracks
exactly these. The risk to flag: do **not** add metrics whose label set
correlates 1:1 with our scenario taxonomy (e.g., never label by `fault_type`
or anything from `scripts/research-lab/triage_labels.py`).

### M4. Resource saturation gauges

`process_cpu_usage`, `process_memory_resident_bytes`, `process_open_fds`,
language-specific GC metrics (`go_gc_duration_seconds`, `dotnet_gc_*`,
`python_gc_*`, `nodejs_heap_size_total_bytes`). Standard runtime metrics
that every Prometheus client library emits by default — we just need to
expose `/metrics` on each service.

## What we are NOT adding (the bias-avoidance list)

These would be tempting because they'd help our model, but they encode
information a real production service wouldn't emit:

- Custom span attributes that name our scenarios (`scenario.id`, `fault.injected`, `expected_severity`)
- Metrics labeled by scenario family or fault type
- Log fields that hint at the triage label (`is_ticket_worthy=true`)
- Synthetic alerts that fire only when our injector runs
- Trace baggage that propagates our `dataset_run_id` through the app
- Any field listed in `docs/triage-task-contract.md` "Field Policy" as eval-only

If we add any of these, the resulting dataset is effectively self-labeled and
useless for honest benchmarking. The discipline matters more than any
single feature.

## Updated recommended validation path

Incremental, same shape as Part 1:

1. **cartservice (.NET) is the single highest-leverage starting point**, not
   checkoutservice as in Part 1. Reasons: (a) it has zero OTel coverage today,
   (b) the Redis StackExchange instrumentation package is drop-in, (c) the
   cart-redis fault family is our most-collected family in v4-large so the
   uplift will be statistically visible quickly.
2. Add OTel SDK + StackExchange.Redis instrumentation + RecordError on
   handler errors. Rebuild image, redeploy.
3. Collect 1-2 runs of `cart-redis-degradation-critical`. Measure:
   - Does `trace_error_count` rise on `active_fault` cartservice windows? (today
     it doesn't fire because there are no cartservice spans at all)
   - Does `loganalyzer` PR-AUC on cart-redis family move?
4. If yes → port the pattern to the rest of the .NET-equivalent OTel idioms
   in adservice (Java) and shippingservice (Go).
5. Then layer T2-T4 and metrics work across all services in priority order.

---

# Part 3: Cross-cutting plan items

## Suggested integration into the broader plan

Add as new phase **D13: Production-realistic instrumentation (logs + traces +
metrics)** in `dataset-todo.md`, sequenced **before D4 (v5 collection)** so
the upgraded telemetry lands in v5 rather than requiring a v5.1 reshoot.

- Belongs in sprint **D-3.5** alongside chaos-mesh tooling — it's pure dev
  work, no collection yet.
- Pairs naturally with **D11 (system faults)**: structured traces and
  per-dependency metrics make network/DNS/disk faults much more recognizable,
  since chaos-mesh faults often leave no application-level exception trail
  (a packet-loss fault never throws — it just makes spans slow).
- Pairs with **D12 (orphan faults)**: orphan-fault detection depends on the
  model learning the *shape* of a real fault from telemetry alone; richer
  spans and metrics give it more shape to learn.
- T1 (parity OTel coverage on missing services) should be done **first** —
  every later phase assumes those services emit traces.

## What this DOES NOT solve

- **Cross-app generalization (D6).** Only fixes Online Boutique; if we add
  Sock Shop / TrainTicket we'll re-do this exercise there.
- **Sampling realism.** We stay at `AlwaysSample` for dataset density;
  production typically uses 1-10% head sampling or tail-based on
  errors/latency. Document the gap, don't fix it for v5.
- **Latency-dominated fault detection from logs alone.** Better traces help
  loganalyzer catch productcatalog-latency, but log signal still won't match
  trace signal for those.
- **Real Jira-Cloud integration.** Out of scope; same as before.

## Open questions to resolve before starting

1. **Where do shared interceptors / middlewares live?** Per-service handwritten,
   or shared helper packages checked into
   `microservices-demo-google/src/_shared-<lang>/`? Shared is cleaner but means
   maintaining a fork divergence from upstream Google.
2. **Image registry.** Local kind has its own registry already; cloud VM
   needs GCR/Artifact Registry push. Confirm v5 cloud collection can pull
   the modified images.
3. **Upstream divergence policy.** The user has already forked
   `microservices-demo-google/` into their git, so we have a fork to commit
   to. Decide: do we track upstream Google's microservices-demo and rebase
   monthly, or hard-fork and accept divergence? Hard-fork is simpler now,
   but blocks free pickups of Google's improvements (new services, updated
   tracing libraries, security patches).
4. **OTel collector capacity.** With richer per-RPC spans, span events, and
   per-dependency child spans, the collector throughput goes up roughly 3-5×.
   Verify the kind cluster's OTel collector replica count and resource
   limits in `deploy/research-lab/observability/` before launching v5.
5. **Loki ingest volume.** Per-RPC structured logs at p95 traffic will
   multiply log volume substantially. Re-check Loki retention / disk sizing
   for the v5 cloud VM (`docs/gcp-production-dataset-vm-runbook.md`).
6. **Sampling fidelity disclosure.** Where in the paper / dataset README do
   we disclose that we're 100%-sampled? Suggest: a dedicated "Production
   fidelity" section in the v5 dataset README that lists every realism
   compromise we made (sampling, single-cluster, no real customer PII, no
   geo-distributed traffic).

## Summary of all changes proposed in this doc

| ID | Change | Domain | Bias risk? |
| --- | --- | --- | --- |
| L1 | Per-RPC structured request log via interceptor | Logs | none |
| L2 | Structured error context at dependency boundaries | Logs | none |
| L3 | Business-event log layer | Logs | low — keep labels generic |
| T1 | Bring cartservice, adservice, shippingservice to OTel parity | Traces | none |
| T2 | `RecordError` + `SetStatus(Error)` on every error-returning handler | Traces | none |
| T3 | Manual child spans for dependency calls with semantic-convention attrs | Traces | none |
| T4 | Span events for state transitions (cache miss, retry, fallback) | Traces | none |
| T5 | Document the 100%-sampling divergence; do NOT change it | Traces | none (a *disclosure* fix, not a code fix) |
| M1 | OTel MeterProvider + Prometheus exporter for RED metrics per RPC | Metrics | none |
| M2 | Per-dependency client metrics | Metrics | none |
| M3 | A handful of business-event counters (carefully chosen labels) | Metrics | low — bias only if labels mirror our scenario taxonomy |
| M4 | Standard runtime / saturation gauges | Metrics | none |

Every entry above is something a competent production SRE team would expect
from a microservice in 2026. Nothing in this list encodes our research
labels, scenario taxonomy, or injection mechanism.

## Open questions to resolve before starting

1. **Where does the interceptor live?** Per-service handwritten, or a shared
   helper library checked into `microservices-demo-google/src/_shared/`?
   Shared is cleaner but means maintaining a fork divergence from upstream
   Google.
2. **Image registry.** Local kind has its own registry already; cloud VM
   needs GCR/Artifact Registry push. Confirm v5 cloud collection can pull
   the modified images.
3. **Upstream divergence policy.** Do we track upstream Google's
   microservices-demo and rebase on it, or hard-fork? Hard-fork is simpler
   now, but blocks free pickups of Google's improvements (new services,
   updated tracing).
