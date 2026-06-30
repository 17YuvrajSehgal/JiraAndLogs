#!/usr/bin/env bash
#SBATCH --account=def-anonymous
#SBATCH --job-name=triage-lb
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=05:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Triage-quality leaderboard (PR-AUC / ECE / precision@FPR) via the comparison
# harness, OFFLINE-SAFE pipelines only (no nomic/LM-Studio, no neo4j). Fresh,
# seed-42, correct splits -> paper-results/triage-leaderboard/<LABEL>/.
# Env (--export): DSID, LABEL
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"; cd "$REPO"; mkdir -p logs
: "${DSID:?}"; : "${LABEL:?}"
GLOBAL_DIR="data/derived/global/${DSID}"
OUT="paper-results/triage-leaderboard/${LABEL}"; mkdir -p "$OUT"
JOBID="${SLURM_JOB_ID:-manual}"; LOGFILE="${REPO}/logs/triagelb_${LABEL}_${JOBID}.log"
ln -sf "$LOGFILE" "${REPO}/logs/triagelb_${LABEL}.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1
module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-24}"
echo "=== triage-leaderboard [$LABEL] on $(hostname) $(date -u +%FT%TZ) ==="
python -u -m comparison.cli --global-dir "$GLOBAL_DIR" \
  --pipelines "${PIPELINES:-hgb,rf,logistic_sklearn,bm25_retrieval,bi_encoder_hybrid}" \
  --no-ensemble --n-bootstrap 1000 --target-fpr 0.05 \
  --runs-root "/scratch/${USER}/cmp-runs/${LABEL}" \
  --output-dir "$OUT" || { echo "FAILED triage-leaderboard"; exit 1; }
git -C "$REPO" rev-parse HEAD > "$OUT/git-sha.txt" 2>/dev/null || true
echo "=== triage-leaderboard [$LABEL] done $(date -u +%FT%TZ) ==="
ls -1 "$OUT"
