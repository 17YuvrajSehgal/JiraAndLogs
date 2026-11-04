#!/bin/bash
# Dry run of the WHOLE cluster path with a stub model, so a 6 h job does
# not die on something structural. No GPU is used and no real request is
# made: a tiny local HTTP server answers in the OpenAI shape.
#
# What this actually proves, in the order it would otherwise bite:
#   1. the two python environments coexist (vLLM's 3.12, the agent's 3.11)
#   2. bridge.sh works in ENDPOINT mode, i.e. local curl and not ssh
#   3. the spool round-trip works on /scratch
#   4. run_agent builds the population, honours --subset, and runs both arms
#   5. rows, metrics and transcripts are actually written
#
# What it cannot prove: answer quality. That needs the real model.
set -uo pipefail
S=/scratch/yuvraj17
BASE=$S/JiraAndLogs_scratch/c7run
C7=$BASE/JiraAndLogs/industry-c7
PORT=${PORT:-8771}
SPOOL=$C7/data/agent/spool-smoke
mkdir -p "$BASE/logs" "$SPOOL"
rm -f "$SPOOL"/* 2>/dev/null

module load python/3.11 >/dev/null 2>&1
PY=$BASE/venv/bin/python3
echo "agent python: $($PY -V 2>&1)"

# ---- 1. the stub model ----------------------------------------------------
cat > "$BASE/stub_server.py" <<'PY'
import json, re
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
PORT = int(sys.argv[1])
PATH_RE = re.compile(r"([\w./+-]+\.(?:scala|java|hpp|cpp|cc|h|c)\b)")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "qwen3.8-27b"}]})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except Exception: body = {}
        # Echo back a path the prompt itself mentions, so the harness has
        # something real to resolve; otherwise every answer is EMPTY and
        # the output-writing path is never exercised.
        text = json.dumps(body)[:200000]
        paths = PATH_RE.findall(text)
        pick = paths[0] if paths else "src/main.c"
        msg = {"role": "assistant",
               "content": f"Looking at it.\n```\n{pick}\nline: 1\nfunction: f\n```"}
        self._send({"choices": [{"message": msg, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
PY
"$PY" "$BASE/stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null; touch "$SPOOL/STOP" 2>/dev/null' EXIT
sleep 2
curl -s -m 5 "http://localhost:$PORT/v1/models" | grep -q qwen3.8-27b \
  && echo "stub model up on :$PORT" || { echo "stub FAILED"; exit 1; }

# ---- 2. the bridge, in ENDPOINT mode --------------------------------------
ENDPOINT="http://localhost:$PORT" MAXJOBS=8 \
  bash "$C7/agent/bridge.sh" "$SPOOL" > "$BASE/logs/smoke-bridge.log" 2>&1 &
BRIDGE=$!
trap 'kill $STUB $BRIDGE 2>/dev/null; touch "$SPOOL/STOP" 2>/dev/null' EXIT
sleep 4
grep -q "bridge up" "$BASE/logs/smoke-bridge.log" \
  && echo "bridge up: $(grep 'bridge up' "$BASE/logs/smoke-bridge.log")" \
  || { echo "BRIDGE FAILED"; cat "$BASE/logs/smoke-bridge.log"; exit 1; }

# ---- 3. both arms, two instances each -------------------------------------
cd "$BASE/JiraAndLogs" || exit 1
export C7_SPOOL="$SPOOL"
for arm in locagent cosil; do
  rm -f "$C7/data/agent/agent-smoke-$arm.jsonl"
  echo "=== $arm ==="
  C7_SPOOL="$SPOOL" timeout 900 "$PY" industry-c7/agent/run_agent.py \
      --arm "$arm" --tag "smoke-$arm" \
      --subset industry-c7/data/results/baseline-pilot.json \
      --full --limit 2 --workers 2 2>&1 | tail -4
done

# ---- 4. what actually landed ----------------------------------------------
echo "=== rows written ==="
for arm in locagent cosil; do
  f=$C7/data/agent/agent-smoke-$arm.jsonl
  n=$(grep -c . "$f" 2>/dev/null || echo 0)
  echo "  $arm: $n rows"
  [ "$n" -gt 0 ] && "$PY" - "$f" <<'PY'
import json, sys
for l in open(sys.argv[1], encoding="utf-8"):
    if not l.strip(): continue
    r = json.loads(l)
    print(f"     {r['id']:28s} err={r.get('error')} stop={r.get('stop_reason')} "
          f"rank={len(r.get('ranking') or [])} acc@5={r.get('metrics',{}).get('acc@5')} "
          f"empty={r.get('empty')}")
PY
done
echo "=== transcripts ==="
ls "$C7/data/agent/transcripts" | grep -c smoke || echo 0
