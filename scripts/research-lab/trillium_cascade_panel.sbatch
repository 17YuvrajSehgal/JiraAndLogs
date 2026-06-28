#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=cascade-panel
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=06:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Retrieval cascade panel (BiEncoder, BM25, KG, Hybrid-RRF) for ONE dataset,
# on the C1-fixed split, into the clean paper-results/ tree. Each job runs its
# OWN Apptainer Neo4j (own data dir) so datasets run in parallel on separate
# nodes with isolated graphs.
#
# Required env (pass via --export):
#   DSID  = global dataset dir name (under data/derived/global)
#   LABEL = paper-results label (online-boutique | otel-demo | wol-v3)
#   HSUB  = humanized subdir (bulk-20260531 for OB/OTel, bulk-20260617 for WoL)
# Submit (from trig-login01), e.g.:
#   sbatch --export=ALL,DSID=2026-06-09-otel-demo-v1-global,LABEL=otel-demo,HSUB=bulk-20260531 \
#          scripts/research-lab/trillium_cascade_panel.sbatch
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"
cd "$REPO"; mkdir -p logs

: "${DSID:?set DSID}"; : "${LABEL:?set LABEL}"; : "${HSUB:?set HSUB}"
GLOBAL_DIR="data/derived/global/${DSID}"
OUT="paper-results/retrieval-cascades/${LABEL}"
mkdir -p "$OUT"

JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/cascade_${LABEL}_${JOBID}.log"
ln -sf "$LOGFILE" "${REPO}/logs/cascade_${LABEL}.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-24}" TOKENIZERS_PARALLELISM=false
export NEO4J_URI="neo4j://127.0.0.1:7687" NEO4J_USERNAME="neo4j" NEO4J_PASSWORD="123456789"
export NEO4J_DATABASE="neo4j" NEO4J_BASE="${NEO4J_BASE:-/scratch/${USER}/neo4j-${LABEL}}"
NEO4J_SH="deploy/research-lab/neo4j_apptainer.sh"

echo "=== cascade panel [$LABEL] dsid=$DSID hsub=$HSUB on $(hostname) $(date -u +%FT%TZ) ==="
nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1

# fail-fast preflight: required inputs must exist
for f in "$GLOBAL_DIR/global-triage-examples.jsonl" \
         "$GLOBAL_DIR/jira-shadow-humanized-v2/$HSUB/timeline.jsonl" \
         "$GLOBAL_DIR/v2_kg_extractions/all_extractions.jsonl"; do
  [[ -f "$f" ]] || { echo "FATAL missing required input: $f" >&2; exit 1; }
done

cleanup() { bash "$NEO4J_SH" stop || true; }
trap cleanup EXIT
bash "$NEO4J_SH" start || { echo "FATAL neo4j failed" >&2; exit 1; }

# load this dataset's graph into the single 'neo4j' DB (idempotent: skip if loaded)
n_inc=$(python - <<'PY' 2>/dev/null
from neo4j import GraphDatabase
try:
    d=GraphDatabase.driver("neo4j://127.0.0.1:7687",auth=("neo4j","123456789"))
    with d.session() as s: print(s.run("MATCH (n:Incident) RETURN count(n) c").single()["c"])
    d.close()
except Exception: print(0)
PY
)
if [[ "${n_inc:-0}" -le 0 || "${RELOAD_GRAPH:-0}" == "1" ]]; then
  echo "[graph] loading $DSID graph ..."
  python -u -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir "$GLOBAL_DIR" --source llm --database neo4j
else
  echo "[graph] $n_inc Incident nodes present — skipping reload"
fi

COMMON=(--global-dir "$GLOBAL_DIR" --out-dir "$OUT")
HUM=(--humanized-subdir "$HSUB")
CASCADES="${CASCADES:-biencoder bm25 kg hybrid}"   # subset selector
echo "[panel] running cascades: $CASCADES"

case " $CASCADES " in *" biencoder "*)
  echo "### BiEncoder"; python -u scripts/research-lab/run_biencoder_wol_mode3.py "${COMMON[@]}" "${HUM[@]}" || echo "FAILED biencoder";; esac
case " $CASCADES " in *" bm25 "*)
  echo "### BM25"; python -u scripts/research-lab/run_bm25_wol_mode3.py "${COMMON[@]}" || echo "FAILED bm25"
  echo "### BM25-synth"; python -u scripts/research-lab/synthesize_bm25_results.py --global-dir "$GLOBAL_DIR" --out-dir "$OUT" || echo "FAILED bm25-synth";; esac
case " $CASCADES " in *" kg "*)
  echo "### KG"; python -u scripts/research-lab/run_kg_retrieval_wol_mode3.py "${COMMON[@]}" "${HUM[@]}" || echo "FAILED kg";; esac
case " $CASCADES " in *" hybrid "*)
  echo "### Hybrid-RRF (epochs=5)"; python -u scripts/research-lab/run_hybrid_rrf_wol_mode3.py "${COMMON[@]}" "${HUM[@]}" --biencoder-finetune-epochs 5 || echo "FAILED hybrid";; esac

git -C "$REPO" rev-parse HEAD > "$OUT/git-sha.txt" 2>/dev/null || true
echo "=== cascade panel [$LABEL] done $(date -u +%FT%TZ) ==="
echo "results in $OUT:"; ls -1 "$OUT"/*-mode3-results.json 2>/dev/null
