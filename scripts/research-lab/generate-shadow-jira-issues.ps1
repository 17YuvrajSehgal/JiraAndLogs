[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$IncidentEpisodeId,
    [string]$ProjectKey = "OBSRV",
    [string]$ProjectName = "Observability Research Lab",
    [string]$Reporter = "Research Lab Automation",
    [string]$DefaultAssignee = "Service Owner",
    [switch]$RealisticNoise,
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

function Get-InitialPriorityForSeverity {
    param(
        [string]$Severity,
        [int]$Bucket
    )

    $finalPriority = Get-PriorityForSeverity -Severity $Severity
    if ($Bucket -eq 1 -and $finalPriority -eq "Critical") {
        return "Major"
    }
    if ($Bucket -eq 2 -and $finalPriority -eq "Major") {
        return "Minor"
    }
    return $finalPriority
}

function Get-IssueSummary {
    param(
        [object]$Episode,
        [switch]$RealisticNoise
    )

    $serviceText = (@($Episode.affected_services) -join ", ")
    if (-not $serviceText) {
        $serviceText = "Online Boutique"
    }

    $type = $Episode.incident_type
    if (-not $type) {
        $type = "incident"
    }

    if ($RealisticNoise) {
        $primaryService = [string](@($Episode.affected_services | Select-Object -First 1))
        if (-not $primaryService) {
            $primaryService = "Online Boutique"
        }

        switch ([string]$Episode.incident_type) {
            "outage" { return "Customer checkout path seeing elevated failures" }
            "degradation" { return "Intermittent slowness reported around $primaryService" }
            "near_miss" { return "Noisy service health signal under review" }
            default { return "Service health investigation for $primaryService" }
        }
    }

    return "[$($Episode.severity.ToUpperInvariant())] $serviceText $type during $($Episode.scenario_id)"
}

function Get-RealisticComponents {
    param(
        [string[]]$Components,
        [int]$Bucket
    )

    $values = @($Components)
    if ($values.Count -eq 0) {
        $values = @("Online Boutique")
    }
    if ($Bucket -eq 0 -and $values.Count -gt 1) {
        return @($values | Select-Object -First ($values.Count - 1))
    }
    if ($Bucket -eq 2 -and -not ($values -contains "frontend")) {
        return @($values + "frontend")
    }
    if ($Bucket -eq 3 -and -not ($values -contains "checkoutservice")) {
        return @($values + "checkoutservice")
    }
    return $values
}

function Get-HumanTriageNote {
    param(
        [object]$Episode,
        [int]$Bucket
    )

    switch ($Bucket) {
        0 { return "Initial report is noisy. Checking whether this is customer traffic, a recent rollout, or a dependency issue." }
        1 { return "Support saw intermittent failures before the automated alert stabilized. Priority may need adjustment after owner review." }
        2 { return "Component mapping is not fully confirmed yet; starting with the most visible impacted service and adding owners as evidence improves." }
        default { return "Correlating logs, alerts, and traces. There may be more than one symptom in the same customer journey." }
    }
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

    $issueNumberValue = 0
    if ($issueKey -match "(\d+)$") {
        $issueNumberValue = [int]$Matches[1]
    }
    $realismBucket = $issueNumberValue % 4
    $createdAt = [DateTimeOffset]::Parse([string]$episode.start_time)
    if ($RealisticNoise) {
        $createdAt = $createdAt.AddMinutes(6 + ($realismBucket * 5))
    }
    $updatedAt = [DateTimeOffset]::Parse([string]$episode.end_time).AddMinutes(12)
    if ($updatedAt -lt $createdAt.AddMinutes(5)) {
        $updatedAt = $createdAt.AddMinutes(5)
    }
    $triageAt = $createdAt.AddMinutes(6)
    $investigationAt = $createdAt.AddMinutes(18)
    $resolvedAt = $updatedAt.AddMinutes(35)
    $finalPriority = Get-PriorityForSeverity -Severity $episode.severity
    $initialPriority = $finalPriority
    if ($RealisticNoise) {
        $initialPriority = Get-InitialPriorityForSeverity -Severity $episode.severity -Bucket $realismBucket
    }

    $components = @($episode.affected_services | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    if ($components.Count -eq 0) {
        $components = @("Online Boutique")
    }
    $jiraComponents = $components
    if ($RealisticNoise) {
        $jiraComponents = @(Get-RealisticComponents -Components $components -Bucket $realismBucket | Sort-Object -Unique)
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

    $logQuery = '{namespace="online-boutique-research", app=~"' + (($jiraComponents | ForEach-Object { [regex]::Escape($_) }) -join "|") + '"}'
    $metricQuery = 'kube_pod_info{namespace="online-boutique-research",pod=~"' + (($jiraComponents | ForEach-Object { [regex]::Escape($_) + "-.*" }) -join "|") + '"}'
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
Jira components at creation: $($jiraComponents -join ", ")
Incident window: $($episode.start_time) to $($episode.end_time)

Telemetry windows:
$($telemetryWindowIds -join "`n")

Alert fingerprints:
$($alertFingerprints -join "`n")

Trace ids:
$($traceIds -join "`n")
"@

    $humanTriageNote = $null
    if ($RealisticNoise) {
        $humanTriageNote = Get-HumanTriageNote -Episode $episode -Bucket $realismBucket
    }

    $commentsBody = @"
Generated during the research lab workflow. The issue is intentionally linked to raw telemetry exports so ranking experiments can be audited.

Triage note: $humanTriageNote

Log query: $logQuery
Metric query: $metricQuery
Trace ids: $traceQuery
"@
    if (-not $RealisticNoise) {
        $commentsBody = @"
Generated during the research lab workflow. The issue is intentionally linked to raw telemetry exports so ranking experiments can be audited.

Log query: $logQuery
Metric query: $metricQuery
Trace ids: $traceQuery
"@
    }

    $history = @()
    $history += New-JiraHistoryItem -Id "$issueKey-h1" -Author $Reporter -Created $createdAt.ToString("o") -Field "status" -From $null -To "Needs Triage"
    $history += New-JiraHistoryItem -Id "$issueKey-h2" -Author $Reporter -Created $triageAt.ToString("o") -Field "priority" -From $null -To $initialPriority
    $history += New-JiraHistoryItem -Id "$issueKey-h3" -Author $DefaultAssignee -Created $investigationAt.ToString("o") -Field "status" -From "Needs Triage" -To "In Progress"
    $historyIndex = 4
    if ($RealisticNoise -and $initialPriority -ne $finalPriority) {
        $history += New-JiraHistoryItem -Id "$issueKey-h$historyIndex" -Author $DefaultAssignee -Created $investigationAt.AddMinutes(9).ToString("o") -Field "priority" -From $initialPriority -To $finalPriority
        $historyIndex++
    }
    if ($RealisticNoise -and (($jiraComponents -join "|") -ne ($components -join "|"))) {
        $history += New-JiraHistoryItem -Id "$issueKey-h$historyIndex" -Author $DefaultAssignee -Created $investigationAt.AddMinutes(14).ToString("o") -Field "components" -From ($jiraComponents -join ", ") -To ($components -join ", ")
        $historyIndex++
    }
    $history += New-JiraHistoryItem -Id "$issueKey-h$historyIndex" -Author $DefaultAssignee -Created $resolvedAt.ToString("o") -Field "status" -From "In Progress" -To "Resolved"

    $activityEvents = @()
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a1" -Author $Reporter -Timestamp $createdAt.ToString("o") -Type "issue_created" -Description "Issue created from telemetry-linked incident episode."
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a2" -Author $Reporter -Timestamp $triageAt.ToString("o") -Type "field_changed" -Field "priority" -From $null -To $initialPriority -Description "Priority set during initial triage."
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a3" -Author $DefaultAssignee -Timestamp $investigationAt.ToString("o") -Type "comment" -Body $commentsBody -Description "Investigation comment added with telemetry links."
    $activityIndex = 4
    if ($RealisticNoise -and $initialPriority -ne $finalPriority) {
        $activityEvents += New-JiraActivityEvent -Id "$issueKey-a$activityIndex" -Author $DefaultAssignee -Timestamp $investigationAt.AddMinutes(9).ToString("o") -Type "field_changed" -Field "priority" -From $initialPriority -To $finalPriority -Description "Priority corrected after impact review."
        $activityIndex++
    }
    if ($RealisticNoise -and (($jiraComponents -join "|") -ne ($components -join "|"))) {
        $activityEvents += New-JiraActivityEvent -Id "$issueKey-a$activityIndex" -Author $DefaultAssignee -Timestamp $investigationAt.AddMinutes(14).ToString("o") -Type "field_changed" -Field "components" -From ($jiraComponents -join ", ") -To ($components -join ", ") -Description "Components corrected after service-owner review."
        $activityIndex++
    }
    $activityEvents += New-JiraActivityEvent -Id "$issueKey-a$activityIndex" -Author $DefaultAssignee -Timestamp $resolvedAt.ToString("o") -Type "field_changed" -Field "status" -From "In Progress" -To "Resolved" -Description "Synthetic incident resolved after recovery window."

    $issue = [ordered]@{
        jira_shadow_issue_id = $shadowIssueId
        jira_issue_key = $issueKey
        dataset_run_id = $DatasetRunId
        incident_episode_id = $episodeId
        metadata = [ordered]@{
            summary = Get-IssueSummary -Episode $episode -RealisticNoise:$RealisticNoise
            project_id = $null
            project_key = $ProjectKey
            project_name = $ProjectName
            issue_type = "Incident"
            status = "Resolved"
            priority = $finalPriority
            initial_priority = $initialPriority
            affects_versions = @("research-lab-local")
            components = $jiraComponents
            corrected_components = $components
            realism_profile = if ($RealisticNoise) { "v2.1-noisy-human-triage" } else { "deterministic-v2" }
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
