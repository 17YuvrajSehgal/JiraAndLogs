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

This workflow records dataset manifests, incident episodes, telemetry windows,
alert events, raw Loki/Prometheus/Tempo exports, and Jira shadow issues.

Dataset v2 planning has started in `docs/dataset-v2-realism-plan.md`. The first
executable v2 run plan is `deploy/research-lab/run-plans/dataset-v2-pilot.json`.
It adds payment outage, checkout restart, Redis restart, recommendation restart
near-miss, and traffic spike near-miss scenarios while staying inside the
current runner capabilities.

The telemetry exporter now writes padded Loki context at two levels:

- per telemetry window, including exact service logs, padded service logs, and
  padded namespace logs;
- per full dataset run in `raw/loki/run-context.json`, preserving a continuous
  namespace-level log corpus for reconstruction and research review.

Historical Prometheus `ALERTS` query-range results are converted into
`alerts.jsonl`, alongside current Alertmanager state, so alert evidence is not
lost after an alert resolves.

## Highest-value improvements

1. Add `trace_id` and `span_id` to JSON logs for every service.
2. Add stable synthetic `request_id` propagation across service calls.
3. Add low-cardinality business metrics for checkout, cart, payment, product lookup, and recommendation flows.
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

Do the deployment scaffold first, then add custom instrumentation in a controlled second step. That keeps the upstream demo runnable while giving us a clear before/after measurement of how much better the dataset becomes when logs, metrics, traces, and Jira shadow issues are fully correlated.
