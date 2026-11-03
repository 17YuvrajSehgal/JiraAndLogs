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
# Single hop. The trillium login node routes to the GPU nodes directly
# (verified: curl trig0012:8000 from tri-login05 returns 200), so the
# forward rides the existing authenticated session. Going through
# trig-login01 with -J needs credentials for THAT host on this laptop,
# which only exist on trillium, so the jump form binds nothing and the
# port stays closed while ssh sits there looking alive.
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
     -o ServerAliveCountMax=6 \
     -L "$PORT:$NODE:$PORT" -N trillium
