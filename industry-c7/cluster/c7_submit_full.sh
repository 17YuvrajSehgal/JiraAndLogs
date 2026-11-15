# Full run of the staged workflow arm (--arm wf), five project-disjoint
# shards, each to its own file agent-wf-<shard>.jsonl (NOT the
# agent-full-* files of the v3 main run).
#
# Full 26,544-instance runs only. Each job runs its shard at seed 42, then
# the same shard at seeds 7 and 123 (agent-wf-<shard>-seed7.jsonl, ...),
# and after that keeps the server hosted and takes tasks from
# queue/pending. Every run is resumable.
#
#   bash c7_submit_full.sh --test-only     # ask the scheduler, queue nothing
#   bash c7_submit_full.sh                 # submit
cd /scratch/$USER/c7-data || exit 1
for sh in s1 s2 s3 s4 s5; do
  TAG=wf-$sh EXTRA_ARGS="--arm wf" FOLLOW_ON_SEEDS="7 123" ARMS= \
    bash industry-c7/cluster/submit-shard.sh $sh "$@" 2>&1 | grep -v "^--- queue\|JOBID"
done
squeue -u $USER -o "%.10i %.12j %.9T %.10M %.11l %.20S %R"
