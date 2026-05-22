[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [Parameter(Mandatory = $true)]
    [string]$GlobalDatasetId,

    [string]$RunsRoot,
    [string]$DerivedRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_window_memory_matchings.py"
$pyArgs = @(
    $scriptPath,
    "--dataset-run-id", $DatasetRunId,
    "--global-dataset-id", $GlobalDatasetId
)

if ($RunsRoot)    { $pyArgs += @("--runs-root", $RunsRoot) }
if ($DerivedRoot) { $pyArgs += @("--derived-root", $DerivedRoot) }
if ($Force)       { $pyArgs += "--force" }

& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Window memory matchings build failed for $DatasetRunId."
}