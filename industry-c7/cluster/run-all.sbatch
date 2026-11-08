#!/bin/bash
# Serve the model AND run one stage of the work, in ONE job on ONE node.
#
# Why: every earlier run drove the agents from the laptop over nested ssh.
# The laptop had to stay awake, and the transport capped concurrency at the
# control master's MaxSessions (~8 workers) while the server sat at 32
# sequences. Measured: local tool work is 3.0 s of a 325 s instance, so
# neither the GPU nor the laptop was the limit -- ssh was. Here the agent
# talks to http://localhost:8000 on its own node.
#
# ONE STAGE PER JOB. Short jobs backfill far sooner than long ones and the
# stages are independent.
#
# C7_STAGE IS REQUIRED AND HAS NO DEFAULT. It used to default to
# "locagent", and when sbatch did not propagate the variable two jobs
# silently ran the same arm and wrote the same output file under the same
# tag -- one of them rewriting it under the other. A missing stage must
# fail loudly at second zero, not produce a confident wrong run.
#
# RESUMABLE: run_agent.py keeps only rows that SUCCEEDED and skips ids
# already present; judge_explanations.py --rate skips verdicts already
# written. A job killed at its walltime is continued by resubmitting the
# identical command. Nothing repeats, nothing duplicates.
#
# Submit with cluster/submit.sh, which passes the per-cluster flags and
# --export. Trillium: --account=def-naser2 --gpus-per-node=1, --mem
# REJECTED. Nibi: --account=def-naser2_gpu --gpus-per-node=h100:1 --mem.
#
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --time=03:00:00
#SBATCH --job-name=c7-stage
#SBATCH --output=%x-%j.out

set -uo pipefail
S=/scratch/yuvraj17
BASE=${C7_BASE:-$S/c7-data}
C7=$BASE/industry-c7
WORKERS="${WORKERS:-12}"
PORT=${PORT:-8000}

# ---- the tree must be the 27-project one --------------------------------
# BASE used to default to $S/JiraAndLogs_scratch/c7run, which is the OLD
# 4-project tree. That tree is still on disk, still self-consistent and
# still runnable, so a job submitted there produces results that look
# perfectly healthy and are silently scored on kafka/mariadb/mongodb/qt
# alone. A path default cannot be trusted to encode which dataset this is,
# so assert the dataset itself.
NPROJ=$(ls "$C7"/data/benchmark/*.jsonl 2>/dev/null | grep -vc -- -memory.jsonl)
if [ "$NPROJ" != "27" ]; then
  echo "REFUSING: $C7/data/benchmark has $NPROJ projects, expected 27." >&2
  echo "C7_BASE=$BASE is not the current tree. The old 4-project tree" >&2
  echo "lives at $S/JiraAndLogs_scratch/c7run and must not be run." >&2
  exit 1
fi

# ---- the stage, with no default ------------------------------------------
STAGE="${C7_STAGE:-}"
case "$STAGE" in
  locagent|cosil|judge) ;;
  "") echo "REFUSING: C7_STAGE is not set. It has no default on purpose:" >&2
      echo "a silent default is what made two jobs run the same arm." >&2
      echo "Use cluster/submit.sh, or --export=ALL,C7_STAGE=locagent" >&2
      exit 1 ;;
  *)  echo "REFUSING: C7_STAGE='$STAGE' is not one of locagent|cosil|judge" >&2
      exit 1 ;;
esac

# ---- context length, pinned to the paper's own runs ----------------------
# submit-final.sh served the 4,409-instance run at 65536 and every number
# in the paper comes from that server. Nibi's submit-qwen.sh defaults to
# 131072. Serving an arm at a different window would be a confound that
# nothing in the output records.
MAXLEN="${MAXLEN:-65536}"
if [ "$MAXLEN" != "65536" ]; then
  echo "REFUSING: max-model-len=$MAXLEN; the paper's runs used 65536" >&2
  exit 1
fi

# ---- one job per stage ----------------------------------------------------
# Two jobs on the same stage would share an output file and a tag. The
# resume logic rewrites that file, so the second job would rewrite it under
# the first. A lock keyed on the stage makes that impossible.
LOCK=$C7/data/agent/.lock-$STAGE
if [ -f "$LOCK" ]; then
  other=$(cat "$LOCK" 2>/dev/null)
  if squeue -j "$other" -h -o %T 2>/dev/null | grep -q RUNNING; then
    echo "REFUSING: job $other is already running stage '$STAGE'." >&2
    exit 1
  fi
  echo "note: stale lock from job $other (not running); taking over"
fi
mkdir -p "$C7/data/agent"
echo "${SLURM_JOB_ID:-local}" > "$LOCK"

SPOOL=$C7/data/agent/spool-${SLURM_JOB_ID:-local}
mkdir -p "$BASE/logs" "$SPOOL"
echo "node=$(hostname) job=${SLURM_JOB_ID:-none} stage=$STAGE maxlen=$MAXLEN"

MODEL_DIR=""
for cand in "$S/models/Qwen3.8-27B" "$S/c7-llm/models/Qwen3.8-27B"; do
  [ -f "$cand/config.json" ] && { MODEL_DIR=$cand; break; }
done
VLLM_BIN=$S/c7-llm/vllm-venv/bin/vllm
[ -n "$MODEL_DIR" ] || { echo "no model found" >&2; exit 1; }
[ -x "$VLLM_BIN" ] || { echo "no vllm at $VLLM_BIN" >&2; exit 1; }
echo "model=$MODEL_DIR"

if [ "$STAGE" != "judge" ]; then
  f=$C7/data/agent/agent-$STAGE-eval.jsonl
  echo "resume: $STAGE has $(grep -c . "$f" 2>/dev/null || echo 0) rows already"
fi

# ---- 1. serve -------------------------------------------------------------
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$S/c7-llm/cache
mkdir -p "$CACHE"/vllm "$CACHE"/hf "$CACHE"/triton "$CACHE"/inductor "$CACHE"/xdg
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

# vLLM and the agent each have their own standalone venv; the server runs
# in its own subshell because mixing the two breaks whichever loads second.
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
BRIDGE_PID=""
cleanup () {
  touch "$SPOOL/STOP" 2>/dev/null
  [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null
  kill "$VLLM_PID" 2>/dev/null
  wait "$VLLM_PID" 2>/dev/null
  rm -rf "$SPOOL" 2>/dev/null
  rm -f "$LOCK" 2>/dev/null
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

# ---- 1a. is the thinking switch actually honoured by THIS server? ---------
# The local LM Studio server silently ignores chat_template_kwargs and keeps
# reasoning on, so a run can be configured for thinking-off and served with
# thinking-on while nothing in the output says so. Never assume a switch
# works; ask the server that is about to run 26,544 instances.
C7="$C7" ENDPOINT="http://localhost:$PORT" "$PY" - <<'THINKCHK'   || { echo "THINKING CHECK FAILED: not starting" >&2; exit 1; }
import json, os, sys, urllib.request
sys.path.insert(0, os.environ["C7"] + "/agent")
sys.path.insert(0, os.environ["C7"] + "/scripts")
import agent as A
body = {"model": A.MODEL, "temperature": 0, "max_tokens": 200, "seed": 42,
        "messages": [{"role": "user", "content": "What is 17*23? Number only."}],
        **A.THINK_SWITCH}
req = urllib.request.Request(os.environ["ENDPOINT"] + "/v1/chat/completions",
                             data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
try:
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
except Exception as e:
    print(f"  the server REJECTED the thinking switch: {e}", file=sys.stderr)
    print(f"  switch sent: {json.dumps(A.THINK_SWITCH)}", file=sys.stderr)
    sys.exit(1)
msg = d["choices"][0]["message"]
rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get(
    "reasoning_tokens", 0)
has = bool(msg.get("reasoning_content") or msg.get("reasoning"))
print(f"  thinking requested: {A.ENABLE_THINKING}; server returned "
      f"reasoning_tokens={rt}, reasoning_field={has}")
if not A.ENABLE_THINKING and (rt or has):
    print("  REFUSING: thinking is configured OFF and the server kept it ON.",
          file=sys.stderr)
    sys.exit(1)
if A.ENABLE_THINKING and not (rt or has):
    print("  REFUSING: thinking is configured ON and the server kept it OFF.",
          file=sys.stderr)
    sys.exit(1)
print("  thinking check ok")
THINKCHK

# ---- 1b. PREFLIGHT on the compute node ------------------------------------
# tree_sitter_language_pack fetches its parsers from GitHub at RUNTIME, and
# compute nodes have no internet. The cache also defaults under /home,
# which compute nodes do not mount. Both were true on the first real run:
# 178 of 185 instances died with a DownloadError and the job still looked
# healthy from the outside -- a server up, a bridge up, rows being written.
# The parsers now live on /scratch under XDG_CACHE_HOME, and this check
# runs HERE, on the compute node, where the login node's internet cannot
# hide the problem. Ten seconds against three wasted hours.
# The agent venv is a standalone CPython 3.12.16 built with uv at
# $S/c7-llm/agent-venv, so there is no module to load. It carries the
# laptop's exact pins (langchain 1.4.9, langgraph 1.2.20, pydantic 2.14.3,
# tree-sitter-language-pack 1.22.1) so a cluster run cannot drift from a
# local one.
PY=$S/c7-llm/agent-venv/bin/python
[ -x "$PY" ] || { echo "no agent venv at $PY" >&2; exit 1; }
C7="$C7" "$PY" - <<'PREFLIGHT' || { echo "PREFLIGHT FAILED: not starting" >&2; exit 1; }
import sys
import os
sys.path.insert(0, os.environ["C7"] + "/scripts")
try:
    from tree_sitter_language_pack import get_parser, cache_dir
except Exception as e:
    print(f"  cannot import the parser pack: {e}", file=sys.stderr); sys.exit(1)
# The language list is READ FROM THE CODE, never typed here. This block used
# to name java, cpp and scala. When .py and .go were added to LANG_OF it
# would have passed on a node with no Go parser and then failed per
# instance, which is the shape of the bug that killed 178 of 185 runs once.
from function_stage import LANG_OF  # noqa: E402
print(f"  parser cache: {cache_dir()}")
SAMPLE = {"java": b"class A { void m() {} }", "cpp": b"int f(){return 0;}",
          "scala": b"object A { def m(): Int = 1 }",
          "python": b"def f():\n    return 1\n",
          "go": b"package m\nfunc F() int { return 1 }\n"}
langs = sorted(set(LANG_OF.values()))
bad = []
for lang in langs:
    code = SAMPLE.get(lang)
    if code is None:
        bad.append(f"{lang}: in LANG_OF but this preflight has no sample for it")
        continue
    try:
        get_parser(lang).parse(code)
    except Exception as e:
        bad.append(f"{lang}: {type(e).__name__}: {str(e)[:120]}")
if bad:
    print("  PARSERS UNUSABLE ON THIS NODE:", file=sys.stderr)
    for b in bad:
        print(f"    {b}", file=sys.stderr)
    sys.exit(1)
print(f"  preflight ok: {', '.join(langs)} all parse with no network")
PREFLIGHT

# ---- 2. the local bridge --------------------------------------------------
ENDPOINT="http://localhost:$PORT" MAXJOBS=28 \
  bash "$C7/agent/bridge.sh" "$SPOOL" \
  > "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" 2>&1 &
BRIDGE_PID=$!
sleep 5
grep -q "bridge up" "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" \
  || { echo "bridge failed:" >&2
       cat "$BASE/logs/bridge-${SLURM_JOB_ID:-local}.log" >&2; exit 1; }
echo "bridge up (local endpoint)"

cd "$BASE" || exit 1
export C7_SPOOL="$SPOOL"

# ---- 3. the one stage -----------------------------------------------------
if [ "$STAGE" = "judge" ]; then
  echo "=== T17 judge pass ==="
  "$PY" industry-c7/scripts/judge_explanations.py --rate --rater=qwen
else
  echo "=== T25 $STAGE on the 1,000-instance sample ==="
  "$PY" industry-c7/agent/run_agent.py --arm "$STAGE" --tag "$STAGE-eval" \
      --subset industry-c7/data/results/baseline-sample.json \
      --full --workers "$WORKERS"
  echo "=== $STAGE now at $(grep -c . "$C7/data/agent/agent-$STAGE-eval.jsonl" 2>/dev/null || echo 0)/1000 rows ==="
fi
echo "=== job done ==="
