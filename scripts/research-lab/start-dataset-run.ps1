[CmdletBinding()]
param(
    [string]$DatasetRunId = ("run-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")),
    [string]$DatasetName = "online-boutique-jira-telemetry",
    [string]$Environment = "research-local",
    [string]$TrafficProfileId = "baseline-checkout-mix",
    [string]$ScenarioId = "baseline-normal-traffic",
    [string]$WorkloadNamespace = "online-boutique-research",
    [string]$ObservabilityNamespace = "observability",
    [string]$Notes = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if ((Test-Path -LiteralPath $runRoot) -and -not $Force) {
    throw "Dataset run already exists: $runRoot. Use -Force to recreate the run scaffold."
}

New-ResearchLabDirectory -Path $runRoot
New-ResearchLabDirectory -Path (Join-ResearchLabPath @($runRoot, "raw", "loki"))
New-ResearchLabDirectory -Path (Join-ResearchLabPath @($runRoot, "raw", "prometheus"))
New-ResearchLabDirectory -Path (Join-ResearchLabPath @($runRoot, "raw", "tempo"))
New-ResearchLabDirectory -Path (Join-ResearchLabPath @($runRoot, "summaries"))

$jsonlFiles = @(
    "episodes.jsonl",
    "telemetry_windows.jsonl",
    "alerts.jsonl",
    "jira_shadow_issues.jsonl"
)

foreach ($fileName in $jsonlFiles) {
    $path = Join-Path $runRoot $fileName
    if ($Force -or -not (Test-Path -LiteralPath $path)) {
        Set-Content -LiteralPath $path -Value @() -Encoding UTF8
    }
}

$services = @(Get-ResearchLabWorkloadServices -Namespace $WorkloadNamespace)
$context = Get-ResearchLabKubeContext

$manifestPath = Join-Path $runRoot "manifest.json"

$manifest = [ordered]@{
    dataset_run_id = $DatasetRunId
    dataset_name = $DatasetName
    started_at = Get-ResearchLabUtcNow
    ended_at = $null
    environment = $Environment
    git = Get-ResearchLabGitInfo
    workload = [ordered]@{
        name = "online-boutique"
        namespace = $WorkloadNamespace
        image_tag = $null
        services = $services
        cluster_context = $context
        traffic_profile_id = $TrafficProfileId
        scenario_id = $ScenarioId
    }
    observability_stack = [ordered]@{
        metrics = "prometheus"
        logs = "loki"
        traces = "tempo"
        dashboards = "grafana"
        alerts = "alertmanager"
        namespace = $ObservabilityNamespace
    }
    notes = $Notes
}

Write-ResearchLabJsonFile -Path $manifestPath -Value $manifest

$summary = @(
    "# Dataset Run $DatasetRunId",
    "",
    "- Dataset: $DatasetName",
    "- Environment: $Environment",
    "- Kubernetes context: $context",
    "- Workload namespace: $WorkloadNamespace",
    "- Observability namespace: $ObservabilityNamespace",
    "- Traffic profile: $TrafficProfileId",
    "- Initial scenario: $ScenarioId",
    "- Started at: $($manifest.started_at)",
    "",
    "## Next Commands",
    "",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-scenario.ps1 -DatasetRunId `"$DatasetRunId`" -ScenarioFile deploy\research-lab\scenarios\baselines\baseline-normal-traffic.yaml",
    "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\validate-dataset-run.ps1 -DatasetRunId `"$DatasetRunId`""
)

Set-Content -LiteralPath (Join-ResearchLabPath @($runRoot, "summaries", "run-summary.md")) -Value $summary -Encoding UTF8

Write-Host "Dataset run scaffold created:"
Write-Host "  $runRoot"
Write-Host ""
Write-Host "Manifest:"
Write-Host "  $manifestPath"
