#!/usr/bin/env bash
#SBATCH --job-name=v2-judge
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --time=02:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Task #6 -- LLM-as-judge with hard negatives, judging the system's actual top-1.
# Needs Qwen2.5-7B-Instruct in the HF cache; fetch_models.sh must have been run
# with it included (see V2_JUDGE_MODEL there).
#   sbatch --account=<rap> scripts/v2/trillium_v2_judge.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
mkdir -p logs
module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false

python - <<'PY' || { echo "!! Qwen2.5-7B not cached; run fetch_models.sh on a login node"; exit 1; }
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen2.5-7B-Instruct", local_files_only=True)
print("  judge model cached OK")
PY

python scripts/v2/llm_judge_hard_negatives.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --humanized-subdir bulk-20260617 \
    --predictions paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl \
    --out-dir paper-results-v2/gold-validation/wol-v3 \
    --limit "${V2_JUDGE_LIMIT:-300}"
echo "=== done: $(date -Is) ==="
