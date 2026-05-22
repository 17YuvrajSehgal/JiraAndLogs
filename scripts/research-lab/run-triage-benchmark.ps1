[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GlobalDatasetId,

    [Parameter(Mandatory = $true)]
    [string]$BenchmarkId,

    [string]$DerivedRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_triage_benchmark.py"
$pyArgs = @(
    $scriptPath,
    "--global-dataset-id", $GlobalDatasetId,
    "--benchmark-id", $BenchmarkId
)

if ($DerivedRoot) { $pyArgs += @("--derived-root", $DerivedRoot) }
if ($Force)       { $pyArgs += "--force" }

& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Triage benchmark '$BenchmarkId' failed for $GlobalDatasetId."
}
