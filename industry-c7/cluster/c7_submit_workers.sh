# Submit N identical queue workers on whatever cluster this runs from.
# A worker serves the model and takes tasks from queue/pending; it has no
# shard of its own, so it does not matter which worker starts where.
#
#   bash c7_submit_workers.sh <n> <walltime> <b1|b2|b3> [--test-only]
#     b1 = up to 3 h, b2 = up to 12 h, b3 = up to 24 h (shorter starts sooner)
#
# Short jobs are the point: at submission the schedulers put a 24 h job
# days away (nibi 2026-11-17) and a 3 h job about an hour away. Every task
# is resumable, so a worker cut off by its walltime loses nothing: the next
# worker takes the task over and continues from the rows already written.
# Cores: one GPU's share of its node (nibi 112/8, fir 48/4, rorqual 64/4,
# trillium 96/4). The shard jobs asked for 24 everywhere, which on fir is
# half a node for one GPU: harder to place and billed as two GPUs.
set -u
N="${1:?n}"; WALL="${2:?walltime}"; P="${3:?b1|b2|b3}"; TEST=()
[ "${4:-}" = "--test-only" ] && TEST=(--test-only)
BASE=/scratch/$USER/c7-data
JOB=$BASE/industry-c7/cluster/run-shard.sbatch
case "$(hostname -f 2>/dev/null || hostname)" in
  *trig*|*trillium*|tri-*) C=trillium; OFF=8; FLAGS=(--account=def-naser2 --gpus-per-node=1 --cpus-per-task=24) ;;
  *nibi*|l[0-9]*.nibi*)    C=nibi;     OFF=0; FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --cpus-per-task=14 --mem=120G --partition=gpubase_bygpu_$P) ;;
  *fir*|fc*)               C=fir;      OFF=3; FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --cpus-per-task=12 --mem=120G --partition=gpubase_bygpu_$P) ;;
  *rorqual*|rg*)           C=rorqual;  OFF=6; FLAGS=(--account=def-naser2_gpu --gpus-per-node=1 --cpus-per-task=16 --mem=120G --partition=gpubase_bygpu_$P) ;;
  *) echo "unknown cluster $(hostname)" >&2; exit 1 ;;
esac
mkdir -p "$BASE/logs" && cd "$BASE/logs" || exit 1
for i in $(seq 1 "$N"); do
  sbatch "${TEST[@]}" "${FLAGS[@]}" -t "$WALL" --job-name="c7w-$P" \
    --export=ALL,SHARD=w,WORKER=1,TP=1,MAXLEN=65536,SEED=42,WORKERS=24,TASK_OFFSET=$OFF,QUEUE_IDLE_MAX_S=2700,FOLLOW_ON_SEEDS=,ARMS=,TAG=,SUBSET=,C7_PROJECTS= \
    "$JOB" 2>&1 | grep -oE "Submitted batch job [0-9]+|to start at [^ ]+|rror.*" | head -1
done | sort | uniq -c
echo "$C: $(squeue -u $USER -h -t PD | wc -l) pending, $(squeue -u $USER -h -t R | wc -l) running"
