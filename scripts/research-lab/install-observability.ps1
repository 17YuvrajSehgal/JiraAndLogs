$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$repoRoot = Get-ResearchLabRepoRoot
$valuesRoot = Join-ResearchLabPath @($repoRoot, "deploy", "research-lab", "observability", "values")
$localHelm = Join-ResearchLabPath @($repoRoot, ".tools", "helm.exe")

$helm = Get-Command helm -ErrorAction SilentlyContinue
if ($null -eq $helm -and (Test-Path $localHelm)) {
    $helm = $localHelm
}
if ($null -eq $helm) {
    throw "helm is not installed. Install Helm before running this script, or place helm.exe at .tools\helm.exe."
}

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl is not installed."
}

kubectl apply -f (Join-ResearchLabPath @($repoRoot, "deploy", "research-lab", "namespaces.yaml"))

& $helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
& $helm repo add grafana https://grafana.github.io/helm-charts
& $helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
& $helm repo update

& $helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
    --namespace observability `
    --values (Join-Path $valuesRoot "kube-prometheus-stack-values.yaml")

& $helm upgrade --install tempo grafana/tempo `
    --namespace observability `
    --values (Join-Path $valuesRoot "tempo-values.yaml")

& $helm upgrade --install loki grafana/loki `
    --namespace observability `
    --values (Join-Path $valuesRoot "loki-values.yaml")

& $helm upgrade --install alloy grafana/alloy `
    --namespace observability `
    --values (Join-Path $valuesRoot "alloy-values.yaml")

& $helm upgrade --install grafana grafana/grafana `
    --namespace observability `
    --values (Join-Path $valuesRoot "grafana-values.yaml")

& $helm upgrade --install opentelemetry-collector open-telemetry/opentelemetry-collector `
    --namespace observability `
    --values (Join-Path $valuesRoot "opentelemetry-collector-values.yaml")

kubectl get pods -n observability
