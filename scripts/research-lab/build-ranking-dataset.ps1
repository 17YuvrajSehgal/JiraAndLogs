[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_ranking_dataset.py"
$args = @(
    $scriptPath,
    "--dataset-run-id", $DatasetRunId
)

if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($Force) {
    $args += "--force"
}

& $PythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Ranking dataset build failed for $DatasetRunId."
}
