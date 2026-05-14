$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$overlay = Join-Path $repoRoot "deploy\research-lab\online-boutique"

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl is not installed."
}

kubectl kustomize $overlay --load-restrictor=LoadRestrictionsNone

