Set-StrictMode -Version Latest

function Join-ResearchLabPath {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Parts
    )

    if ($Parts.Count -eq 0) {
        throw "At least one path part is required."
    }

    $path = $Parts[0]
    for ($i = 1; $i -lt $Parts.Count; $i++) {
        foreach ($segment in ([string]$Parts[$i] -split '[\\/]+')) {
            if ([string]::IsNullOrWhiteSpace($segment)) {
                continue
            }
            $path = Join-Path $path $segment
        }
    }
    return $path
}

function Get-ResearchLabRepoRoot {
    return (Resolve-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))).Path
}

function Get-ResearchLabRunRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatasetRunId
    )

    $repoRoot = Get-ResearchLabRepoRoot
    return Join-ResearchLabPath @($repoRoot, "data", "runs", $DatasetRunId)
}

function New-ResearchLabDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Get-ResearchLabUtcNow {
    return ([DateTimeOffset]::UtcNow).ToString("o")
}

function ConvertTo-ResearchLabJson {
    param(
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [object]$InputObject
    )

    process {
        $InputObject | ConvertTo-Json -Depth 64
    }
}

function ConvertTo-ResearchLabJsonLine {
    param(
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [object]$InputObject
    )

    process {
        $InputObject | ConvertTo-Json -Depth 64 -Compress
    }
}

function Write-ResearchLabJsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-ResearchLabDirectory -Path $parent
    }

    $json = $Value | ConvertTo-ResearchLabJson
    Set-Content -LiteralPath $Path -Value $json -Encoding UTF8
}

function Read-ResearchLabJsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "JSON file not found: $Path"
    }

    $text = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "JSON file is empty: $Path"
    }

    return $text | ConvertFrom-Json
}

function Add-ResearchLabJsonLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-ResearchLabDirectory -Path $parent
    }

    $json = $Value | ConvertTo-ResearchLabJsonLine
    Add-Content -LiteralPath $Path -Value $json -Encoding UTF8
}

function Read-ResearchLabJsonLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    $records = @()
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $Path) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        try {
            $records += ($line | ConvertFrom-Json)
        } catch {
            throw "Failed to parse JSONL file $Path at line $lineNumber. $($_.Exception.Message)"
        }
    }

    return @($records)
}

function Write-ResearchLabJsonLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object[]]$Records
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-ResearchLabDirectory -Path $parent
    }

    $lines = @()
    foreach ($record in $Records) {
        $lines += ($record | ConvertTo-ResearchLabJsonLine)
    }

    Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
}

function Get-ResearchLabProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name
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

function Merge-ResearchLabJsonLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object[]]$Records,

        [Parameter(Mandatory = $true)]
        [string]$KeyProperty
    )

    $merged = [ordered]@{}
    foreach ($record in (Read-ResearchLabJsonLines -Path $Path)) {
        $key = Get-ResearchLabProperty -Object $record -Name $KeyProperty
        if ($key) {
            $merged[[string]$key] = $record
        }
    }

    foreach ($record in $Records) {
        $key = Get-ResearchLabProperty -Object $record -Name $KeyProperty
        if (-not $key) {
            throw "Cannot merge record without key property '$KeyProperty'."
        }
        $merged[[string]$key] = $record
    }

    Write-ResearchLabJsonLines -Path $Path -Records @($merged.Values)
}

function Test-ResearchLabCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-ResearchLabPowerShellCommand {
    try {
        $currentProcessPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        if (-not [string]::IsNullOrWhiteSpace($currentProcessPath) -and (Test-Path -LiteralPath $currentProcessPath)) {
            return $currentProcessPath
        }
    } catch {
        # Fall through to PATH lookup.
    }

    foreach ($name in @("pwsh", "powershell")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            return $cmd.Source
        }
    }

    throw "Unable to find a PowerShell executable. Install PowerShell 7+ as 'pwsh' or Windows PowerShell as 'powershell'."
}

function Invoke-ResearchLabTextCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$ArgumentList = @(),

        [switch]$IgnoreFailure
    )

    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $FilePath @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0 -and -not $IgnoreFailure) {
        throw "Command failed: $FilePath $($ArgumentList -join ' ')"
    }

    return (($output | Out-String).Trim())
}

function Get-ResearchLabGitInfo {
    $repoRoot = Get-ResearchLabRepoRoot

    $commit = "unknown"
    $branch = $null
    $status = @()

    if (Test-ResearchLabCommand -Name "git") {
        Push-Location $repoRoot
        try {
            $commitText = Invoke-ResearchLabTextCommand -FilePath "git" -ArgumentList @("rev-parse", "HEAD") -IgnoreFailure
            if ($commitText) {
                $commit = ($commitText -split "`r?`n")[0]
            }

            $branchText = Invoke-ResearchLabTextCommand -FilePath "git" -ArgumentList @("branch", "--show-current") -IgnoreFailure
            if ($branchText) {
                $branch = ($branchText -split "`r?`n")[0]
            }

            $statusText = Invoke-ResearchLabTextCommand -FilePath "git" -ArgumentList @("status", "--porcelain") -IgnoreFailure
            if ($statusText) {
                $status = @($statusText -split "`r?`n" | Where-Object { $_ })
            }
        } finally {
            Pop-Location
        }
    }

    return [ordered]@{
        repository = $repoRoot
        commit_sha = $commit
        branch = $branch
        dirty = ($status.Count -gt 0)
        status_short = $status
    }
}

function Invoke-ResearchLabKubectlJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [switch]$IgnoreFailure
    )

    if (-not (Test-ResearchLabCommand -Name "kubectl")) {
        if ($IgnoreFailure) {
            return $null
        }
        throw "kubectl is not installed or not on PATH."
    }

    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & kubectl @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0) {
        if ($IgnoreFailure) {
            return $null
        }
        throw "kubectl command failed: kubectl $($ArgumentList -join ' ')"
    }

    $text = (($output | Out-String).Trim())
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    return $text | ConvertFrom-Json
}

function Invoke-ResearchLabKubectlText {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [switch]$IgnoreFailure
    )

    if (-not (Test-ResearchLabCommand -Name "kubectl")) {
        if ($IgnoreFailure) {
            return $null
        }
        throw "kubectl is not installed or not on PATH."
    }

    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & kubectl @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0) {
        if ($IgnoreFailure) {
            return $null
        }
        throw "kubectl command failed: kubectl $($ArgumentList -join ' ')"
    }

    return (($output | Out-String).Trim())
}

function Get-ResearchLabKubeContext {
    $context = Invoke-ResearchLabKubectlText -ArgumentList @("config", "current-context") -IgnoreFailure
    if ($context) {
        return ($context -split "`r?`n")[0]
    }
    return $null
}

function Get-ResearchLabWorkloadServices {
    param(
        [string]$Namespace = "online-boutique-research"
    )

    $json = Invoke-ResearchLabKubectlJson -ArgumentList @("get", "deployments", "-n", $Namespace, "-o", "json") -IgnoreFailure
    if ($null -eq $json -or $null -eq $json.items) {
        return @()
    }

    $services = @()
    foreach ($item in $json.items) {
        $services += [string]$item.metadata.name
    }
    return @($services | Sort-Object -Unique)
}

function ConvertTo-ResearchLabUnixSeconds {
    param(
        [Parameter(Mandatory = $true)]
        [DateTimeOffset]$DateTime
    )

    return $DateTime.ToUnixTimeSeconds()
}

function ConvertTo-ResearchLabUnixNanoseconds {
    param(
        [Parameter(Mandatory = $true)]
        [DateTimeOffset]$DateTime
    )

    $seconds = [int64]$DateTime.ToUnixTimeSeconds()
    $ticksWithinSecond = [int64]($DateTime.UtcTicks % [TimeSpan]::TicksPerSecond)
    return [string](($seconds * [int64]1000000000) + ($ticksWithinSecond * [int64]100))
}

function ConvertFrom-ResearchLabYamlScalar {
    param(
        [AllowNull()]
        [object]$Value,

        [switch]$AsString
    )

    if ($null -eq $Value) {
        return $null
    }

    $text = ([string]$Value).Trim()
    if ($text.Length -ge 2) {
        if (($text.StartsWith('"') -and $text.EndsWith('"')) -or ($text.StartsWith("'") -and $text.EndsWith("'"))) {
            $text = $text.Substring(1, $text.Length - 2)
        }
    }

    if ($text -cmatch '^(null|Null|NULL|~)$') {
        return $null
    }
    if ($AsString) {
        return $text
    }

    if ($text -cmatch '^(true|True|TRUE)$') {
        return $true
    }
    if ($text -cmatch '^(false|False|FALSE)$') {
        return $false
    }
    if ($text -match '^-?\d+$') {
        return [int]$text
    }

    return $text
}

function Test-ResearchLabKeyPath {
    param(
        [string[]]$Actual,
        [string[]]$Expected
    )

    if ($Actual.Count -ne $Expected.Count) {
        return $false
    }

    for ($i = 0; $i -lt $Actual.Count; $i++) {
        if ($Actual[$i] -ne $Expected[$i]) {
            return $false
        }
    }

    return $true
}

function Remove-ResearchLabStackAtOrAboveIndent {
    param(
        [object[]]$Stack,
        [int]$Indent
    )

    $newStack = @()
    foreach ($entry in $Stack) {
        if ($entry.indent -lt $Indent) {
            $newStack += $entry
        }
    }
    return @($newStack)
}

function Get-ResearchLabYamlBlockValue {
    param(
        [string[]]$Lines,
        [int]$StartIndex,
        [int]$ParentIndent,
        [string]$Mode
    )

    $block = @()
    for ($i = $StartIndex + 1; $i -lt $Lines.Count; $i++) {
        $line = $Lines[$i]
        if ([string]::IsNullOrWhiteSpace($line)) {
            $block += ""
            continue
        }

        $indent = ($line.Length - $line.TrimStart().Length)
        if ($indent -le $ParentIndent) {
            break
        }

        $trimAt = [Math]::Min($line.Length, $ParentIndent + 2)
        $block += $line.Substring($trimAt)
    }

    if ($Mode -eq ">") {
        return (($block | ForEach-Object { $_.Trim() }) -join " ").Trim()
    }

    return ($block -join "`n").TrimEnd()
}

function Get-ResearchLabYamlScalar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string[]]$KeyPath,

        [switch]$AsString
    )

    $lines = Get-Content -LiteralPath $Path
    $stack = @()

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) {
            continue
        }

        if ($line -match '^(\s*)([A-Za-z0-9_-]+):\s*(.*)$') {
            $indent = $Matches[1].Length
            $key = $Matches[2]
            $value = $Matches[3].Trim()

            $stack = @(Remove-ResearchLabStackAtOrAboveIndent -Stack $stack -Indent $indent)

            $currentPath = @()
            foreach ($entry in $stack) {
                $currentPath += [string]$entry.key
            }
            $currentPath += $key

            if (Test-ResearchLabKeyPath -Actual $currentPath -Expected $KeyPath) {
                if ($value -eq "|" -or $value -eq ">") {
                    return (Get-ResearchLabYamlBlockValue -Lines $lines -StartIndex $i -ParentIndent $indent -Mode $value)
                }
                return (ConvertFrom-ResearchLabYamlScalar -Value $value -AsString:$AsString)
            }

            if ([string]::IsNullOrWhiteSpace($value) -or $value -eq "|" -or $value -eq ">") {
                $stack += [pscustomobject]@{
                    indent = $indent
                    key = $key
                }
            }
        }
    }

    return $null
}

function Get-ResearchLabYamlList {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string[]]$KeyPath
    )

    $lines = Get-Content -LiteralPath $Path
    $stack = @()

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) {
            continue
        }

        if ($line -match '^(\s*)([A-Za-z0-9_-]+):\s*(.*)$') {
            $indent = $Matches[1].Length
            $key = $Matches[2]
            $value = $Matches[3].Trim()

            $stack = @(Remove-ResearchLabStackAtOrAboveIndent -Stack $stack -Indent $indent)

            $currentPath = @()
            foreach ($entry in $stack) {
                $currentPath += [string]$entry.key
            }
            $currentPath += $key

            if (Test-ResearchLabKeyPath -Actual $currentPath -Expected $KeyPath) {
                $items = @()
                for ($j = $i + 1; $j -lt $lines.Count; $j++) {
                    $nextLine = $lines[$j]
                    if ([string]::IsNullOrWhiteSpace($nextLine)) {
                        continue
                    }

                    $nextIndent = ($nextLine.Length - $nextLine.TrimStart().Length)
                    if ($nextIndent -le $indent) {
                        break
                    }

                    if ($nextLine -match '^\s*-\s*(.+?)\s*$') {
                        $items += (ConvertFrom-ResearchLabYamlScalar -Value $Matches[1] -AsString)
                    }
                }
                return @($items)
            }

            if ([string]::IsNullOrWhiteSpace($value) -or $value -eq "|" -or $value -eq ">") {
                $stack += [pscustomobject]@{
                    indent = $indent
                    key = $key
                }
            }
        }
    }

    return @()
}

function Get-ResearchLabYamlMap {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string[]]$KeyPath,

        [switch]$ValuesAsString
    )

    $lines = Get-Content -LiteralPath $Path
    $stack = @()

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) {
            continue
        }

        if ($line -match '^(\s*)([A-Za-z0-9_-]+):\s*(.*)$') {
            $indent = $Matches[1].Length
            $key = $Matches[2]
            $value = $Matches[3].Trim()

            $stack = @(Remove-ResearchLabStackAtOrAboveIndent -Stack $stack -Indent $indent)

            $currentPath = @()
            foreach ($entry in $stack) {
                $currentPath += [string]$entry.key
            }
            $currentPath += $key

            if (Test-ResearchLabKeyPath -Actual $currentPath -Expected $KeyPath) {
                $map = [ordered]@{}
                $childIndent = $null
                for ($j = $i + 1; $j -lt $lines.Count; $j++) {
                    $nextLine = $lines[$j]
                    if ([string]::IsNullOrWhiteSpace($nextLine)) {
                        continue
                    }

                    $nextIndent = ($nextLine.Length - $nextLine.TrimStart().Length)
                    if ($nextIndent -le $indent) {
                        break
                    }

                    if ($nextLine -match '^(\s*)([A-Za-z0-9_-]+):\s*(.*)$') {
                        $actualIndent = $Matches[1].Length
                        if ($null -eq $childIndent) {
                            $childIndent = $actualIndent
                        }
                        if ($actualIndent -eq $childIndent) {
                            $map[$Matches[2]] = ConvertFrom-ResearchLabYamlScalar -Value $Matches[3].Trim() -AsString:$ValuesAsString
                        }
                    }
                }
                return $map
            }

            if ([string]::IsNullOrWhiteSpace($value) -or $value -eq "|" -or $value -eq ">") {
                $stack += [pscustomobject]@{
                    indent = $indent
                    key = $key
                }
            }
        }
    }

    return [ordered]@{}
}

function Get-ResearchLabScenarioConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScenarioFile
    )

    if (-not (Test-Path -LiteralPath $ScenarioFile)) {
        throw "Scenario file not found: $ScenarioFile"
    }

    $scenarioId = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("scenario_id") -AsString
    if (-not $scenarioId) {
        throw "Scenario file does not define scenario_id: $ScenarioFile"
    }

    $duration = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "expected_duration_seconds")
    if ($null -eq $duration) {
        $duration = 300
    }

    $affectedService = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "affected_service") -AsString
    if (-not $affectedService) {
        $affectedService = "frontend"
    }

    return [pscustomobject]@{
        scenario_file = $ScenarioFile
        scenario_id = $scenarioId
        title = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("title") -AsString
        dataset_run_id = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("dataset_run_id") -AsString
        traffic_profile_id = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("traffic_profile_id") -AsString
        environment = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("environment") -AsString
        jira_candidate = [bool](Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("jira_candidate"))
        # D12.1 (2026-05-24): produces_jira_ticket gates whether the
        # incident yields a Jira shadow row. Absent or true → behaviour
        # unchanged; explicit false marks the scenario as an *orphan
        # fault* (a fault the system would catch but no human filed a
        # ticket for). See dataset-todo.md Phase D12.
        produces_jira_ticket = $(
            $__p = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("produces_jira_ticket")
            if ($null -eq $__p) { $true } else { [bool]$__p }
        )
        expected_jira_issue_type = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("expected_jira", "issue_type") -AsString
        expected_jira_priority = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("expected_jira", "priority") -AsString
        expected_jira_components = @(Get-ResearchLabYamlList -Path $ScenarioFile -KeyPath @("expected_jira", "components"))
        expected_jira_labels = @(Get-ResearchLabYamlList -Path $ScenarioFile -KeyPath @("expected_jira", "labels"))
        expected_jira_summary_template = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("expected_jira", "summary_template") -AsString
        expected_jira_description_template = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("expected_jira", "description_template") -AsString
        fault_id = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "fault_id") -AsString
        fault_type = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "fault_type") -AsString
        affected_service = $affectedService
        expected_duration_seconds = [int]$duration
        expected_user_impact = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "blast_radius", "user_visible") -AsString
        expected_error_rate = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "blast_radius", "expected_error_rate") -AsString
        expected_latency_impact = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("fault", "blast_radius", "expected_latency_impact") -AsString
        severity = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("labels", "severity") -AsString
        incident_type = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("labels", "incident_type") -AsString
        root_cause_category = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("labels", "root_cause_category") -AsString
        should_alert = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("labels", "should_alert") -AsString
        should_create_jira_shadow_issue = [bool](Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("labels", "should_create_jira_shadow_issue"))
        execution_action = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "action") -AsString
        execution_namespace = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "namespace") -AsString
        execution_target_kind = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "target_kind") -AsString
        execution_target_name = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "target_name") -AsString
        execution_target_container = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "target_container") -AsString
        execution_selector = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "selector") -AsString
        execution_replicas = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "replicas")
        execution_restore_replicas = Get-ResearchLabYamlScalar -Path $ScenarioFile -KeyPath @("execution", "restore_replicas")
        execution_env = Get-ResearchLabYamlMap -Path $ScenarioFile -KeyPath @("execution", "env") -ValuesAsString
        execution_restore_env = Get-ResearchLabYamlMap -Path $ScenarioFile -KeyPath @("execution", "restore_env")
    }
}

function Get-ResearchLabScenarioServices {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Scenario
    )

    $services = @()
    if ($Scenario.affected_service) {
        $services += [string]$Scenario.affected_service
    }
    foreach ($component in @($Scenario.expected_jira_components)) {
        if ($component -and $component -ne "Online Boutique" -and $component -ne "None") {
            $services += [string]$component
        }
    }
    if ($Scenario.incident_type -ne "baseline") {
        $services += "frontend"
    }
    if ($Scenario.incident_type -eq "outage" -or $Scenario.incident_type -eq "degradation") {
        $services += "checkoutservice"
    }

    return @($services | Where-Object { $_ } | Sort-Object -Unique)
}

Export-ModuleMember -Function *-ResearchLab*
