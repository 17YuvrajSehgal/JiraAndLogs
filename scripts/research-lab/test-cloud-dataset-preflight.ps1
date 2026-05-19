[CmdletBinding()]
param(
    [string]$CorpusFile = "deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json",
    [string]$DatasetRunPrefix = "preflight-dataset",
    [string]$Bucket = "",
    [int]$MinFreeDiskGb = 250,
    [string]$PythonExe = "python3",
    [switch]$SkipClusterChecks
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Write-PreflightPass {
    param([string]$Message)
    Write-Host "[PASS] $Message"
}

function Write-PreflightWarn {
    param([string]$Message)
    $warnings.Add($Message) | Out-Null
    Write-Host "[WARN] $Message"
}

function Write-PreflightFail {
    param([string]$Message)
    $failures.Add($Message) | Out-Null
    Write-Host "[FAIL] $Message"
}

function Resolve-PreflightPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return (Join-ResearchLabPath @((Get-ResearchLabRepoRoot), $Path))
}

function Test-PreflightCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Required
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        if ($Required) {
            Write-PreflightFail "Missing required command: $Name"
        } else {
            Write-PreflightWarn "Missing optional command: $Name"
        }
        return $false
    }

    Write-PreflightPass "$Name found at $($cmd.Source)"
    return $true
}

function Invoke-PreflightJsonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$Description
    )

    try {
        $output = & $Command @ArgumentList 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-PreflightFail "$Description failed: $($output -join ' ')"
            return $null
        }
        return ($output -join "`n") | ConvertFrom-Json
    } catch {
        Write-PreflightFail "$Description failed: $($_.Exception.Message)"
        return $null
    }
}

function Test-PreflightPodsReady {
    param([Parameter(Mandatory = $true)][string]$Namespace)

    $pods = Invoke-PreflightJsonCommand -Command "kubectl" -ArgumentList @("get", "pods", "-n", $Namespace, "-o", "json") -Description "kubectl get pods in $Namespace"
    if ($null -eq $pods) {
        return
    }

    $items = @($pods.items)
    if ($items.Count -eq 0) {
        Write-PreflightFail "No pods found in namespace $Namespace"
        return
    }

    $notReady = @()
    foreach ($pod in $items) {
        $phase = [string]$pod.status.phase
        $readyCondition = @($pod.status.conditions | Where-Object { $_.type -eq "Ready" } | Select-Object -First 1)
        $isReady = ($phase -eq "Running" -and $readyCondition.Count -gt 0 -and [string]$readyCondition[0].status -eq "True")
        if (-not $isReady) {
            $notReady += "$($pod.metadata.name):$phase"
        }
    }

    if ($notReady.Count -gt 0) {
        Write-PreflightFail "Namespace $Namespace has non-ready pods: $($notReady -join ', ')"
        return
    }

    Write-PreflightPass "All pods are ready in namespace $Namespace ($($items.Count) pods)"
}

function Test-PreflightService {
    param(
        [Parameter(Mandatory = $true)][string]$Namespace,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    $output = kubectl get "svc/$ServiceName" -n $Namespace 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-PreflightFail "Missing service $Namespace/$ServiceName"
        return
    }

    Write-PreflightPass "Service exists: $Namespace/$ServiceName"
}

$repoRoot = Get-ResearchLabRepoRoot
Write-Host "Research lab cloud dataset preflight"
Write-Host "  repo_root: $repoRoot"
Write-Host "  corpus_file: $CorpusFile"
Write-Host "  dataset_run_prefix: $DatasetRunPrefix"
Write-Host "  min_free_disk_gb: $MinFreeDiskGb"
if ($Bucket) {
    Write-Host "  bucket: $Bucket"
}
Write-Host ""

Test-PreflightCommand -Name "docker" -Required | Out-Null
Test-PreflightCommand -Name "kubectl" -Required | Out-Null
Test-PreflightCommand -Name "kind" -Required | Out-Null
Test-PreflightCommand -Name "helm" -Required | Out-Null
if (-not (Test-PreflightCommand -Name "pwsh")) {
    Test-PreflightCommand -Name "powershell" -Required | Out-Null
}
if (-not (Test-PreflightCommand -Name $PythonExe -Required)) {
    if ($PythonExe -ne "python") {
        Test-PreflightCommand -Name "python" -Required | Out-Null
    }
}
if ($Bucket) {
    Test-PreflightCommand -Name "gcloud" -Required | Out-Null
}

try {
    $powerShell = Get-ResearchLabPowerShellCommand
    Write-PreflightPass "Child PowerShell command resolves to $powerShell"
} catch {
    Write-PreflightFail $_.Exception.Message
}

try {
    $driveRoot = [System.IO.Path]::GetPathRoot($repoRoot)
    $driveInfo = [System.IO.DriveInfo]::new($driveRoot)
    $freeGb = [math]::Round($driveInfo.AvailableFreeSpace / 1GB, 2)
    if ($freeGb -lt $MinFreeDiskGb) {
        Write-PreflightFail "Free disk is $freeGb GB; expected at least $MinFreeDiskGb GB"
    } else {
        Write-PreflightPass "Free disk is $freeGb GB"
    }
} catch {
    Write-PreflightWarn "Could not determine free disk space: $($_.Exception.Message)"
}

$demoRoot = Join-ResearchLabPath @($repoRoot, "microservices-demo-google")
if (Test-Path -LiteralPath $demoRoot) {
    Write-PreflightPass "Online Boutique clone exists: $demoRoot"
} else {
    Write-PreflightFail "Online Boutique clone is missing: $demoRoot"
}

$resolvedCorpusFile = Resolve-PreflightPath -Path $CorpusFile
if (-not (Test-Path -LiteralPath $resolvedCorpusFile)) {
    Write-PreflightFail "Corpus file not found: $resolvedCorpusFile"
} else {
    try {
        $corpus = Get-Content -LiteralPath $resolvedCorpusFile -Raw | ConvertFrom-Json
        $plannedRunCount = 0
        $planAliases = @{}
        foreach ($plan in @($corpus.plans)) {
            $alias = [string]$plan.plan_alias
            if ($planAliases.ContainsKey($alias)) {
                Write-PreflightFail "Duplicate corpus plan_alias: $alias"
            }
            $planAliases[$alias] = $true

            $repeat = [int]$plan.repeat
            if ($repeat -lt 1) {
                Write-PreflightFail "Corpus plan $alias has repeat < 1"
            }
            $plannedRunCount += $repeat

            $planFile = Resolve-PreflightPath -Path ([string]$plan.plan_file)
            if (-not (Test-Path -LiteralPath $planFile)) {
                Write-PreflightFail "Run plan not found for alias ${alias}: $planFile"
                continue
            }

            $runPlan = Get-Content -LiteralPath $planFile -Raw | ConvertFrom-Json
            $scenarioCount = @($runPlan.scenarios).Count
            if ($scenarioCount -eq 0) {
                Write-PreflightFail "Run plan has no scenarios: $planFile"
            }

            foreach ($entry in @($runPlan.scenarios)) {
                $scenarioFile = Resolve-PreflightPath -Path ([string]$entry.scenario_file)
                if (-not (Test-Path -LiteralPath $scenarioFile)) {
                    Write-PreflightFail "Scenario file not found: $scenarioFile"
                    continue
                }
                try {
                    $scenario = Get-ResearchLabScenarioConfig -ScenarioFile $scenarioFile
                    if (-not $scenario.scenario_id) {
                        Write-PreflightFail "Scenario missing scenario_id: $scenarioFile"
                    }
                    if ($scenario.execution_action -eq "SetEnv" -and $scenario.execution_env.Count -eq 0) {
                        Write-PreflightFail "SetEnv scenario has no execution.env: $scenarioFile"
                    }
                    if ($scenario.execution_action -eq "ScaleDeployment" -and $null -eq $scenario.execution_replicas) {
                        Write-PreflightFail "ScaleDeployment scenario has no execution.replicas: $scenarioFile"
                    }
                    if ($scenario.jira_candidate -and -not $scenario.should_create_jira_shadow_issue) {
                        Write-PreflightWarn "Jira candidate without should_create_jira_shadow_issue=true: $($scenario.scenario_id)"
                    }
                } catch {
                    Write-PreflightFail "Scenario parse failed for ${scenarioFile}: $($_.Exception.Message)"
                }
            }
        }
        Write-PreflightPass "Corpus references are valid; planned runs: $plannedRunCount"
    } catch {
        Write-PreflightFail "Corpus parse failed: $($_.Exception.Message)"
    }
}

try {
    foreach ($file in @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1")) {
        $null = [scriptblock]::Create((Get-Content -LiteralPath $file.FullName -Raw))
    }
    Write-PreflightPass "All research-lab PowerShell scripts parse"
} catch {
    Write-PreflightFail "PowerShell parse check failed: $($_.Exception.Message)"
}

$childPowerShellMatches = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1" | Select-String -Pattern '&\s+powershell\b')
if ($childPowerShellMatches.Count -gt 0) {
    Write-PreflightFail "Found hardcoded child 'powershell' invocations: $($childPowerShellMatches.Count)"
} else {
    Write-PreflightPass "No hardcoded child 'powershell' invocations found"
}

try {
    $pyFiles = @(
        (Join-Path $PSScriptRoot "build_cross_run_evaluation.py"),
        (Join-Path $PSScriptRoot "build_global_hard_negative_dataset.py"),
        (Join-Path $PSScriptRoot "build_ranking_dataset.py"),
        (Join-Path $PSScriptRoot "build_run_aware_holdout_evaluation.py"),
        (Join-Path $PSScriptRoot "run_global_pipeline_benchmark.py")
    )
    & $PythonExe -m py_compile @pyFiles
    if ($LASTEXITCODE -ne 0) {
        Write-PreflightFail "Python compile check failed with exit code $LASTEXITCODE"
    } else {
        Write-PreflightPass "Python dataset scripts compile"
    }
} catch {
    Write-PreflightFail "Python compile check failed: $($_.Exception.Message)"
}

if ($Bucket) {
    $bucketDescribe = gcloud storage buckets describe $Bucket 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-PreflightPass "GCS bucket is reachable: $Bucket"
    } else {
        Write-PreflightFail "GCS bucket is not reachable: $Bucket. $($bucketDescribe -join ' ')"
    }
}

if (-not $SkipClusterChecks) {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-PreflightPass "Docker engine is reachable"
    } else {
        Write-PreflightFail "Docker engine is not reachable: $($dockerInfo -join ' ')"
    }

    $nodes = Invoke-PreflightJsonCommand -Command "kubectl" -ArgumentList @("get", "nodes", "-o", "json") -Description "kubectl get nodes"
    if ($null -ne $nodes) {
        $notReadyNodes = @()
        foreach ($node in @($nodes.items)) {
            $ready = @($node.status.conditions | Where-Object { $_.type -eq "Ready" } | Select-Object -First 1)
            if ($ready.Count -eq 0 -or [string]$ready[0].status -ne "True") {
                $notReadyNodes += [string]$node.metadata.name
            }
        }
        if ($notReadyNodes.Count -gt 0) {
            Write-PreflightFail "NotReady Kubernetes nodes: $($notReadyNodes -join ', ')"
        } else {
            Write-PreflightPass "All Kubernetes nodes are Ready ($(@($nodes.items).Count) nodes)"
        }
    }

    foreach ($namespace in @("observability", "online-boutique-research")) {
        $namespaceCheck = kubectl get namespace $namespace 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-PreflightFail "Missing namespace: $namespace"
        } else {
            Write-PreflightPass "Namespace exists: $namespace"
            Test-PreflightPodsReady -Namespace $namespace
        }
    }

    Test-PreflightService -Namespace "observability" -ServiceName "loki-gateway"
    Test-PreflightService -Namespace "observability" -ServiceName "kube-prometheus-stack-prometheus"
    Test-PreflightService -Namespace "observability" -ServiceName "tempo"
    Test-PreflightService -Namespace "observability" -ServiceName "kube-prometheus-stack-alertmanager"
    Test-PreflightService -Namespace "online-boutique-research" -ServiceName "frontend"
}

Write-Host ""
Write-Host "Preflight summary:"
Write-Host "  warnings: $($warnings.Count)"
Write-Host "  failures: $($failures.Count)"

if ($warnings.Count -gt 0) {
    foreach ($warning in $warnings) {
        Write-Host "  WARN: $warning"
    }
}
if ($failures.Count -gt 0) {
    foreach ($failure in $failures) {
        Write-Host "  FAIL: $failure"
    }
    throw "Preflight failed. Fix failures before starting a multi-day dataset run."
}

Write-Host "Preflight passed. You can start the dataset run."
