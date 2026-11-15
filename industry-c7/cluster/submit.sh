#!/bin/bash
# Submit the C7 stages on whichever cluster this runs from.
#
# The stage is passed with --export=ALL,C7_STAGE=..., not an `ENV=x sbatch`
# prefix. The prefix form is what broke the first attempt: sbatch did not
# carry the variable into the job, run-all.sbatch fell back to its default,
# and two jobs ran the same arm into the same output file. --export is the
# documented way and is what submit-qwen.sh already used.
#
# Trillium and Nibi disagree in ways that are errors, not warnings:
#            account            gpus-per-node   --mem
#   Trillium def-naser2         1               REJECTED
#   Nibi     def-naser2_gpu     h100:1          120G, and the _gpu account
#                                               is required for a GPU job
#
# Usage, from the cluster:
#   bash industry-c7/cluster/submit.sh arms    # locagent + cosil, 3 h each
#   bash industry-c7/cluster/submit.sh judge   # T17, 1 h
#   bash industry-c7/cluster/submit.sh locagent
# Resume after a timeout: run the SAME command again.
set -u
WHAT="${1:-}"
case "$WHAT" in
  arms|judge|locagent|cosil|all) ;;
  *) echo "usage: submit.sh arms|judge|locagent|cosil|all" >&2; exit 1 ;;
esac
BASE=${C7_BASE:-/scratch/yuvraj17/c7-data}
JOB=$BASE/industry-c7/cluster/run-all.sbatch
[ -f "$JOB" ] || { echo "no job script at $JOB" >&2; exit 1; }

case "$(hostname -f 2>/dev/null || hostname)" in
  *nibi*|l[0-9]*.nibi*)
    CLUSTER=nibi
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --mem=120G) ;;
  *trig*|*tri-*|*trillium*)
    CLUSTER=trillium
    FLAGS=(--account=def-naser2 --gpus-per-node=1) ;;   # --mem is rejected
  *) echo "unknown cluster $(hostname); add it to submit.sh" >&2; exit 1 ;;
esac
echo "cluster=$CLUSTER flags=${FLAGS[*]}"
mkdir -p "$BASE/logs" && cd "$BASE/logs" || exit 1

submit () {   # $1 stage, $2 walltime
  printf '  %-9s %s  ' "$1" "$2"
  sbatch "${FLAGS[@]}" -t "$2" --job-name="c7-$1" \
    --export=ALL,C7_STAGE="$1",MAXLEN=65536 "$JOB" 2>&1 | tail -1
}

case "$WHAT" in
  locagent|cosil) submit "$WHAT" 3:00:00 ;;
  judge)          submit judge 1:00:00 ;;
  arms)           submit locagent 3:00:00; submit cosil 3:00:00 ;;
  all)            submit locagent 3:00:00; submit cosil 3:00:00
                  submit judge 1:00:00 ;;
esac

echo "--- queue ---"
squeue -u "$USER" -o "%.10i %.12j %.9T %.11l %.20S %.18R"
