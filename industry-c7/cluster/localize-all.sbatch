#!/bin/bash
# Lexical retrieval over all 27 projects, one Trillium CPU node.
#
# Measured on the laptop: 4.57 s per instance, 38,001 instances, so ~48 h
# of single-threaded work. Each project is independent and one run uses
# about two cores, so a 192-core node absorbs all 27 at once and the
# wall time collapses to whatever the LARGEST project takes -- hive at
# 4,692 instances, roughly 6 h.
#
# localize.py imports nothing outside the standard library (verified),
# so there is no venv, no pip and no internet dependency here. That is
# the whole reason this phase is safe to run on a compute node; the
# tree-sitter stage is not, and is deliberately not in this job.
#
# Restartable: each project is skipped when its results file already
# parses, so a timeout is resumed by resubmitting the same script.
#
#SBATCH --account=def-naser2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=192
#SBATCH --time=12:00:00
#SBATCH --job-name=c7-localize
#SBATCH --output=/scratch/yuvraj17/c7-data/logs/localize-%j.out

set -uo pipefail
D=/scratch/yuvraj17/c7-data
cd "$D/industry-c7"
mkdir -p "$D/logs" data/results data/loclogs

echo "node=$(hostname)  job=${SLURM_JOB_ID:-none}  cores=$(nproc)"
python3 -c "import sys; print('python', sys.version.split()[0])"

# Biggest first. The tail is set by the longest project, so starting it
# last would leave 191 cores idle while hive finishes alone.
PROJECTS=$(python3 - <<'PY'
import json, pathlib
b = pathlib.Path("data/benchmark")
sz = []
for f in b.glob("*.jsonl"):
    if f.name.endswith("-memory.jsonl"):
        continue
    sz.append((sum(1 for _ in f.open(encoding="utf-8")), f.stem))
print(" ".join(p for _n, p in sorted(sz, reverse=True)))
PY
)
echo "order: $PROJECTS"

pids=()
for p in $PROJECTS; do
  out="data/results/${p}-instances.jsonl"
  if [ -s "$out" ]; then
    echo "skip $p (already has results)"
    continue
  fi
  python3 -u scripts/localize.py --project "$p" \
      > "data/loclogs/${p}.log" 2>&1 &
  pids+=($!)
  echo "started $p pid $!"
done

echo "${#pids[@]} projects running; waiting"
fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=$((fail + 1))
done

echo "=== finished, $fail non-zero exits ==="
for f in data/loclogs/*.log; do
  p=$(basename "$f" .log)
  n=$( [ -s "data/results/${p}-instances.jsonl" ] \
       && wc -l < "data/results/${p}-instances.jsonl" || echo 0 )
  printf '%-12s %7s rows   %s\n' "$p" "$n" "$(tail -1 "$f" | cut -c1-70)"
done
exit $fail
