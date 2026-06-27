#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=wol-v3-hybrid-rrf
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=23:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# WoL v3 Hybrid-RRF cascade on Trillium GPU subcluster (submit from trig-login01).
#
# Pipeline = SPLADE + fine-tuned BiEncoder + Neo4j graph, fused with RRF.
# Mirrors the local PowerShell command but adapted for the cluster:
#   * 1x H100 (SPLADE/BiEncoder run on GPU) + 24 CPU cores from a shared node
#   * Alliance python/venv + offline HuggingFace cache (compute nodes: no net)
#   * BM25 hard-negative mining parallelised across all allocated cores
#     (BIENC_BM25_JOBS) — the step that took ~20h single-threaded locally
#   * Neo4j Community stood up in-job via Apptainer (no Docker on Trillium)
#
# For maximum BM25 cores (whole node, 96 cores + 4 GPUs) swap the resource
# lines for:  --partition=compute_full_node  --cpus-per-task=96.
#
# Submit:   sbatch scripts/research-lab/trillium_hybrid_rrf.sbatch
# Watch:    tail -f logs/v3_hybrid_rrf.log         (stable symlink, live)
# ---------------------------------------------------------------------------
set -uo pipefail

# ---- paths / config ----
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"
GLOBAL_DIR="data/derived/global/2026-06-17-wol-real-v3-global"
OUT_DIR="${GLOBAL_DIR}/tch-lite-refit"
HUMANIZED_SUB="bulk-20260617"
BIENC_EPOCHS=3

cd "$REPO"
mkdir -p logs "$OUT_DIR"

# ---- live logging: mirror EVERYTHING (echoes, neo4j, reload, pipeline
# heartbeats) to one unbuffered, job-stamped file, plus a stable symlink you
# can always `tail -f`. The Slurm --output file also gets the same stream.
JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/v3_hybrid_rrf_${JOBID}.log"
ln -sf "$LOGFILE" "${REPO}/logs/v3_hybrid_rrf.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1
echo ">>> live log: $LOGFILE"
echo ">>> stable:   ${REPO}/logs/v3_hybrid_rrf.log  (tail -f this)"

# ---- environment ----
module load python/3.12
source .venv/bin/activate

export PYTHONPATH="src"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# Offline HuggingFace (SPLADE + MiniLM pre-cached on the login node).
export HF_HOME="/scratch/${USER}/hf_cache"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# Parallelise BM25 hard-negative mining across all allocated cores.
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-24}"
export TOKENIZERS_PARALLELISM=false

# Neo4j (Apptainer) — single DB "neo4j"; force reload into it so the pipeline
# (which connects to the default db) and the loader agree on Community Edition.
export NEO4J_URI="neo4j://127.0.0.1:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="123456789"
export NEO4J_DATABASE="neo4j"
export NEO4J_BASE="/scratch/${USER}/neo4j-v3"
NEO4J_SH="deploy/research-lab/neo4j_apptainer.sh"

echo "=== WoL v3 Hybrid-RRF (1x H100) on $(hostname) ==="
echo "global-dir=$GLOBAL_DIR  out=$OUT_DIR  bienc_epochs=$BIENC_EPOCHS"
echo "BIENC_BM25_JOBS=$BIENC_BM25_JOBS  HF_HUB_OFFLINE=$HF_HUB_OFFLINE"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1
echo "started: $(date -u +%FT%TZ)"

# ---- start Neo4j; guarantee teardown on any exit ----
cleanup() { bash "$NEO4J_SH" stop || true; }
trap cleanup EXIT
bash "$NEO4J_SH" start || { echo "FATAL: neo4j failed to start" >&2; exit 1; }

# ---- (re)load the v3 graph into the 'neo4j' DB ----
# Skip if already loaded (Incident count > 0) AND RELOAD_GRAPH != 1.
NEED_RELOAD=1
if [[ "${RELOAD_GRAPH:-0}" != "1" ]]; then
    n_inc=$(python - <<'PY' 2>/dev/null
from neo4j import GraphDatabase
try:
    d=GraphDatabase.driver("neo4j://127.0.0.1:7687",auth=("neo4j","123456789"))
    with d.session() as s:
        print(s.run("MATCH (n:Incident) RETURN count(n) AS c").single()["c"])
    d.close()
except Exception:
    print(0)
PY
)
    if [[ "${n_inc:-0}" -gt 0 ]]; then
        echo "[graph] Neo4j already has ${n_inc} Incident nodes — skipping reload (set RELOAD_GRAPH=1 to force)"
        NEED_RELOAD=0
    fi
fi

if [[ "$NEED_RELOAD" == "1" ]]; then
    echo "[graph] reloading v3 graph into DB '$NEO4J_DATABASE' (this is the ~50 min step) ..."
    # Output already streams to the main live log via the exec tee above.
    python -u -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
        --global-dir "$GLOBAL_DIR" --source llm --database neo4j
    echo "[graph] reload finished: $(date -u +%FT%TZ)"
fi

# ---- run the Hybrid-RRF cascade ----
# The run script prints a "[hybrid-rrf:heartbeat]" line every 30s so the live
# log never goes silent during the long fine-tune / scoring loops.
echo "[hybrid] launching cascade ... (tail -f logs/v3_hybrid_rrf.log)"
python -u scripts/research-lab/run_hybrid_rrf_wol_mode3.py \
    --global-dir "$GLOBAL_DIR" \
    --out-dir "$OUT_DIR" \
    --humanized-subdir "$HUMANIZED_SUB" \
    --biencoder-finetune-epochs "$BIENC_EPOCHS"
rc=$?

echo "finished: $(date -u +%FT%TZ)  exit=$rc"
echo "results: $OUT_DIR/hybrid-rrf-mode3-results.json"
exit "$rc"
