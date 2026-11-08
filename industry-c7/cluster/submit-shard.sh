#!/bin/bash
# Submit one shard of the main agent run (arm=lc) on whatever cluster this
# runs from.
#
# A SHARD IS A PROJECT SET, NOT A CLUSTER. The first version named shards
# after clusters, which breaks the moment a shard has to run somewhere else:
# four of the five clusters had no model, no venv and no dataset staged, so
# their shards went to Trillium and a file called agent-full-narval.jsonl
# would have been written by a Trillium H100. Shards are s1..s5 and the
# cluster is recorded in the job log and the node name.
#
#   s1  cassandra drill hive pdfbox solr                  5672 instances
#   s2  beam geode hadoop infinispan sakai wildfly        5852
#   s3  derby groovy mongodb phoenix qt spark             5641
#   s4  ambari flink impala kafka mariadb pig             5709
#   s5  camel hbase ignite keycloak                       3670
#                                                        -----
#                                                        26544
#
# Project-disjoint, so two shards can never rewrite each other's rows and
# all five can run at once. Each writes agent-full-<shard>.jsonl.
#
# NOTE: s1's first run was submitted under the old naming and writes
# agent-full-trillium.jsonl. Same project set, same config; the merge globs
# agent-full-*.jsonl so the name does not matter, only disjointness does.
#
# The five clusters disagree in ways that are errors, not warnings:
#
#            account          gpus-per-node   --mem      24h partition
#   trillium def-naser2       1               REJECTED   (auto -> compute)
#   nibi     def-naser2_gpu   h100:1          120G       gpubase_bygpu_b3
#   fir      def-naser2_gpu   h100:1          120G       gpubase_bygpu_b3
#   rorqual  def-naser2_gpu   1               120G       gpubase_bygpu_b3
#   narval   def-naser2_gpu   a100:2          240G       gpubase_bygpu_b3
#
# narval is the one that cannot match the others on a single GPU: its A100s
# are 40GB (the a100_3g.20gb MIG profile only exists on 40GB cards) and the
# weights are 52GB, so it would serve at TP=2 across two cards. Same model,
# same window, same temperature, same thinking switch; a different parallel
# layout. Collective reductions change floating-point order, so at
# temperature 0 a token can still differ. Prefer not to mix it into a single
# reported run.
#
# Usage, from the cluster:
#   bash industry-c7/cluster/submit-shard.sh s2
#   bash industry-c7/cluster/submit-shard.sh s2 --test-only
#   bash industry-c7/cluster/submit-shard.sh all        # s2..s5
# Resume after a walltime kill: run the SAME command again.
set -u

BASE=${C7_BASE:-/scratch/$USER/c7-data}
JOB=$BASE/industry-c7/cluster/run-shard.sbatch
[ -f "$JOB" ] || { echo "no job script at $JOB" >&2; exit 1; }

P_s1="cassandra drill hive pdfbox solr"
P_s2="beam geode hadoop infinispan sakai wildfly"
P_s3="derby groovy mongodb phoenix qt spark"
P_s4="ambari flink impala kafka mariadb pig"
P_s5="camel hbase ignite keycloak"

WHICH="${1:-}"
case "$WHICH" in
  s1|s2|s3|s4|s5) SHARDS=("$WHICH") ;;
  all)            SHARDS=(s2 s3 s4 s5) ;;
  *) echo "usage: submit-shard.sh s1|s2|s3|s4|s5|all [--test-only]" >&2
     exit 1 ;;
esac
TEST=()
[ "${2:-}" = "--test-only" ] && TEST=(--test-only)

case "$(hostname -f 2>/dev/null || hostname)" in
  *trig*|*trillium*|tri-*)
    CLUSTER=trillium; TP=1
    FLAGS=(--account=def-naser2 --gpus-per-node=1) ;;        # --mem rejected
  *nibi*|l[0-9]*.nibi*)
    CLUSTER=nibi; TP=1
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --mem=120G
           --partition=gpubase_bygpu_b3) ;;
  *fir*|fc*)
    CLUSTER=fir; TP=1
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=h100:1 --mem=120G
           --partition=gpubase_bygpu_b3) ;;
  *rorqual*|rg*)
    CLUSTER=rorqual; TP=1
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=1 --mem=120G
           --partition=gpubase_bygpu_b3) ;;
  *narval*|ng*)
    CLUSTER=narval; TP=2
    FLAGS=(--account=def-naser2_gpu --gpus-per-node=a100:2 --mem=240G
           --partition=gpubase_bygpu_b3) ;;
  *) echo "unknown cluster $(hostname); add it to submit-shard.sh" >&2
     exit 1 ;;
esac

echo "cluster=$CLUSTER tp=$TP"
echo "flags: ${FLAGS[*]}"
mkdir -p "$BASE/logs" && cd "$BASE/logs" || exit 1

for sh in "${SHARDS[@]}"; do
  eval "PROJECTS=\$P_$sh"
  [ -n "${PROJECTS:-}" ] || { echo "no project list for $sh" >&2; exit 1; }
  printf '%-4s %s\n' "$sh" "$PROJECTS"
  sbatch "${TEST[@]}" "${FLAGS[@]}" -t 24:00:00 --job-name="c7-$sh" \
    --export=ALL,SHARD="$sh",C7_PROJECTS="$PROJECTS",TP="$TP",MAXLEN=65536,WORKERS="${WORKERS:-24}" \
    "$JOB" 2>&1 | grep -v -E "^SBATCH (WARNING|:)|^ You have requested|^ need this amount"
done

echo "--- queue ---"
squeue -u "$USER" -o "%.10i %.10j %.9T %.10M %.11l %.20S %.18R"
