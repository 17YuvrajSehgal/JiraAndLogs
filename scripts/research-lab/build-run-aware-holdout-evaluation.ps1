[CmdletBinding()]
param(
    [string[]]$DatasetRunId = @(),
    [string]$EvaluationId = "current",
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_run_aware_holdout_evaluation.py"
$args = @(
    $scriptPath,
    "--evaluation-id", $EvaluationId
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
    throw "Run-aware holdout evaluation build failed."
}
