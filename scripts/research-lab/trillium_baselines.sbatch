#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=icse-baselines
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --time=04:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Prior-art retrieval baselines (review.md gap #1) for all three datasets.
# No Neo4j needed. GPU for dense/cross-encoder embeddings. Writes to the clean
# publishable paper-results/baselines/ tree. Submit from trig-login01.
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"
cd "$REPO"; mkdir -p logs

JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/baselines_${JOBID}.log"
ln -sf "$LOGFILE" "${REPO}/logs/baselines.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

echo "=== ICSE baselines on $(hostname) — $(date -u +%FT%TZ) ==="
nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1

# dataset:humanized-subdir  ->  paper-results dataset label
declare -A SUB=(
  [2026-05-25-dataset-v5-large-global]=bulk-20260531
  [2026-06-09-otel-demo-v1-global]=bulk-20260531
  [2026-06-17-wol-real-v3-global]=bulk-20260617
)
declare -A LABEL=(
  [2026-05-25-dataset-v5-large-global]=online-boutique
  [2026-06-09-otel-demo-v1-global]=otel-demo
  [2026-06-17-wol-real-v3-global]=wol-v3
)
# method -> baselines subdir
declare -A FAM=( [bge]=sota-dense [e5]=sota-dense [mpnet]=sota-dense [tfidf]=tfidf [ce]=cross-encoder-rerank )

GLOBAL_ROOT="data/derived/global"
for dsid in 2026-06-09-otel-demo-v1-global 2026-05-25-dataset-v5-large-global 2026-06-17-wol-real-v3-global; do
  for method in tfidf mpnet e5 bge ce; do
    out="paper-results/baselines/${FAM[$method]}/${LABEL[$dsid]}"
    echo "--- [$dsid] method=$method -> $out ---"
    python -u scripts/research-lab/run_baseline_retrievers.py \
      --global-dir "$GLOBAL_ROOT/$dsid" \
      --humanized-subdir "${SUB[$dsid]}" \
      --method "$method" --out-dir "$out" || echo "FAILED: $dsid/$method"
  done
done

# provenance stub
git -C "$REPO" rev-parse HEAD > paper-results/provenance/git-sha-baselines.txt 2>/dev/null || true
echo "=== baselines done — $(date -u +%FT%TZ) ==="
