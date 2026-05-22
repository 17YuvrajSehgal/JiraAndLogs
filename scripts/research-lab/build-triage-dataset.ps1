[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$OutputRoot,
    [string]$ScenariosRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_triage_dataset.py"
$pyArgs = @(
    $scriptPath,
    "--dataset-run-id", $DatasetRunId
)

if ($OutputRoot)    { $pyArgs += @("--output-root", $OutputRoot) }
if ($ScenariosRoot) { $pyArgs += @("--scenarios-root", $ScenariosRoot) }
if ($Force)         { $pyArgs += "--force" }

& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Triage dataset build failed for $DatasetRunId."
}