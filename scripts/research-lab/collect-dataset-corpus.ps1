[CmdletBinding()]
param(
    [string]$CorpusFile = "deploy\research-lab\corpora\dataset-v3-production-corpus.json",
    [string]$DatasetRunPrefix,
    [int]$StartAt = 1,
    [int]$MaxRuns = 0,
    [switch]$Quick,
    [switch]$RecordOnly,
    [switch]$NoTelemetryExport,
    [switch]$SkipJiraGeneration,
    [switch]$ForceNewRun,
    [switch]$SkipDerivedBuild,
    [switch]$SkipAggregateBuild,
    [switch]$PlanOnly,
    [string]$PythonExe = "python"
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

function Get-CorpusValue {
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

function New-SafeRunIdPart {
    param([Parameter(Mandatory = $true)][string]$Value)

    $safe = ($Value.ToLowerInvariant() -replace "[^a-z0-9\-]+", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($safe)) {
        throw "Unable to create safe run id segment from value: $Value"
    }

    return $safe
}

function Get-ExistingDerivedRunIds {
    param([Parameter(Mandatory = $true)][string]$Prefix)

    $repoRoot = Get-ResearchLabRepoRoot
    $derivedRoot = Join-ResearchLabPath @($repoRoot, "data", "derived")
    if (-not (Test-Path -LiteralPath $derivedRoot)) {
        return @()
    }

    $runIds = @()
    foreach ($dir in @(Get-ChildItem -LiteralPath $derivedRoot -Directory -Filter "$Prefix-*")) {
        $rankingExamples = Join-Path $dir.FullName "ranking_examples.jsonl"
        if (Test-Path -LiteralPath $rankingExamples) {
            $runIds += $dir.Name
        }
    }

    return @($runIds | Sort-Object -Unique)
}

function Test-DerivedRunExists {
    param([Parameter(Mandatory = $true)][string]$DatasetRunId)

    $repoRoot = Get-ResearchLabRepoRoot
    $rankingExamples = Join-ResearchLabPath @($repoRoot, "data", "derived", $DatasetRunId, "ranking_examples.jsonl")
    return (Test-Path -LiteralPath $rankingExamples)
}

function Get-CompletedCorpusRunIds {
    param(
        [Parameter(Mandatory = $true)][object[]]$PlannedRuns,
        [switch]$RequireDerived
    )

    $completed = @()
    foreach ($run in @($PlannedRuns)) {
        $runId = [string]$run.dataset_run_id
        $runRoot = Get-ResearchLabRunRoot -DatasetRunId $runId
        $validationReport = Join-ResearchLabPath @($runRoot, "summaries", "validation-report.json")
        if (-not (Test-Path -LiteralPath $validationReport)) {
            continue
        }
        if ($RequireDerived -and -not (Test-DerivedRunExists -DatasetRunId $runId)) {
            continue
        }
        $completed += $runId
    }

    return @($completed | Sort-Object -Unique)
}

function Write-CorpusRunManifest {
    param(
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][object]$Corpus,
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][object[]]$PlannedRuns,
        [Parameter(Mandatory = $true)][object[]]$SelectedRuns,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$CompletedRunIds,
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$StartedAt
    )

    $manifest = [ordered]@{
        schema_version = 1
        corpus_id = [string](Get-CorpusValue -Object $Corpus -Name "corpus_id" -DefaultValue "dataset-corpus")
        dataset_run_prefix = $Prefix
        status = $Status
        started_at = $StartedAt
        updated_at = Get-ResearchLabUtcNow
        corpus_file = $resolvedCorpusFile
        planned_run_count = $PlannedRuns.Count
        selected_run_count = $SelectedRuns.Count
        completed_run_count = $CompletedRunIds.Count
        completed_run_ids = @($CompletedRunIds | Sort-Object -Unique)
        selected_runs = @($SelectedRuns)
        all_planned_runs = @($PlannedRuns)
    }

    Write-ResearchLabJsonFile -Path $OutputPath -Value $manifest
}

if ($StartAt -lt 1) {
    throw "StartAt is 1-based and must be at least 1."
}
if ($MaxRuns -lt 0) {
    throw "MaxRuns must be 0 for all remaining runs, or a positive integer."
}

$repoRoot = Get-ResearchLabRepoRoot
$powerShell = Get-ResearchLabPowerShellCommand
$resolvedCorpusFile = Resolve-ResearchLabInputPath -Path $CorpusFile
if (-not (Test-Path -LiteralPath $resolvedCorpusFile)) {
    throw "Corpus file not found: $resolvedCorpusFile"
}

$corpus = Read-ResearchLabJsonFile -Path $resolvedCorpusFile
$corpusId = [string](Get-CorpusValue -Object $corpus -Name "corpus_id" -DefaultValue "dataset-corpus")
if ([string]::IsNullOrWhiteSpace($DatasetRunPrefix)) {
    $defaultPrefix = [string](Get-CorpusValue -Object $corpus -Name "default_dataset_run_prefix" -DefaultValue $corpusId)
    $DatasetRunPrefix = "{0}-{1}" -f (New-SafeRunIdPart -Value $defaultPrefix), ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"))
} else {
    $DatasetRunPrefix = New-SafeRunIdPart -Value $DatasetRunPrefix
}

$plannedRuns = @()
$globalIndex = 0
foreach ($plan in @($corpus.plans)) {
    $planAlias = New-SafeRunIdPart -Value ([string](Get-CorpusValue -Object $plan -Name "plan_alias"))
    $planFile = [string](Get-CorpusValue -Object $plan -Name "plan_file")
    $repeat = [int](Get-CorpusValue -Object $plan -Name "repeat" -DefaultValue 1)
    if ($repeat -lt 1) {
        throw "Plan repeat must be at least 1 for alias $planAlias."
    }
    if ([string]::IsNullOrWhiteSpace($planFile)) {
        throw "Corpus plan $planAlias is missing plan_file."
    }

    $resolvedPlanFile = Resolve-ResearchLabInputPath -Path $planFile
    if (-not (Test-Path -LiteralPath $resolvedPlanFile)) {
        throw "Plan file not found for corpus alias $planAlias`: $resolvedPlanFile"
    }

    for ($i = 1; $i -le $repeat; $i++) {
        $globalIndex++
        $plannedRuns += [ordered]@{
            index = $globalIndex
            dataset_run_id = ("{0}-{1}-r{2:d2}" -f $DatasetRunPrefix, $planAlias, $i)
            plan_alias = $planAlias
            plan_repeat_index = $i
            plan_file = $planFile
            purpose = [string](Get-CorpusValue -Object $plan -Name "purpose" -DefaultValue "")
        }
    }
}

if ($plannedRuns.Count -eq 0) {
    throw "Corpus has no planned runs: $resolvedCorpusFile"
}

$selectedRuns = @($plannedRuns | Where-Object { [int]$_.index -ge $StartAt })
if ($MaxRuns -gt 0) {
    $selectedRuns = @($selectedRuns | Select-Object -First $MaxRuns)
}
if ($selectedRuns.Count -eq 0) {
    throw "No corpus runs selected. Check StartAt and MaxRuns."
}

Write-Host "Dataset corpus plan:"
Write-Host "  corpus_id: $corpusId"
Write-Host "  dataset_run_prefix: $DatasetRunPrefix"
Write-Host "  planned_runs: $($plannedRuns.Count)"
Write-Host "  selected_runs: $($selectedRuns.Count)"
Write-Host "  start_at: $StartAt"
Write-Host "  max_runs: $MaxRuns"
foreach ($run in $selectedRuns) {
    Write-Host ("  [{0}] {1} -> {2}" -f $run.index, $run.dataset_run_id, $run.plan_file)
}

if ($PlanOnly) {
    Write-Host "PlanOnly requested; no dataset runs were started."
    return
}

$startedAt = Get-ResearchLabUtcNow
$corpusOutputRoot = Join-ResearchLabPath @($repoRoot, "data", "derived", "corpora", $DatasetRunPrefix)
$manifestPath = Join-Path $corpusOutputRoot "corpus-run-manifest.json"
$completedRunIds = @(Get-CompletedCorpusRunIds -PlannedRuns $plannedRuns -RequireDerived:((-not $SkipDerivedBuild)))

Write-CorpusRunManifest `
    -OutputPath $manifestPath `
    -Corpus $corpus `
    -Prefix $DatasetRunPrefix `
    -PlannedRuns $plannedRuns `
    -SelectedRuns $selectedRuns `
    -CompletedRunIds $completedRunIds `
    -Status "running" `
    -StartedAt $startedAt

foreach ($run in $selectedRuns) {
    $runId = [string]$run.dataset_run_id
    $runRoot = Get-ResearchLabRunRoot -DatasetRunId $runId
    $runManifest = Join-Path $runRoot "manifest.json"

    if ((Test-Path -LiteralPath $runManifest) -and -not $ForceNewRun) {
        Write-Host "Skipping existing corpus run:"
        Write-Host "  dataset_run_id: $runId"
        Write-Host "  reason: manifest already exists; use -ForceNewRun to rebuild it"
        $validationReport = Join-ResearchLabPath @($runRoot, "summaries", "validation-report.json")
        if (-not (Test-Path -LiteralPath $validationReport)) {
            throw "Existing corpus run has a manifest but no validation report: $runId. Remove the partial run or rerun this range with -ForceNewRun."
        }
        if ((-not $SkipDerivedBuild) -and (-not (Test-DerivedRunExists -DatasetRunId $runId))) {
            Write-Host "  derived_status: missing; rebuilding derived ranking data"
            & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build-ranking-dataset.ps1") `
                -DatasetRunId $runId `
                -Force
            if ($LASTEXITCODE -ne 0) {
                throw "Derived ranking dataset build failed for existing corpus run $runId."
            }
        }
        $completedRunIds += $runId
        continue
    }

    Write-Host "Starting corpus run $($run.index) of $($plannedRuns.Count):"
    Write-Host "  dataset_run_id: $runId"
    Write-Host "  plan_file: $($run.plan_file)"

    $collectArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "collect-dataset-plan.ps1"),
        "-DatasetRunId", $runId,
        "-PlanFile", ([string]$run.plan_file)
    )
    if ($Quick) {
        $collectArgs += "-Quick"
    }
    if ($RecordOnly) {
        $collectArgs += "-RecordOnly"
    }
    if ($NoTelemetryExport) {
        $collectArgs += "-NoTelemetryExport"
    }
    if ($SkipJiraGeneration) {
        $collectArgs += "-SkipJiraGeneration"
    }
    if ($ForceNewRun) {
        $collectArgs += "-ForceNewRun"
    }
    if (-not $SkipDerivedBuild) {
        $collectArgs += "-BuildDerived"
    }

    & $powerShell @collectArgs
    if ($LASTEXITCODE -ne 0) {
        Write-CorpusRunManifest `
            -OutputPath $manifestPath `
            -Corpus $corpus `
            -Prefix $DatasetRunPrefix `
            -PlannedRuns $plannedRuns `
            -SelectedRuns $selectedRuns `
            -CompletedRunIds $completedRunIds `
            -Status "failed" `
            -StartedAt $startedAt
        throw "Corpus run failed: $runId"
    }

    $completedRunIds = @($completedRunIds + $runId | Sort-Object -Unique)
    Write-CorpusRunManifest `
        -OutputPath $manifestPath `
        -Corpus $corpus `
        -Prefix $DatasetRunPrefix `
        -PlannedRuns $plannedRuns `
        -SelectedRuns $selectedRuns `
        -CompletedRunIds $completedRunIds `
        -Status "running" `
        -StartedAt $startedAt
}

$derivedRunIds = @(Get-ExistingDerivedRunIds -Prefix $DatasetRunPrefix)
if ($derivedRunIds.Count -eq 0) {
    $derivedRunIds = @($completedRunIds | Sort-Object -Unique)
}

if (-not $SkipAggregateBuild) {
    if ($SkipDerivedBuild) {
        Write-Warning "Skipping aggregate build because -SkipDerivedBuild was set."
    } elseif ($derivedRunIds.Count -eq 0) {
        Write-Warning "Skipping aggregate build because no derived per-run datasets were found."
    } else {
        $aggregateSuffix = [string](Get-CorpusValue -Object $corpus -Name "aggregate_id_suffix" -DefaultValue "aggregate")
        $holdoutSuffix = [string](Get-CorpusValue -Object $corpus -Name "holdout_id_suffix" -DefaultValue "holdout")
        $aggregateId = "$DatasetRunPrefix-$aggregateSuffix"
        $holdoutId = "$DatasetRunPrefix-$holdoutSuffix"

        Write-Host "Building corpus cross-run aggregate:"
        Write-Host "  aggregate_id: $aggregateId"
        Write-Host "  derived_run_count: $($derivedRunIds.Count)"
        $datasetRunIdArgument = ($derivedRunIds -join ",")
        & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build-cross-run-evaluation.ps1") `
            -AggregateId $aggregateId `
            -DatasetRunId $datasetRunIdArgument `
            -PythonExe $PythonExe `
            -Force
        if ($LASTEXITCODE -ne 0) {
            throw "Corpus cross-run aggregate build failed."
        }

        if ($derivedRunIds.Count -ge 2) {
            Write-Host "Building corpus run-aware holdout evaluation:"
            Write-Host "  evaluation_id: $holdoutId"
            & $powerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build-run-aware-holdout-evaluation.ps1") `
                -EvaluationId $holdoutId `
                -DatasetRunId $datasetRunIdArgument `
                -PythonExe $PythonExe `
                -Force
            if ($LASTEXITCODE -ne 0) {
                throw "Corpus run-aware holdout build failed."
            }
        } else {
            Write-Warning "Skipping holdout build because at least two derived runs are required."
        }
    }
}

$completedRunIds = @(Get-CompletedCorpusRunIds -PlannedRuns $plannedRuns -RequireDerived:((-not $SkipDerivedBuild)))
foreach ($runId in @($derivedRunIds)) {
    if ($completedRunIds -notcontains $runId) {
        $completedRunIds += $runId
    }
}
$completedRunIds = @($completedRunIds | Sort-Object -Unique)
$finalStatus = "partial_complete"
if ($completedRunIds.Count -ge $plannedRuns.Count) {
    $finalStatus = "complete"
}

Write-CorpusRunManifest `
    -OutputPath $manifestPath `
    -Corpus $corpus `
    -Prefix $DatasetRunPrefix `
    -PlannedRuns $plannedRuns `
    -SelectedRuns $selectedRuns `
    -CompletedRunIds $completedRunIds `
    -Status $finalStatus `
    -StartedAt $startedAt

Write-Host "Dataset corpus workflow complete:"
Write-Host "  corpus_id: $corpusId"
Write-Host "  dataset_run_prefix: $DatasetRunPrefix"
Write-Host "  completed_selected_runs: $($completedRunIds.Count)"
Write-Host "  derived_runs_available_for_prefix: $($derivedRunIds.Count)"
Write-Host "  manifest: $manifestPath"
