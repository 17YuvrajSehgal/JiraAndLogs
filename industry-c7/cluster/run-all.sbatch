#!/bin/bash
# Serve the model AND run the agents in ONE job, on the same node.
#
# Why this exists: every previous run drove the agents from the laptop and
# reached the GPU over nested ssh. That meant the laptop had to stay awake
# for the whole run, and the transport capped concurrency at the control
# master's MaxSessions (~8 workers) while the server sat at 32 sequences
# -- the GPU was never the limit. Here the agent talks to
# http://localhost:8000 on its own node: no ssh per request, no bridge
# over the network, no laptop. Submit it and walk away.
#
# Everything is restart-safe: run_agent.py skips ids already in its output
# file, so a job that hits its walltime is resumed by resubmitting.
#
# Usage (from the GPU login node):
#   sbatch -t 6:00:00 --gpus-per-node=1 --cpus-per-task=24 --mem=120G \
#          industry-c7/cluster/run-all.sbatch
#   STAGES=baselines sbatch ... run-all.sbatch     # just T25
#   STAGES=judge     sbatch ... run-all.sbatch     # just T17
#
#SBATCH --account=def-naser2
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=120G
#SBATCH --time=06:00:00
#SBATCH --job-name=c7-run-all
#SBATCH --output=/scratch/yuvraj17/JiraAndLogs_scratch/c7run/logs/run-%j.out

set -uo pipefail
S=/scratch/yuvraj17
BASE=$S/JiraAndLogs_scratch/c7run
C7=$BASE/JiraAndLogs/industry-c7
STAGES="${STAGES:-baselines,judge}"
WORKERS="${WORKERS:-10}"        # per arm; two arms stay under --max-num-seqs
PORT=8000
mkdir -p "$BASE/logs" "$C7/data/agent/spool"

echo "node: $(hostname)  job: ${SLURM_JOB_ID:-none}  stages: $STAGES"
nvidia-smi -L 2>/dev/null | head -2

# ---- 1. serve -------------------------------------------------------------
# Compute nodes have no internet and do not mount /home: caches on /scratch.
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$S/c7-llm/cache
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

# vLLM's venv is built against python 3.12 and the agent's against 3.11, so
# the server runs in its own subshell with its own module loaded. Mixing
# them in one environment breaks whichever loads second.
(
  module load python/3.12.4 >/dev/null 2>&1
  exec "$S/c7-llm/vllm-venv/bin/vllm" serve "$S/models/Qwen3.8-27B" \
    --served-model-name qwen3.8-27b \
    --tensor-parallel-size 1 --max-model-len 65536 --max-num-seqs 32 \
    --gpu-memory-utilization 0.92 --port $PORT \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --reasoning-parser qwen3 --enable-prefix-caching
) > "$BASE/logs/vllm-${SLURM_JOB_ID:-local}.log" 2>&1 &
VLLM_PID=$!
cleanup () { kill "$VLLM_PID" 2>/dev/null; wait "$VLLM_PID" 2>/dev/null; }
trap cleanup EXIT

echo "waiting for the server ..."
for i in $(seq 1 180); do
  if curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b; then
    echo "server up after $((i * 10))s"; break
  fi
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM died during startup; see logs/vllm-${SLURM_JOB_ID:-local}.log" >&2
    tail -20 "$BASE/logs/vllm-${SLURM_JOB_ID:-local}.log" >&2
    exit 1
  fi
  sleep 10
done
curl -s -m 5 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b || {
  echo "server never became ready" >&2; exit 1; }

# ---- 2. the local bridge --------------------------------------------------
# agent.py always posts through the spool, so the bridge still runs -- but
# in ENDPOINT mode it is a plain local curl, not an ssh session, which is
# the whole point.
module load python/3.11 >/dev/null 2>&1
export PATH="$BASE/venv/bin:$PATH"
rm -f "$C7/data/agent/spool"/STOP "$C7/data/agent/spool"/req-* \
      "$C7/data/agent/spool"/resp-* 2>/dev/null
ENDPOINT="http://localhost:$PORT" MAXJOBS=28 \
  bash "$C7/agent/bridge.sh" "$C7/data/agent/spool" \
  > "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" 2>&1 &
BRIDGE_PID=$!
cleanup () { touch "$C7/data/agent/spool/STOP" 2>/dev/null
             kill "$BRIDGE_PID" "$VLLM_PID" 2>/dev/null
             wait "$VLLM_PID" 2>/dev/null; }
sleep 5
grep -q "bridge up" "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" \
  && echo "bridge up (local endpoint)" \
  || { echo "bridge failed to start" >&2
       cat "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" >&2; exit 1; }

cd "$BASE/JiraAndLogs" || exit 1
PY="$BASE/venv/bin/python3"

# ---- 3. the work ----------------------------------------------------------
if [[ ",$STAGES," == *",baselines,"* ]]; then
  for arm in locagent cosil; do
    echo "=== T25 $arm, 1,000 instances ==="
    $PY industry-c7/agent/run_agent.py --arm "$arm" --tag "$arm-eval" \
        --subset industry-c7/data/results/baseline-sample.json \
        --full --workers "$WORKERS" &
  done
  wait
  echo "=== T25 both arms finished ==="
fi

if [[ ",$STAGES," == *",judge,"* ]]; then
  echo "=== T17 judge pass ==="
  $PY industry-c7/scripts/judge_explanations.py --rate --rater=qwen
fi

echo "=== all stages done ==="
