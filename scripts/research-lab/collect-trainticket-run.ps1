[CmdletBinding()]
param(
    [string]$DatasetRunId = ("trainticket-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")),
    [string]$WorkloadNamespace = "trainticket",
    [string]$ObservabilityNamespace = "observability",
    [switch]$Quick,
    [switch]$RecordOnly,
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$ForceNewRun,
    [int]$ScenarioDurationSeconds = 0,
    [int]$PostWindowSeconds = -1
)

# Train-ticket equivalent of collect-dataset-run.ps1.
# Differences from the boutique version:
#   * Uses scenarios under deploy/research-lab/scenarios/trainticket/
#   * Defaults workload namespace to `trainticket`
#   * Tags the run manifest with DatasetName=train-ticket-jira-telemetry
# The downstream scripts (run-scenario, export-telemetry-window) are app-
# agnostic and pick up the namespace from the scenario YAML or via param.

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
$powerShell = Get-ResearchLabPowerShellCommand

if ((Test-Path -LiteralPath (Join-Path $runRoot "manifest.json")) -and -not $ForceNewRun) {
    Write-Host "Using existing dataset run: $DatasetRunId"
} else {
    $startArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "start-dataset-run.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-DatasetName", "train-ticket-jira-telemetry",
        "-ScenarioId", "tt-pilot-collection",
        "-TrafficProfileId", "trainticket-booking-mix",
        "-WorkloadNamespace", $WorkloadNamespace,
        "-ObservabilityNamespace", $ObservabilityNamespace,
        "-Notes", "Collected through collect-trainticket-run.ps1"
    )
    if ($ForceNewRun) {
        $startArgs += "-Force"
    }

    & $powerShell @startArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start dataset run $DatasetRunId."
    }
}

$scenarios = @(
    "deploy\research-lab\scenarios\trainticket\baselines\baseline-normal-traffic.yaml",
    "deploy\research-lab\scenarios\trainticket\faults\ts-auth-service-unavailable-critical.yaml",
    "deploy\research-lab\scenarios\trainticket\faults\ts-preserve-service-unavailable-critical.yaml",
    "deploy\research-lab\scenarios\trainticket\faults\ts-order-service-pod-restart-major.yaml",
    "deploy\research-lab\scenarios\trainticket\faults\ts-config-service-unavailable-nearmiss.yaml",
    "deploy\research-lab\scenarios\trainticket\baselines\baseline-normal-traffic.yaml"
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
        "-Namespace", $WorkloadNamespace,
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

    & $powerShell @args
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
        "-WorkloadNamespace", $WorkloadNamespace,
        "-RunLevelLokiOnly"
    )

    & $powerShell @runContextArgs
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

& $powerShell @validateArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dataset validation failed for $DatasetRunId."
}

Write-Host "Train-ticket dataset collection workflow complete:"
Write-Host "  dataset_run_id: $DatasetRunId"
Write-Host "  run_root: $runRoot"
