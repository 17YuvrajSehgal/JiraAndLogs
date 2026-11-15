#!/bin/bash
# One tool for the multi-cluster run. Lives in industry-c7/cluster/. Run from WSL:
#   bash c7_fleet.sh status            what is queued / running / written, everywhere
#   bash c7_fleet.sh stage             push code + small inputs, prove the tree works
#   bash c7_fleet.sh verify            is the dataset byte-identical everywhere?
#   bash c7_fleet.sh submit [--test-only]
#   bash c7_fleet.sh monitor [minutes] loop: one run per tag, on one cluster only
#   bash c7_fleet.sh cancel-old-nibi   the five jobs submitted before the queue existed
#
# narval is left out on purpose: it has no agent venv, and its A100-40GB
# cards would serve at TP=2, a different parallel layout from every other
# shard.
CLUSTERS="${CLUSTERS:-nibi fir rorqual trillium-gpu}"
R=/scratch/yuvraj17/c7-data
W=/mnt/c/workplace/JiraAndLogs

rsh () {  # run stdin as a script on a cluster
  if [ "$1" = trillium-gpu ]; then timeout -k 10 "${T:-120}" ssh -o BatchMode=yes trillium 'ssh trig-login01 bash -s'
  else timeout -k 10 "${T:-120}" ssh -o BatchMode=yes "$1" bash -s; fi
}
rhost () { [ "$1" = trillium-gpu ] && echo trillium || echo "$1"; }   # rsync target

case "${1:-status}" in
status)
  for h in $CLUSTERS; do
    echo "================ $h"
    rsh "$h" <<'EOF' 2>&1 | tail -30
cd /scratch/$USER/c7-data || exit 1
squeue -u $USER -h -o "%.10i %.10j %.8T %.9M %.19S %R" | sed 's/^/  job /'
for f in industry-c7/data/agent/agent-wf*.jsonl industry-c7/data/agent/agent-lc1000*.jsonl industry-c7/data/agent/agent-wfoff*.jsonl; do
  [ -e "$f" ] && printf '  rows %6d  %s\n' "$(grep -c . $f)" "$(basename $f)"; done
for d in claimed done failed started; do
  n=$(ls queue/$d 2>/dev/null | tr '\n' ' '); [ -n "$n" ] && echo "  $d: $n"; done
EOF
  done ;;

stage)
  cd $W || exit 1
  for h in $CLUSTERS; do
    echo "================ $h"; t=$(rhost $h)
    rsync -a --exclude __pycache__ --exclude '*.pyc' industry-c7/agent industry-c7/scripts industry-c7/cluster "$t:$R/industry-c7/" \
      && rsync -a industry-c7/data/results/*-noise-dump.jsonl industry-c7/data/results/baseline-sample.json industry-c7/data/results/baseline-pilot.json "$t:$R/industry-c7/data/results/" \
      && rsync -a industry-c7/cluster/c7_submit_full.sh industry-c7/cluster/c7_submit_workers.sh "$t:$R/" \
      && { [ "${STAGE_TASKS:-1}" != 1 ] || rsync -a industry-c7/cluster/tasks/ "$t:$R/queue/pending/"; } || { echo "  RSYNC FAILED"; continue; }
    T=600 rsh "$h" <<'EOF' 2>&1 | tail -8
cd /scratch/$USER/c7-data || exit 1
sed -i 's/\r$//' c7_submit_full.sh c7_submit_workers.sh industry-c7/cluster/*.sh industry-c7/cluster/*.sbatch $(ls queue/pending/*.task 2>/dev/null)
mkdir -p queue/{pending,claimed,done,failed,skip,started,finished}
echo "  tasks pending: $(ls queue/pending/*.task 2>/dev/null | wc -l)"
echo "  code: $(cat industry-c7/agent/*.py industry-c7/scripts/*.py industry-c7/cluster/run-shard.sbatch industry-c7/cluster/submit-shard.sh c7_submit_full.sh | sha256sum | cut -c1-16)"
PY=/scratch/$USER/c7-llm/agent-venv/bin/python
[ -x $PY ] || { echo "  NO AGENT VENV"; exit 1; }
echo "  e2e: $($PY industry-c7/agent/test_e2e_v4.py 2>&1 | grep -E 'checks passed|^FAIL|Traceback' | head -3 | tr '\n' ' ')"
EOF
  done
  echo "================ laptop"
  cd $W && echo "  code: $(cat industry-c7/agent/*.py industry-c7/scripts/*.py industry-c7/cluster/run-shard.sbatch industry-c7/cluster/submit-shard.sh industry-c7/cluster/c7_submit_full.sh | tr -d '\r' | sha256sum | cut -c1-16)" ;;

verify)
  manifest='
cd $ROOTDIR || exit 1
( cd industry-c7/data/benchmark && for f in *.jsonl *.json; do echo "bench/$f $(sha256sum < $f | cut -c1-20)"; done
  cd ../results && for f in *-instances.jsonl *-summary.json *-noise-dump.jsonl baseline-sample.json baseline-pilot.json; do echo "res/$f $(sha256sum < $f | cut -c1-20)"; done ) | sort > /tmp/c7_manifest.$$ 2>/dev/null
echo "files=$(wc -l < /tmp/c7_manifest.$$) all=$(sha256sum < /tmp/c7_manifest.$$ | cut -c1-16)"
cat /tmp/c7_manifest.$$; rm -f /tmp/c7_manifest.$$'
  mkdir -p /tmp/c7v
  ( export ROOTDIR=$W; eval "$manifest" ) > /tmp/c7v/laptop.txt 2>/dev/null
  echo "laptop        $(head -1 /tmp/c7v/laptop.txt)"
  for h in $CLUSTERS; do
    echo "ROOTDIR=$R; $manifest" | T=900 rsh "$h" > /tmp/c7v/$h.txt 2>/dev/null
    d=$(diff <(tail -n +2 /tmp/c7v/laptop.txt) <(tail -n +2 /tmp/c7v/$h.txt) | grep -c '^[<>]')
    printf '%-13s %s   lines differing from laptop: %s\n' "$h" "$(head -1 /tmp/c7v/$h.txt)" "$d"
    [ "$d" != 0 ] && diff <(tail -n +2 /tmp/c7v/laptop.txt) <(tail -n +2 /tmp/c7v/$h.txt) | grep '^[<>]' | head -8
  done
  echo "--- repos: do sampled snapshot commits exist? (refs differ between mirrors by design)"
  for h in $CLUSTERS; do
    T=900 rsh "$h" <<'EOF' 2>&1 | tail -2 | sed "s/^/$h  /"
cd /scratch/$USER/c7-data || exit 1
/scratch/$USER/c7-llm/agent-venv/bin/python - <<'PY'
import json, random, subprocess, sys
sys.path.insert(0, "industry-c7/scripts")
from localize import BENCH, FULL_REPOS, PROJECTS
ok = bad = 0
for p in sorted(PROJECTS):
    rows = [json.loads(l) for l in (BENCH / f"{p}.jsonl").open(encoding="utf-8")]
    for b in random.Random(1).sample(rows, min(15, len(rows))):
        r = subprocess.run(["git", "--git-dir", str(FULL_REPOS[p]), "cat-file", "-e", b["snapshot_sha"] + "^{commit}"],
                           capture_output=True)
        ok += r.returncode == 0; bad += r.returncode != 0
print(f"repos={len(FULL_REPOS)} sampled snapshot commits present: {ok}, missing: {bad}")
PY
EOF
  done ;;

submit)
  shift
  for h in $CLUSTERS; do
    echo "================ $h"
    echo "cd /scratch/\$USER/c7-data && bash c7_submit_full.sh $* 2>&1 | grep -E 'Submitted|to start at|REFUS|rror|cluster=' " | T=300 rsh "$h" 2>&1 | tail -14
  done ;;

workers)
  # bash c7_fleet.sh workers <n> <walltime> <b1|b2|b3> [--test-only]
  shift
  for h in $CLUSTERS; do
    echo "================ $h"
    echo "bash /scratch/yuvraj17/c7-data/c7_submit_workers.sh $*" | T=300 rsh "$h" 2>&1 | tail -6
  done ;;

cancel-shard-jobs)
  # the per-shard jobs (names c7-s1..c7-s5), and only while still PENDING
  for h in $CLUSTERS; do
    echo "================ $h"
    echo 'for j in $(squeue -u $USER -h -t PD -n c7-s1,c7-s2,c7-s3,c7-s4,c7-s5 -o %i); do scancel $j && echo "  cancelled $j"; done; echo "  left: $(squeue -u $USER -h | wc -l)"' | T=120 rsh "$h" 2>&1 | tail -8
  done ;;

cancel-old-nibi)
  # exactly the five job ids submitted at 01:55 with the pre-queue script,
  # and only while they are still PENDING
  ssh nibi 'for j in 26681423 26681424 26681425 26681426 26681427; do
      s=$(squeue -h -j $j -o %T 2>/dev/null); echo "  $j ${s:-gone}"
      [ "$s" = PENDING ] && scancel $j && echo "    cancelled"; done' ;;

monitor)
  # One run per tag. A job writes queue/started/<tag> when it begins a tag
  # (server already up). The first cluster to do so owns the tag; every
  # other cluster gets queue/skip/<tag>, and its job moves on to its next
  # tag instead of repeating the work. Nothing is cancelled: a duplicate
  # job that starts late is spare capacity for the seeds.
  mins="${2:-600}"; end=$(( $(date +%s) + mins * 60 ))
  mkdir -p /tmp/c7mon
  # cluster task state rows, rewritten every poll (state: running, stopped = cut
  # off and resumable, done, FAILED). An unreachable cluster keeps its old lines.
  TRACK="${TRACK:-/mnt/c/workplace/JiraAndLogs/c7-task-tracker.txt}"
  while [ "$(date +%s)" -lt "$end" ]; do
    : > /tmp/c7mon/started.txt
    beat="$(date +%m-%d\ %H:%M)"
    for h in $CLUSTERS; do
      echo 'cd /scratch/$USER/c7-data/queue/started 2>/dev/null && for f in *; do [ -e "$f" ] && echo "$f $(cut -d" " -f1 $f)"; done
            cd /scratch/$USER/c7-data && for f in queue/started/*; do n=${f##*/}; [ -e "$f" ] || continue; st=stopped; [ -d queue/claimed/$n ] && st=running; [ -e queue/failed/$n ] && st=FAILED; [ -e queue/done/$n ] && st=done; echo "#T $n $st $(wc -l < industry-c7/data/agent/agent-${n#*-}.jsonl 2>/dev/null || echo 0)"; done
            echo "#Q $(squeue -u $USER -h -t R | wc -l) $(squeue -u $USER -h -t PD | wc -l) $(cat /scratch/$USER/c7-data/industry-c7/data/agent/agent-wf-t*.jsonl 2>/dev/null | wc -l)"' \
        | T=60 rsh "$h" 2>/dev/null > /tmp/c7mon/$h.raw
      grep -v '^#' /tmp/c7mon/$h.raw | sed "s/^/$h /" >> /tmp/c7mon/started.txt
      # which task is where: one line per (task, cluster) that has started it
      grep -q '^#Q' /tmp/c7mon/$h.raw && { grep -v "^$h " "$TRACK" 2>/dev/null; grep '^#T' /tmp/c7mon/$h.raw | sed "s/^#T/$h/"; } | sort -k2,2 -k1,1 > "$TRACK.new" && mv "$TRACK.new" "$TRACK"
      q=$(grep '^#Q' /tmp/c7mon/$h.raw | cut -d' ' -f2-)
      # one heartbeat line per poll: running / pending / rows written
      beat="$beat | $h R/PD/rows ${q:-UNREACHABLE}"
    done
    echo "$beat"
    # owner = earliest start per tag
    sort -k2,2 -k3,3n /tmp/c7mon/started.txt | awk '!seen[$2]++ {print $2, $1}' > /tmp/c7mon/owner.txt
    while read -r tag owner; do
      for h in $CLUSTERS; do
        [ "$h" = "$owner" ] && continue
        grep -q "^$h $tag$" /tmp/c7mon/skipped.txt 2>/dev/null && continue
        echo "mkdir -p /scratch/\$USER/c7-data/queue/skip && echo $owner > /scratch/\$USER/c7-data/queue/skip/$tag" \
          | T=60 rsh "$h" 2>/dev/null && echo "$h $tag" >> /tmp/c7mon/skipped.txt \
          && echo "$(date +%H:%M) $tag is running on $owner -> $h will skip it"
      done
    done < /tmp/c7mon/owner.txt
    sleep 150
  done ;;
esac
