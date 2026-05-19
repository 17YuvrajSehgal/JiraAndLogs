$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$repoRoot = Get-ResearchLabRepoRoot
$namespaceFile = Join-ResearchLabPath @($repoRoot, "deploy", "research-lab", "namespaces.yaml")
$overlay = Join-ResearchLabPath @($repoRoot, "deploy", "research-lab", "online-boutique")

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl is not installed."
}

kubectl apply -f $namespaceFile
kubectl kustomize $overlay --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
kubectl get pods -n online-boutique-research
