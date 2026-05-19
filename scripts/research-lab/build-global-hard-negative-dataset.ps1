[CmdletBinding()]
param(
    [string[]]$DatasetRunId = @(),
    [string]$DatasetRunPrefix,
    [string]$CorpusManifest,
    [string]$GlobalDatasetId = "current",
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_global_hard_negative_dataset.py"
$args = @(
    $scriptPath,
    "--global-dataset-id", $GlobalDatasetId
)

foreach ($runIdValue in $DatasetRunId) {
    foreach ($runId in ($runIdValue -split ",")) {
        $normalizedRunId = $runId.Trim()
        if (-not [string]::IsNullOrWhiteSpace($normalizedRunId)) {
            $args += @("--dataset-run-id", $normalizedRunId)
        }
    }
}

if ($DatasetRunPrefix) {
    $args += @("--dataset-run-prefix", $DatasetRunPrefix)
}
if ($CorpusManifest) {
    $args += @("--corpus-manifest", $CorpusManifest)
}
if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($Force) {
    $args += "--force"
}

& $PythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Global hard-negative dataset build failed."
}
