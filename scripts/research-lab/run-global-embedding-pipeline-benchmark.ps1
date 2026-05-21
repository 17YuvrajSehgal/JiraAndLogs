[CmdletBinding()]
param(
    [string]$GlobalDatasetId = "current",
    [string]$BenchmarkId = "embedding-v1",
    [string]$GlobalRoot,
    [string]$OutputRoot,
    [string]$PythonExe = "python",
    [int]$HashDimension = 768,
    [switch]$IncludeSentenceTransformers,
    [string]$SentenceTransformerModel = "sentence-transformers/all-MiniLM-L6-v2",
    [string]$SentenceTransformerCache,
    [int]$BatchSize = 16,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_global_embedding_pipeline_benchmark.py"
$args = @(
    $scriptPath,
    "--global-dataset-id", $GlobalDatasetId,
    "--benchmark-id", $BenchmarkId,
    "--hash-dimension", $HashDimension,
    "--sentence-transformer-model", $SentenceTransformerModel,
    "--batch-size", $BatchSize
)

if ($GlobalRoot) {
    $args += @("--global-root", $GlobalRoot)
}
if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($IncludeSentenceTransformers) {
    $args += "--include-sentence-transformers"
}
if ($SentenceTransformerCache) {
    $args += @("--sentence-transformer-cache", $SentenceTransformerCache)
}
if ($Force) {
    $args += "--force"
}

& $PythonExe @args
if ($LASTEXITCODE -ne 0) {
    throw "Global embedding pipeline benchmark failed."
}
