# Small debugging pilot on the login node: the workflow arm and the free
# loop on the same 20 instances, against the server c7_probe.sh started.
S=/scratch/$USER; BASE=$S/c7-data; C7=$BASE/industry-c7
. $BASE/logs/login-pilot.env
PY=$S/c7-llm/agent-venv/bin/python
cd $BASE || exit 1
pkill -u $USER -f "run_agent.py --arm (wf|lc) --full --tag login2-" ; sleep 2; echo "old pilot runs left: $(pgrep -u $USER -f "tag login2-" | wc -l)"
$PY - <<'PY'
import json
d = json.load(open("industry-c7/data/results/baseline-pilot.json"))
ids = d["ids"][:20]
json.dump({"ids": ids, "from": "baseline-pilot.json[:20]"},
          open("industry-c7/data/results/login-pilot20.json", "w"))
print(len(ids), "ids;", " ".join(sorted({i.split(":")[0] for i in ids})))
PY
PROJ=$($PY -c "import json;print(' '.join('--project '+p for p in sorted({i.split(':')[0] for i in json.load(open('industry-c7/data/results/login-pilot20.json'))['ids']})))")
for arm in wf; do
  C7_LLM_URL=http://127.0.0.1:$PORT/v1 C7_MODEL=qwen3.8-27b nohup $PY industry-c7/agent/run_agent.py \
    --arm $arm --full --tag login4-$arm --workers 6 --seed 42 $PROJ \
    --subset industry-c7/data/results/login-pilot20.json \
    > $BASE/logs/login4-pilot-$arm.log 2>&1 &
  echo "started $arm pid $!"
done
