#!/usr/bin/env bash
# Resumable driver: mine -> sample -> render.
#
# Every stage is idempotent, so this can be re-invoked as often as needed and
# will simply continue. The background runner caps a call at ~10 minutes and
# the full re-mine takes longer than that, so being resumable is the point.
#
# Prints PIPELINE_COMPLETE when there is nothing left to do.

set -u
cd /c/workplace/JiraAndLogs || exit 1

V2=industry-c7/data/benchmark-v2
ANN=industry-c7/annotation
PROJECTS="pdfbox hive hbase hadoop spark flink ambari impala geode ignite camel phoenix beam pig groovy sakai wildfly infinispan keycloak derby solr drill cassandra kafka mariadb mongodb qt"

# ---- stage 1: mine any project still missing -------------------------------
missing=0
for p in $PROJECTS; do
  if [ ! -f "$V2/$p.jsonl" ]; then
    missing=$((missing+1))
    echo "=== MINING $p ==="
    python industry-c7/scripts/mine_benchmark.py --project "$p" --out benchmark-v2 2>&1 \
      | grep -E "final_instances|instances ->|Traceback|Error" | tail -2
  fi
done

still=0
for p in $PROJECTS; do
  [ -f "$V2/$p.jsonl" ] || still=$((still+1))
done
if [ "$still" -gt 0 ]; then
  echo "STAGE1_INCOMPLETE: $still projects still to mine - re-invoke"
  exit 0
fi
echo "STAGE1_DONE: all 27 projects mined"

# ---- stage 2: draw the sample ----------------------------------------------
if [ ! -f "$ANN/sample.json" ]; then
  echo "=== SAMPLING ==="
  python industry-c7/scripts/annotation_sample.py 2>&1 | tail -12 || exit 0
fi
[ -f "$ANN/sample.json" ] || { echo "STAGE2_FAILED"; exit 0; }
echo "STAGE2_DONE: sample drawn"

# ---- stage 3: render the evidence packets ----------------------------------
want=$(python -c "import json;print(json.load(open('$ANN/sample.json'))['n'])" 2>/dev/null || echo 0)
have=$(ls "$ANN"/packets/*.md 2>/dev/null | wc -l)
if [ "$have" -lt "$want" ]; then
  echo "=== RENDERING ($have/$want) ==="
  python industry-c7/scripts/annotation_render.py 2>&1 | tail -6
  have=$(ls "$ANN"/packets/*.md 2>/dev/null | wc -l)
fi
echo "STAGE3: $have packets rendered of $want"

# ---- summary ---------------------------------------------------------------
python - <<'PY'
import json, glob
n = sum(1 for f in glob.glob('industry-c7/data/benchmark-v2/*.jsonl')
        for _ in open(f, encoding='utf-8'))
print(f"benchmark-v2: {n:,} instances across "
      f"{len(glob.glob('industry-c7/data/benchmark-v2/*.jsonl'))} projects")
PY
echo "PIPELINE_COMPLETE"
