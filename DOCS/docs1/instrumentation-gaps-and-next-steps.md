# Instrumentation Gaps and Next Steps

The research scaffold prepares Online Boutique for unified telemetry, but there are still important gaps before the dataset can be considered production-grade.

## Current state

Online Boutique already has partial OpenTelemetry tracing support:

- `frontend`
- `checkoutservice`
- `currencyservice`
- `emailservice`
- `paymentservice`
- `productcatalogservice`
- `recommendationservice`

Some services have limited or unavailable tracing:

- `adservice`
- `cartservice`
- `shippingservice`

The overlay still collects logs from all pods and Kubernetes metadata from all workloads, so these services remain useful for incident episodes even before perfect tracing exists.

The first dataset acquisition workflow now exists:

- `scripts/research-lab/start-dataset-run.ps1`
- `scripts/research-lab/run-scenario.ps1`
- `scripts/research-lab/export-telemetry-window.ps1`
- `scripts/research-lab/generate-shadow-jira-issues.ps1`
- `scripts/research-lab/validate-dataset-run.ps1`
- `scripts/research-lab/collect-dataset-run.ps1`
- `scripts/research-lab/collect-dataset-plan.ps1`
- `scripts/research-lab/collect-dataset-corpus.ps1`

This workflow records dataset manifests, incident episodes, telemetry windows,
alert events, raw Loki/Prometheus/Tempo exports, and Jira shadow issues.

The active dataset plan is `docs/dataset-v4-plan.md`. Earlier dataset
versions (v1, v2, v2.1, v3) have been removed during the move to the
Jira-as-memory product framing. The historical v3 corpus mechanics live in
`docs/production-corpus-dataset-plan.md` and remain valid for the v4
collection pipeline.

This adds multi-plan batch collection for a larger production-style dataset
before we start comparing heavier ML, NLP, AI, or agent pipelines.

The telemetry exporter now writes padded Loki context at two levels:

- per telemetry window, including exact service logs, padded service logs, and
  padded namespace logs;
- per full dataset run in `raw/loki/run-context.json`, preserving a continuous
  namespace-level log corpus for reconstruction and research review.

Historical Prometheus `ALERTS` query-range results are converted into
`alerts.jsonl`, alongside current Alertmanager state, so alert evidence is not
lost after an alert resolves. Kubernetes event, restart, rollout, and readiness
summaries are also attached to telemetry window features for new runs.

## Highest-value improvements

> Status note (added 2026-05-24): items 1 and 3 are now formally planned
> and partly executed under Phase D13 of `dataset-todo.md` (telemetry
> upgrade). Per-RPC structured logs with `trace_id`/`span_id` correlation
> are shipping for Go/.NET/Node/Python via shared interceptors under
> `microservices-demo-google/src/_shared-<lang>/`. cartservice has full
> OTel coverage for the first time. See `microservice-changes.md` and
> `microservice-changes-todo.md` for the full design and execution plan,
> and `docs/telemetry-implementation-decisions.md` for the M0 decisions.

1. ~~Add `trace_id` and `span_id` to JSON logs for every service.~~ → IN PROGRESS via D13/M2.1.
2. Add stable synthetic `request_id` propagation across service calls.
3. ~~Add low-cardinality business metrics for checkout, cart, payment, product lookup, and recommendation flows.~~ → PLANNED via D13/M4.4 (post-gate).
4. Add richer scenario actions for network latency, CPU pressure, memory pressure, and cascading multi-service faults.
5. Add a dedicated alert webhook receiver that stores raw Alertmanager payloads before any transformation.
6. Add schema validation with a real JSON Schema validator instead of only structural validation.
7. Add scenario replay manifests that pin exact script parameters, Docker image digests, and Helm chart versions for external paper review.
8. Add derived feature builders that turn raw evidence into ranking-ready rows without mutating the raw dataset.

## Why this matters

Real on-call workflows depend on correlation:

- which request was impacted,
- which trace shows the failure path,
- which log lines explain the error,
- which alert fired,
- which Jira issue captured the incident,
- which commit/deployment/fault caused the behavior.

Without these joins, the model will learn weaker patterns and the future product will be harder to trust.

## Recommendation

Collect Dataset v3 in batches, inspect the validation and failure-analysis
outputs after each batch, then add custom instrumentation in a controlled
second step. That keeps the upstream demo runnable while giving us a clear
before/after measurement of how much better the dataset becomes when logs,
metrics, traces, Kubernetes state, and Jira shadow issues are fully correlated.
