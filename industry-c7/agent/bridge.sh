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
NODE="${NODE:-trig0051}"
MAXJOBS="${MAXJOBS:-6}"
CURL_TIMEOUT="${CURL_TIMEOUT:-300}"
mkdir -p "$SPOOL"
echo "bridge up: spool=$SPOOL node=$NODE maxjobs=$MAXJOBS"

handle () {
  local req="$1" id="$2"
  ssh -o ConnectTimeout=20 trillium \
      "ssh trig-login01 'curl -s -m $CURL_TIMEOUT \
         http://$NODE:8000/v1/chat/completions \
         -H \"Content-Type: application/json\" -d @-'" \
      < "$req" > "$SPOOL/.tmp-$id" 2>"$SPOOL/.err-$id"
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
