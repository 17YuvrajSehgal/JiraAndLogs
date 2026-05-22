[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunId,

    [string]$DerivedRoot,
    [string]$RunsRoot,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "validate_run_feature_distribution.py"
$pyArgs = @(
    $scriptPath,
    "--dataset-run-id", $DatasetRunId
)
if ($DerivedRoot) { $pyArgs += @("--derived-root", $DerivedRoot) }
if ($RunsRoot)    { $pyArgs += @("--runs-root", $RunsRoot) }

& $PythonExe @pyArgs
# Exit code is propagated: 0 = pass, 1 = fail. Caller (collect-dataset-corpus.ps1)
# can decide whether to halt the corpus on a failed run.
exit $LASTEXITCODE
