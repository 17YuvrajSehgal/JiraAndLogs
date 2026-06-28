#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=kg-ablation
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=08:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# KG-usefulness ablation: Hybrid-RRF WITHOUT the graph retriever (SPLADE +
# BiEncoder only). The WITH-graph result is the cascade-panel hybrid already in
# paper-results/retrieval-cascades/<label>/. Delta = with - without quantifies
# the KG's marginal contribution. No Neo4j needed.
#
# Env (--export): DSID, LABEL, HSUB   (same meaning as cascade panel)
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"; mkdir -p logs
: "${DSID:?}"; : "${LABEL:?}"; : "${HSUB:?}"
GLOBAL_DIR="data/derived/global/${DSID}"
OUT="paper-results/kg-usefulness/${LABEL}"; mkdir -p "$OUT"

JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/kgabl_${LABEL}_${JOBID}.log"; ln -sf "$LOGFILE" "${REPO}/logs/kgabl_${LABEL}.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}" OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-24}"
export HYBRID_TRIAGE_SCORE_SAMPLE=5000   # subsample train/val triage scoring (test Hit@K unaffected) — avoids the score_train timeout
export TOKENIZERS_PARALLELISM=false

echo "=== KG-ablation [$LABEL] (hybrid --skip-graph) on $(hostname) $(date -u +%FT%TZ) ==="
python -u scripts/research-lab/run_hybrid_rrf_wol_mode3.py \
  --global-dir "$GLOBAL_DIR" --out-dir "$OUT" \
  --humanized-subdir "$HSUB" --biencoder-finetune-epochs 5 --skip-graph \
  || { echo "FAILED kg-ablation"; exit 1; }

git -C "$REPO" rev-parse HEAD > "$OUT/git-sha.txt" 2>/dev/null || true
echo "=== KG-ablation [$LABEL] done $(date -u +%FT%TZ) ==="
ls -1 "$OUT"/*-mode3-results.json 2>/dev/null
