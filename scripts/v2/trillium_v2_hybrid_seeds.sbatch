#!/usr/bin/env bash
#SBATCH --job-name=v2-hyb
#SBATCH --partition=compute
#SBATCH --nodes=1 --ntasks=1 --gpus-per-node=1 --cpus-per-task=24
#SBATCH --time=05:00:00
#SBATCH --array=0-4
#SBATCH --output=logs/slurm-%x-%A_%a.out
# ---------------------------------------------------------------------------
# Hybrid fusion across the SAME five seeds as the bi-encoder, on World of Logs.
#
# Why this is needed: the 5-seed bi-encoder run showed WoL Hit@5 varies
# 0.898-0.946 (sd 0.0196) -- the largest seed variance of the three datasets --
# and the published single-seed 0.905 sits near the LOW end of that range. The
# headline "+0.065 Hit@5 for fusion over the dense retriever" was computed
# against that single low draw, with a query-bootstrap CI that ignored seed
# variance entirely.
#
# Hybrid embeds the same fine-tuned bi-encoder, so it presumably inherits that
# variance. Comparing a single hybrid run against a 5-seed bi-encoder mean would
# be just as wrong in the other direction. This runs hybrid on seeds 42,1,2,3,4
# so the comparison is seed-matched and the margin can be stated with a
# seed-aware interval.
#
#   sbatch --account=<rap> scripts/v2/trillium_v2_hybrid_seeds.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || exit 1
mkdir -p logs
module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}" TOKENIZERS_PARALLELISM=false

SEEDS=(42 1 2 3 4)
seed="${SEEDS[${SLURM_ARRAY_TASK_ID:-0}]}"
out="paper-results-v2/multiseed-hybrid/wol-v3/seed${seed}"
echo "=== hybrid WoL seed=${seed}  node=$(hostname)  $(date -Is) ==="
if [[ -f "$out/hybrid-rrf-mode3-results.json" ]]; then
  echo "  already complete"; exit 0
fi
mkdir -p "$out"
python scripts/research-lab/run_hybrid_rrf_wol_mode3.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --humanized-subdir bulk-20260617 \
    --out-dir "$out" \
    --seed "$seed"
rc=$?
echo "=== hybrid seed=${seed} exit=$rc  $(date -Is) ==="
exit $rc
