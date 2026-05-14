[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$TelemetryWindowId,
    [string]$IncidentEpisodeId,
    [string]$WorkloadNamespace = "online-boutique-research",
    [string]$ObservabilityNamespace = "observability",
    [int]$StepSeconds = 15,
    [int]$LokiLimit = 5000,
    [int]$LokiPaddingSeconds = 300,
    [int]$LokiContextLimit = 5000,
    [int]$TempoLimit = 100,
    [switch]$RunLevelLokiOnly,
    [switch]$NoPortForward,
    [string]$LokiBaseUrl = "http://127.0.0.1:13100",
    [string]$PrometheusBaseUrl = "http://127.0.0.1:19090",
    [string]$TempoBaseUrl = "http://127.0.0.1:13200",
    [string]$AlertmanagerBaseUrl = "http://127.0.0.1:19093"
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\ResearchLab.psm1") -Force

function Start-LocalPortForward {
    param(
        [Parameter(Mandatory = $true)][string]$TargetNamespace,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][int]$LocalPort,
        [Parameter(Mandatory = $true)][int]$RemotePort
    )

    $portSpec = "{0}:{1}" -f $LocalPort, $RemotePort
    $process = Start-Process `
        -FilePath "kubectl" `
        -ArgumentList @("-n", $TargetNamespace, "port-forward", $ServiceName, $portSpec) `
        -PassThru `
        -WindowStyle Hidden

    Start-Sleep -Seconds 4
    if ($process.HasExited) {
        throw "Port-forward exited early for $ServiceName $portSpec."
    }

    return $process
}

function Stop-LocalPortForward {
    param([object[]]$Processes)

    foreach ($process in @($Processes)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
}

function Invoke-JsonEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 45
    )

    try {
        return [ordered]@{
            ok = $true
            uri = $Uri
            fetched_at = Get-ResearchLabUtcNow
            response = Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds
        }
    } catch {
        return [ordered]@{
            ok = $false
            uri = $Uri
            fetched_at = Get-ResearchLabUtcNow
            error = $_.Exception.Message
        }
    }
}

function Get-StableHash {
    param([Parameter(Mandatory = $true)][string]$Text)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $sha.ComputeHash($bytes)
        return (($hash | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $sha.Dispose()
    }
}

function ConvertTo-SafeFileNamePart {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9_.-]', '-')
}

function Get-ExportProperty {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            return $Object[$Name]
        }
        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }

    return $property.Value
}

function Get-LokiEntryCount {
    param([object]$LokiResponse)

    if (-not (Get-ExportProperty -Object $LokiResponse -Name "ok")) {
        return 0
    }

    $response = Get-ExportProperty -Object $LokiResponse -Name "response"
    $data = Get-ExportProperty -Object $response -Name "data"
    $result = Get-ExportProperty -Object $data -Name "result"
    if ($null -eq $result) {
        return 0
    }

    $count = 0
    foreach ($stream in @($result)) {
        $values = Get-ExportProperty -Object $stream -Name "values"
        $count += @($values).Count
    }
    return $count
}

function Get-LokiStreamCount {
    param([object]$LokiResponse)

    if (-not (Get-ExportProperty -Object $LokiResponse -Name "ok")) {
        return 0
    }
    $response = Get-ExportProperty -Object $LokiResponse -Name "response"
    $data = Get-ExportProperty -Object $response -Name "data"
    $result = Get-ExportProperty -Object $data -Name "result"
    if ($null -eq $result) {
        return 0
    }

    return @($result).Count
}

function Get-TempoTraceIds {
    param([object]$TempoResponse)

    $ids = @()
    $ok = Get-ExportProperty -Object $TempoResponse -Name "ok"
    $response = Get-ExportProperty -Object $TempoResponse -Name "response"
    $traces = Get-ExportProperty -Object $response -Name "traces"
    if ($ok -and $null -ne $traces) {
        foreach ($trace in @($traces)) {
            if ($trace.traceID) {
                $ids += [string]$trace.traceID
            }
        }
    }
    return @($ids | Sort-Object -Unique)
}

function New-AlertEvents {
    param(
        [Parameter(Mandatory = $true)][object]$AlertmanagerResponse,
        [Parameter(Mandatory = $true)][string]$DatasetRunId,
        [Parameter(Mandatory = $true)][string]$EpisodeId,
        [Parameter(Mandatory = $true)][string[]]$WindowIds
    )

    $events = @()
    if (-not $AlertmanagerResponse.ok -or $null -eq $AlertmanagerResponse.response) {
        return @()
    }

    foreach ($alert in @($AlertmanagerResponse.response)) {
        $labels = $alert.labels
        $annotations = $alert.annotations
        $alertName = $labels.alertname
        if (-not $alertName) {
            $alertName = "unknown-alert"
        }

        $fingerprint = $alert.fingerprint
        if (-not $fingerprint) {
            $fingerprint = (Get-StableHash -Text (($alert | ConvertTo-Json -Depth 16)))
        }

        $state = "firing"
        if ($alert.status.state -eq "resolved") {
            $state = "resolved"
        }

        $events += [ordered]@{
            alert_event_id = "$DatasetRunId-$fingerprint"
            dataset_run_id = $DatasetRunId
            incident_episode_id = $EpisodeId
            alert_fingerprint = [string]$fingerprint
            alert_name = [string]$alertName
            status = $state
            starts_at = [string]$alert.startsAt
            ends_at = if ($alert.endsAt) { [string]$alert.endsAt } else { $null }
            generator_url = if ($alert.generatorURL) { [string]$alert.generatorURL } else { $null }
            source = "alertmanager-current"
            query = $null
            sample_count = 1
            window_start = $null
            window_end = $null
            labels = $labels
            annotations = $annotations
            linked_trace_ids = @()
            linked_telemetry_window_ids = $WindowIds
            jira_candidate = $false
        }
    }

    return @($events)
}

function ConvertTo-AlertTimestamp {
    param([Parameter(Mandatory = $true)][double]$UnixSeconds)

    $wholeSeconds = [Math]::Floor($UnixSeconds)
    $milliseconds = [Math]::Round(($UnixSeconds - $wholeSeconds) * 1000)
    return ([DateTimeOffset]::FromUnixTimeSeconds([int64]$wholeSeconds).AddMilliseconds($milliseconds)).ToString("o")
}

function ConvertTo-PlainObjectMap {
    param([object]$Object)

    $map = [ordered]@{}
    if ($null -eq $Object) {
        return $map
    }

    foreach ($property in $Object.PSObject.Properties) {
        $map[$property.Name] = $property.Value
    }
    return $map
}

function New-PrometheusAlertEvents {
    param(
        [Parameter(Mandatory = $true)][object]$PrometheusAlertQuery,
        [Parameter(Mandatory = $true)][string]$DatasetRunId,
        [Parameter(Mandatory = $true)][string]$EpisodeId,
        [Parameter(Mandatory = $true)][string]$WindowId,
        [Parameter(Mandatory = $true)][string]$WindowStart,
        [Parameter(Mandatory = $true)][string]$WindowEnd,
        [Parameter(Mandatory = $true)][bool]$WindowJiraCandidate
    )

    $events = @()
    if (-not (Get-ExportProperty -Object $PrometheusAlertQuery -Name "ok")) {
        return @()
    }
    $response = Get-ExportProperty -Object $PrometheusAlertQuery -Name "response"
    $data = Get-ExportProperty -Object $response -Name "data"
    $result = Get-ExportProperty -Object $data -Name "result"
    if ($null -eq $result) {
        return @()
    }

    foreach ($series in @($result)) {
        $samples = @($series.values | Where-Object { $_ -and $_.Count -ge 2 -and [double]($_[1]) -gt 0 })
        if ($samples.Count -eq 0) {
            continue
        }

        $labels = ConvertTo-PlainObjectMap -Object $series.metric
        $alertName = $labels["alertname"]
        if (-not $alertName) {
            $alertName = "unknown-alert"
        }

        $state = "firing"
        if ($labels["alertstate"] -and [string]$labels["alertstate"] -eq "resolved") {
            $state = "resolved"
        }

        $labelText = ($labels | ConvertTo-Json -Depth 16 -Compress)
        $fingerprint = (Get-StableHash -Text $labelText).Substring(0, 16)
        $eventId = "$DatasetRunId-$WindowId-prom-alert-$fingerprint"
        $firstSample = $samples | Select-Object -First 1
        $lastSample = $samples | Select-Object -Last 1

        $events += [ordered]@{
            alert_event_id = $eventId
            dataset_run_id = $DatasetRunId
            incident_episode_id = $EpisodeId
            alert_fingerprint = $fingerprint
            alert_name = [string]$alertName
            status = $state
            starts_at = ConvertTo-AlertTimestamp -UnixSeconds ([double]$firstSample[0])
            ends_at = ConvertTo-AlertTimestamp -UnixSeconds ([double]$lastSample[0])
            generator_url = $null
            source = "prometheus-alerts-query-range"
            query = "ALERTS"
            sample_count = $samples.Count
            window_start = $WindowStart
            window_end = $WindowEnd
            labels = $labels
            annotations = [ordered]@{}
            linked_trace_ids = @()
            linked_telemetry_window_ids = @($WindowId)
            jira_candidate = $WindowJiraCandidate
        }
    }

    return @($events)
}

function Get-ParsedLokiSectionCounts {
    param(
        [Parameter(Mandatory = $true)][object]$LokiExport,
        [Parameter(Mandatory = $true)][string]$SectionName
    )

    $sectionProperty = $LokiExport.PSObject.Properties | Where-Object { $_.Name -eq $SectionName } | Select-Object -First 1
    if ($null -eq $sectionProperty) {
        return [pscustomobject]@{
            streams = 0
            entries = 0
        }
    }

    $section = $sectionProperty.Value
    $streams = 0
    $entries = 0

    if ($null -ne $section.response -and $null -ne $section.response.data -and $null -ne $section.response.data.result) {
        $result = @($section.response.data.result)
        $streams = $result.Count
        foreach ($stream in $result) {
            $valuesProperty = $stream.PSObject.Properties | Where-Object { $_.Name -eq "values" } | Select-Object -First 1
            if ($null -ne $valuesProperty) {
                $entries += @($valuesProperty.Value).Count
            }
        }
    }

    return [pscustomobject]@{
        streams = $streams
        entries = $entries
    }
}

function Get-TimeBounds {
    param([Parameter(Mandatory = $true)][object[]]$Windows)

    $oldestStart = $null
    $latestEnd = $null

    foreach ($window in @($Windows)) {
        $start = [DateTimeOffset]::Parse([string]$window.start_time)
        $end = [DateTimeOffset]::Parse([string]$window.end_time)

        if ($null -eq $oldestStart -or $start -lt $oldestStart) {
            $oldestStart = $start
        }
        if ($null -eq $latestEnd -or $end -gt $latestEnd) {
            $latestEnd = $end
        }
    }

    return [pscustomobject]@{
        start_time = $oldestStart
        end_time = $latestEnd
    }
}

$runRoot = Get-ResearchLabRunRoot -DatasetRunId $DatasetRunId
if (-not (Test-Path -LiteralPath (Join-Path $runRoot "manifest.json"))) {
    throw "Dataset run does not exist: $DatasetRunId"
}

$windowsPath = Join-Path $runRoot "telemetry_windows.jsonl"
$episodesPath = Join-Path $runRoot "episodes.jsonl"
$alertsPath = Join-Path $runRoot "alerts.jsonl"

$allWindows = @(Read-ResearchLabJsonLines -Path $windowsPath)
$targetWindows = @($allWindows)
if ($TelemetryWindowId) {
    $targetWindows = @($targetWindows | Where-Object { $_.telemetry_window_id -eq $TelemetryWindowId })
}
if ($IncidentEpisodeId) {
    $targetWindows = @($targetWindows | Where-Object { $_.incident_episode_id -eq $IncidentEpisodeId })
}

if ($targetWindows.Count -eq 0) {
    throw "No telemetry windows matched the requested filters."
}

$portForwards = @()
try {
    if (-not $NoPortForward) {
        $portForwards += Start-LocalPortForward -TargetNamespace $ObservabilityNamespace -ServiceName "svc/loki-gateway" -LocalPort 13100 -RemotePort 80
        $portForwards += Start-LocalPortForward -TargetNamespace $ObservabilityNamespace -ServiceName "svc/kube-prometheus-stack-prometheus" -LocalPort 19090 -RemotePort 9090
        $portForwards += Start-LocalPortForward -TargetNamespace $ObservabilityNamespace -ServiceName "svc/tempo" -LocalPort 13200 -RemotePort 3200
        $portForwards += Start-LocalPortForward -TargetNamespace $ObservabilityNamespace -ServiceName "svc/kube-prometheus-stack-alertmanager" -LocalPort 19093 -RemotePort 9093
    }

    $allAlertEvents = @()
    $episodeTraceIds = @{}
    $episodeAlertFingerprints = @{}

    $timeBounds = Get-TimeBounds -Windows $targetWindows
    $runContextStart = $timeBounds.start_time.AddSeconds(-1 * $LokiPaddingSeconds)
    $runContextEnd = $timeBounds.end_time.AddSeconds($LokiPaddingSeconds)
    $runContextStartNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $runContextStart
    $runContextEndNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $runContextEnd
    $runNamespaceQuery = "{namespace=""$WorkloadNamespace""}"
    $runNamespaceUri = "$LokiBaseUrl/loki/api/v1/query_range?query=$([uri]::EscapeDataString($runNamespaceQuery))&start=$runContextStartNs&end=$runContextEndNs&limit=$LokiContextLimit"
    Write-Host "Exporting run-level Loki context for $($targetWindows.Count) telemetry windows"
    $runContextFileName = "run-context.json"
    if ($TelemetryWindowId) {
        $runContextFileName = "window-context-$(ConvertTo-SafeFileNamePart -Value $TelemetryWindowId).json"
    } elseif ($IncidentEpisodeId) {
        $runContextFileName = "episode-context-$(ConvertTo-SafeFileNamePart -Value $IncidentEpisodeId).json"
    }
    $runLokiContext = [ordered]@{
        dataset_run_id = $DatasetRunId
        fetched_at = Get-ResearchLabUtcNow
        target_window_count = $targetWindows.Count
        target_filter = [ordered]@{
            telemetry_window_id = if ($TelemetryWindowId) { $TelemetryWindowId } else { $null }
            incident_episode_id = if ($IncidentEpisodeId) { $IncidentEpisodeId } else { $null }
        }
        window = [ordered]@{
            start_time = $timeBounds.start_time.ToString("o")
            end_time = $timeBounds.end_time.ToString("o")
            padded_start_time = $runContextStart.ToString("o")
            padded_end_time = $runContextEnd.ToString("o")
            padding_seconds = $LokiPaddingSeconds
        }
        namespace_query = $runNamespaceQuery
        namespace_context = Invoke-JsonEndpoint -Uri $runNamespaceUri
    }
    Write-ResearchLabJsonFile -Path (Join-ResearchLabPath @($runRoot, "raw", "loki", $runContextFileName)) -Value $runLokiContext
    Write-Host ("  Run-level Loki namespace entries: {0}" -f (Get-LokiEntryCount -LokiResponse $runLokiContext.namespace_context))

    if ($RunLevelLokiOnly) {
        Write-Host "Telemetry export complete:"
        Write-Host "  windows_exported: 0"
        return
    }

    foreach ($window in $targetWindows) {
        $windowId = [string]$window.telemetry_window_id
        $serviceName = [string]$window.service_name
        $namespace = $WorkloadNamespace
        if ($window.k8s.namespace) {
            $namespace = [string]$window.k8s.namespace
        }

        $start = [DateTimeOffset]::Parse([string]$window.start_time)
        $end = [DateTimeOffset]::Parse([string]$window.end_time)
        $paddedStart = $start.AddSeconds(-1 * $LokiPaddingSeconds)
        $paddedEnd = $end.AddSeconds($LokiPaddingSeconds)
        $startNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $start
        $endNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $end
        $paddedStartNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $paddedStart
        $paddedEndNs = ConvertTo-ResearchLabUnixNanoseconds -DateTime $paddedEnd
        $startSec = ConvertTo-ResearchLabUnixSeconds -DateTime $start
        $endSec = ConvertTo-ResearchLabUnixSeconds -DateTime $end

        Write-Host "Exporting telemetry window $windowId ($serviceName)"

        $serviceLokiQuery = "{namespace=""$namespace"", app=""$serviceName""}"
        $namespaceLokiQuery = "{namespace=""$namespace""}"
        $serviceWindowUri = "$LokiBaseUrl/loki/api/v1/query_range?query=$([uri]::EscapeDataString($serviceLokiQuery))&start=$startNs&end=$endNs&limit=$LokiLimit"
        $serviceContextUri = "$LokiBaseUrl/loki/api/v1/query_range?query=$([uri]::EscapeDataString($serviceLokiQuery))&start=$paddedStartNs&end=$paddedEndNs&limit=$LokiContextLimit"
        $namespaceContextUri = "$LokiBaseUrl/loki/api/v1/query_range?query=$([uri]::EscapeDataString($namespaceLokiQuery))&start=$paddedStartNs&end=$paddedEndNs&limit=$LokiContextLimit"
        $loki = [ordered]@{
            fetched_at = Get-ResearchLabUtcNow
            window = [ordered]@{
                start_time = $start.ToString("o")
                end_time = $end.ToString("o")
                padded_start_time = $paddedStart.ToString("o")
                padded_end_time = $paddedEnd.ToString("o")
                padding_seconds = $LokiPaddingSeconds
            }
            service_query = $serviceLokiQuery
            namespace_query = $namespaceLokiQuery
            service_window = Invoke-JsonEndpoint -Uri $serviceWindowUri
            service_context = Invoke-JsonEndpoint -Uri $serviceContextUri
            namespace_context = Invoke-JsonEndpoint -Uri $namespaceContextUri
        }
        $lokiPath = Join-ResearchLabPath @($runRoot, "raw", "loki", "$windowId.json")
        Write-ResearchLabJsonFile -Path $lokiPath -Value $loki
        $parsedLoki = Get-Content -LiteralPath $lokiPath -Raw | ConvertFrom-Json
        $serviceWindowLogCounts = Get-ParsedLokiSectionCounts -LokiExport $parsedLoki -SectionName "service_window"
        $serviceContextLogCounts = Get-ParsedLokiSectionCounts -LokiExport $parsedLoki -SectionName "service_context"
        $namespaceContextLogCounts = Get-ParsedLokiSectionCounts -LokiExport $parsedLoki -SectionName "namespace_context"
        Write-Host ("  Loki entries: exact={0} service_context={1} namespace_context={2}" -f `
            (Get-ExportProperty -Object $serviceWindowLogCounts -Name "entries"), `
            (Get-ExportProperty -Object $serviceContextLogCounts -Name "entries"), `
            (Get-ExportProperty -Object $namespaceContextLogCounts -Name "entries"))

        $podRegex = "$serviceName-.*"
        $promQueries = [ordered]@{
            pod_info = 'kube_pod_info{namespace="' + $namespace + '",pod=~"' + $podRegex + '"}'
            restarts = 'kube_pod_container_status_restarts_total{namespace="' + $namespace + '",pod=~"' + $podRegex + '"}'
            cpu_usage = 'container_cpu_usage_seconds_total{namespace="' + $namespace + '",pod=~"' + $podRegex + '",container!="POD",container!=""}'
            memory_working_set = 'container_memory_working_set_bytes{namespace="' + $namespace + '",pod=~"' + $podRegex + '",container!="POD",container!=""}'
            alerts = "ALERTS"
        }

        $promResults = [ordered]@{
            fetched_at = Get-ResearchLabUtcNow
            start_time = $start.ToString("o")
            end_time = $end.ToString("o")
            step_seconds = $StepSeconds
            queries = [ordered]@{}
        }

        foreach ($queryName in $promQueries.Keys) {
            $query = $promQueries[$queryName]
            $uri = "$PrometheusBaseUrl/api/v1/query_range?query=$([uri]::EscapeDataString($query))&start=$startSec&end=$endSec&step=$StepSeconds"
            $promResults.queries[$queryName] = Invoke-JsonEndpoint -Uri $uri
        }
        Write-ResearchLabJsonFile -Path (Join-ResearchLabPath @($runRoot, "raw", "prometheus", "$windowId.json")) -Value $promResults

        $prometheusQueries = Get-ExportProperty -Object $promResults -Name "queries"
        $prometheusAlertsQuery = Get-ExportProperty -Object $prometheusQueries -Name "alerts"
        $historicalAlertEvents = @(New-PrometheusAlertEvents `
            -PrometheusAlertQuery $prometheusAlertsQuery `
            -DatasetRunId $DatasetRunId `
            -EpisodeId ([string]$window.incident_episode_id) `
            -WindowId $windowId `
            -WindowStart $start.ToString("o") `
            -WindowEnd $end.ToString("o") `
            -WindowJiraCandidate ([bool]$window.labels.jira_candidate))

        $tempoSearchUri = "$TempoBaseUrl/api/search?start=$startSec&end=$endSec&limit=$TempoLimit"
        $tempoSearch = Invoke-JsonEndpoint -Uri $tempoSearchUri
        $traceIds = @(Get-TempoTraceIds -TempoResponse $tempoSearch)
        $traceDetails = [ordered]@{}
        foreach ($traceId in @($traceIds | Select-Object -First 20)) {
            $traceDetails[$traceId] = Invoke-JsonEndpoint -Uri "$TempoBaseUrl/api/traces/$traceId"
        }
        $tempo = [ordered]@{
            search = $tempoSearch
            traces = $traceDetails
        }
        Write-ResearchLabJsonFile -Path (Join-ResearchLabPath @($runRoot, "raw", "tempo", "$windowId.json")) -Value $tempo

        $alertmanager = Invoke-JsonEndpoint -Uri "$AlertmanagerBaseUrl/api/v2/alerts"
        $alertEvents = @(New-AlertEvents `
            -AlertmanagerResponse $alertmanager `
            -DatasetRunId $DatasetRunId `
            -EpisodeId ([string]$window.incident_episode_id) `
            -WindowIds @($windowId))
        $alertEvents += $historicalAlertEvents
        $allAlertEvents += $alertEvents

        $window.trace_ids = $traceIds
        $window.features.logs.exported = $true
        $window.features.logs | Add-Member -NotePropertyName stream_count -NotePropertyValue ([int](Get-ExportProperty -Object $serviceWindowLogCounts -Name "streams")) -Force
        $window.features.logs | Add-Member -NotePropertyName entry_count -NotePropertyValue ([int](Get-ExportProperty -Object $serviceWindowLogCounts -Name "entries")) -Force
        $window.features.logs | Add-Member -NotePropertyName context_stream_count -NotePropertyValue ([int](Get-ExportProperty -Object $serviceContextLogCounts -Name "streams")) -Force
        $window.features.logs | Add-Member -NotePropertyName context_entry_count -NotePropertyValue ([int](Get-ExportProperty -Object $serviceContextLogCounts -Name "entries")) -Force
        $window.features.logs | Add-Member -NotePropertyName namespace_context_stream_count -NotePropertyValue ([int](Get-ExportProperty -Object $namespaceContextLogCounts -Name "streams")) -Force
        $window.features.logs | Add-Member -NotePropertyName namespace_context_entry_count -NotePropertyValue ([int](Get-ExportProperty -Object $namespaceContextLogCounts -Name "entries")) -Force
        $window.features.logs | Add-Member -NotePropertyName padding_seconds -NotePropertyValue $LokiPaddingSeconds -Force
        $window.features.metrics.exported = $true
        $window.features.metrics | Add-Member -NotePropertyName query_count -NotePropertyValue $promQueries.Count -Force
        $window.features.metrics | Add-Member -NotePropertyName historical_alert_event_count -NotePropertyValue $historicalAlertEvents.Count -Force
        $window.features.traces.exported = $true
        $window.features.traces | Add-Member -NotePropertyName trace_count -NotePropertyValue $traceIds.Count -Force

        $episodeId = [string]$window.incident_episode_id
        if ($episodeId) {
            if (-not $episodeTraceIds.ContainsKey($episodeId)) {
                $episodeTraceIds[$episodeId] = @()
            }
            $episodeTraceIds[$episodeId] = @($episodeTraceIds[$episodeId] + $traceIds | Sort-Object -Unique)

            if (-not $episodeAlertFingerprints.ContainsKey($episodeId)) {
                $episodeAlertFingerprints[$episodeId] = @()
            }
            $episodeAlertFingerprints[$episodeId] = @($episodeAlertFingerprints[$episodeId] + (@($alertEvents) | ForEach-Object { $_.alert_fingerprint }) | Sort-Object -Unique)
        }

        for ($i = 0; $i -lt $allWindows.Count; $i++) {
            if ([string]$allWindows[$i].telemetry_window_id -eq $windowId) {
                $allWindows[$i] = $window
                break
            }
        }
    }

    if ($allAlertEvents.Count -gt 0) {
        Merge-ResearchLabJsonLines -Path $alertsPath -Records $allAlertEvents -KeyProperty "alert_event_id"
    }

    Write-ResearchLabJsonLines -Path $windowsPath -Records $allWindows

    $episodes = @(Read-ResearchLabJsonLines -Path $episodesPath)
    foreach ($episode in $episodes) {
        $episodeId = [string]$episode.incident_episode_id
        if ($episodeTraceIds.ContainsKey($episodeId)) {
            $episode.trace_ids = @($episodeTraceIds[$episodeId])
        }
        if ($episodeAlertFingerprints.ContainsKey($episodeId)) {
            $episode.alert_fingerprints = @($episodeAlertFingerprints[$episodeId])
        }
    }
    Write-ResearchLabJsonLines -Path $episodesPath -Records $episodes
} finally {
    Stop-LocalPortForward -Processes $portForwards
}

Write-Host "Telemetry export complete:"
Write-Host "  windows_exported: $($targetWindows.Count)"
