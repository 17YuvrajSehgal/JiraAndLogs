#!/bin/bash
# ONE SHARD of the main agent run (arm=lc), served and driven on ONE node.
#
# The 26,544-instance eval split is cut into project-disjoint shards, one
# per cluster. Each shard writes its OWN output file, keyed by SHARD, so
# two clusters can never rewrite each other's rows. run-all.sbatch takes a
# lock for exactly that reason; disjoint output files make the lock
# unnecessary and let all five clusters run at once.
#
# Required:
#   SHARD        short name, becomes the tag and the output filename
#   C7_PROJECTS  space-separated project list for this shard
# Optional:
#   TP           tensor-parallel size (default 1; narval's A100-40GB needs 2)
#   WORKERS      agent concurrency (default 24)
#   MAXLEN       pinned to 65536, see below
#
# Submit through cluster/submit-shard.sh, which supplies the per-cluster
# account and --gpus-per-node dialect. Those differ in ways that are errors,
# not warnings.
#
# RESUMABLE: run_agent.py keeps only rows that SUCCEEDED (is_dead_row) and
# skips ids already present. A job killed at walltime is continued by
# resubmitting the identical command.
#
#SBATCH --nodes=1
#SBATCH --cpus-per-task=24
#SBATCH --time=24:00:00
#SBATCH --job-name=c7-shard
#SBATCH --output=%x-%j.out

set -uo pipefail
S=/scratch/$USER
BASE=${C7_BASE:-$S/c7-data}
C7=$BASE/industry-c7
WORKERS="${WORKERS:-24}"
# A fixed 8000 works only while no two of these jobs share a node. Nothing
# guarantees that: a Trillium node has 4 to 8 GPUs and the scheduler is
# free to pack single-GPU jobs onto one. The second vLLM would then fail to
# bind and the job would die after loading 52GB of weights. Take the first
# free port instead.
pick_port () {
  for p in $(seq "${1:-8000}" "$((${1:-8000} + 200))"); do
    if ! (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then echo "$p"; return; fi
  done
  echo "no free port in range" >&2; exit 1
}
PORT=${PORT:-$(pick_port 8000)}
echo "port=$PORT"
TP="${TP:-1}"

# ---- the shard identity, no defaults ------------------------------------
SHARD="${SHARD:-}"
[ -n "$SHARD" ] || { echo "REFUSING: SHARD is not set (it names the output file)" >&2; exit 1; }
# SUBSET names a json list of "project:KEY" and spans whatever projects it
# likes, so C7_PROJECTS is not required with it. Used for small paired
# arms: pick instances the main run has already finished, rerun them with
# one setting changed, and compare against rows that already exist instead
# of paying for both sides.
SUBSET="${SUBSET:-}"
PROJECTS="${C7_PROJECTS:-}"
if [ -n "$SUBSET" ]; then
  [ -f "$C7/$SUBSET" ] || { echo "REFUSING: no subset file at $C7/$SUBSET" >&2; exit 1; }
  echo "subset: $SUBSET ($(grep -c '"' "$C7/$SUBSET") entries)"
elif [ -z "$PROJECTS" ]; then
  echo "REFUSING: set C7_PROJECTS or SUBSET" >&2; exit 1
fi

# ---- the tree must be the 27-project one --------------------------------
NPROJ=$(ls "$C7"/data/benchmark/*.jsonl 2>/dev/null | grep -vc -- -memory.jsonl)
if [ "$NPROJ" != "27" ]; then
  echo "REFUSING: $C7/data/benchmark has $NPROJ projects, expected 27." >&2
  echo "C7_BASE=$BASE is not the current tree." >&2
  exit 1
fi

# ---- context length, pinned to the paper's own runs ---------------------
# Every number in the paper comes from a server at 65536. Serving one shard
# at a different window would be a confound that nothing in the output
# records, and this run is split across five clusters that each default
# differently.
MAXLEN="${MAXLEN:-65536}"
if [ "$MAXLEN" != "65536" ]; then
  echo "REFUSING: max-model-len=$MAXLEN; every shard must serve at 65536" >&2
  exit 1
fi

# Mahsa asked for three seeds and the average of them. A second seed must
# not write into the first seed's file, so the seed is part of the tag
# whenever it is not the default 42. Seed 42 keeps its bare name so the
# runs already on disk stay addressable.
SEED="${SEED:-42}"
# TAG can be set outright, and must be for anything that is NOT part of the
# main run. The default spells "full-<shard>", and data/agent/agent-full-*
# is the glob that the region scorer and the progress count both use to
# mean "the main run". A side arm named full-something lands inside that
# glob, where it is either summed into the totals or, since it reruns
# instances the main run already did, trips the disjointness guard and
# blocks region scoring outright.
#
# That is exactly what a seed suffix used to do. "full-s2-seed7" still
# begins with "full-", so agent-full-s2-seed7.jsonl matched the main-run
# glob: the progress count read 53,088 of 26,544 and region scoring
# refused on every project because each issue_key now sat in two files.
# A non-default seed therefore leads with the seed instead of with "full",
# which puts it outside the glob while staying obvious on disk.
if [ -n "${TAG:-}" ]; then
  :
elif [ "$SEED" = "42" ]; then TAG="full-$SHARD"
else TAG="seed$SEED-$SHARD"
fi
case "$TAG" in
  full-*-seed*) echo "REFUSING: TAG=$TAG matches the main-run glob agent-full-*" >&2
                exit 1 ;;
esac
OUTF=$C7/data/agent/agent-$TAG.jsonl
mkdir -p "$C7/data/agent" "$BASE/logs"
echo "node=$(hostname) job=${SLURM_JOB_ID:-none} shard=$SHARD tp=$TP maxlen=$MAXLEN seed=$SEED"
echo "projects: $PROJECTS"
echo "resume: $(grep -c . "$OUTF" 2>/dev/null || echo 0) rows already in $(basename "$OUTF")"

# ---- the interpreters, defined BEFORE anything uses them ----------------
# run-all.sbatch used "$PY" in its thinking check 48 lines before PY was
# assigned. With set -u that is an unbound-variable exit at second zero, so
# every job died before serving anything. Define both up front.
PY=$S/c7-llm/agent-venv/bin/python
VLLM_BIN=$S/c7-llm/vllm-venv/bin/vllm
[ -x "$PY" ] || { echo "no agent venv at $PY" >&2; exit 1; }
[ -x "$VLLM_BIN" ] || { echo "no vllm at $VLLM_BIN" >&2; exit 1; }

MODEL_DIR=""
for cand in "$S/models/Qwen3.8-27B" "$S/c7-llm/models/Qwen3.8-27B"; do
  [ -f "$cand/config.json" ] && { MODEL_DIR=$cand; break; }
done
[ -n "$MODEL_DIR" ] || { echo "no model found under $S" >&2; exit 1; }
echo "model=$MODEL_DIR"

# ---- 1. serve -----------------------------------------------------------
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
CACHE=$S/c7-llm/cache
mkdir -p "$CACHE"/vllm "$CACHE"/hf "$CACHE"/triton "$CACHE"/inductor "$CACHE"/xdg
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor

# Identical to run-all.sbatch's validated serving flags. Only TP varies, and
# only because narval's A100s are 40GB and the weights are 52GB.
(
  module load python/3.12.4 >/dev/null 2>&1
  exec "$VLLM_BIN" serve "$MODEL_DIR" \
    --served-model-name qwen3.8-27b \
    --tensor-parallel-size "$TP" --max-model-len "$MAXLEN" --max-num-seqs 32 \
    --gpu-memory-utilization 0.92 --port "$PORT" \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --reasoning-parser qwen3 --enable-prefix-caching
) > "$BASE/logs/vllm-$SHARD-${SLURM_JOB_ID:-local}.log" 2>&1 &
VLLM_PID=$!
cleanup () {
  kill "$VLLM_PID" 2>/dev/null
  wait "$VLLM_PID" 2>/dev/null
}
trap cleanup EXIT

echo "waiting for the server ..."
for i in $(seq 1 180); do
  curl -s -m 2 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b && {
    echo "server up after $((i * 10))s"; break; }
  kill -0 "$VLLM_PID" 2>/dev/null || {
    echo "vLLM died during startup:" >&2
    tail -30 "$BASE/logs/vllm-$SHARD-${SLURM_JOB_ID:-local}.log" >&2; exit 1; }
  sleep 10
done
curl -s -m 5 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b \
  || { echo "server never became ready" >&2; exit 1; }

# ---- 1a. does THIS server serve the configuration we think it does? -----
# Five shards must be one system. Ask each server what it is actually doing
# rather than trusting that five sbatch files agree.
C7="$C7" ENDPOINT="http://localhost:$PORT" WANT_MAXLEN="$MAXLEN" \
  "$PY" "$C7/cluster/config_check.py" \
  || { echo "CONFIG CHECK FAILED: not starting" >&2; exit 1; }

# ---- 1b. PREFLIGHT on the compute node ----------------------------------
# tree_sitter_language_pack fetches parsers from GitHub at RUNTIME and
# compute nodes have no internet. This check runs HERE, where the login
# node's internet cannot hide a missing parser.
C7="$C7" "$PY" "$C7/cluster/parser_check.py" \
  || { echo "PREFLIGHT FAILED: not starting" >&2; exit 1; }

# ---- 2. the shard -------------------------------------------------------
cd "$BASE" || exit 1
ARGS=()
if [ -n "$SUBSET" ]; then
  ARGS+=(--subset "industry-c7/$SUBSET")
else
  for p in $PROJECTS; do ARGS+=(--project "$p"); done
fi

# How long is left on the clock? Asked once, from the scheduler, because a
# follow-on task must not be started with ten minutes to run. Outside
# SLURM this reports a large number, so a local run behaves as before.
JOB_END=$(scontrol show job "${SLURM_JOB_ID:-0}" -o 2>/dev/null \
          | grep -oE 'EndTime=[^ ]+' | head -1 | cut -d= -f2)
JOB_END_EPOCH=$( [ -n "$JOB_END" ] && date -d "$JOB_END" +%s 2>/dev/null || echo 0 )
remaining_s () {
  if [ "${JOB_END_EPOCH:-0}" -gt 0 ]; then echo $(( JOB_END_EPOCH - $(date +%s) ))
  else echo 999999; fi
}
hhmm () { printf '%dh%02dm' $(( $1 / 3600 )) $(( ($1 % 3600) / 60 )); }

run_seed () {
  local seed="$1" tag="$2" outf="$C7/data/agent/agent-$2.jsonl"
  echo "=== shard $SHARD: arm=lc, workers=$WORKERS, seed $seed, thinking off ==="
  echo "    tag=$tag KEEP_FULL=${C7_KEEP_FULL:-6 (default)} CTX_CHARS=${C7_CTX_CHARS:-0 (off)}"
  echo "    walltime left: $(hhmm "$(remaining_s)")"
  C7_LLM_URL="http://localhost:$PORT/v1" C7_MODEL=qwen3.8-27b \
    "$PY" industry-c7/agent/run_agent.py \
      --arm lc --full --tag "$tag" --workers "$WORKERS" \
      --seed "$seed" "${ARGS[@]}"
  echo "=== shard $SHARD seed $seed now at $(grep -c . "$outf" 2>/dev/null || echo 0) rows ==="
}

run_seed "$SEED" "$TAG"

# ---- 3. spend the rest of the walltime ----------------------------------
# Seed 42 finished its five shards in 8 to 14 hours of a 24 hour
# allocation, then exited and handed back 58.7 GPU-hours with a 52GB
# server already loaded, while the two agentic baselines sat in queues 600
# jobs deep. Getting the server up is the expensive part. Once it is up,
# the job should keep feeding it.
#
# Follow-on work is the SAME shard at another seed. That needs no
# coordination at all: the project list does not change and each seed
# writes its own file, so two jobs can never contend. Stealing unfinished
# projects from a slower shard would pack better, but it breaks the
# project-disjoint guarantee that lets five of these run at once, so it is
# deliberately not done here.
#
# Every task is resumable, so one cut off at walltime continues on
# resubmission instead of starting over.
FOLLOW_ON_SEEDS="${FOLLOW_ON_SEEDS:-}"
MIN_FOLLOW_ON_S="${MIN_FOLLOW_ON_S:-3600}"
for fs in $FOLLOW_ON_SEEDS; do
  [ "$fs" = "$SEED" ] && continue
  left=$(remaining_s)
  if [ "$left" -lt "$MIN_FOLLOW_ON_S" ]; then
    echo "=== follow-on stops: $(hhmm "$left") left, needs $(hhmm "$MIN_FOLLOW_ON_S") ==="
    break
  fi
  if [ "$fs" = "42" ]; then ftag="full-$SHARD"; else ftag="seed$fs-$SHARD"; fi
  fout=$C7/data/agent/agent-$ftag.jsonl
  echo "=== follow-on: seed $fs on shard $SHARD, $(hhmm "$left") left,"
  echo "    resuming from $(grep -c . "$fout" 2>/dev/null || echo 0) rows ==="
  run_seed "$fs" "$ftag"
done

# If the job is about to exit with real time still on the clock, say so
# loudly and with the number, so the waste is visible in the log instead
# of being found in sacct a day later.
left=$(remaining_s)
if [ "$left" -gt "$MIN_FOLLOW_ON_S" ] && [ "$left" -lt 999999 ]; then
  echo "=== NOTE: exiting with $(hhmm "$left") of walltime unused, on a node"
  echo "    whose server is loaded. FOLLOW_ON_SEEDS=\"7 123\" spends it. ==="
fi
echo "=== job done ==="
