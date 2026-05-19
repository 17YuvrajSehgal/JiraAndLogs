$ErrorActionPreference = "Stop"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        Write-Host "MISSING  $Name"
        return $false
    }

    Write-Host "OK       $Name -> $($cmd.Source)"
    return $true
}

$repoRoot = Resolve-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$localHelm = Join-Path (Join-Path $repoRoot ".tools") "helm.exe"

$hasDocker = Test-Command docker
$hasKubectl = Test-Command kubectl
$hasHelm = Test-Command helm
if (-not $hasHelm -and (Test-Path -LiteralPath $localHelm)) {
    Write-Host "OK       helm -> $localHelm"
    $hasHelm = $true
}
$hasKind = Test-Command kind

Write-Host ""

if ($hasDocker) {
    Write-Host "Docker:"
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $dockerOutput = docker version --format "  Client={{.Client.Version}} Server={{.Server.Version}}" 2>&1
    $ErrorActionPreference = $oldErrorActionPreference
    if ($LASTEXITCODE -eq 0) {
        $dockerOutput | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "  Docker is installed, but this shell could not access the engine."
        Write-Host "  Run this from a shell with Docker Desktop access."
    }
}

if ($hasKubectl) {
    Write-Host "kubectl:"
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    kubectl version --client 2>$null
    $context = kubectl config current-context 2>$null
    $ErrorActionPreference = $oldErrorActionPreference
    if ($LASTEXITCODE -eq 0 -and $context) {
        Write-Host "  Current context: $context"
    } else {
        Write-Host "  No current Kubernetes context is configured."
    }
}

if (-not $hasHelm) {
    Write-Host ""
    Write-Host "Helm is required for the observability stack."
}

if (-not $hasKind) {
    Write-Host "kind is optional if Docker Desktop Kubernetes is enabled."
}
