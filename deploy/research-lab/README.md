# Research Lab Deployment

This directory contains the deployment scaffold for the Jira-aware telemetry research lab.

The goal is to run Google's Online Boutique with a local observability stack and metadata contract that can later produce Jira-shaped incident records. The upstream demo clone stays unchanged; this scaffold uses Kustomize overlays and Helm values from outside `microservices-demo-google`.

## Canonical rebuild runbook

Use [docs/research-lab-deployment.md](../../docs/research-lab-deployment.md) for the complete cold-start rebuild commands, including:

- Docker Desktop Kubernetes and standalone kind cluster paths.
- clean namespace deletion before a rebuild.
- Helm fallback through `.tools\helm.exe`.
- observability installation.
- Online Boutique deployment.
- image pull recovery steps.
- frontend, Loki, Prometheus, Tempo, and Grafana validation commands.

You can use either Docker Desktop Kubernetes or a local `kind` cluster. Docker Desktop Kubernetes is the fastest path for this workstation because it has already been verified with context `docker-desktop`.

## Namespaces

- `online-boutique-research`: Online Boutique services and load generator.
- `observability`: OpenTelemetry Collector, Prometheus, Alertmanager, Loki, Tempo, Grafana, and Alloy.

Apply namespaces:

```powershell
kubectl apply -f deploy/research-lab/namespaces.yaml
```

PowerShell may block local scripts depending on execution policy. Run helper scripts like this:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/check-prereqs.ps1
```

Full verified rebuild short path:

```powershell
Set-Location C:\workplace\JiraAndLogs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\check-prereqs.ps1
kubectl config use-context docker-desktop
kubectl delete namespace online-boutique-research observability --ignore-not-found
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=300s
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\apply-online-boutique.ps1
kubectl wait --for=condition=Ready pods --all -n online-boutique-research --timeout=300s
kubectl get pods -n observability
kubectl get pods -n online-boutique-research
kubectl logs -n online-boutique-research deploy/loadgenerator --tail=30
```

After deployment is healthy, the first dataset workflow is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001" `
  -Quick
```

## Online Boutique overlay

Render the research overlay:

```powershell
kubectl kustomize deploy/research-lab/online-boutique --load-restrictor=LoadRestrictionsNone
```

Apply it:

```powershell
kubectl kustomize deploy/research-lab/online-boutique --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
```

The load restrictor flag is required because the overlay intentionally lives outside the cloned Google repository while referencing its Kustomize base.

## Observability stack

The observability stack is represented as Helm values under `deploy/research-lab/observability/values`.

Install order once Helm is available:

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
  --namespace observability `
  --values deploy/research-lab/observability/values/kube-prometheus-stack-values.yaml

helm upgrade --install tempo grafana/tempo `
  --namespace observability `
  --values deploy/research-lab/observability/values/tempo-values.yaml

helm upgrade --install loki grafana/loki `
  --namespace observability `
  --values deploy/research-lab/observability/values/loki-values.yaml

helm upgrade --install alloy grafana/alloy `
  --namespace observability `
  --values deploy/research-lab/observability/values/alloy-values.yaml

helm upgrade --install grafana grafana/grafana `
  --namespace observability `
  --values deploy/research-lab/observability/values/grafana-values.yaml

helm upgrade --install opentelemetry-collector open-telemetry/opentelemetry-collector `
  --namespace observability `
  --values deploy/research-lab/observability/values/opentelemetry-collector-values.yaml
```

## Metadata rule

Low-cardinality metadata is allowed in labels and OpenTelemetry resource attributes.

High-cardinality metadata must stay out of Prometheus labels:

- request ids
- session ids
- trace ids
- span ids
- individual fault ids when they change frequently
- raw Jira keys in high-volume metrics

Those fields belong in logs, traces, event tables, and exported dataset records.
