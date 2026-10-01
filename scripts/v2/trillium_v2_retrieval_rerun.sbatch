#!/usr/bin/env bash
#SBATCH --job-name=v2-retrieval-rerun
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --time=06:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# v2 retrieval re-run on World of Logs. Closes two gaps in one job:
#
#   #7  TF-IDF and MPNet report strict-relation metrics in their result JSONs
#       but their per-query predictions were not retained, so they could not
#       enter the paired-bootstrap panel. Re-running regenerates them.
#
#   #14 No run persisted per-candidate retrieval scores, so the escalation
#       policy had no top-1/top-2 margin feature -- the most likely reason it
#       failed to beat a plain confidence threshold. run_baseline_retrievers.py
#       now writes `candidate_scores` and `score_margin_top1_top2`.
#
# Submit the account via SBATCH_ACCOUNT rather than hardcoding it; the committed
# scripts carry an anonymized placeholder for double-blind review.
#   sbatch --account=<your-rap> scripts/v2/trillium_v2_retrieval_rerun.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
mkdir -p logs

JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/v2_retrieval_${JOBID}.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
# /project is NOT purged like /scratch; see trillium_v2_multiseed.sbatch.
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

GLOBAL="data/derived/global/2026-06-17-wol-real-v3-global"
HSUB="bulk-20260617"
OUT="paper-results-v2/baselines/wol-v3"
mkdir -p "$OUT"

# Only the HF-backed methods need the cache; tfidf is pure sklearn. Check once
# up front so a setup error is not mistaken for a modelling result.
if [[ ! -d "$HF_HOME" ]]; then
  echo "!! HF_HOME missing: $HF_HOME -- run scripts/v2/fetch_models.sh on a login node"
  exit 1
fi

# Skip methods whose predictions already exist, so a partially-completed run
# can be resumed without redoing finished work.
METHODS="${V2_METHODS:-tfidf mpnet bge e5 ce}"

echo "=== v2 retrieval re-run ==="
echo "  repo:   $REPO"
echo "  commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "  global: $GLOBAL"
echo "  node:   $(hostname)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1

# The two methods whose predictions are missing from the paired panel, plus the
# three already present -- re-run together so every row of the strict-relation
# table comes from one commit with identical corpus and visibility rules.
for METHOD in $METHODS; do
  echo ""
  if [[ -s "$OUT/${METHOD}-predictions.jsonl" ]]; then
    echo "--- [$METHOD] predictions already present, skipping ---"
    continue
  fi
  echo "--- [$METHOD] ---"
  python scripts/research-lab/run_baseline_retrievers.py \
      --global-dir "$GLOBAL" \
      --humanized-subdir "$HSUB" \
      --method "$METHOD" \
      --out-dir "$OUT" \
    || echo "!! $METHOD FAILED (continuing)"
done

echo ""
echo "=== verifying score persistence (the #14 rescue depends on it) ==="
python - <<'PY'
import json, pathlib
out = pathlib.Path("paper-results-v2/baselines/wol-v3")
for p in sorted(out.glob("*-predictions.jsonl")):
    with p.open(encoding="utf-8") as fh:
        d = json.loads(fh.readline())
    has = d.get("candidate_scores") is not None
    marg = d.get("score_margin_top1_top2")
    print(f"  {p.name:<28} scores={'YES' if has else 'NO '}  "
          f"margin={'%.4f' % marg if marg is not None else 'None'}")
PY

echo ""
echo "=== done: $(date -Is) ==="
