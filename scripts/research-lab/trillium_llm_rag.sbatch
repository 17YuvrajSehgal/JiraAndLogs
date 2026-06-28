#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=llm-rag
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --time=03:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# LLM-RAG baseline (review.md gap #2): retrieve-then-Qwen-rerank over the dense
# (bge) top-k candidates, 500-window subset per dataset -> paper-results/baselines/llm-rag/.
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"; mkdir -p logs
JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/llmrag_${JOBID}.log"; ln -sf "$LOGFILE" "${REPO}/logs/llm_rag.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1
module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
echo "=== LLM-RAG on $(hostname) $(date -u +%FT%TZ) ==="
declare -A SUB=( [online-boutique]="2026-05-25-dataset-v5-large-global bulk-20260531" \
                 [otel-demo]="2026-06-09-otel-demo-v1-global bulk-20260531" \
                 [wol-v3]="2026-06-17-wol-real-v3-global bulk-20260617" )
for label in otel-demo online-boutique wol-v3; do
  set -- ${SUB[$label]}; dsid=$1; hsub=$2
  cand="paper-results/baselines/sota-dense/$label/bge-predictions.jsonl"
  [[ -f "$cand" ]] || { echo "SKIP $label — no candidates ($cand)"; continue; }
  echo "--- LLM-RAG $label ---"
  python -u scripts/research-lab/run_llm_rag.py --global-dir "data/derived/global/$dsid" \
    --humanized-subdir "$hsub" --candidates "$cand" \
    --out-dir "paper-results/baselines/llm-rag/$label" --limit 500 --seed 42 || echo "FAILED $label"
done
echo "=== LLM-RAG done $(date -u +%FT%TZ) ==="
