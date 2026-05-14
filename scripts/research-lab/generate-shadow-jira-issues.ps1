[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$IncidentEpisodeId,
    [string]$ProjectKey = "OBSRV",
    [string]$ProjectName = "Observability Research Lab",
    [string]$Reporter = "Research Lab Automation",
    [string]$DefaultAssignee = "Service Owner",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\ResearchLab.psm1") -Force

function Get-PriorityForSeverity {
    param([string]$Severity)

    switch ($Severity) {
        "critical" { return "Critical" }
        "major" { return "Major" }
        "minor" { return "Minor" }
        default { return "Low" }
    }
}

function Get-IssueSummary {
    param([object]$Episode)

    $serviceText = (@($Episode.affected_services) -join ", ")
    if (-not $serviceText) {
        $serviceText = "Online Boutique"
    }

    $type = $Episode.incident_type
    if (-not $type) {
        $type = "incident"
    }

    return "[$($Episode.severity.ToUpperInvariant())] $serviceText $type during $($Episode.scenario_id)"
}

function New-JiraHistoryItem {
    param(
        [string]$Id,
        [string]$Author,
        [string]$Created,
        [string]$Field,
        [string]$From,
        [string]$To
    )

    return [ordered]@{
        id = $Id
        author = $Author
        created = $Created
        items = @(
            [ordered]@{
                field = $Field
                fieldtype = "jira"
                from = $From
                to = $To
                from_id = $null
                to_id = $null
            }
        )
    }
}

function New-JiraActivityEvent {
    param(
        [string]$Id,
        [string]$Author,
        [string]$Timestamp,
        [string]$Type,
        [string]$Description,
        [string]$Field = $null,
        [string]$From = $null,
        [string]$To = $null,
        [string]$Body = $null
    )

    return [ordered]@{
        type = $Type
        id = $Id
        author = $Author
        created = $Timestamp
        timestamp = $Timestamp
        field = $Field
        from = $From
        to = $To
        body = $Body
        description = $Description
    }
}

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if (-not (Test-Path -LiteralPath (Join-Path $runRoot "manifest.json"))) {
    throw "Dataset run does not exist: $DatasetRunId"
}

$episodesPath = Join-Path $runRoot "episodes.jsonl"
$windowsPath = Join-Path $runRoot "telemetry_windows.jsonl"
$alertsPath = Join-Path $runRoot "alerts.jsonl"
$issuesPath = Join-Path $runRoot "jira_shadow_issues.jsonl"

$episodes = @(Read-ResearchLabJsonLines -Path $episodesPath)
if ($IncidentEpisodeId) {
    $episodes = @($episodes | Where-Object { $_.incident_episode_id -eq $IncidentEpisodeId })
}

$windows = @(Read-ResearchLabJsonLines -Path $windowsPath)
$alerts = @(Read-ResearchLabJsonLines -Path $alertsPath)
$existingIssues = @(Read-ResearchLabJsonLines -Path $issuesPath)

$issuesByEpisode = @{}
foreach ($issue in $existingIssues) {
    if ($issue.incident_episode_id) {
        $issuesByEpisode[[string]$issue.incident_episode_id] = $issue
    }
}

$nextNumber = 1000 + $existingIssues.Count + 1
$newIssues = @()

foreach ($episode in $episodes) {
    if (-not [bool]$episode.jira_candidate) {
        continue
    }

    $episodeId = [string]$episode.incident_episode_id
    if ($issuesByEpisode.ContainsKey($episodeId) -and -not $Force) {
        Write-Host "Skipping existing shadow Jira issue for episode $episodeId"
        continue
    }

    $episodeWindows = @($windows | Where-Object { $_.incident_episode_id -eq $episodeId })
    $episodeAlerts = @($alerts | Where-Object { $_.incident_episode_id -eq $episodeId })

    $telemetryWindowIds = @($episodeWindows | ForEach-Object { $_.telemetry_window_id } | Sort-Object -Unique)
    $traceIds = @($episodeWindows | ForEach-Object { @($_.trace_ids) } | Sort-Object -Unique)
    $alertFingerprints = @($episodeAlerts | ForEach-Object { $_.alert_fingerprint } | Sort-Object -Unique)

    $existingIssue = $null
    if ($issuesByEpisode.ContainsKey($episodeId)) {
        $existingIssue = $issuesByEpisode[$episodeId]
    }

    if ($null -ne $existingIssue -and $existingIssue.jira_issue_key) {
        $issueKey = [string]$existingIssue.jira_issue_key
    } else {
        $issueKey = "$ProjectKey-$nextNumber"
        $nextNumber++
    }

    if ($null -ne $existingIssue -and $existingIssue.jira_shadow_issue_id) {
        $shadowIssueId = [string]$existingIssue.jira_shadow_issue_id
    } else {
        $shadowIssueId = "shadow-$episodeId"
    }

    $createdAt = [DateTimeOffset]::Parse([string]$episode.start_time)
    $updatedAt = [DateTimeOffset]::Parse([string]$episode.end_time).AddMinutes(12)
    $triageAt = $createdAt.AddMinutes(6)
    $investigationAt = $createdAt.AddMinutes(18)
    $resolvedAt = $updatedAt.AddMinutes(35)

    $components = @($episode.affected_services | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    if ($components.Count -eq 0) {
        $components = @("Online Boutique")
    }

    $labels = @(
        "synthetic-incident",
        "telemetry-linked",
        "dataset-$DatasetRunId",
        "scenario-$($episode.scenario_id)",
        "severity-$($episode.severity)"
    )
    if ($episode.root_cause_category) {
        $labels += "root-$($episode.root_cause_category)"
    }

    $logQuery = '{namespace="online-boutique-research", app=~"' + (($components | ForEach-Object { [regex]::Escape($_) }) -join "|") + '"}'
    $metricQuery = 'kube_pod_info{namespace="online-boutique-research",pod=~"' + (($components | ForEach-Object { [regex]::Escape($_) + "-.*" }) -join "|") + '"}'
    $traceQuery = $null
    if ($traceIds.Count -gt 0) {
        $traceQuery = ($traceIds -join ",")
    }

    $description = @"
Synthetic lab issue generated from Online Boutique telemetry.

Dataset run: $DatasetRunId
Episode: $episodeId
Scenario: $($episode.scenario_id)
Fault id: $($episode.fault_id)
Incident type: $($episode.incident_type)
Root cause category: $($episode.root_cause_category)
Affected services: $($components -join ", ")
Incident window: $($episode.start_time) to $($episode.end_time)

Telemetry windows:
$($telemetryWindowIds -join "`n")

Alert fingerprints:
$($alertFingerprints -join "`n")

Trace ids:
$($traceIds -join "`n")
"@

    $commentsBody = @"
Generated during the research lab workflow. The issue is intentionally linked to raw telemetry exports so ranking experiments can be audited.

Log query: $logQuery
Metric query: $metricQuery
Trace ids: $traceQuery
"@

    $history = @()
    $history += New-JiraHistoryItem -Id "$issueKey-h1" -Author $Reporter -Created $createdAt.ToString("o") -Field "status" -From $null -To "Needs Triage"
    $history += New-JiraHistoryItem -Id "$issueKey-h2" -Author $Reporter -Created $triageAt.ToString("o") -Field "priority" -From $null -To (Get-PriorityForSeverity -Severity $episode.severity)
    $history += New-JiraHistoryItem -Id "$issueKey-h3" -Author $DefaultAssignee -Created $investigationAt.ToString("o") -Field "status" -From "Needs Triage" -To "In Progress"
    $history += New-JiraHistoryItem -Id "$issueKey-h4" -Author $DefaultAssignee -Created $resolvedAt.ToString("o") -Field "status" -From "In Progress" -To "Resolved"

    $activityEvents = @()
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a1" -Author $Reporter -Timestamp $createdAt.ToString("o") -Type "issue_created" -Description "Issue created from telemetry-linked incident episode."
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a2" -Author $Reporter -Timestamp $triageAt.ToString("o") -Type "field_changed" -Field "priority" -From $null -To (Get-PriorityForSeverity -Severity $episode.severity) -Description "Priority set during automated triage."
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a3" -Author $DefaultAssignee -Timestamp $investigationAt.ToString("o") -Type "comment" -Body $commentsBody -Description "Investigation comment added with telemetry links."
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a4" -Author $DefaultAssignee -Timestamp $resolvedAt.ToString("o") -Type "field_changed" -Field "status" -From "In Progress" -To "Resolved" -Description "Synthetic incident resolved after recovery window."

    $issue = [ordered]@{
        jira_shadow_issue_id = $shadowIssueId
        jira_issue_key = $issueKey
        dataset_run_id = $DatasetRunId
        incident_episode_id = $episodeId
        metadata = [ordered]@{
            summary = Get-IssueSummary -Episode $episode
            project_id = $null
            project_key = $ProjectKey
            project_name = $ProjectName
            issue_type = "Incident"
            status = "Resolved"
            priority = Get-PriorityForSeverity -Severity $episode.severity
            affects_versions = @("research-lab-local")
            components = $components
            labels = @($labels | Sort-Object -Unique)
            resolution = "Recovered"
            fix_versions = @()
            description = $description
            attachments = @()
            assignee = $DefaultAssignee
            reporter = $Reporter
            watcher_count = 2
            created_at = $createdAt.ToString("o")
            updated_at = $updatedAt.ToString("o")
            resolved_at = $resolvedAt.ToString("o")
            related_issues = @()
            comments_id = @("$issueKey-comment-1")
            comments_body = $commentsBody
            development = [ordered]@{
                commit_count = 0
                pr_count = 0
                branch_count = 0
                repository_count = 1
                last_updated = $updatedAt.ToString("o")
            }
        }
        telemetry_links = [ordered]@{
            alert_fingerprints = $alertFingerprints
            telemetry_window_ids = $telemetryWindowIds
            trace_ids = $traceIds
            log_query = $logQuery
            metric_query = $metricQuery
            trace_query = $traceQuery
        }
        history = $history
        activity = @(
            [ordered]@{
                date = $createdAt.ToString("yyyy-MM-dd")
                events = $activityEvents
            }
        )
        worklog = @()
        submissions = @()
    }

    if ($issuesByEpisode.ContainsKey($episodeId) -and $Force) {
        $existingIssues = @($existingIssues | Where-Object { $_.incident_episode_id -ne $episodeId })
    }
    $newIssues += $issue

    $episode.jira_shadow_issue_id = $shadowIssueId
    $episode.jira_issue_key = $issueKey
    $episode.telemetry_window_ids = $telemetryWindowIds
    $episode.trace_ids = $traceIds
    $episode.alert_fingerprints = $alertFingerprints
}

if ($newIssues.Count -gt 0) {
    Write-ResearchLabJsonLines -Path $issuesPath -Records @($existingIssues + $newIssues)
    Write-ResearchLabJsonLines -Path $episodesPath -Records @(Read-ResearchLabJsonLines -Path $episodesPath | ForEach-Object {
        $current = $_
        foreach ($updated in $episodes) {
            if ($current.incident_episode_id -eq $updated.incident_episode_id) {
                $current = $updated
                break
            }
        }
        $current
    })
}

Write-Host "Shadow Jira generation complete:"
Write-Host "  generated: $($newIssues.Count)"
