#!/bin/bash
# Serve an open LLM with vLLM (OpenAI-compatible API, port 8000) on Trillium
# GPU nodes. Parameterized by env vars; SBATCH defaults below are for the
# 4-GPU GLM-5.3-Flash run and are overridden on the sbatch command line for
# the 1-GPU Qwen3.8-27B pilot.
#
# Pilot, 1x H100, Qwen3.8-27B (debug partition, fast queue; Trillium
# forbids --mem, memory follows the GPU/CPU share):
#   sbatch -p debug -t 1:00:00 --gpus-per-node=1 --cpus-per-task=24 \
#     --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1 \
#     serve-llm.sbatch
#
# Real runs, 4x H100, GLM-5.3-Flash NVFP4:
#   sbatch --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/GLM-5.3-Flash-NVFP4,NAME=glm-5.3-flash,TP=4,EVAL_PROMPTS=/scratch/yuvraj17/c7-llm/prompts.jsonl \
#     serve-llm.sbatch
#
# With EVAL_PROMPTS set, eval_client.py runs against the server and the job
# exits when done (no idle GPU burn). Without it, the server runs to walltime.
#SBATCH --account=def-naser2
# no --partition: Trillium auto-routes whole-node (4-GPU) jobs; pass
# -p debug/compute explicitly only for 1-GPU jobs
#SBATCH --nodes=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=96
#SBATCH --time=24:00:00
#SBATCH --job-name=vllm-serve
#SBATCH --output=/scratch/yuvraj17/c7-llm/logs/serve-%j.out

set -euo pipefail
S=/scratch/yuvraj17
MODEL_DIR=${MODEL_DIR:?export MODEL_DIR=...}
NAME=${NAME:?export NAME=...}
TP=${TP:-4}
MAXLEN=${MAXLEN:-65536}
SIF=$S/sifs/vllm-openai.sif
PORT=8000

echo "node: $(hostname)  serving $NAME (TP=$TP) from $MODEL_DIR"
nvidia-smi -L

# compute nodes have no internet: everything must come from /scratch
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
export APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1
export APPTAINERENV_VLLM_NO_USAGE_STATS=1
# GPU compute nodes do not mount /home: every cache must live on /scratch
CACHE=$S/c7-llm/cache
mkdir -p $CACHE/vllm $CACHE/hf $CACHE/triton $CACHE/inductor $CACHE/xdg
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor
# flashinfer kernels come from flashinfer-jit-cache-sm90a (installed via
# `vllm download-kernels` on the login node; version-matched, offline-safe)

SERVE_ARGS=(serve "$MODEL_DIR"
    --served-model-name "$NAME"
    --tensor-parallel-size "$TP"
    --max-model-len "$MAXLEN"
    --max-num-seqs "${MAXSEQS:-256}"
    --gpu-memory-utilization 0.92
    --port $PORT)
# pip venv preferred (smaller, faster to stage); container is the fallback
if [ -x $S/c7-llm/vllm-venv/bin/vllm ]; then
  echo "stack: pip venv"
  module load python/3.12.4
  $S/c7-llm/vllm-venv/bin/vllm "${SERVE_ARGS[@]}" \
    > $S/c7-llm/logs/vllm-$SLURM_JOB_ID.log 2>&1 &
else
  echo "stack: apptainer $SIF"
  module load apptainer/1.4.5
  apptainer exec --nv --bind /scratch:/scratch "$SIF" \
    vllm "${SERVE_ARGS[@]}" \
    > $S/c7-llm/logs/vllm-$SLURM_JOB_ID.log 2>&1 &
fi
VLLM_PID=$!

# wait for the server (large models take minutes to load and warm up)
for i in $(seq 1 120); do
  if curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q "$NAME"; then
    echo "server up after ~$((i*15))s"; break
  fi
  kill -0 $VLLM_PID 2>/dev/null || { echo "vllm died; see vllm-$SLURM_JOB_ID.log"; exit 1; }
  sleep 15
done

# smoke test: one deterministic completion, logged
curl -s "http://localhost:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\": \"$NAME\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: SERVING_OK\"}],
  \"max_tokens\": 10, \"temperature\": 0
}" | tee $S/c7-llm/logs/smoke-$SLURM_JOB_ID.json
echo
echo "endpoint: http://$(hostname):$PORT/v1"

if [ -n "${EVAL_PROMPTS:-}" ] && [ -f "$EVAL_PROMPTS" ]; then
  echo "running eval client on $EVAL_PROMPTS"
  python3 $S/c7-llm/eval_client.py \
    --prompts "$EVAL_PROMPTS" \
    --endpoint "http://localhost:$PORT/v1" \
    --model "$NAME" \
    --out "${EVAL_PROMPTS%.jsonl}-$NAME-responses.jsonl"
  echo "eval done; shutting down"
else
  wait $VLLM_PID
fi
