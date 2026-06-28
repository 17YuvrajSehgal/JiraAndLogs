#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=robustness
#SBATCH --partition=compute
#SBATCH --nodes=1 --ntasks=1 --gpus-per-node=1 --cpus-per-task=24 --time=03:00:00
#SBATCH --output=logs/slurm-%x-%j.out
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"; mkdir -p logs
JOBID="${SLURM_JOB_ID:-manual}"; LOGFILE="${REPO}/logs/robustness_${JOBID}.log"; ln -sf "$LOGFILE" logs/robustness.log
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1
module load python/3.12 arrow/21.0.0; source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}" TOKENIZERS_PARALLELISM=false
echo "=== robustness multi-seed biencoder $(hostname) $(date -u +%FT%TZ) ==="
declare -A SUB=( [online-boutique]="2026-05-25-dataset-v5-large-global bulk-20260531" \
                 [otel-demo]="2026-06-09-otel-demo-v1-global bulk-20260531" )
for label in otel-demo online-boutique; do
  set -- ${SUB[$label]}
  for seed in 1 2; do
    out="paper-results/robustness/multiseed/$label/seed$seed"; mkdir -p "$out"
    echo "--- biencoder $label seed=$seed ---"
    python -u scripts/research-lab/run_biencoder_wol_mode3.py --global-dir "data/derived/global/$1" \
      --humanized-subdir "$2" --out-dir "$out" --seed $seed || echo "FAILED $label seed$seed"
  done
done
echo "=== robustness done $(date -u +%FT%TZ) ==="
