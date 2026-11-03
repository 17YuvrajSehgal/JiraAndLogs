#!/bin/bash
# Bring up the transport for an agent run: port forward, then bridge.
# Idempotent -- running it twice does not start a second of either.
#
# Run from WSL, where the authenticated trillium session lives:
#   bash up.sh [jobid]
#   MAXJOBS=32 bash up.sh 1225385
#
# Why a forward and not the nested ssh the bridge used to do: each request
# was two ssh logins, capped by the control master's MaxSessions, which is
# why MAXJOBS sat at 6 while the GPU idled. Forwarded connections are
# channels, so concurrency is bounded by the server instead.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
C7=$(cd "$HERE/.." && pwd)
PORT="${PORT:-8000}"
MAXJOBS="${MAXJOBS:-32}"
SPOOL="${SPOOL:-$C7/data/agent/spool}"
LOGS="${LOGS:-$C7/data/agent}"
JOB="${1:-}"

mkdir -p "$SPOOL" "$LOGS"
rm -f "$SPOOL"/STOP

# ---- 1. port forward -------------------------------------------------------
if curl -s -m 5 "http://localhost:$PORT/v1/models" 2>/dev/null | grep -q '"id"'; then
  echo "forward already up on :$PORT"
else
  pkill -f "ssh.*-L $PORT:.*:$PORT" 2>/dev/null || true
  nohup bash "$HERE/tunnel.sh" $JOB > "$LOGS/tunnel.log" 2>&1 &
  echo "tunnel starting (log: $LOGS/tunnel.log)"
  for i in $(seq 1 60); do
    curl -s -m 5 "http://localhost:$PORT/v1/models" 2>/dev/null | grep -q '"id"' && break
    sleep 10
  done
  if ! curl -s -m 5 "http://localhost:$PORT/v1/models" 2>/dev/null | grep -q '"id"'; then
    echo "forward did not come up; see $LOGS/tunnel.log" >&2
    tail -5 "$LOGS/tunnel.log" >&2
    exit 1
  fi
  echo "forward up on :$PORT"
fi
curl -s -m 5 "http://localhost:$PORT/v1/models" | head -c 200; echo

# ---- 2. bridge -------------------------------------------------------------
if pgrep -f "bridge.sh $SPOOL" > /dev/null; then
  echo "bridge already running (maxjobs unchanged; kill it to change)"
else
  ENDPOINT="http://localhost:$PORT" MAXJOBS="$MAXJOBS" \
    nohup bash "$C7/agent/bridge.sh" "$SPOOL" > "$LOGS/bridge.log" 2>&1 &
  sleep 4
  if ! pgrep -f "bridge.sh $SPOOL" > /dev/null; then
    echo "bridge failed to start:" >&2; tail -5 "$LOGS/bridge.log" >&2; exit 1
  fi
  echo "bridge up, maxjobs=$MAXJOBS (log: $LOGS/bridge.log)"
fi
head -2 "$LOGS/bridge.log" 2>/dev/null
echo "ready"
