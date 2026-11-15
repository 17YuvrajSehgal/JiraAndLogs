#!/bin/bash
# Per-file comparison of the code on every cluster against the laptop.
R=/scratch/yuvraj17/c7-data
lst='cd $ROOTDIR && for f in industry-c7/agent/*.py industry-c7/scripts/*.py industry-c7/cluster/run-shard.sbatch industry-c7/cluster/submit-shard.sh industry-c7/cluster/c7_submit_full.sh industry-c7/cluster/c7_submit_workers.sh; do echo "$f $(tr -d "\r" < $f | sha256sum | cut -c1-16)"; done | LC_ALL=C sort'
( ROOTDIR=/mnt/c/workplace/JiraAndLogs; eval "$lst" ) > /tmp/code_laptop.txt
echo "laptop: $(wc -l < /tmp/code_laptop.txt) files"
for h in nibi fir rorqual trillium-gpu; do
  if [ $h = trillium-gpu ]; then echo "ROOTDIR=$R; $lst" | ssh trillium 'ssh trig-login01 bash -s' > /tmp/code_$h.txt 2>/dev/null
  else echo "ROOTDIR=$R; $lst" | ssh $h bash -s > /tmp/code_$h.txt 2>/dev/null; fi
  echo "$h: $(wc -l < /tmp/code_$h.txt) files; differing from laptop: $(diff /tmp/code_laptop.txt /tmp/code_$h.txt | grep -c '^[<>]')"
  diff /tmp/code_laptop.txt /tmp/code_$h.txt | grep '^[<>]' | head -8
done
