# Research Lab Deployment Runbook

This runbook rebuilds the local Online Boutique research lab from a cold start.
It assumes the repository is already available at `C:\workplace\JiraAndLogs`.
The commands are written for PowerShell on Windows.

The lab has two namespaces:

- `online-boutique-research`: Google Online Boutique services and load generator.
- `observability`: Prometheus, Alertmanager, Loki, Tempo, Grafana, Alloy, and OpenTelemetry Collector.

The current dataset metadata mode is `JIRA_MODE=shadow`. No Jira credentials are
needed for the MVP ranking dataset. Later Jira generation can use the same
`DATASET_RUN_ID`, `SCENARIO_ID`, and `TRAFFIC_PROFILE_ID` values that are injected
into the application pods.

For the dataset creation contract, run contents, and scenario-to-Jira process,
see `docs/dataset-acquisition-plan.md`.

## 1. Start From The Repo Root

```powershell
Set-Location C:\workplace\JiraAndLogs
```

If the Google demo clone is missing, clone it into the expected folder name:

```powershell
git clone https://github.com/GoogleCloudPlatform/microservices-demo.git microservices-demo-google
```

## 2. Check Required Tools

Docker Desktop must be running. Kubernetes can come from Docker Desktop or from
kind. Use one cluster path, not both.

```powershell
docker version
kubectl version --client
kubectl config get-contexts
helm version
kind version
```

Run the project prerequisite checker:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\check-prereqs.ps1
```

If `helm` is not on `PATH`, the scripts also accept a workspace-local Helm binary
at `.tools\helm.exe`. Install it with:

```powershell
New-Item -ItemType Directory -Force .tools | Out-Null
Invoke-WebRequest -Uri https://get.helm.sh/helm-v3.16.4-windows-amd64.zip -OutFile .tools\helm.zip
Expand-Archive .tools\helm.zip -DestinationPath .tools\helm-unpack -Force
Copy-Item .tools\helm-unpack\windows-amd64\helm.exe .tools\helm.exe -Force
.\.tools\helm.exe version
```

## 3. Choose A Cluster

### Option A: Docker Desktop Kubernetes

This is the path used for the first verified local deployment.

1. Open Docker Desktop.
2. Enable Kubernetes.
3. Select the `kind` provisioning method if Docker Desktop offers it.
4. Start with one node unless you are running heavier experiments.

Then select and verify the context:

```powershell
kubectl config use-context docker-desktop
kubectl cluster-info
kubectl get nodes -o wide
```

### Option B: Standalone kind

Use this if Docker Desktop Kubernetes is disabled or you want a disposable lab
cluster that is independent of Docker Desktop's built-in Kubernetes.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\create-kind-cluster.ps1
kubectl config use-context kind-jira-telemetry-lab
kubectl cluster-info
kubectl get nodes -o wide
```

To delete and recreate the standalone kind cluster:

```powershell
kind delete cluster --name jira-telemetry-lab
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\create-kind-cluster.ps1
```

## 4. Clean An Existing Lab

For a clean rebuild on an existing cluster:

```powershell
kubectl delete namespace online-boutique-research observability --ignore-not-found
```

Wait until both namespaces disappear:

```powershell
kubectl get namespaces
```

If a namespace is stuck terminating, inspect it before deleting anything else:

```powershell
kubectl describe namespace online-boutique-research
kubectl describe namespace observability
```

## 5. Install Observability

The install script creates namespaces, adds Helm repos, installs the charts, and
uses the values under `deploy\research-lab\observability\values`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\install-observability.ps1
```

Wait for the observability stack:

```powershell
kubectl wait --for=condition=Ready pods --all -n observability --timeout=300s
kubectl get pods -n observability -o wide
```

Manual Helm commands, if you need to run them without the script:

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
  --namespace observability `
  --create-namespace `
  --values deploy\research-lab\observability\values\kube-prometheus-stack-values.yaml

helm upgrade --install tempo grafana/tempo `
  --namespace observability `
  --values deploy\research-lab\observability\values\tempo-values.yaml

helm upgrade --install loki grafana/loki `
  --namespace observability `
  --values deploy\research-lab\observability\values\loki-values.yaml

helm upgrade --install alloy grafana/alloy `
  --namespace observability `
  --values deploy\research-lab\observability\values\alloy-values.yaml

helm upgrade --install grafana grafana/grafana `
  --namespace observability `
  --values deploy\research-lab\observability\values\grafana-values.yaml

helm upgrade --install opentelemetry-collector open-telemetry/opentelemetry-collector `
  --namespace observability `
  --values deploy\research-lab\observability\values\opentelemetry-collector-values.yaml
```

If you are using `.tools\helm.exe`, replace `helm` with `.\.tools\helm.exe`.

## 6. Deploy Online Boutique

Render the overlay first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\render-online-boutique.ps1
```

Apply the application:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\apply-online-boutique.ps1
```

Wait for the application:

```powershell
kubectl wait --for=condition=Ready pods --all -n online-boutique-research --timeout=300s
kubectl get pods -n online-boutique-research -o wide
```

Manual Kustomize commands, if you need to run without the script:

```powershell
kubectl apply -f deploy\research-lab\namespaces.yaml
kubectl kustomize deploy\research-lab\online-boutique --load-restrictor=LoadRestrictionsNone
kubectl kustomize deploy\research-lab\online-boutique --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
```

The `--load-restrictor=LoadRestrictionsNone` flag is required because the overlay
lives outside the cloned Google repository while referencing its Kustomize base.

## 7. Recover From Image Pull Issues

A cold cluster pulls all images. If a pod is stuck in `ImagePullBackOff`, inspect
the exact image first:

```powershell
kubectl get pods -n online-boutique-research
kubectl describe pod -n online-boutique-research -l app=redis-cart
kubectl describe pod -n online-boutique-research -l app=loadgenerator
```

If Docker Hub has a transient pull failure for Redis, pre-pull Redis and restart
the pod:

```powershell
docker pull redis:alpine
kubectl delete pod -n online-boutique-research -l app=redis-cart
kubectl wait --for=condition=Ready pods -l app=redis-cart -n online-boutique-research --timeout=180s
```

The load generator init container is pinned to
`registry.k8s.io/e2e-test-images/busybox:1.29-4` to avoid the Docker Hub
`busybox:latest` pull dependency.

## 8. Validate The Application

Open a frontend port-forward:

```powershell
kubectl -n online-boutique-research port-forward svc/frontend 8080:80
```

In a second PowerShell window:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/
```

Check load generator traffic:

```powershell
kubectl logs -n online-boutique-research deploy/loadgenerator --tail=60
```

Expected traffic includes endpoints such as `/`, `/cart`, `/cart/checkout`,
`/product/...`, and `/setCurrency`.

## 9. Validate Logs, Metrics, And Traces

### Logs In Loki

```powershell
$pf = Start-Process -FilePath kubectl -ArgumentList @('-n','observability','port-forward','svc/loki-gateway','13100:80') -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
$uri = 'http://127.0.0.1:13100/loki/api/v1/query_range?query=%7Bnamespace%3D%22online-boutique-research%22%7D&limit=5'
Invoke-RestMethod -Uri $uri
Stop-Process -Id $pf.Id -Force
```

Expected result: `status` is `success`, and returned streams include labels such
as `namespace`, `pod`, `service_name`, `service_tier`, and `research_dataset`.

### Metrics In Prometheus

```powershell
$pf = Start-Process -FilePath kubectl -ArgumentList @('-n','observability','port-forward','svc/kube-prometheus-stack-prometheus','19090:9090') -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
$uri = 'http://127.0.0.1:19090/api/v1/query?query=kube_pod_info%7Bnamespace%3D%22online-boutique-research%22%7D'
Invoke-RestMethod -Uri $uri
Stop-Process -Id $pf.Id -Force
```

Expected result: Prometheus returns one series per Online Boutique pod.

### Traces In Tempo

```powershell
$pf = Start-Process -FilePath kubectl -ArgumentList @('-n','observability','port-forward','svc/tempo','13200:3200') -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
Invoke-RestMethod -Uri 'http://127.0.0.1:13200/api/search?limit=10'
Stop-Process -Id $pf.Id -Force
```

Expected result: Tempo returns traces from services such as `frontend`,
`currencyservice`, `productcatalogservice`, `recommendationservice`, or health
checks.

## 10. Open Local UIs

Run each port-forward in its own PowerShell window.

```powershell
kubectl -n online-boutique-research port-forward svc/frontend 8080:80
kubectl -n observability port-forward svc/grafana 3000:80
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n observability port-forward svc/loki-gateway 3100:80
kubectl -n observability port-forward svc/tempo 3200:3200
```

URLs:

- Online Boutique: `http://127.0.0.1:8080`
- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`
- Loki API: `http://127.0.0.1:3100`
- Tempo API: `http://127.0.0.1:3200`

Grafana local credentials:

```text
Username: admin
Password: admin
```

## 11. Dataset Metadata To Change Per Run

The run metadata lives in
`deploy\research-lab\online-boutique\kustomization.yaml` under
`configMapGenerator`.

Change these values before a new controlled dataset run:

```yaml
DATASET_RUN_ID: local-dev-run-001
SCENARIO_ID: baseline-normal-traffic
TRAFFIC_PROFILE_ID: baseline-checkout-mix
JIRA_MODE: shadow
```

Recommended naming:

```text
DATASET_RUN_ID: yyyy-mm-dd-short-purpose-run-number
SCENARIO_ID: scenario family plus severity
TRAFFIC_PROFILE_ID: traffic profile file name without extension
```

Apply metadata changes with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\apply-online-boutique.ps1
kubectl rollout status deployment/frontend -n online-boutique-research
kubectl rollout status deployment/loadgenerator -n online-boutique-research
```

## 12. Future Jira Configuration

No real Jira connection is required for the current lab. When we move from shadow
issues to real Jira Cloud issue creation, we will need:

- Jira Cloud site URL.
- Project key.
- Issue type for generated incidents.
- API token or OAuth app credentials.
- Reporter and assignee mapping.
- Component names matching service ownership.
- Rules for which incident episodes become Jira issues.

Keep raw Jira issue keys out of high-volume Prometheus labels. Store them in
event records, logs, traces, and exported dataset files instead.

## 13. Full Rebuild Short Path

Use this when Docker Desktop is running and Kubernetes already has a working
context:

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

After the lab is healthy, collect the first dataset with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-first-small-dataset-001" `
  -Quick
```

Use `-RecordOnly` for a metadata and baseline dry run that does not inject
faults. Use `-NoTelemetryExport` only for script testing, because it skips raw
Loki, Prometheus, and Tempo evidence.

Fast script-only smoke test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "dry-run-001" `
  -RecordOnly `
  -NoTelemetryExport `
  -ScenarioDurationSeconds 1 `
  -PostWindowSeconds 0 `
  -ForceNewRun
```
