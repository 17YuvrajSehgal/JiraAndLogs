[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [Parameter(Mandatory = $true)]
    [string]$ScenarioFile,

    [ValidateSet("Auto", "RecordOnly", "SetEnv", "RestartPods", "ScaleDeployment")]
    [string]$Action = "Auto",

    [int]$DurationSeconds = 0,
    [int]$PreWindowSeconds = 300,
    [int]$PostWindowSeconds = 180,
    [string]$Namespace = "online-boutique-research",
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\ResearchLab.psm1") -Force

function ConvertTo-SafeIdPart {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9_.-]', '-')
}

function Wait-ResearchLabDeployment {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetNamespace
    )

    Invoke-ResearchLabKubectlText -ArgumentList @(
        "rollout", "status", "deployment/$Name",
        "-n", $TargetNamespace,
        "--timeout=240s"
    ) | Out-Host
}

function Get-DeploymentEnvMap {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetNamespace,
        [string]$TargetContainer
    )

    $deployment = Invoke-ResearchLabKubectlJson -ArgumentList @("get", "deployment", $Name, "-n", $TargetNamespace, "-o", "json")
    $map = [ordered]@{}
    foreach ($container in @($deployment.spec.template.spec.containers)) {
        if ($TargetContainer -and [string]$container.name -ne $TargetContainer) {
            continue
        }
        foreach ($env in @($container.env)) {
            if ($env.name) {
                $map[[string]$env.name] = $env.value
            }
        }
    }
    return $map
}

function Set-DeploymentEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetNamespace,
        [Parameter(Mandatory = $true)][hashtable]$Values,
        [string]$TargetContainer
    )

    $args = @("set", "env", "deployment/$Name", "-n", $TargetNamespace)
    if ($TargetContainer) {
        $args += "--containers=$TargetContainer"
    }
    foreach ($key in $Values.Keys) {
        $value = $Values[$key]
        if ($null -eq $value) {
            $args += "$key-"
        } else {
            $args += "$key=$value"
        }
    }

    Invoke-ResearchLabKubectlText -ArgumentList $args | Out-Host
    Wait-ResearchLabDeployment -Name $Name -TargetNamespace $TargetNamespace
}

function Invoke-ScenarioAction {
    param(
        [Parameter(Mandatory = $true)][object]$Scenario,
        [Parameter(Mandatory = $true)][string]$SelectedAction,
        [Parameter(Mandatory = $true)][string]$TargetNamespace,
        [Parameter(Mandatory = $true)][int]$ActiveDurationSeconds,
        [switch]$DoNotRestore
    )

    $restore = [ordered]@{
        action = $SelectedAction
        namespace = $TargetNamespace
        target_name = $Scenario.execution_target_name
        target_container = $Scenario.execution_target_container
        selector = $Scenario.execution_selector
        original_replicas = $null
        original_env = $null
    }

    if ($SelectedAction -eq "RecordOnly") {
        Start-Sleep -Seconds $ActiveDurationSeconds
        return $restore
    }

    if ($SelectedAction -eq "SetEnv") {
        $target = $Scenario.execution_target_name
        if (-not $target) {
            $target = $Scenario.affected_service
        }
        if (-not $target) {
            throw "SetEnv action requires execution.target_name or fault.affected_service."
        }

        $envValues = @{}
        foreach ($key in $Scenario.execution_env.Keys) {
            $envValues[$key] = [string]$Scenario.execution_env[$key]
        }
        if ($envValues.Count -eq 0) {
            throw "SetEnv action requires execution.env values."
        }

        $targetContainer = $Scenario.execution_target_container
        $restore.original_env = Get-DeploymentEnvMap -Name $target -TargetNamespace $TargetNamespace -TargetContainer $targetContainer
        Set-DeploymentEnv -Name $target -TargetNamespace $TargetNamespace -Values $envValues -TargetContainer $targetContainer
        Start-Sleep -Seconds $ActiveDurationSeconds

        if (-not $DoNotRestore) {
            $restoreValues = @{}
            foreach ($key in $envValues.Keys) {
                if ($restore.original_env.Contains($key)) {
                    $restoreValues[$key] = $restore.original_env[$key]
                } else {
                    $restoreValues[$key] = $null
                }
            }
            Set-DeploymentEnv -Name $target -TargetNamespace $TargetNamespace -Values $restoreValues -TargetContainer $targetContainer
        }

        return $restore
    }

    if ($SelectedAction -eq "RestartPods") {
        $selector = $Scenario.execution_selector
        if (-not $selector) {
            $selector = "app=$($Scenario.affected_service)"
        }
        if (-not $selector) {
            throw "RestartPods action requires execution.selector or fault.affected_service."
        }

        Invoke-ResearchLabKubectlText -ArgumentList @("delete", "pod", "-n", $TargetNamespace, "-l", $selector) | Out-Host
        Start-Sleep -Seconds 5
        Invoke-ResearchLabKubectlText -ArgumentList @(
            "wait", "--for=condition=Ready", "pods",
            "-n", $TargetNamespace,
            "-l", $selector,
            "--timeout=240s"
        ) | Out-Host
        Start-Sleep -Seconds $ActiveDurationSeconds
        return $restore
    }

    if ($SelectedAction -eq "ScaleDeployment") {
        $target = $Scenario.execution_target_name
        if (-not $target) {
            $target = $Scenario.affected_service
        }
        if (-not $target) {
            throw "ScaleDeployment action requires execution.target_name or fault.affected_service."
        }

        $deployment = Invoke-ResearchLabKubectlJson -ArgumentList @("get", "deployment", $target, "-n", $TargetNamespace, "-o", "json")
        $restore.original_replicas = [int]$deployment.spec.replicas

        $replicas = 0
        if ($null -ne $Scenario.execution_replicas) {
            $replicas = [int]$Scenario.execution_replicas
        }

        Invoke-ResearchLabKubectlText -ArgumentList @("scale", "deployment/$target", "-n", $TargetNamespace, "--replicas=$replicas") | Out-Host
        if ($replicas -gt 0) {
            Wait-ResearchLabDeployment -Name $target -TargetNamespace $TargetNamespace
        }

        Start-Sleep -Seconds $ActiveDurationSeconds

        if (-not $DoNotRestore) {
            $restoreReplicas = $restore.original_replicas
            if ($null -ne $Scenario.execution_restore_replicas) {
                $restoreReplicas = [int]$Scenario.execution_restore_replicas
            }
            Invoke-ResearchLabKubectlText -ArgumentList @("scale", "deployment/$target", "-n", $TargetNamespace, "--replicas=$restoreReplicas") | Out-Host
            Wait-ResearchLabDeployment -Name $target -TargetNamespace $TargetNamespace
        }

        return $restore
    }

    throw "Unsupported action: $SelectedAction"
}

function New-TelemetryWindowRecord {
    param(
        [Parameter(Mandatory = $true)][string]$DatasetRunId,
        [Parameter(Mandatory = $true)][string]$EpisodeId,
        [Parameter(Mandatory = $true)][object]$Scenario,
        [Parameter(Mandatory = $true)][string]$WindowType,
        [Parameter(Mandatory = $true)][DateTimeOffset]$StartTime,
        [Parameter(Mandatory = $true)][DateTimeOffset]$EndTime,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$TargetNamespace
    )

    $safeService = ConvertTo-SafeIdPart -Value $ServiceName
    $windowId = "$(ConvertTo-SafeIdPart -Value $EpisodeId)-$(ConvertTo-SafeIdPart -Value $WindowType)-$safeService"

    return [ordered]@{
        telemetry_window_id = $windowId
        dataset_run_id = $DatasetRunId
        incident_episode_id = $EpisodeId
        scenario_id = $Scenario.scenario_id
        fault_id = $Scenario.fault_id
        start_time = $StartTime.ToString("o")
        end_time = $EndTime.ToString("o")
        service_name = $ServiceName
        k8s = [ordered]@{
            namespace = $TargetNamespace
            pod = $null
            node = $null
            deployment = $ServiceName
        }
        trace_ids = @()
        request_ids = @()
        features = [ordered]@{
            metrics = [ordered]@{
                exported = $false
            }
            logs = [ordered]@{
                exported = $false
            }
            traces = [ordered]@{
                exported = $false
            }
        }
        labels = [ordered]@{
            jira_candidate = [bool]$Scenario.should_create_jira_shadow_issue
            severity = $Scenario.severity
            affected_service = $Scenario.affected_service
            incident_type = $Scenario.incident_type
            root_cause_category = $Scenario.root_cause_category
            window_type = $WindowType
        }
    }
}

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if (-not (Test-Path -LiteralPath (Join-Path $runRoot "manifest.json"))) {
    throw "Dataset run does not exist. Start it first with start-dataset-run.ps1: $DatasetRunId"
}

$scenarioPath = $ScenarioFile
if (-not [System.IO.Path]::IsPathRooted($scenarioPath)) {
    $scenarioPath = Join-Path (Get-ResearchLabRepoRoot) $scenarioPath
}

$scenario = Get-ResearchLabScenarioConfig -ScenarioFile $scenarioPath
if ($scenario.execution_namespace) {
    $Namespace = $scenario.execution_namespace
}

$selectedAction = $Action
if ($selectedAction -eq "Auto") {
    if ($scenario.execution_action) {
        $selectedAction = $scenario.execution_action
    } else {
        $selectedAction = "RecordOnly"
    }
}

if ($DurationSeconds -le 0) {
    $DurationSeconds = [int]$scenario.expected_duration_seconds
}

$timestampPart = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$episodeId = "$(ConvertTo-SafeIdPart -Value $DatasetRunId)-$(ConvertTo-SafeIdPart -Value $scenario.scenario_id)-$timestampPart"

$preStart = [DateTimeOffset]::UtcNow.AddSeconds(-1 * $PreWindowSeconds)
$runStart = [DateTimeOffset]::UtcNow

Write-Host "Running scenario:"
Write-Host "  dataset_run_id: $DatasetRunId"
Write-Host "  scenario_id: $($scenario.scenario_id)"
Write-Host "  action: $selectedAction"
Write-Host "  duration_seconds: $DurationSeconds"

$actionMetadata = $null
$activeStart = [DateTimeOffset]::UtcNow
$activeEnd = $activeStart
$recoveryEnd = $activeEnd

try {
    $actionMetadata = Invoke-ScenarioAction `
        -Scenario $scenario `
        -SelectedAction $selectedAction `
        -TargetNamespace $Namespace `
        -ActiveDurationSeconds $DurationSeconds `
        -DoNotRestore:$SkipRestore

    $activeEnd = [DateTimeOffset]::UtcNow

    if ($PostWindowSeconds -gt 0) {
        Start-Sleep -Seconds $PostWindowSeconds
    }
    $recoveryEnd = [DateTimeOffset]::UtcNow
} catch {
    $activeEnd = [DateTimeOffset]::UtcNow
    throw
}

$services = @(Get-ResearchLabScenarioServices -Scenario $scenario)
if ($services.Count -eq 0) {
    $services = @($scenario.affected_service)
}

$windowRecords = @()
if ($selectedAction -eq "RecordOnly") {
    foreach ($service in $services) {
        $windowRecords += New-TelemetryWindowRecord `
            -DatasetRunId $DatasetRunId `
            -EpisodeId $episodeId `
            -Scenario $scenario `
            -WindowType "observation_window" `
            -StartTime $runStart `
            -EndTime $activeEnd `
            -ServiceName $service `
            -TargetNamespace $Namespace
    }
} else {
    foreach ($service in $services) {
        $windowRecords += New-TelemetryWindowRecord `
            -DatasetRunId $DatasetRunId `
            -EpisodeId $episodeId `
            -Scenario $scenario `
            -WindowType "pre_fault_baseline" `
            -StartTime $preStart `
            -EndTime $runStart `
            -ServiceName $service `
            -TargetNamespace $Namespace

        $windowRecords += New-TelemetryWindowRecord `
            -DatasetRunId $DatasetRunId `
            -EpisodeId $episodeId `
            -Scenario $scenario `
            -WindowType "active_fault" `
            -StartTime $activeStart `
            -EndTime $activeEnd `
            -ServiceName $service `
            -TargetNamespace $Namespace

        if ($PostWindowSeconds -gt 0) {
            $windowRecords += New-TelemetryWindowRecord `
                -DatasetRunId $DatasetRunId `
                -EpisodeId $episodeId `
                -Scenario $scenario `
                -WindowType "recovery_window" `
                -StartTime $activeEnd `
                -EndTime $recoveryEnd `
                -ServiceName $service `
                -TargetNamespace $Namespace
        }
    }
}

$episode = [ordered]@{
    incident_episode_id = $episodeId
    dataset_run_id = $DatasetRunId
    scenario_id = $scenario.scenario_id
    fault_id = $scenario.fault_id
    traffic_profile_id = $scenario.traffic_profile_id
    start_time = $runStart.ToString("o")
    end_time = $recoveryEnd.ToString("o")
    affected_services = $services
    severity = $scenario.severity
    incident_type = $scenario.incident_type
    root_cause_category = $scenario.root_cause_category
    jira_candidate = [bool]$scenario.should_create_jira_shadow_issue
    jira_shadow_issue_id = $null
    jira_issue_key = $null
    alert_fingerprints = @()
    trace_ids = @()
    telemetry_window_ids = @($windowRecords | ForEach-Object { $_.telemetry_window_id })
    labels = [ordered]@{
        title = $scenario.title
        action = $selectedAction
        should_alert = $scenario.should_alert
        should_create_jira_shadow_issue = [bool]$scenario.should_create_jira_shadow_issue
    }
    ground_truth = [ordered]@{
        injected = ($selectedAction -ne "RecordOnly")
        fault_type = $scenario.fault_type
        expected_user_impact = $scenario.expected_user_impact
        expected_error_rate = $scenario.expected_error_rate
        expected_latency_impact = $scenario.expected_latency_impact
        action_metadata = $actionMetadata
    }
}

Merge-ResearchLabJsonLines -Path (Join-Path $runRoot "episodes.jsonl") -Records @($episode) -KeyProperty "incident_episode_id"
Merge-ResearchLabJsonLines -Path (Join-Path $runRoot "telemetry_windows.jsonl") -Records $windowRecords -KeyProperty "telemetry_window_id"

$summaryLine = "- $($episode.start_time) scenario=$($scenario.scenario_id) episode=$episodeId action=$selectedAction windows=$($windowRecords.Count)"
Add-Content -LiteralPath (Join-ResearchLabPath @($runRoot, "summaries", "run-summary.md")) -Value $summaryLine -Encoding UTF8

if (-not $NoTelemetryExport) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "export-telemetry-window.ps1") `
        -DatasetRunId $DatasetRunId `
        -IncidentEpisodeId $episodeId
    if ($LASTEXITCODE -ne 0) {
        throw "Telemetry export failed for episode $episodeId."
    }
}

if ((-not $SkipJiraGeneration) -and [bool]$scenario.should_create_jira_shadow_issue) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "generate-shadow-jira-issues.ps1") `
        -DatasetRunId $DatasetRunId `
        -IncidentEpisodeId $episodeId
    if ($LASTEXITCODE -ne 0) {
        throw "Shadow Jira generation failed for episode $episodeId."
    }
}

Write-Host "Scenario complete:"
Write-Host "  episode_id: $episodeId"
Write-Host "  windows: $($windowRecords.Count)"
