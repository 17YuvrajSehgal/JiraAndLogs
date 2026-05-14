$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$namespaceFile = Join-Path $repoRoot "deploy\research-lab\namespaces.yaml"
$overlay = Join-Path $repoRoot "deploy\research-lab\online-boutique"

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl is not installed."
}

kubectl apply -f $namespaceFile
kubectl kustomize $overlay --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
kubectl get pods -n online-boutique-research

