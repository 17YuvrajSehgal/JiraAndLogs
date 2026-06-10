<#
.SYNOPSIS
    Deploys the OpenTelemetry Demo (Astronomy Shop) into the research cluster
    for cross-app dataset collection.

.DESCRIPTION
    1. Reads pinned chart version + repo URL from helm-version.txt
    2. Adds the open-telemetry helm repo if not already present
    3. Applies namespace.yaml (creates `otel-demo-research`)
    4. helm upgrade --install with helm-values.yaml
    5. Waits for all demo pods to be Ready (default 10 min timeout)
    6. Optional smoke check: port-forward + curl the frontend-proxy

.PARAMETER ContextName
    kubectl context to target. Defaults to current context.

.PARAMETER SkipSmokeCheck
    Skip the post-install smoke check (faster for batch invocations).

.PARAMETER WaitTimeoutSeconds
    Pod-ready wait timeout. Default 600 (10 min).

.PARAMETER DryRun
    Render manifests without applying. Useful for first-time verification.

.NOTES
    Isolation contract: this script affects ONLY the `otel-demo-research`
    namespace and the named helm release `otel-demo`. The OB v5-large
    deployment (`online-boutique-research` namespace) is untouched.

    Idempotent: re-running upgrades in place; safe to run repeatedly.
#>
[CmdletBinding()]
param(
    [string]$ContextName = $null,
    [switch]$SkipSmokeCheck = $false,
    [int]$WaitTimeoutSeconds = 600,
    [switch]$DryRun = $false
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# 1. Parse helm-version.txt to load pinned version constants.
# ---------------------------------------------------------------------------
$versionFile = Join-Path $ScriptDir 'helm-version.txt'
if (-not (Test-Path $versionFile)) {
    throw "helm-version.txt not found at $versionFile"
}

$pins = @{}
Get-Content $versionFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $parts = $line.Split('=', 2)
    if ($parts.Length -eq 2) {
        $pins[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$CHART_VERSION   = $pins.CHART_VERSION
$CHART_REPO_URL  = $pins.CHART_REPO_URL
$CHART_REPO_NAME = $pins.CHART_REPO_NAME
$CHART_NAME      = $pins.CHART_NAME
$RELEASE_NAME    = $pins.RELEASE_NAME
$NAMESPACE       = $pins.NAMESPACE

Write-Host "==> Pinned versions" -ForegroundColor Cyan
Write-Host "    chart   = $CHART_REPO_NAME/$CHART_NAME@$CHART_VERSION"
Write-Host "    release = $RELEASE_NAME"
Write-Host "    ns      = $NAMESPACE"

# ---------------------------------------------------------------------------
# 2. Prerequisite checks
# ---------------------------------------------------------------------------
Write-Host "`n==> Checking prerequisites..." -ForegroundColor Cyan
foreach ($tool in @('kubectl', 'helm')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is not on PATH"
    }
}

if ($ContextName) {
    Write-Host "    switching kubectl context -> $ContextName"
    & kubectl config use-context $ContextName | Out-Null
}

$currentCtx = & kubectl config current-context
Write-Host "    kubectl context = $currentCtx"

# Verify the observability namespace exists (we depend on it for telemetry routing).
$obsNs = & kubectl get ns observability --ignore-not-found -o name 2>$null
if (-not $obsNs) {
    Write-Warning "Namespace 'observability' not found. OTel Demo will deploy but telemetry will fail to forward."
    Write-Warning "Deploy your existing observability stack first."
}

# ---------------------------------------------------------------------------
# 3. Add the helm repo (idempotent)
# ---------------------------------------------------------------------------
Write-Host "`n==> Configuring helm repo..." -ForegroundColor Cyan
$existingRepos = & helm repo list -o json 2>$null | ConvertFrom-Json
$hasRepo = $existingRepos | Where-Object { $_.name -eq $CHART_REPO_NAME }
if (-not $hasRepo) {
    & helm repo add $CHART_REPO_NAME $CHART_REPO_URL
} else {
    Write-Host "    helm repo '$CHART_REPO_NAME' already present"
}
& helm repo update $CHART_REPO_NAME | Out-Null

# ---------------------------------------------------------------------------
# 4. Apply namespace
# ---------------------------------------------------------------------------
Write-Host "`n==> Applying namespace..." -ForegroundColor Cyan
$nsFile = Join-Path $ScriptDir 'namespace.yaml'
if ($DryRun) {
    & kubectl apply --dry-run=client -f $nsFile
} else {
    & kubectl apply -f $nsFile
}

# ---------------------------------------------------------------------------
# 5. helm upgrade --install
# ---------------------------------------------------------------------------
Write-Host "`n==> Deploying chart..." -ForegroundColor Cyan
$valuesFile = Join-Path $ScriptDir 'helm-values.yaml'

$helmArgs = @(
    'upgrade', '--install', $RELEASE_NAME, "$CHART_REPO_NAME/$CHART_NAME",
    '--namespace', $NAMESPACE,
    '--version', $CHART_VERSION,
    '--values', $valuesFile,
    '--wait',
    '--timeout', "$($WaitTimeoutSeconds)s"
)
if ($DryRun) { $helmArgs += '--dry-run' }

& helm @helmArgs

# ---------------------------------------------------------------------------
# 6. Pod readiness check (helm --wait already does this, but report it)
# ---------------------------------------------------------------------------
if (-not $DryRun) {
    Write-Host "`n==> Pod status:" -ForegroundColor Cyan
    & kubectl get pods -n $NAMESPACE
}

# ---------------------------------------------------------------------------
# 7. Smoke check — invoke one synthetic checkout if requested
# ---------------------------------------------------------------------------
if (-not $SkipSmokeCheck -and -not $DryRun) {
    Write-Host "`n==> Smoke check: hitting frontend-proxy..." -ForegroundColor Cyan
    Write-Host "    (If this hangs, port-forward manually: kubectl port-forward -n $NAMESPACE svc/frontend-proxy 8080:8080)"
    try {
        $job = Start-Job -ScriptBlock {
            param($ns)
            & kubectl port-forward -n $ns svc/frontend-proxy 18080:8080
        } -ArgumentList $NAMESPACE
        Start-Sleep -Seconds 3
        $r = Invoke-WebRequest -Uri 'http://localhost:18080/' -UseBasicParsing -TimeoutSec 10
        Write-Host "    HTTP $($r.StatusCode) - smoke OK"
    } catch {
        Write-Warning "    Smoke check failed: $_"
        Write-Warning "    Investigate before running scenarios."
    } finally {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -ErrorAction SilentlyContinue
    }
}

Write-Host "`n==> Deploy complete." -ForegroundColor Green
Write-Host "    Next: run scripts/research-lab/otel-demo/Install-OtelDemo.ps1 helpers or one of the dataset collection plans (Phase 2 pilot)."
