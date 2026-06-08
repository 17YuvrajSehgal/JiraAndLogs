# `deploy/otel-demo/` — OpenTelemetry Demo deployment overlay

Deploys the OpenTelemetry Astronomy Shop demo into our research observability environment for the cross-app dataset collection. Cluster-resident assets only — the application source lives in the (gitignored) `opentelemetry-demo/` clone and is **never edited**; we deploy via the upstream published images.

## What this directory contains

| File | Purpose |
|---|---|
| `helm-version.txt` | Pinned helm chart version + repo URL + image tag |
| `helm-values.yaml` | Override values for the upstream chart: disables bundled observability, pins images, routes telemetry to our stack |
| `otel-collector-config.yaml` | Custom OTel Collector config; exports OTLP to our existing `observability/` namespace stack |
| `namespace.yaml` | `otel-demo-research` namespace + static research labels |
| `flagd-baseline.json` | All 16 feature flags in their `off` baseline state; used by scenario runner to restore between scenarios |
| `helm-install.ps1` | One-shot deploy: add repo, install/upgrade chart, wait for pods, smoke-check |

## Prerequisites

- A kubectl context pointing at the research cluster (local kind or GCP VM)
- Helm 3.10+ installed
- Our existing observability stack running in the `observability` namespace (Loki, Tempo, Prometheus, OTel Collector, Alloy)
- ~6 GiB RAM available on the cluster for OTel Demo workloads
- chaos-mesh installed (optional; required only for the 4 network-fault scenarios)

## Deploy

```powershell
# From repo root
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File deploy\otel-demo\helm-install.ps1
```

This will:
1. Add the `open-telemetry` helm repo if missing
2. Apply `namespace.yaml`
3. `helm upgrade --install` the chart with our values
4. Wait for all pods to be Ready (10 min timeout)
5. Smoke-check by invoking one synthetic checkout request against the frontend-proxy

Expected runtime: ~3–6 min on a warm cluster.

## Verify

After deploy, confirm:

```powershell
# All pods Ready
kubectl get pods -n otel-demo-research

# Telemetry flowing to our stack: hit the demo frontend
kubectl port-forward -n otel-demo-research svc/frontend-proxy 8080:8080
# Browse http://localhost:8080 to generate a checkout

# Confirm traces in Tempo (via Grafana or query)
# Confirm logs in Loki: { app_id="otel-demo" }
# Confirm metrics in Prometheus: rate({job=~"otel-demo-.*"})
```

## Teardown

```powershell
helm uninstall otel-demo -n otel-demo-research
kubectl delete namespace otel-demo-research
```

The OB v5-large dataset and its `online-boutique-research` namespace are unaffected.

## Verification points for first deploy

These chart-version-sensitive items should be confirmed when first deploying:

- [ ] `jaeger.enabled`, `prometheus.enabled`, `grafana.enabled`, `opensearch.enabled` at chart `0.40.9` are the correct top-level keys to disable bundled backends.
- [ ] `opentelemetry-collector.config` correctly overrides the bundled collector config.
- [ ] Our research-injection labels propagate via `default.envOverrides` without leaking into application-level telemetry.
- [ ] The `OTEL_EXPORTER_OTLP_ENDPOINT` env override targets our existing observability collector and is reachable from the demo namespace.

If any of these fail on first deploy, fix in `helm-values.yaml` and re-run `helm-install.ps1` (it's idempotent).

## Related documentation

- `docs5/00-otel-demo-cross-app-plan.md` — strategy + scenarios
- `docs5/01-otel-demo-implementation-plan.md` — file-level implementation plan with isolation guarantees
- Upstream chart: <https://github.com/open-telemetry/opentelemetry-helm-charts/tree/main/charts/opentelemetry-demo>
- Upstream demo docs: <https://opentelemetry.io/docs/demo/>
