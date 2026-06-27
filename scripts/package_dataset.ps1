param(
    [string]$Dataset = "all"   # "all" | "ob" | "otel" | "wol"
)

$TOOLS  = "C:\Program Files\MongoDB\Tools\100\bin"
$GLOBAL = "C:\workplace\JiraAndLogs\data\derived\global"
$OUT    = "C:\workplace\JiraAndLogs\data\published"

$import = "$TOOLS\mongoimport.exe"
$dump   = "$TOOLS\mongodump.exe"

function Import-Collection($db, $coll, $file) {
    if (-not (Test-Path $file)) { Write-Warning "SKIP (not found): $file"; return }
    Write-Host "  importing $coll ..."
    & $import --db $db --collection $coll --file $file --drop --quiet
    if ($LASTEXITCODE -ne 0) { throw "mongoimport failed for $coll in $db" }
}

function Export-Archive($db, $archivePath) {
    Write-Host "  dumping $db -> $archivePath"
    & $dump --db $db --archive=$archivePath --gzip
    if ($LASTEXITCODE -ne 0) { throw "mongodump failed for $db" }
}

function Drop-Database($db) {
    # mongosh not required — drop temp DBs via Compass: right-click DB -> Drop Database
    Write-Host "  (temp DB '$db' left in place — drop via Compass if needed)"
}

# ── Online Boutique ────────────────────────────────────────────────────────────
function Package-OB {
    $db  = "ob_v1"
    $dir = "$GLOBAL\2026-05-25-dataset-v5-large-global"
    Write-Host "`n[Online Boutique] importing into $db ..."
    Import-Collection $db "windows"    "$dir\global-triage-examples.jsonl"
    Import-Collection $db "memory"     "$dir\jira-memory-corpus.jsonl"
    Import-Collection $db "matchings"  "$dir\window-memory-matchings.jsonl"
    Import-Collection $db "kg_memory"  "$dir\v2_kg_extractions\all_extractions.jsonl"
    Import-Collection $db "kg_windows" "$dir\v2_kg_extractions_windows\all_extractions.jsonl"
    Export-Archive $db "$OUT\online-boutique\ob_v1.archive.gz"
    Drop-Database $db
    Write-Host "[Online Boutique] done."
}

# ── OTel Demo ─────────────────────────────────────────────────────────────────
function Package-OTel {
    $db  = "otel_demo_v1"
    $dir = "$GLOBAL\2026-06-09-otel-demo-v1-global"
    Write-Host "`n[OTel Demo] importing into $db ..."
    Import-Collection $db "windows"    "$dir\global-triage-examples.jsonl"
    Import-Collection $db "memory"     "$dir\jira-memory-corpus.jsonl"
    Import-Collection $db "matchings"  "$dir\window-memory-matchings.jsonl"
    Import-Collection $db "kg_memory"  "$dir\v2_kg_extractions\all_extractions.jsonl"
    Import-Collection $db "kg_windows" "$dir\v2_kg_extractions_windows\all_extractions.jsonl"
    Export-Archive $db "$OUT\otel-demo\otel_demo_v1.archive.gz"
    Drop-Database $db
    Write-Host "[OTel Demo] done."
}

# ── WoL v2 ────────────────────────────────────────────────────────────────────
function Package-WoL {
    $db  = "wol_v2"
    $dir = "$GLOBAL\2026-06-15-wol-real-v2-global"
    Write-Host "`n[WoL v2] importing into $db ..."
    Import-Collection $db "windows"           "$dir\global-triage-examples.jsonl"
    Import-Collection $db "memory"            "$dir\jira-memory-corpus.jsonl"
    Import-Collection $db "matchings"         "$dir\window-memory-matchings.jsonl"
    Import-Collection $db "matchings_strong"  "$dir\window-memory-matchings-strong.jsonl"
    Import-Collection $db "kg_memory"         "$dir\v2_kg_extractions\all_extractions.jsonl"
    Import-Collection $db "kg_windows"        "$dir\v2_kg_extractions_windows\all_extractions.jsonl"
    Export-Archive $db "$OUT\wol-v2\wol_v2.archive.gz"
    Drop-Database $db
    Write-Host "[WoL v2] done."
}

switch ($Dataset) {
    "ob"   { Package-OB }
    "otel" { Package-OTel }
    "wol"  { Package-WoL }
    "all"  { Package-OB; Package-OTel; Package-WoL }
    default { Write-Error "Unknown dataset: $Dataset. Use ob | otel | wol | all" }
}

Write-Host "`nAll archives written to $OUT"
