#!/usr/bin/env bash
# Bundle the large (gitignored) artifacts into release archives + checksums.
# Usage: bash scripts/research-lab/make_release_archives.sh [OUTDIR]
# Default OUTDIR: /scratch/$USER/release
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"
OUT="${1:-/scratch/${USER}/release}"; mkdir -p "$OUT"
GROOT="data/derived/global"
# zstd if available (fast, good ratio), else gzip
if command -v zstd >/dev/null 2>&1; then C=(--zstd); EXT="tar.zst"; else C=(-z); EXT="tar.gz"; fi
echo "=== release archives -> $OUT (ext=$EXT) ==="

declare -A DS=( [online-boutique]=2026-05-25-dataset-v5-large-global
                [otel-demo]=2026-06-09-otel-demo-v1-global
                [wol-v3]=2026-06-17-wol-real-v3-global )
for label in online-boutique otel-demo wol-v3; do
  d="$GROOT/${DS[$label]}"
  [[ -d "$d" ]] || { echo "skip $label (missing $d)"; continue; }
  echo "[archive] dataset $label ..."
  tar "${C[@]}" -cf "$OUT/dataset-${label}.${EXT}" -C "$GROOT" "${DS[$label]}"
done

# paper-results bulky bits: predictions, traces, ablation per-cell reports
echo "[archive] paper-results predictions + traces ..."
find paper-results \( -name "*-predictions.jsonl" -o -name "*-scores.jsonl" \
  -o -path "*/traces/*" -o -path "*-cells/*" \) -print0 2>/dev/null \
  | tar "${C[@]}" -cf "$OUT/paper-results-predictions-traces.${EXT}" --null -T -

echo "[checksums] SHA256SUMS.txt ..."
( cd "$OUT" && sha256sum ./*."${EXT}" > SHA256SUMS.txt )
echo "=== done ==="; ls -lh "$OUT"/*."${EXT}" "$OUT"/SHA256SUMS.txt 2>/dev/null | awk '{print $5"\t"$NF}'
