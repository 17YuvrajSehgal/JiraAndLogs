#!/usr/bin/env bash
#SBATCH --job-name=v2-extrinsic
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --time=06:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Task #25 -- extrinsic RCA evaluation, both steps.
# Pre-registration: icse-review-results/08-extrinsic-rca-eval.md
# 2,000 generations (~220 tok each) + 2,000 judgements on one H100.
#   sbatch --account=def-naser2 scripts/v2/trillium_v2_extrinsic.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || exit 1
mkdir -p logs
module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false

python - <<'PY' || { echo "!! Qwen2.5-7B not cached; run fetch_models.sh on a login node"; exit 1; }
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen2.5-7B-Instruct", local_files_only=True)
print("  model cached OK")
PY

OUT="paper-results-v2/extrinsic-rca"
if [[ ! -s "$OUT/generations.jsonl" ]]; then
  python scripts/v2/extrinsic_rca_generate.py \
      --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
      --predictions paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl \
      --out-dir "$OUT" --n "${V2_EXTRINSIC_N:-500}" || exit 1
else
  echo "generations already present -- skipping to judging"
fi
python scripts/v2/extrinsic_rca_judge.py --run-dir "$OUT"
echo "=== done: $(date -Is) ==="
