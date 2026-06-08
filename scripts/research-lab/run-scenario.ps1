[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [Parameter(Mandatory = $true)]
    [string]$ScenarioFile,

    [ValidateSet("Auto", "RecordOnly", "SetEnv", "RestartPods", "ScaleDeployment", "ChaosMeshChaos", "Flagd", "MultiFault")]
    [string]$Action = "Auto",

    [int]$DurationSeconds = 0,
    [int]$PreWindowSeconds = 300,
    [int]$PostWindowSeconds = 180,
    [string]$Namespace = "online-boutique-research",
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$RealisticJiraNoise,
    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

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

    if ($SelectedAction -eq "ChaosMeshChaos") {
        # D11 (2026-05-25): apply a chaos-mesh resource (NetworkChaos,
        # StressChaos, DNSChaos, IOChaos, etc.) for ActiveDurationSeconds
        # then delete it. The chaos resource lives in its own manifest
        # file under deploy/research-lab/scenarios/chaos/ so the scenario
        # YAML stays orchestration-only.
        #
        # Prerequisite: chaos-mesh must be installed in the cluster
        # (chaos-testing namespace + CRDs). See install steps in
        # docs/gcp-production-dataset-vm-runbook.md "Install chaos-mesh".
        #
        # Hardening (2026-05-25): chaos-mesh resources have finalizers
        # that block deletion until `AllRecovered: True`. If the inject
        # failed (e.g. safe-mode blocks targeting kube-system pods),
        # AllRecovered stays False forever and `kubectl delete` hangs.
        # We use a bounded delete (--timeout=45s) and fall back to
        # patching the finalizer off if the bounded delete fails.
        $manifest = $Scenario.execution_chaos_manifest
        if (-not $manifest) {
            throw "ChaosMeshChaos action requires execution.chaos_manifest (path to a chaos-mesh resource yaml)."
        }
        $repoRoot = Get-ResearchLabRepoRoot
        $manifestPath = if ([System.IO.Path]::IsPathRooted($manifest)) {
            $manifest
        } else {
            Join-ResearchLabPath @($repoRoot, $manifest)
        }
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            throw "ChaosMeshChaos manifest not found: $manifestPath"
        }

        # Parse name/kind/namespace from the manifest for finalizer-fallback.
        $chaosKind = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^kind:" | Select-Object -First 1).Line -replace "^kind:\s*", ""
        $chaosName = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^\s+name:" | Select-Object -First 1).Line -replace "^\s+name:\s*", ""
        $chaosNs = (Get-Content -LiteralPath $manifestPath | Select-String -Pattern "^\s+namespace:" | Select-Object -First 1).Line -replace "^\s+namespace:\s*", ""
        $chaosResource = "$($chaosKind.ToLower())/$chaosName"

        Write-Host "ChaosMeshChaos applying: $manifestPath ($chaosResource in $chaosNs)"
        Invoke-ResearchLabKubectlText -ArgumentList @("apply", "-f", $manifestPath) | Out-Host
        $restore.chaos_manifest = $manifestPath
        $restore.chaos_resource = $chaosResource
        $restore.chaos_namespace = $chaosNs

        # Brief settle so the chaos-controller has time to schedule the
        # action onto the affected pods before we start the active-fault
        # window timer.
        Start-Sleep -Seconds 5

        Start-Sleep -Seconds $ActiveDurationSeconds

        if (-not $DoNotRestore) {
            Write-Host "ChaosMeshChaos deleting (bounded 45s): $chaosResource"
            $deleteOk = $false
            try {
                Invoke-ResearchLabKubectlText -ArgumentList @(
                    "delete", "-f", $manifestPath,
                    "--ignore-not-found=true",
                    "--timeout=45s"
                ) | Out-Host
                $deleteOk = ($LASTEXITCODE -eq 0)
            } catch {
                Write-Warning "Bounded delete threw: $($_.Exception.Message)"
                $deleteOk = $false
            }

            if (-not $deleteOk) {
                # Finalizer fallback: patch finalizers to [] then force-delete.
                # Happens when chaos-mesh's AllInjected stayed False (e.g. the
                # chaos couldn't be applied to the targeted pods at all),
                # so AllRecovered also stays False and the finalizer blocks
                # the normal delete forever.
                Write-Warning "Bounded delete failed; patching finalizer + force-delete: $chaosResource"
                try {
                    Invoke-ResearchLabKubectlText -ArgumentList @(
                        "patch", $chaosResource, "-n", $chaosNs,
                        "--type=merge", "-p", '{"metadata":{"finalizers":[]}}'
                    ) | Out-Host
                } catch {
                    Write-Warning "Finalizer patch failed: $($_.Exception.Message)"
                }
                try {
                    Invoke-ResearchLabKubectlText -ArgumentList @(
                        "delete", $chaosResource, "-n", $chaosNs,
                        "--grace-period=0", "--force",
                        "--ignore-not-found=true"
                    ) | Out-Host
                } catch {
                    Write-Warning "Force-delete failed: $($_.Exception.Message)"
                }
            }
            # Brief settle so cleanup actions (iptables rules, sidecar
            # removals) finish before the recovery window starts.
            Start-Sleep -Seconds 5
        }

        return $restore
    }

    if ($SelectedAction -eq "MultiFault") {
        # OTel Demo multi-fault orchestration (docs5/01 Phase 1c).
        # Delegates entirely to scripts/research-lab/otel-demo/Invoke-MultiFaultOrchestration.ps1
        # which owns the inject/wait/restore sequence for L2/L3/L4 scenarios.
        $compType = $Scenario.execution_composition_type
        if (-not $compType) {
            throw "MultiFault action requires execution.composition_type (concurrent | cascade | compound_primitive)."
        }
        $componentsFile = $Scenario.execution_components_file
        if (-not $componentsFile) {
            throw "MultiFault action requires execution.components_file (path to sidecar JSON)."
        }
        if (-not [System.IO.Path]::IsPathRooted($componentsFile)) {
            $componentsFile = Join-ResearchLabPath @((Get-ResearchLabRepoRoot), $componentsFile)
        }
        if (-not (Test-Path -LiteralPath $componentsFile)) {
            throw "MultiFault components file not found: $componentsFile"
        }

        $orchestrator = Join-Path $PSScriptRoot (Join-Path "otel-demo" "Invoke-MultiFaultOrchestration.ps1")
        if (-not (Test-Path -LiteralPath $orchestrator)) {
            throw "Invoke-MultiFaultOrchestration.ps1 not found at $orchestrator"
        }

        $orchestratorArgs = @(
            "-ComponentsFile", $componentsFile,
            "-CompositionType", $compType,
            "-DurationSeconds", $ActiveDurationSeconds,
            "-Namespace", $TargetNamespace
        )
        if ($Scenario.execution_cascade_emergence_window_seconds) {
            $orchestratorArgs += "-CascadeEmergenceWindowSeconds"
            $orchestratorArgs += [int]$Scenario.execution_cascade_emergence_window_seconds
        }
        if ($DoNotRestore) {
            $orchestratorArgs += "-SkipRestore"
        }

        Write-Host "MultiFault dispatch -> $orchestrator"
        $orchResult = & pwsh -NoProfile -ExecutionPolicy Bypass -File $orchestrator @orchestratorArgs
        $restore.composition_type = $compType
        $restore.components_file = $componentsFile
        $restore.orchestrator_result = $orchResult
        return $restore
    }

    if ($SelectedAction -eq "Flagd") {
        # OTel Demo-specific primitive (introduced 2026-06-08, docs5/01 Phase 1b).
        # Delegates to scripts/research-lab/otel-demo/Invoke-FlagdFlip.ps1
        # which patches the flagd ConfigMap, sleeps DurationSeconds, then
        # restores the original variant. Active-fault window timing is owned
        # by the helper (the inject/sleep/restore sequence) so we do NOT
        # Start-Sleep here.
        $flagName = $Scenario.execution_flagd_flag
        if (-not $flagName) {
            $flagName = $Scenario.flagd_flag
        }
        if (-not $flagName) {
            throw "Flagd action requires execution.flagd_flag (flag name)."
        }
        $variant = $Scenario.execution_flagd_variant
        if (-not $variant) {
            $variant = "on"
        }
        $cmName = $Scenario.execution_flagd_configmap_name
        if (-not $cmName) {
            $cmName = "otel-demo-flagd-config"
        }
        $cmKey = $Scenario.execution_flagd_configmap_key
        if (-not $cmKey) {
            $cmKey = "demo.flagd.json"
        }

        $flipScript = Join-Path $PSScriptRoot (Join-Path "otel-demo" "Invoke-FlagdFlip.ps1")
        if (-not (Test-Path -LiteralPath $flipScript)) {
            throw "Invoke-FlagdFlip.ps1 not found at $flipScript"
        }

        Write-Host "Flagd action: flag='$flagName' variant='$variant' ns='$TargetNamespace' configmap='$cmName/$cmKey'"
        $flipArgs = @(
            "-FlagName", $flagName,
            "-Variant", $variant,
            "-DurationSeconds", $ActiveDurationSeconds,
            "-Namespace", $TargetNamespace,
            "-ConfigMapName", $cmName,
            "-ConfigMapKey", $cmKey
        )
        if ($DoNotRestore) {
            $flipArgs += "-SkipRestore"
        }

        $flipResult = & pwsh -NoProfile -ExecutionPolicy Bypass -File $flipScript @flipArgs
        $restore.flagd_flag = $flagName
        $restore.flagd_variant_applied = $variant
        $restore.flagd_configmap = "$cmName/$cmKey"
        $restore.flagd_result = $flipResult
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
    $scenarioPath = Join-ResearchLabPath @((Get-ResearchLabRepoRoot), $scenarioPath)
}

$scenario = Get-ResearchLabScenarioConfig -ScenarioFile $scenarioPath
$powerShell = Get-ResearchLabPowerShellCommand

# Record provenance: scenario YAML SHA256, file size, and whether the
# YAML carries an authored triage block. The SHA pins the exact label
# decisions used for this episode so a reviewer can detect mid-collection
# scenario edits.
$scenarioYamlSha = $null
$scenarioYamlBytes = 0
$scenarioTriageBlockPresent = $false
try {
    $scenarioYamlBytes = (Get-Item -LiteralPath $scenarioPath).Length
    $hash = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($scenarioPath)
        $hashBytes = $hash.ComputeHash($bytes)
        $scenarioYamlSha = (($hashBytes | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $hash.Dispose()
    }
    $rawYamlText = [System.IO.File]::ReadAllText($scenarioPath)
    $scenarioTriageBlockPresent = ($rawYamlText -match '(?m)^triage:\s*$')
} catch {
    Write-Warning "Could not hash scenario YAML at ${scenarioPath}: $($_.Exception.Message)"
}
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
    # D12.1: orphan-fault gate. True = scenario produces a Jira ticket
    # (normal behavior); False = orphan fault, no ticket filed.
    produces_jira_ticket = [bool]$scenario.produces_jira_ticket
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
    provenance = [ordered]@{
        scenario_file = ($scenarioPath -replace [Regex]::Escape((Get-ResearchLabRepoRoot) + [System.IO.Path]::DirectorySeparatorChar), "")
        scenario_yaml_sha256 = $scenarioYamlSha
        scenario_yaml_bytes = $scenarioYamlBytes
        scenario_triage_block_present = $scenarioTriageBlockPresent
        recorded_at = Get-ResearchLabUtcNow
    }
}

Merge-ResearchLabJsonLines -Path (Join-Path $runRoot "episodes.jsonl") -Records @($episode) -KeyProperty "incident_episode_id"
Merge-ResearchLabJsonLines -Path (Join-Path $runRoot "telemetry_windows.jsonl") -Records $windowRecords -KeyProperty "telemetry_window_id"

$summaryLine = "- $($episode.start_time) scenario=$($scenario.scenario_id) episode=$episodeId action=$selectedAction windows=$($windowRecords.Count)"
Add-Content -LiteralPath (Join-ResearchLabPath @($runRoot, "summaries", "run-summary.md")) -Value $summaryLine -Encoding UTF8

if (-not $NoTelemetryExport) {
    & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "export-telemetry-window.ps1") `
        -DatasetRunId $DatasetRunId `
        -IncidentEpisodeId $episodeId
    if ($LASTEXITCODE -ne 0) {
        throw "Telemetry export failed for episode $episodeId."
    }
}

# D12.1 (2026-05-24): produces_jira_ticket=false makes a scenario an
# orphan fault — the system records the episode + windows but skips
# shadow-jira generation entirely. The episode's jira_candidate /
# should_create_jira_shadow_issue fields still describe whether a human
# *would have* filed; produces_jira_ticket describes whether one
# actually did.
if ((-not $SkipJiraGeneration) -and [bool]$scenario.should_create_jira_shadow_issue `
        -and [bool]$scenario.produces_jira_ticket) {
    $jiraArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "generate-shadow-jira-issues.ps1"),
        "-DatasetRunId", $DatasetRunId,
        "-IncidentEpisodeId", $episodeId
    )
    if ($RealisticJiraNoise) {
        $jiraArgs += "-RealisticNoise"
    }

    & $powerShell @jiraArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Shadow Jira generation failed for episode $episodeId."
    }
}

Write-Host "Scenario complete:"
Write-Host "  episode_id: $episodeId"
Write-Host "  windows: $($windowRecords.Count)"
