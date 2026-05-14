[CmdletBinding()]
param(
    [string[]]$DatasetRunId = @(),
    [string]$AggregateId = "current",
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_cross_run_evaluation.py"
$args = @(
    $scriptPath,
    "--aggregate-id", $AggregateId
)

foreach ($runIdValue in $DatasetRunId) {
    foreach ($runId in ($runIdValue -split ",")) {
        $normalizedRunId = $runId.Trim()
        if (-not [string]::IsNullOrWhiteSpace($normalizedRunId)) {
            $args += @("--dataset-run-id", $normalizedRunId)
        }
    }
}

if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($Force) {
    $args += "--force"
}

& $PythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Cross-run evaluation build failed."
}
