[CmdletBinding()]
param(
    [string]$GlobalDatasetId = "current",
    [string]$BenchmarkId = "current",
    [string]$GlobalRoot,
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_global_pipeline_benchmark.py"
$args = @(
    $scriptPath,
    "--global-dataset-id", $GlobalDatasetId,
    "--benchmark-id", $BenchmarkId
)

if ($GlobalRoot) {
    $args += @("--global-root", $GlobalRoot)
}
if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($Force) {
    $args += "--force"
}

& $PythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Global pipeline benchmark failed."
}
