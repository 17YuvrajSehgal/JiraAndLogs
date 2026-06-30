#!/usr/bin/env bash
#SBATCH --account=def-anonymous
#SBATCH --job-name=gold-judge
#SBATCH --partition=compute
#SBATCH --nodes=1 --ntasks=1 --gpus-per-node=1 --cpus-per-task=12 --time=02:00:00
#SBATCH --output=logs/slurm-%x-%j.out
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"; mkdir -p logs
JOBID="${SLURM_JOB_ID:-manual}"; LOGFILE="${REPO}/logs/goldjudge_${JOBID}.log"; ln -sf "$LOGFILE" logs/gold_judge.log
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1
module load python/3.12 arrow/21.0.0; source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
echo "=== gold-judge $(hostname) $(date -u +%FT%TZ) ==="
declare -A SUB=( [online-boutique]="2026-05-25-dataset-v5-large-global bulk-20260531" \
                 [otel-demo]="2026-06-09-otel-demo-v1-global bulk-20260531" \
                 [wol-v3]="2026-06-17-wol-real-v3-global bulk-20260617" )
for label in otel-demo online-boutique wol-v3; do
  set -- ${SUB[$label]}
  python -u scripts/research-lab/run_llm_judge_gold.py --global-dir "data/derived/global/$1" \
    --humanized-subdir "$2" --out-dir "paper-results/gold-validation/$label" --limit 300 --seed 42 || echo "FAILED $label"
done
echo "=== gold-judge done $(date -u +%FT%TZ) ==="
