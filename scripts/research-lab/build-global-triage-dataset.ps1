[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRunPrefix,

    [Parameter(Mandatory = $true)]
    [string]$GlobalDatasetId,

    [string]$DerivedRoot,
    [string[]]$TrainFamilies,
    [string[]]$ValidationFamilies,
    [string[]]$TestFamilies,
    [string]$PythonExe = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "build_global_triage_dataset.py"
$pyArgs = @(
    $scriptPath,
    "--dataset-run-prefix", $DatasetRunPrefix,
    "--global-dataset-id", $GlobalDatasetId
)

if ($DerivedRoot) { $pyArgs += @("--derived-root", $DerivedRoot) }
if ($TrainFamilies)      { $pyArgs += @("--train-families");      $pyArgs += $TrainFamilies }
if ($ValidationFamilies) { $pyArgs += @("--validation-families"); $pyArgs += $ValidationFamilies }
if ($TestFamilies)       { $pyArgs += @("--test-families");       $pyArgs += $TestFamilies }
if ($Force)              { $pyArgs += "--force" }

& $PythonExe @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Global triage dataset build failed for prefix $DatasetRunPrefix."
}