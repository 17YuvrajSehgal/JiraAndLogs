[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunPrefix,

    [Parameter(Mandatory = $true)]
    [string]$GlobalDatasetId,

    [string]$RunsRoot,
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_jira_memory_corpus.py"
$pyArgs = @(
    $scriptPath,
    "--dataset-run-prefix", $DatasetRunPrefix,
    "--global-dataset-id", $GlobalDatasetId
)

if ($RunsRoot)   { $pyArgs += @("--runs-root", $RunsRoot) }
if ($OutputRoot) { $pyArgs += @("--output-root", $OutputRoot) }
if ($Force)      { $pyArgs += "--force" }

& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Jira memory corpus build failed for prefix $DatasetRunPrefix."
}