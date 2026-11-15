#!/bin/bash
# read-only: real elapsed time of my finished GPU jobs since Nov 5, and what is queued now
q='echo "--- finished/ended jobs"; sacct -u $USER -X -S 2026-11-05 -n -P -o JobID,JobName,State,Start,End,Elapsed,Timelimit,AllocTRES | grep -v PENDING | grep -iE "gpu" | sed -E "s/billing=[^,]*,//; s/,mem=[^,|]*//; s/,node=1//" | tail -25
echo "--- now"; squeue -u $USER -h -o "%.9i %.6j %.8T %.9M %.19S %r" | cut -c1-90'
for h in nibi fir rorqual; do echo "======== $h"; echo "$q" | timeout 120 ssh $h bash -s 2>&1; done
echo "======== trillium-gpu"; echo "$q" | timeout 120 ssh trillium 'ssh trig-login01 bash -s' 2>&1
