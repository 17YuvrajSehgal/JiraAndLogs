#!/bin/bash
# Open a laptop tunnel to the currently-running vLLM server on Trillium.
# Finds the newest serving job's node from its log, then forwards
# localhost:8000 -> node:8000 through tri-login + trig-login01.
# Run from WSL (where the authenticated trillium SSH session lives):
#   bash tunnel.sh            # then: curl http://localhost:8000/v1/models
set -e
NODE=$(ssh trillium "grep -h '^node: ' \$(ls -t /scratch/yuvraj17/c7-llm/logs/serve-*.out | head -3) 2>/dev/null | head -1 | awk '{print \$2}'")
[ -z "$NODE" ] && { echo "no running server found in recent logs"; exit 1; }
echo "tunneling localhost:8000 -> $NODE:8000 (Ctrl-C to stop)"
ssh -o ProxyJump=trillium -J trillium trig-login01 -L 8000:$NODE:8000 -N
