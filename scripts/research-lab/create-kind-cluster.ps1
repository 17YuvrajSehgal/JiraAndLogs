$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$config = Join-Path $repoRoot "deploy\research-lab\kind-config.yaml"

if (-not (Get-Command kind -ErrorAction SilentlyContinue)) {
    throw "kind is not installed. Install kind or enable Docker Desktop Kubernetes."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is not installed or not on PATH."
}

$existing = kind get clusters 2>$null
if ($existing -contains "jira-telemetry-lab") {
    Write-Host "kind cluster jira-telemetry-lab already exists."
} else {
    kind create cluster --config $config
}

kubectl cluster-info --context kind-jira-telemetry-lab

