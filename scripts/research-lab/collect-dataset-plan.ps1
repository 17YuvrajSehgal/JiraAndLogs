[CmdletBinding()]
param(
    [string]$DatasetRunId = ("run-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")),
    [string]$PlanFile = "deploy\research-lab\run-plans\dataset-v2-pilot.json",
    [switch]$Quick,
    [switch]$RecordOnly,
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$RealisticJiraNoise,
    [switch]$ForceNewRun,
    [switch]$BuildDerived,
    [int]$ScenarioDurationSeconds = 0,
    [int]$PostWindowSeconds = -1
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

function Resolve-ResearchLabInputPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return (Join-ResearchLabPath @((Get-ResearchLabRepoRoot), $Path))
}

function Get-PlanValue {
    param(
        [object]$Object,
        [string]$Name,
        [object]$DefaultValue = $null
    )

    $value = Get-ResearchLabProperty -Object $Object -Name $Name
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        return $DefaultValue
    }

    return $value
}

function Get-PlanBoolean {
    param(
        [object]$Object,
        [string]$Name,
        [bool]$DefaultValue = $false
    )

    $value = Get-ResearchLabProperty -Object $Object -Name $Name
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        return $DefaultValue
    }
    if ($value -is [bool]) {
        return [bool]$value
    }
    return [System.Convert]::ToBoolean([string]$value)
}

$resolvedPlanFile = Resolve-ResearchLabInputPath -Path $PlanFile
if (-not (Test-Path -LiteralPath $resolvedPlanFile)) {
    throw "Run plan not found: $resolvedPlanFile"
}
$powerShell = Get-ResearchLabPowerShellCommand

$plan = Get-Content -LiteralPath $resolvedPlanFile -Raw | ConvertFrom-Json
$planId = [string](Get-PlanValue -Object $plan -Name "plan_id" -DefaultValue "dataset-plan")
$trafficProfileId = [string](Get-PlanValue -Object $plan -Name "traffic_profile_id" -DefaultValue "baseline-checkout-mix")
$environment = [string](Get-PlanValue -Object $plan -Name "environment" -DefaultValue "research-local")
$defaultPostWindowSeconds = [int](Get-PlanValue -Object $plan -Name "default_post_window_seconds" -DefaultValue 180)
$quickDurationSeconds = [int](Get-PlanValue -Object $plan -Name "quick_duration_seconds" -DefaultValue 90)
$quickPostWindowSeconds = [int](Get-PlanValue -Object $plan -Name "quick_post_window_seconds" -DefaultValue 60)
$planRealisticJiraNoise = Get-PlanBoolean -Object $plan -Name "realistic_jira_noise" -DefaultValue $false

if ($Quick) {
    $defaultPostWindowSeconds = $quickPostWindowSeconds
}
if ($PostWindowSeconds -ge 0) {
    $defaultPostWindowSeconds = $PostWindowSeconds
}

$scenarioPlan = @()
foreach ($entry in @($plan.scenarios)) {
    $repeat = [int](Get-PlanValue -Object $entry -Name "repeat" -DefaultValue 1)
    if ($repeat -lt 1) {
        throw "Scenario repeat must be at least 1 in plan $resolvedPlanFile."
    }

    for ($i = 0; $i -lt $repeat; $i++) {
        $scenarioPlan += $entry
    }
}

if ($scenarioPlan.Count -eq 0) {
    throw "Run plan has no scenarios: $resolvedPlanFile"
}

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if ((Test-Path -LiteralPath (Join-Path $runRoot "manifest.json")) -and -not $ForceNewRun) {
    Write-Host "Using existing dataset run: $DatasetRunId"
} else {
    $startArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "start-dataset-run.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-Environment", $environment,
        "-ScenarioId", $planId,
        "-TrafficProfileId", $trafficProfileId,
        "-Notes", "Collected through collect-dataset-plan.ps1 with plan $planId from $PlanFile"
    )
    if ($ForceNewRun) {
        $startArgs += "-Force"
    }

    & $powerShell @startArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start dataset run $DatasetRunId."
    }
}

$index = 0
foreach ($entry in $scenarioPlan) {
    $index++
    $scenarioFile = [string](Get-PlanValue -Object $entry -Name "scenario_file")
    if (-not $scenarioFile) {
        throw "Scenario entry $index in $resolvedPlanFile is missing scenario_file."
    }

    $duration = 0
    if ($Quick) {
        $duration = [int](Get-PlanValue -Object $entry -Name "quick_duration_seconds" -DefaultValue $quickDurationSeconds)
    } else {
        $duration = [int](Get-PlanValue -Object $entry -Name "duration_seconds" -DefaultValue 0)
    }
    if ($ScenarioDurationSeconds -gt 0) {
        $duration = $ScenarioDurationSeconds
    }

    $postWindow = [int](Get-PlanValue -Object $entry -Name "post_window_seconds" -DefaultValue $defaultPostWindowSeconds)
    if ($Quick) {
        $postWindow = [int](Get-PlanValue -Object $entry -Name "quick_post_window_seconds" -DefaultValue $defaultPostWindowSeconds)
    }
    if ($PostWindowSeconds -ge 0) {
        $postWindow = $PostWindowSeconds
    }

    $action = [string](Get-PlanValue -Object $entry -Name "action" -DefaultValue "Auto")
    if ($RecordOnly) {
        $action = "RecordOnly"
    }

    Write-Host "Plan step $index of $($scenarioPlan.Count): $scenarioFile"

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
    $entryRealisticJiraNoise = Get-PlanBoolean -Object $entry -Name "realistic_jira_noise" -DefaultValue $planRealisticJiraNoise
    if ($RealisticJiraNoise -or $entryRealisticJiraNoise) {
        $args += "-RealisticJiraNoise"
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

if ($BuildDerived) {
    & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build-ranking-dataset.ps1") `
        -DatasetRunId $DatasetRunId `
        -Force
    if ($LASTEXITCODE -ne 0) {
        throw "Derived ranking dataset build failed for $DatasetRunId."
    }
}

Write-Host "Dataset plan workflow complete:"
Write-Host "  dataset_run_id: $DatasetRunId"
Write-Host "  plan_id: $planId"
Write-Host "  scenarios_run: $($scenarioPlan.Count)"
Write-Host "  run_root: $runRoot"
