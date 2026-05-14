[CmdletBinding()]
param(
    [string]$DatasetRunId = ("run-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")),
    [switch]$Quick,
    [switch]$RecordOnly,
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$ForceNewRun,
    [int]$ScenarioDurationSeconds = 0,
    [int]$PostWindowSeconds = -1
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\ResearchLab.psm1") -Force

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if ((Test-Path -LiteralPath (Join-Path $runRoot "manifest.json")) -and -not $ForceNewRun) {
    Write-Host "Using existing dataset run: $DatasetRunId"
} else {
    $startArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "start-dataset-run.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-ScenarioId", "first-small-dataset",
        "-TrafficProfileId", "baseline-checkout-mix",
        "-Notes", "Collected through collect-dataset-run.ps1"
    )
    if ($ForceNewRun) {
        $startArgs += "-Force"
    }

    & powershell @startArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start dataset run $DatasetRunId."
    }
}

$scenarios = @(
    "deploy\research-lab\scenarios\baselines\baseline-normal-traffic.yaml",
    "deploy\research-lab\scenarios\faults\productcatalog-latency-major.yaml",
    "deploy\research-lab\scenarios\faults\cart-redis-degradation-critical.yaml",
    "deploy\research-lab\scenarios\faults\frontend-cpu-nearmiss.yaml",
    "deploy\research-lab\scenarios\baselines\baseline-normal-traffic.yaml"
)

foreach ($scenarioFile in $scenarios) {
    $duration = 0
    $postWindow = 180
    if ($Quick) {
        $duration = 90
        $postWindow = 60
    }
    if ($ScenarioDurationSeconds -gt 0) {
        $duration = $ScenarioDurationSeconds
    }
    if ($PostWindowSeconds -ge 0) {
        $postWindow = $PostWindowSeconds
    }

    $action = "Auto"
    if ($RecordOnly) {
        $action = "RecordOnly"
    }

    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "run-scenario.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-ScenarioFile", $scenarioFile,
        "-Action", $action,
        "-PostWindowSeconds", $postWindow
    )

    if ($duration -gt 0) {
        $args += @("-DurationSeconds", $duration)
    }
    if ($NoTelemetryExport) {
        $args += "-NoTelemetryExport"
    }
    if ($SkipJiraGeneration) {
        $args += "-SkipJiraGeneration"
    }

    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "Scenario workflow failed: $scenarioFile"
    }
}

if (-not $NoTelemetryExport) {
    $runContextArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "export-telemetry-window.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-RunLevelLokiOnly"
    )

    & powershell @runContextArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Run-level Loki context export failed for $DatasetRunId."
    }
}

$validateArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "validate-dataset-run.ps1"),
    "-DatasetRunId", $DatasetRunId
)
if ($NoTelemetryExport) {
    $validateArgs += "-AllowMissingRawExports"
}

& powershell @validateArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dataset validation failed for $DatasetRunId."
}

Write-Host "Dataset collection workflow complete:"
Write-Host "  dataset_run_id: $DatasetRunId"
Write-Host "  run_root: $runRoot"
