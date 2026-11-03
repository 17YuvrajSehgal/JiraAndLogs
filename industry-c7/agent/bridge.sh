#!/bin/bash
# Persistent WSL -> cluster bridge for the localization agent.
#
# Why this exists: the agent originally spawned one `wsl.exe` per LLM call.
# At 10-12 workers those accumulated (44 observed), deadlocked WSL, and
# froze the batch twice with no error - the worst failure shape, because a
# wedged transport looks exactly like a slow one. Spawning wsl.exe, not the
# GPU, was always the scarce resource.
#
# This runs as ONE long-lived process inside WSL. Python drops request
# files into a spool directory and polls for matching responses; the bridge
# executes up to MAXJOBS of them concurrently over the already-authenticated
# SSH session. No per-call process creation on the Windows side at all.
#
# Protocol (deliberately dumb, so it cannot deadlock):
#   spool/req-<id>.json   written by Python (complete file, written via
#                         a .tmp + rename so the bridge never sees a partial)
#   spool/resp-<id>.json  written by the bridge, same rename discipline
#   spool/STOP            touch to end the bridge
#
# Usage (from WSL):  bash bridge.sh /mnt/c/.../spool

set -u
SPOOL="${1:?spool dir required}"
# ENDPOINT mode: an already-open port forward (cluster/tunnel.sh) carries
# every request, so a call costs one curl instead of two nested ssh logins.
# The nested form is capped by the control master's MaxSessions, which is
# why MAXJOBS sat at 6 and the GPU was never the limit. Forwarded TCP
# connections are channels, not sessions, so this scales with the server.
ENDPOINT="${ENDPOINT:-}"
# The compute node changes with every SLURM job. A hardcoded default here
# used to outlive the job it named: the bridge then curled a node with no
# server, every call came back empty, and the harness recorded llm_error
# per instance rather than failing - a whole batch of nothing that looks
# like a batch. Discover it from the serve log, same as cluster/tunnel.sh,
# and refuse to start if there is no server.
if [ -z "$ENDPOINT" ]; then
  NODE="${NODE:-$(ssh trillium "grep -h '^node: ' \$(ls -t /scratch/yuvraj17/c7-llm/logs/serve-*.out 2>/dev/null | head -3) 2>/dev/null | head -1 | awk '{print \$2}'")}"
  if [ -z "$NODE" ]; then
    echo "no node found in recent serve logs. Is the vLLM job running?" >&2
    echo "start one, or run with: NODE=<node> bash bridge.sh $SPOOL" >&2
    exit 1
  fi
fi
MAXJOBS="${MAXJOBS:-6}"
CURL_TIMEOUT="${CURL_TIMEOUT:-300}"
mkdir -p "$SPOOL"

models_url () {
  if [ -n "$ENDPOINT" ]; then curl -s -m 15 "$ENDPOINT/v1/models"
  else ssh -o ConnectTimeout=20 trillium \
         "ssh trig-login01 'curl -s -m 15 http://$NODE:8000/v1/models'" 2>/dev/null
  fi
}

# Preflight: one real request before accepting work. Catches a dead or
# still-loading server now instead of 15 hours from now.
if ! models_url | grep -q '"id"'; then
  echo "server not reachable (job ended, still loading, or tunnel down)" >&2
  echo "  endpoint=${ENDPOINT:-ssh:$NODE:8000}" >&2
  exit 1
fi
echo "bridge up: spool=$SPOOL target=${ENDPOINT:-ssh:$NODE:8000} maxjobs=$MAXJOBS"

handle () {
  local req="$1" id="$2"
  if [ -n "$ENDPOINT" ]; then
    curl -s -m "$CURL_TIMEOUT" "$ENDPOINT/v1/chat/completions" \
         -H 'Content-Type: application/json' --data-binary @"$req" \
         > "$SPOOL/.tmp-$id" 2>"$SPOOL/.err-$id"
  else
  ssh -o ConnectTimeout=20 trillium \
      "ssh trig-login01 'curl -s -m $CURL_TIMEOUT \
         http://$NODE:8000/v1/chat/completions \
         -H \"Content-Type: application/json\" -d @-'" \
      < "$req" > "$SPOOL/.tmp-$id" 2>"$SPOOL/.err-$id"
  fi
  if [ ! -s "$SPOOL/.tmp-$id" ]; then
    printf '{"error":"empty response: %s"}' \
      "$(head -c 200 "$SPOOL/.err-$id" 2>/dev/null | tr -d '"\n')" \
      > "$SPOOL/.tmp-$id"
  fi
  mv -f "$SPOOL/.tmp-$id" "$SPOOL/resp-$id.json"
  rm -f "$req" "$SPOOL/.err-$id"
}

while true; do
  [ -e "$SPOOL/STOP" ] && { echo "bridge stopping"; break; }
  found=0
  for req in "$SPOOL"/req-*.json; do
    [ -e "$req" ] || continue
    found=1
    id=$(basename "$req" .json); id=${id#req-}
    # claim it so a second bridge instance cannot take the same request
    if mv "$req" "$SPOOL/.busy-$id" 2>/dev/null; then
      handle "$SPOOL/.busy-$id" "$id" &
      while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do sleep 0.2; done
    fi
  done
  [ "$found" = 0 ] && sleep 0.25
done
wait
