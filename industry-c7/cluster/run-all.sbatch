#!/bin/bash
# Serve the model AND run the agents in ONE job, on ONE node.
#
# Why: every earlier run drove the agents from the laptop over nested ssh.
# The laptop had to stay awake for the whole run, and the transport capped
# concurrency at the control master's MaxSessions (~8 workers) while the
# server sat at 32 sequences. Measured: local tool work is 3.0 s of a 325 s
# instance, about 1%, so neither the GPU nor the laptop was the limit --
# ssh was. Here the agent talks to http://localhost:8000 on its own node.
#
# ONE ARM PER JOB by default. Two 3 h jobs backfill far sooner than one 6 h
# job, and the arms are independent, so there is nothing to gain by pairing
# them. Set ARMS to run several in one allocation.
#
# RESUMABLE, and that is the point of the short walltime: run_agent.py
# keeps only rows that SUCCEEDED and skips ids already present, so a job
# killed at its time limit is continued by resubmitting the same command.
# judge_explanations.py --rate skips ids already in its verdict file the
# same way. Nothing is repeated and nothing is lost.
#
# Usage (from a GPU login node, in $BASE):
#   ARMS=locagent sbatch -t 3:00:00 JiraAndLogs/industry-c7/cluster/run-all.sbatch
#   ARMS=cosil    sbatch -t 3:00:00 JiraAndLogs/industry-c7/cluster/run-all.sbatch
#   ARMS=         STAGES=judge sbatch -t 1:00:00 ... run-all.sbatch
# Resume after a timeout: submit the identical command again.
#
# Submit it with cluster/submit.sh, which supplies the per-cluster flags:
# Trillium wants --account=def-naser2 and --gpus-per-node=1 and REJECTS
# --mem; Nibi wants --account=def-naser2_gpu, --gpus-per-node=h100:1 and
# --mem=120G. Those cannot both live in #SBATCH lines here, so only the
# universal ones do.
#
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --time=03:00:00
#SBATCH --job-name=c7-arm
#SBATCH --output=%x-%j.out

set -uo pipefail
S=/scratch/yuvraj17
BASE=${C7_BASE:-$S/JiraAndLogs_scratch/c7run}
C7=$BASE/JiraAndLogs/industry-c7
ARMS="${ARMS-locagent}"
STAGES="${STAGES:-}"
WORKERS="${WORKERS:-12}"
PORT=${PORT:-8000}
# MUST match the server that produced the paper's numbers. submit-final.sh
# on Trillium served the full 4,409-instance run at 65536, and every number
# in the paper comes from that server. Nibi's submit-qwen.sh used 131072,
# so serving the baselines there with the Nibi default would compare two
# systems under different context windows -- a confound that would be
# invisible in the results and impossible to detect afterwards.
MAXLEN="${MAXLEN:-65536}"
if [ "$MAXLEN" != "65536" ]; then
  echo "REFUSING: max-model-len is $MAXLEN, but the paper's runs used" >&2
  echo "65536. Set MAXLEN=65536, or knowingly re-run every arm." >&2
  exit 1
fi
SPOOL=$C7/data/agent/spool-$SLURM_JOB_ID
mkdir -p "$BASE/logs" "$SPOOL"

echo "node=$(hostname) job=${SLURM_JOB_ID:-none} arms='$ARMS' stages='$STAGES'"

# The model sits in a different place on each cluster; find it rather than
# hardcoding one and failing on the other.
MODEL_DIR=""
for cand in "$S/models/Qwen3.8-27B" "$S/c7-llm/models/Qwen3.8-27B"; do
  [ -f "$cand/config.json" ] && { MODEL_DIR=$cand; break; }
done
VLLM_BIN=$S/c7-llm/vllm-venv/bin/vllm
[ -n "$MODEL_DIR" ] || { echo "no model found" >&2; exit 1; }
[ -x "$VLLM_BIN" ] || { echo "no vllm at $VLLM_BIN" >&2; exit 1; }
echo "model=$MODEL_DIR  max-model-len=$MAXLEN (matches the paper's runs)"

# ---- what is already done (resume) ---------------------------------------
for arm in $ARMS; do
  f=$C7/data/agent/agent-$arm-eval.jsonl
  echo "resume: $arm has $(grep -c . "$f" 2>/dev/null || echo 0) rows already"
done

# ---- 1. serve -------------------------------------------------------------
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$S/c7-llm/cache
mkdir -p "$CACHE"/{vllm,hf,triton,inductor,xdg} 2>/dev/null
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

# vLLM's venv is python 3.12 and the agent's is 3.11, so the server runs in
# its own subshell with its own module. Mixing them breaks whichever loads
# second.
(
  module load python/3.12.4 >/dev/null 2>&1
  exec "$VLLM_BIN" serve "$MODEL_DIR" \
    --served-model-name qwen3.8-27b \
    --tensor-parallel-size 1 --max-model-len "$MAXLEN" --max-num-seqs 32 \
    --gpu-memory-utilization 0.92 --port "$PORT" \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --reasoning-parser qwen3 --enable-prefix-caching
) > "$BASE/logs/vllm-${SLURM_JOB_ID:-local}.log" 2>&1 &
VLLM_PID=$!
cleanup () {
  touch "$SPOOL/STOP" 2>/dev/null
  kill ${BRIDGE_PID:-} "$VLLM_PID" 2>/dev/null
  wait "$VLLM_PID" 2>/dev/null
  rm -rf "$SPOOL" 2>/dev/null
}
trap cleanup EXIT

echo "waiting for the server ..."
for i in $(seq 1 180); do
  curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b && {
    echo "server up after $((i * 10))s"; break; }
  kill -0 "$VLLM_PID" 2>/dev/null || {
    echo "vLLM died during startup:" >&2
    tail -25 "$BASE/logs/vllm-${SLURM_JOB_ID:-local}.log" >&2; exit 1; }
  sleep 10
done
curl -s -m 5 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b \
  || { echo "server never became ready" >&2; exit 1; }

# ---- 2. the local bridge --------------------------------------------------
# agent.py posts through a spool, so the bridge still runs -- but in
# ENDPOINT mode it is a plain local curl, not an ssh session. The spool is
# per-job so two jobs can never steal each other's responses.
module load python/3.11 >/dev/null 2>&1
PY=$BASE/venv/bin/python3
ENDPOINT="http://localhost:$PORT" MAXJOBS=28 \
  bash "$C7/agent/bridge.sh" "$SPOOL" \
  > "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" 2>&1 &
BRIDGE_PID=$!
sleep 5
grep -q "bridge up" "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" \
  || { echo "bridge failed:" >&2
       cat "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" >&2; exit 1; }
echo "bridge up (local endpoint)"

cd "$BASE/JiraAndLogs" || exit 1
export C7_SPOOL="$SPOOL"

# ---- 3. the work ----------------------------------------------------------
for arm in $ARMS; do
  echo "=== T25 $arm on the 1,000-instance sample ==="
  "$PY" industry-c7/agent/run_agent.py --arm "$arm" --tag "$arm-eval" \
      --subset industry-c7/data/results/baseline-sample.json \
      --full --workers "$WORKERS"
  echo "=== $arm now at $(grep -c . "$C7/data/agent/agent-$arm-eval.jsonl" 2>/dev/null || echo 0)/1000 rows ==="
done

if [[ ",$STAGES," == *",judge,"* ]]; then
  echo "=== T17 judge pass ==="
  "$PY" industry-c7/scripts/judge_explanations.py --rate --rater=qwen
fi

echo "=== job done ==="
