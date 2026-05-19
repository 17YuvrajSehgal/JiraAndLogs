[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [switch]$AllowMissingRawExports,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path (Join-Path $PSScriptRoot "lib") "ResearchLab.psm1") -Force

function Add-ValidationMessage {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$List,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $List.Add($Message) | Out-Null
}

function Test-DuplicateIds {
    param(
        [object[]]$Records,
        [string]$IdProperty,
        [string]$Label,
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$Errors
    )

    $seen = @{}
    foreach ($record in @($Records)) {
        $id = Get-ResearchLabProperty -Object $record -Name $IdProperty
        if (-not $id) {
            Add-ValidationMessage -List $Errors -Message "$Label record is missing $IdProperty."
            continue
        }
        if ($seen.ContainsKey([string]$id)) {
            Add-ValidationMessage -List $Errors -Message "$Label has duplicate id: $id"
        } else {
            $seen[[string]$id] = $true
        }
    }
}

function Test-RunId {
    param(
        [object[]]$Records,
        [string]$Label,
        [string]$ExpectedRunId,
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$Errors
    )

    foreach ($record in @($Records)) {
        $recordRunId = Get-ResearchLabProperty -Object $record -Name "dataset_run_id"
        if ($recordRunId -ne $ExpectedRunId) {
            Add-ValidationMessage -List $Errors -Message "$Label record has wrong dataset_run_id. expected=$ExpectedRunId actual=$recordRunId"
        }
    }
}

function Get-ValidationInt {
    param(
        [object]$Object,
        [string]$Name
    )

    $value = Get-ResearchLabProperty -Object $Object -Name $Name
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        return 0
    }

    return [int]$value
}

function Get-LokiSectionEntryCount {
    param(
        [object]$LokiExport,
        [string]$SectionName
    )

    $section = Get-ResearchLabProperty -Object $LokiExport -Name $SectionName
    if ($null -eq $section) {
        return 0
    }

    $ok = Get-ResearchLabProperty -Object $section -Name "ok"
    if (-not $ok) {
        return 0
    }

    $response = Get-ResearchLabProperty -Object $section -Name "response"
    $data = Get-ResearchLabProperty -Object $response -Name "data"
    $result = Get-ResearchLabProperty -Object $data -Name "result"
    if ($null -eq $result) {
        return 0
    }

    $entries = 0
    foreach ($stream in @($result)) {
        $values = Get-ResearchLabProperty -Object $stream -Name "values"
        $entries += @($values).Count
    }

    return $entries
}

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path -LiteralPath $runRoot)) {
    throw "Dataset run folder does not exist: $runRoot"
}

$manifestPath = Join-Path $runRoot "manifest.json"
$episodesPath = Join-Path $runRoot "episodes.jsonl"
$windowsPath = Join-Path $runRoot "telemetry_windows.jsonl"
$alertsPath = Join-Path $runRoot "alerts.jsonl"
$issuesPath = Join-Path $runRoot "jira_shadow_issues.jsonl"

foreach ($path in @($manifestPath, $episodesPath, $windowsPath, $alertsPath, $issuesPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Add-ValidationMessage -List $errors -Message "Missing required file: $path"
    }
}

if ($errors.Count -eq 0) {
    $manifest = Read-ResearchLabJsonFile -Path $manifestPath
    $episodes = @(Read-ResearchLabJsonLines -Path $episodesPath)
    $windows = @(Read-ResearchLabJsonLines -Path $windowsPath)
    $alerts = @(Read-ResearchLabJsonLines -Path $alertsPath)
    $issues = @(Read-ResearchLabJsonLines -Path $issuesPath)

    if ($manifest.dataset_run_id -ne $DatasetRunId) {
        Add-ValidationMessage -List $errors -Message "Manifest dataset_run_id does not match folder name."
    }
    foreach ($required in @("dataset_name", "started_at", "environment", "git", "workload", "observability_stack")) {
        if ($null -eq (Get-ResearchLabProperty -Object $manifest -Name $required)) {
            Add-ValidationMessage -List $errors -Message "Manifest missing required property: $required"
        }
    }

    Test-DuplicateIds -Records $episodes -IdProperty "incident_episode_id" -Label "episodes" -Errors $errors
    Test-DuplicateIds -Records $windows -IdProperty "telemetry_window_id" -Label "telemetry_windows" -Errors $errors
    Test-DuplicateIds -Records $alerts -IdProperty "alert_event_id" -Label "alerts" -Errors $errors
    Test-DuplicateIds -Records $issues -IdProperty "jira_shadow_issue_id" -Label "jira_shadow_issues" -Errors $errors

    Test-RunId -Records $episodes -Label "episodes" -ExpectedRunId $DatasetRunId -Errors $errors
    Test-RunId -Records $windows -Label "telemetry_windows" -ExpectedRunId $DatasetRunId -Errors $errors
    Test-RunId -Records $alerts -Label "alerts" -ExpectedRunId $DatasetRunId -Errors $errors
    Test-RunId -Records $issues -Label "jira_shadow_issues" -ExpectedRunId $DatasetRunId -Errors $errors

    $windowsById = @{}
    foreach ($window in $windows) {
        $windowsById[[string]$window.telemetry_window_id] = $window

        try {
            $start = [DateTimeOffset]::Parse([string]$window.start_time)
            $end = [DateTimeOffset]::Parse([string]$window.end_time)
            if ($end -le $start) {
                Add-ValidationMessage -List $errors -Message "Telemetry window has non-positive duration: $($window.telemetry_window_id)"
            }
        } catch {
            Add-ValidationMessage -List $errors -Message "Telemetry window has invalid timestamp: $($window.telemetry_window_id)"
        }

        if (-not $AllowMissingRawExports) {
            foreach ($source in @("loki", "prometheus", "tempo")) {
                $rawPath = Join-ResearchLabPath @($runRoot, "raw", $source, "$($window.telemetry_window_id).json")
                if (-not (Test-Path -LiteralPath $rawPath)) {
                    Add-ValidationMessage -List $errors -Message "Missing raw $source export for telemetry window: $($window.telemetry_window_id)"
                }
            }
        }
    }

    foreach ($episode in $episodes) {
        $episodeId = [string]$episode.incident_episode_id
        $severity = [string]$episode.severity
        if ($severity -notin @("none", "minor", "major", "critical")) {
            Add-ValidationMessage -List $errors -Message "Episode has invalid severity '$severity': $episodeId"
        }
        if ([string]::IsNullOrWhiteSpace([string]$episode.scenario_id)) {
            Add-ValidationMessage -List $errors -Message "Episode is missing scenario_id: $episodeId"
        }
        if ([string]::IsNullOrWhiteSpace([string]$episode.incident_type)) {
            Add-ValidationMessage -List $errors -Message "Episode is missing incident_type: $episodeId"
        }
        if ([string]::IsNullOrWhiteSpace([string]$episode.root_cause_category)) {
            Add-ValidationMessage -List $errors -Message "Episode is missing root_cause_category: $episodeId"
        }

        $episodeWindows = @($windows | Where-Object { $_.incident_episode_id -eq $episodeId })
        if ($episodeWindows.Count -eq 0) {
            Add-ValidationMessage -List $errors -Message "Episode has no telemetry windows: $episodeId"
        }

        try {
            $start = [DateTimeOffset]::Parse([string]$episode.start_time)
            $end = [DateTimeOffset]::Parse([string]$episode.end_time)
            if ($end -le $start) {
                Add-ValidationMessage -List $errors -Message "Episode has non-positive duration: $episodeId"
            }
        } catch {
            Add-ValidationMessage -List $errors -Message "Episode has invalid timestamp: $episodeId"
        }
    }

    $episodesById = @{}
    foreach ($episode in $episodes) {
        $episodesById[[string]$episode.incident_episode_id] = $episode
    }

    $windowsWithExactLogs = 0
    $windowsWithLogContext = 0
    $windowsWithNamespaceLogContext = 0
    $windowsWithTraces = 0
    $windowsWithHistoricalAlerts = 0
    $runLevelLokiContextEntries = 0

    $runLevelLokiContextPath = Join-ResearchLabPath @($runRoot, "raw", "loki", "run-context.json")
    if (Test-Path -LiteralPath $runLevelLokiContextPath) {
        try {
            $runLevelLokiContext = Read-ResearchLabJsonFile -Path $runLevelLokiContextPath
            $runLevelLokiContextEntries = Get-LokiSectionEntryCount -LokiExport $runLevelLokiContext -SectionName "namespace_context"
        } catch {
            Add-ValidationMessage -List $warnings -Message "Could not parse run-level Loki context export: $runLevelLokiContextPath"
        }
    }

    foreach ($window in $windows) {
        $windowId = [string]$window.telemetry_window_id
        $windowSeverity = [string]$window.labels.severity
        if ($windowSeverity -notin @("none", "minor", "major", "critical")) {
            Add-ValidationMessage -List $errors -Message "Telemetry window has invalid severity '$windowSeverity': $windowId"
        }
        if ([string]::IsNullOrWhiteSpace([string]$window.labels.incident_type)) {
            Add-ValidationMessage -List $errors -Message "Telemetry window is missing incident_type label: $windowId"
        }
        if ([string]::IsNullOrWhiteSpace([string]$window.labels.root_cause_category)) {
            Add-ValidationMessage -List $errors -Message "Telemetry window is missing root_cause_category label: $windowId"
        }

        if (Get-ValidationInt -Object $window.features.logs -Name "entry_count") {
            $windowsWithExactLogs++
        }
        if (Get-ValidationInt -Object $window.features.logs -Name "context_entry_count") {
            $windowsWithLogContext++
        }
        if (Get-ValidationInt -Object $window.features.logs -Name "namespace_context_entry_count") {
            $windowsWithNamespaceLogContext++
        }
        if (Get-ValidationInt -Object $window.features.traces -Name "trace_count") {
            $windowsWithTraces++
        }
        if (Get-ValidationInt -Object $window.features.metrics -Name "historical_alert_event_count") {
            $windowsWithHistoricalAlerts++
        }
    }

    if (-not $AllowMissingRawExports) {
        if ($windowsWithNamespaceLogContext -eq 0 -and $runLevelLokiContextEntries -eq 0) {
            Add-ValidationMessage -List $warnings -Message "No telemetry windows and no run-level export have padded namespace-level Loki context. Logs may be too sparse for research use."
        }
        if ($windowsWithTraces -eq 0) {
            Add-ValidationMessage -List $warnings -Message "No telemetry windows have trace ids."
        }
    }

    foreach ($issue in $issues) {
        $episodeId = [string]$issue.incident_episode_id
        if (-not $episodesById.ContainsKey($episodeId)) {
            Add-ValidationMessage -List $errors -Message "Jira shadow issue links to missing episode: $($issue.jira_shadow_issue_id)"
        }

        $linkedWindows = @($issue.telemetry_links.telemetry_window_ids)
        if ($linkedWindows.Count -eq 0) {
            Add-ValidationMessage -List $errors -Message "Jira shadow issue has no linked telemetry windows: $($issue.jira_shadow_issue_id)"
        }
        foreach ($windowId in $linkedWindows) {
            if (-not $windowsById.ContainsKey([string]$windowId)) {
                Add-ValidationMessage -List $errors -Message "Jira shadow issue links to missing telemetry window: $windowId"
            }
        }
    }

    $negativeEpisodes = @($episodes | Where-Object { -not [bool]$_.jira_candidate })
    $positiveEpisodes = @($episodes | Where-Object { [bool]$_.jira_candidate })
    if ($negativeEpisodes.Count -eq 0) {
        Add-ValidationMessage -List $warnings -Message "No negative episodes found. Ranking datasets need baseline, noisy, or near-miss negatives."
    }
    if ($positiveEpisodes.Count -eq 0) {
        Add-ValidationMessage -List $warnings -Message "No positive Jira-candidate episodes found."
    }

    foreach ($episode in $positiveEpisodes) {
        $hasIssue = @($issues | Where-Object { $_.incident_episode_id -eq $episode.incident_episode_id }).Count -gt 0
        if (-not $hasIssue) {
            Add-ValidationMessage -List $warnings -Message "Positive episode has no shadow Jira issue yet: $($episode.incident_episode_id)"
        }
    }

    $reportObject = [ordered]@{
        dataset_run_id = $DatasetRunId
        validated_at = Get-ResearchLabUtcNow
        counts = [ordered]@{
            episodes = $episodes.Count
            telemetry_windows = $windows.Count
            alert_events = $alerts.Count
            jira_shadow_issues = $issues.Count
            positive_episodes = $positiveEpisodes.Count
            negative_episodes = $negativeEpisodes.Count
        }
        quality = [ordered]@{
            windows_with_exact_logs = $windowsWithExactLogs
            windows_with_service_log_context = $windowsWithLogContext
            windows_with_namespace_log_context = $windowsWithNamespaceLogContext
            run_level_loki_context_entries = $runLevelLokiContextEntries
            windows_with_traces = $windowsWithTraces
            windows_with_historical_alert_events = $windowsWithHistoricalAlerts
        }
        errors = @($errors)
        warnings = @($warnings)
    }

    Write-ResearchLabJsonFile -Path (Join-ResearchLabPath @($runRoot, "summaries", "validation-report.json")) -Value $reportObject

    $reportLines = @()
    $reportLines += "# Validation Report $DatasetRunId"
    $reportLines += ""
    $reportLines += "- Validated at: $($reportObject.validated_at)"
    $reportLines += "- Episodes: $($episodes.Count)"
    $reportLines += "- Telemetry windows: $($windows.Count)"
    $reportLines += "- Alert events: $($alerts.Count)"
    $reportLines += "- Jira shadow issues: $($issues.Count)"
    $reportLines += "- Windows with exact service logs: $windowsWithExactLogs"
    $reportLines += "- Windows with padded service log context: $windowsWithLogContext"
    $reportLines += "- Windows with padded namespace log context: $windowsWithNamespaceLogContext"
    $reportLines += "- Run-level Loki namespace context entries: $runLevelLokiContextEntries"
    $reportLines += "- Windows with traces: $windowsWithTraces"
    $reportLines += "- Windows with historical alert events: $windowsWithHistoricalAlerts"
    $reportLines += "- Errors: $($errors.Count)"
    $reportLines += "- Warnings: $($warnings.Count)"
    $reportLines += ""
    $reportLines += "## Errors"
    if ($errors.Count -eq 0) {
        $reportLines += "- None"
    } else {
        foreach ($message in $errors) {
            $reportLines += "- $message"
        }
    }
    $reportLines += ""
    $reportLines += "## Warnings"
    if ($warnings.Count -eq 0) {
        $reportLines += "- None"
    } else {
        foreach ($message in $warnings) {
            $reportLines += "- $message"
        }
    }
    Set-Content -LiteralPath (Join-ResearchLabPath @($runRoot, "summaries", "validation-report.md")) -Value $reportLines -Encoding UTF8
}

Write-Host "Validation complete:"
Write-Host "  errors: $($errors.Count)"
Write-Host "  warnings: $($warnings.Count)"

if ($errors.Count -gt 0) {
    foreach ($message in $errors) {
        Write-Host "ERROR: $message"
    }
    throw "Dataset run validation failed."
}

if ($Strict -and $warnings.Count -gt 0) {
    foreach ($message in $warnings) {
        Write-Host "WARNING: $message"
    }
    throw "Dataset run validation failed in -Strict mode because warnings were found."
}
