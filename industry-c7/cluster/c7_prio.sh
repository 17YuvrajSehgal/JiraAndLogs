#!/bin/bash
# read-only: why are my jobs low priority, and what would start sooner
q='
echo "--- accounts I can submit under"; sacctmgr -nP show assoc user=$USER format=account,partition,qos 2>/dev/null | sort -u | head -8
echo "--- fair-share (account row, then my row). LevelFS < 1 means the group used more than its share"
for a in $(sacctmgr -nP show assoc user=$USER format=account 2>/dev/null | sort -u); do
  sshare -A $a -u $USER -n -P -o Account,User,RawShares,NormShares,RawUsage,EffectvUsage,LevelFS,FairShare 2>/dev/null | head -2; done
echo "--- who used the group share (top 5 users, GPU account)"
sshare -A def-naser2_gpu -a -n -P -o User,RawUsage,EffectvUsage 2>/dev/null | sort -t"|" -k2,2nr | head -6
echo "--- priority parts of my first pending job (priority age fairshare jobsize partition qos)"
sprio -h -u $USER -o "%.9i %.9Y %.8A %.9F %.8J %.9P %.6Q" 2>/dev/null | head -1
echo "--- priority weights"; scontrol show config 2>/dev/null | grep -E "PriorityWeight|PriorityDecayHalfLife|PriorityMaxAge" | tr -s " " | tr "\n" ";"; echo
echo "--- position: pending jobs with higher priority, per partition I am in"
for p in $(squeue -u $USER -h -t PD -o %P | tr "," "\n" | sort -u); do
  m=$(squeue -u $USER -h -t PD -o %Q | sort -n | tail -1)
  echo "  $p: $(squeue -h -t PD -p $p -o %Q | awk -v m=$m "\$1>m" | wc -l) ahead of $(squeue -h -t PD -p $p | wc -l) pending"; done
'
for h in nibi fir rorqual; do echo "======== $h"; echo "$q" | timeout 150 ssh $h bash -s 2>&1; done
echo "======== trillium-gpu"; echo "$q" | sed 's/def-naser2_gpu/def-naser2/' | timeout 150 ssh trillium 'ssh trig-login01 bash -s' 2>&1
