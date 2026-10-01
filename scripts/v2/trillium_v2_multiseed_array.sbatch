#!/usr/bin/env bash
#SBATCH --job-name=v2-seed
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=04:00:00
#SBATCH --array=0-14
#SBATCH --output=logs/slurm-%x-%A_%a.out
# ---------------------------------------------------------------------------
# Task #8 as a JOB ARRAY -- one task per (dataset, seed) pair.
#
# The monolithic version asked for 20h in a partition with ~1,190 jobs pending
# against ~150 running, on a 0.035 fairshare. A single long job backfills badly;
# fifteen 4h tasks slot into gaps and start far sooner, and a task that dies
# costs one seed instead of the whole grid.
#
# Index -> (dataset, seed):
#   0-4   otel-demo        seeds 42 1 2 3 4
#   5-9   online-boutique  seeds 42 1 2 3 4
#   10-14 wol-v3           seeds 42 1 2 3 4
#
# Seeds 42/1/2 already exist for the two telemetry datasets in paper-results/
# robustness/; those tasks detect the existing output and exit immediately, so
# running the full array is cheap and keeps every seed under one provenance.
#
#   sbatch --account=<rap> scripts/v2/trillium_v2_multiseed_array.sbatch
#   # a subset:
#   sbatch --account=<rap> --array=10-14 scripts/v2/trillium_v2_multiseed_array.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
mkdir -p logs

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}" TOKENIZERS_PARALLELISM=false

DATASETS=(otel-demo online-boutique wol-v3)
SEEDS=(42 1 2 3 4)
GLOBALS=(2026-06-09-otel-demo-v1-global 2026-05-25-dataset-v5-large-global 2026-06-17-wol-real-v3-global)
HSUBS=(bulk-20260531 bulk-20260531 bulk-20260617)

IDX="${SLURM_ARRAY_TASK_ID:-0}"
D=$(( IDX / 5 ))
S=$(( IDX % 5 ))
label="${DATASETS[$D]}"; seed="${SEEDS[$S]}"
gdir="data/derived/global/${GLOBALS[$D]}"; hsub="${HSUBS[$D]}"
out="paper-results-v2/multiseed/${label}/seed${seed}"

echo "=== array task $IDX -> ${label} seed=${seed} ==="
echo "  node:   $(hostname)   $(date -Is)"
echo "  commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "  global: $gdir"

if [[ -f "$out/biencoder-mode3-results.json" ]]; then
  echo "  already complete -- nothing to do"; exit 0
fi
if [[ ! -d "$gdir" ]]; then
  echo "!! missing dataset $gdir"; exit 1
fi

# Fail loudly on a cold cache rather than letting it read as a seed failure.
python - <<'PY' || exit 1
import os, sys
from huggingface_hub import snapshot_download
try:
    snapshot_download("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)
    print("  HF cache OK")
except Exception as e:
    print(f"!! HF cache cold at {os.environ.get('HF_HOME')}: {type(e).__name__}")
    print("!! run scripts/v2/fetch_models.sh on a login node")
    sys.exit(1)
PY

mkdir -p "$out"
python scripts/research-lab/run_biencoder_wol_mode3.py \
    --global-dir "$gdir" \
    --humanized-subdir "$hsub" \
    --out-dir "$out" \
    --seed "$seed"
rc=$?
echo "=== task $IDX (${label} seed=${seed}) exit=$rc  $(date -Is) ==="
exit $rc
