#!/bin/bash
# Submit the C7 jobs on whichever cluster this is run from.
#
# Trillium and Nibi disagree about SLURM in ways that are errors, not
# warnings, so the per-cluster flags live here rather than in #SBATCH
# lines that can only say one thing:
#
#            account            gpus-per-node   --mem
#   Trillium def-naser2         1               REJECTED ("not allowed nor
#                                               necessary on {cluster}")
#   Nibi     def-naser2_gpu     h100:1          120G, and the GPU account
#                                               is required for a GPU job
#
# Nibi also routes by walltime and resources instead of taking -p, and its
# gpubase_interac queue (8 h limit) is the one that actually turns over:
# the only GPU job we ever landed there went from submit to running in
# 2 min 23 s, while every gpubase_b* submission was cancelled unstarted.
#
# Usage, from the cluster:
#   bash industry-c7/cluster/submit.sh arms      # one 3 h job per arm
#   bash industry-c7/cluster/submit.sh judge     # the 1 h T17 pass
#   bash industry-c7/cluster/submit.sh all
# Resume after a timeout: run the SAME command again. run_agent.py keeps
# only rows that succeeded and skips ids already present.
set -u
WHAT="${1:-all}"
BASE=${C7_BASE:-/scratch/yuvraj17/JiraAndLogs_scratch/c7run}
JOB=$BASE/JiraAndLogs/industry-c7/cluster/run-all.sbatch
[ -f "$JOB" ] || { echo "no job script at $JOB" >&2; exit 1; }

case "$(hostname -f 2>/dev/null || hostname)" in
  *nibi*|l[0-9]*.nibi*)
    CLUSTER=nibi
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --mem=120G)
    ;;
  *trig*|*tri-*|*trillium*)
    CLUSTER=trillium
    FLAGS=(--account=def-naser2 --gpus-per-node=1)   # --mem is rejected here
    ;;
  *)
    echo "unknown cluster $(hostname); add it to submit.sh" >&2; exit 1 ;;
esac
echo "cluster=$CLUSTER  flags=${FLAGS[*]}"

mkdir -p "$BASE/logs"
cd "$BASE/logs" || exit 1

submit () {   # $1 name, $2 walltime, then env assignments
  local name=$1 wall=$2; shift 2
  echo -n "  $name ($wall): "
  env "$@" sbatch "${FLAGS[@]}" -t "$wall" --job-name="$name" "$JOB" 2>&1 | tail -1
}

[ "$WHAT" = "arms" ] || [ "$WHAT" = "all" ] && {
  submit c7-locagent 3:00:00 ARMS=locagent MAXLEN=65536
  submit c7-cosil    3:00:00 ARMS=cosil    MAXLEN=65536
}
[ "$WHAT" = "judge" ] || [ "$WHAT" = "all" ] && {
  submit c7-judge 1:00:00 ARMS= STAGES=judge MAXLEN=65536
}

echo "--- queue ---"
squeue -u "$USER" -o "%.10i %.12j %.9T %.11l %.20S %.18R"
