$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$repoRoot = Get-ResearchLabRepoRoot
$overlay = Join-ResearchLabPath @($repoRoot, "deploy", "research-lab", "online-boutique")

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl is not installed."
}

kubectl kustomize $overlay --load-restrictor=LoadRestrictionsNone
