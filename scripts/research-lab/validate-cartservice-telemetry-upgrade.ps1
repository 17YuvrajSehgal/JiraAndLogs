#requires -Version 5.1
<#
.SYNOPSIS
M5.1 validation experiment: cartservice-first telemetry upgrade.

.DESCRIPTION
Per microservice-changes-todo.md Phase M5.1 ("cheap gate"), this script
verifies whether the M1.1 + M3.1 cartservice changes actually move the
needle on the cart-redis fault family before we invest in a full v5 rollout.

Steps:
  1. Build the modified cartservice image and load it into kind.
  2. Re-render + apply the Online Boutique manifests with the new image tag.
  3. Run 2 cart-redis-degradation-critical scenarios via the existing
     collect-dataset-run.ps1 wrapper.
  4. Build the derived per-run datasets for those 2 runs.
  5. Compute the validation metrics:
       (a) trace_error_count distribution on cartservice active_fault windows
           — expected to go from ~0 (current) to a meaningful value
       (b) loganalyzer PR-AUC on the cart-redis family slice
           (compared to a sampled equivalent from v4-large)
  6. Print the GATE result: PASS if PR-AUC up >= 5pt OR trace_error_count
     newly fires; FAIL otherwise.

.PARAMETER ImageTag
Docker tag for the rebuilt cartservice image. Default: v5.0.0-otel-pilot.

.PARAMETER SkipBuild
Skip the docker build + kind load step (re-use an image already loaded).

.PARAMETER SkipCollection
Skip the dataset collection step (re-use existing run dirs).

.PARAMETER RunIdPrefix
Prefix for the dataset runs. Default: 2026-05-24-m5-1-cart-validation

.EXAMPLE
PS> ./validate-cartservice-telemetry-upgrade.ps1
PS> ./validate-cartservice-telemetry-upgrade.ps1 -SkipBuild -SkipCollection
#>

[CmdletBinding()]
param(
    [string]$ImageTag = "v5.0.0-otel-pilot",
    [string]$ClusterName = "jira-telemetry-lab",
    [switch]$SkipBuild,
    [switch]$SkipCollection,
    [string]$RunIdPrefix = "2026-05-24-m5-1-cart-validation"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "../..")
$CartserviceSrc = Join-Path $RepoRoot "microservices-demo-google/src/cartservice/src"

Write-Host "=== M5.1 cartservice telemetry-upgrade validation ===" -ForegroundColor Cyan
Write-Host "RepoRoot:    $RepoRoot"
Write-Host "ImageTag:    $ImageTag"
Write-Host "RunIdPrefix: $RunIdPrefix"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: build + kind-load
# ---------------------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "[1/5] Building cartservice image..." -ForegroundColor Green
    # NOTE: requires the Dockerfile build context fix from
    # docs/telemetry-implementation-build-notes.md (must include
    # ../../_shared-dotnet/RpcLogging/ so the project reference resolves).
    Push-Location (Join-Path $RepoRoot "microservices-demo-google/src")
    try {
        docker build `
            -t "cartservice:$ImageTag" `
            -f cartservice/src/Dockerfile `
            .
        if ($LASTEXITCODE -ne 0) { throw "docker build failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }

    Write-Host "[1/5] Loading image into kind cluster..." -ForegroundColor Green
    kind load docker-image "cartservice:$ImageTag" --name $ClusterName
    if ($LASTEXITCODE -ne 0) {
        throw "kind load failed. Confirm cluster name is '$ClusterName' or pass -ClusterName to this script."
    }
} else {
    Write-Host "[1/5] Skipping build (SkipBuild)." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 2: re-render + apply manifests
# ---------------------------------------------------------------------------
Write-Host "[2/5] Re-rendering + applying Online Boutique manifests..." -ForegroundColor Green
& (Join-Path $PSScriptRoot "render-online-boutique.ps1")
if ($LASTEXITCODE -ne 0) { throw "render-online-boutique.ps1 failed (exit $LASTEXITCODE)" }

# Force cartservice deployment to pick up the new image tag.
# (kustomize patch in deploy/research-lab/online-boutique/patches/enable-otel-and-research-env.yaml
#  already sets SERVICE_VERSION env var; we override the container image here.)
kubectl -n online-boutique-research set image deployment/cartservice server="cartservice:$ImageTag"
kubectl -n online-boutique-research rollout status deployment/cartservice --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "cartservice rollout did not complete" }

# ---------------------------------------------------------------------------
# Step 3: collect 2 cart-redis runs
# ---------------------------------------------------------------------------
$Run1 = "$RunIdPrefix-r01"
$Run2 = "$RunIdPrefix-r02"

if (-not $SkipCollection) {
    foreach ($runId in @($Run1, $Run2)) {
        Write-Host "[3/5] Collecting run $runId (5-scenario default mix incl. cart-redis-degradation-critical)..." -ForegroundColor Green
        # collect-dataset-run.ps1 runs a fixed 5-scenario sequence per run
        # (baseline + productcatalog-latency + cart-redis-degradation-critical + frontend-cpu-nearmiss + baseline).
        # The cart-redis-degradation-critical scenario produces the cartservice/active_fault
        # windows the gate filters on; other scenarios contribute non-cartservice windows
        # that the Python filter drops.
        & (Join-Path $PSScriptRoot "collect-dataset-run.ps1") `
            -DatasetRunId $runId `
            -ForceNewRun
        if ($LASTEXITCODE -ne 0) { throw "collect-dataset-run.ps1 failed for $runId" }
    }
} else {
    Write-Host "[3/5] Skipping collection (SkipCollection). Expecting existing $Run1 and $Run2." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 4: build derived ranking datasets
# ---------------------------------------------------------------------------
foreach ($runId in @($Run1, $Run2)) {
    Write-Host "[4/5] Building derived dataset for $runId..." -ForegroundColor Green
    & (Join-Path $PSScriptRoot "build-ranking-dataset.ps1") -DatasetRunId $runId -Force
    if ($LASTEXITCODE -ne 0) { throw "build-ranking-dataset.ps1 failed for $runId" }
    & (Join-Path $PSScriptRoot "build-triage-dataset.ps1") -DatasetRunId $runId -Force
    if ($LASTEXITCODE -ne 0) { throw "build-triage-dataset.ps1 failed for $runId" }
}

# ---------------------------------------------------------------------------
# Step 5: compute validation metrics
# ---------------------------------------------------------------------------
Write-Host "[5/5] Computing validation metrics..." -ForegroundColor Green

$PyScript = Join-Path $PSScriptRoot "validate_cartservice_telemetry_upgrade.py"
if (-not (Test-Path $PyScript)) {
    throw "Companion Python script not found: $PyScript"
}

python $PyScript `
    --repo-root $RepoRoot `
    --run-ids "$Run1,$Run2" `
    --baseline-prefix "2026-05-22-dataset-v4-large-compact-a" `
    --baseline-runs "2026-05-22-dataset-v4-large-compact-a-r01,2026-05-22-dataset-v4-large-compact-a-r02"

if ($LASTEXITCODE -ne 0) {
    Write-Host "GATE: FAIL — metrics computation errored." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Validation report written to:" -ForegroundColor Cyan
Write-Host "  data/derived/$Run1/m5-1-validation-report.md"
Write-Host "  data/derived/$Run2/m5-1-validation-report.md"
