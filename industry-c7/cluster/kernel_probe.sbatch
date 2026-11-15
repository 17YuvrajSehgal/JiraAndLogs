#!/bin/bash
# Is the SERVED model identical across clusters?
#
# Package lists are a proxy. This asks the question directly: bring up the
# same server with the same flags, then send fixed prompts at temperature 0
# with thinking off and print the completions. Two clusters that return the
# same text for the same prompt are interchangeable for this run; two that
# do not are a confound no package list would have shown.
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --time=00:30:00
#SBATCH --job-name=c7-kprobe
#SBATCH --output=%x-%j.out
set -uo pipefail
S=/scratch/$USER
C7=$S/c7-data/industry-c7
pick_port () {
  for p in $(seq "${1:-8600}" "$((${1:-8600} + 200))"); do
    if ! (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then echo "$p"; return; fi
  done
  echo "no free port" >&2; exit 1
}
PORT=$(pick_port 8600)
VLLM_BIN=$S/c7-llm/vllm-venv/bin/vllm
PY=$S/c7-llm/agent-venv/bin/python
MODEL_DIR=""
for c in "$S/models/Qwen3.8-27B" "$S/c7-llm/models/Qwen3.8-27B"; do
  [ -f "$c/config.json" ] && { MODEL_DIR=$c; break; }
done
echo "PROBE host=$(hostname) model=$MODEL_DIR port=$PORT"

export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$S/c7-llm/cache
mkdir -p "$CACHE"/vllm "$CACHE"/hf "$CACHE"/triton "$CACHE"/inductor "$CACHE"/xdg
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

# NOT /tmp: that is node-local and goes away with the job, which is
# exactly when the log is needed. The first rorqual probe died at
# engine init and took its own root cause with it.
mkdir -p "$S/c7-data/logs"
LOG=$S/c7-data/logs/kprobe-vllm-${SLURM_JOB_ID:-local}.log
( exec "$VLLM_BIN" serve "$MODEL_DIR" \
    --served-model-name qwen3.8-27b \
    --tensor-parallel-size 1 --max-model-len 65536 --max-num-seqs 32 \
    --gpu-memory-utilization 0.92 --port "$PORT" \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --reasoning-parser qwen3 --enable-prefix-caching ) > "$LOG" 2>&1 &
VPID=$!
trap 'kill $VPID 2>/dev/null; wait $VPID 2>/dev/null' EXIT
for i in $(seq 1 120); do
  curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b && break
  kill -0 "$VPID" 2>/dev/null || {
    echo "vLLM died; full log at $LOG"
    grep -iE "error|assert|CUDA|memory|No such|Permission|nvcc" "$LOG" \
      | tail -25
    echo "--- last 40 raw ---"
    tail -40 "$LOG"
    exit 1
  }
  sleep 10
done
curl -s -m 5 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b || {
  echo "server never ready"; tail -20 "$LOG"; exit 1; }

echo "=== BACKEND LINES ==="
grep -oE "FlashInfer kernels are disabled" "$LOG" | sort | uniq -c
grep -oE "Using FlashInfer[A-Za-z ]*|Using FlashAttention[A-Za-z0-9 ]*|attention backend[^,]*|backend=[A-Za-z_]+" "$LOG" | sort | uniq -c

echo "=== FIXED PROMPTS, temperature 0, thinking off ==="
ENDPOINT="http://localhost:$PORT" C7="$C7" "$PY" - <<'PY'
import hashlib, json, os, sys, urllib.request
sys.path.insert(0, os.environ["C7"] + "/agent")
sys.path.insert(0, os.environ["C7"] + "/scripts")
import agent as A
PROMPTS = [
    "What is 17*23? Number only.",
    "List the first 15 prime numbers, comma separated, nothing else.",
    "In one sentence, what does a NullPointerException mean in Java?",
    ("Given this stack trace line: 'at org.apache.hive.Driver.compile"
     "(Driver.java:512)', name the single most likely function to inspect. "
     "Answer with just the function name."),
]
for i, p in enumerate(PROMPTS):
    body = {"model": A.MODEL, "temperature": 0, "max_tokens": 220, "seed": 42,
            "messages": [{"role": "user", "content": p}], **A.THINK_SWITCH}
    req = urllib.request.Request(
        os.environ["ENDPOINT"] + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    m = d["choices"][0]["message"]
    txt = m.get("content") or ""
    rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get(
        "reasoning_tokens", 0)
    print(f"PROMPT{i}_sha256 {hashlib.sha256(txt.encode()).hexdigest()[:16]}")
    print(f"PROMPT{i}_len {len(txt)} tokens {d['usage']['completion_tokens']} "
          f"reasoning {rt} finish {d['choices'][0]['finish_reason']}")
    print(f"PROMPT{i}_text {txt[:200]!r}")
PY
echo "=== PROBE DONE ==="
