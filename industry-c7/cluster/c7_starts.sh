#!/bin/bash
# read-only: scheduler start estimates for my pending jobs
q='squeue -u $USER -h -o "%.10i %.8j %.8T %.10l %.19S %r" | head -8'
for h in nibi fir rorqual; do echo "== $h"; echo "$q" | timeout 90 ssh $h bash -s 2>&1; done
echo "== trillium-gpu"; echo "$q" | timeout 90 ssh trillium 'ssh trig-login01 bash -s' 2>&1
