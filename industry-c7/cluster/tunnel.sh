#!/bin/bash
# Open a laptop tunnel to the running vLLM server on Trillium.
#
# The node comes from squeue, not from the serve logs. Log discovery picks
# the newest log file, which between submitting a job and its starting is
# still the PREVIOUS job's -- so the tunnel would point at a node with no
# server and every request would come back empty.
#
# Run from WSL, where the authenticated trillium session lives:
#   bash tunnel.sh            # then: curl http://localhost:8000/v1/models
#   bash tunnel.sh 1225385    # pin to one job id
set -u
PORT="${PORT:-8000}"
JOB="${1:-}"
Q="squeue -h -u yuvraj17 -n vllm-serve -t RUNNING -o '%i %N'"

row=$(ssh -o BatchMode=yes trillium "ssh -o BatchMode=yes trig-login01 \"$Q\"" 2>/dev/null \
      | { [ -n "$JOB" ] && grep "^$JOB " || cat; } | head -1)
JOBID=${row%% *}
NODE=${row##* }
if [ -z "${NODE:-}" ]; then
  echo "no RUNNING vllm-serve job${JOB:+ with id $JOB}." >&2
  ssh -o BatchMode=yes trillium \
      "ssh -o BatchMode=yes trig-login01 'squeue -u yuvraj17'" >&2 2>/dev/null
  exit 1
fi
echo "job $JOBID on $NODE"

# The server takes minutes to load. Wait for it to actually answer before
# claiming the tunnel is usable.
for i in $(seq 1 80); do
  if ssh -o BatchMode=yes trillium \
       "ssh -o BatchMode=yes trig-login01 'curl -s -m 5 http://$NODE:$PORT/v1/models'" \
       2>/dev/null | grep -q '"id"'; then
    echo "server answering after ~$((i * 15))s"
    break
  fi
  [ "$i" = 80 ] && { echo "server never came up; check the serve log" >&2; exit 1; }
  sleep 15
done

echo "tunneling localhost:$PORT -> $NODE:$PORT (Ctrl-C to stop)"
exec ssh -o ProxyJump=trillium -J trillium trig-login01 \
     -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
     -L "$PORT:$NODE:$PORT" -N
