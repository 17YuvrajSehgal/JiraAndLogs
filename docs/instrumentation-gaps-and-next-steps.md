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

## Highest-value improvements

1. Add `trace_id` and `span_id` to JSON logs for every service.
2. Add stable synthetic `request_id` propagation across service calls.
3. Add low-cardinality business metrics for checkout, cart, payment, product lookup, and recommendation flows.
4. Add a scenario controller that writes `incident_episode`, `alert_event`, `telemetry_window`, and `jira_shadow_issue` records at the same time as faults are injected.
5. Add a dedicated alert webhook receiver that stores raw Alertmanager payloads before any transformation.

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

