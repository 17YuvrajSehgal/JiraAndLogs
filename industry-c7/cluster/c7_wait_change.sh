#!/bin/bash
# Block until something changes in the fleet, then print it and exit, so
# the session that launched this is told. A change is: a job starts
# running, a job leaves the queue, or the monitor process is gone.
#   bash c7_wait_change.sh [max-minutes]
LOG=/mnt/c/workplace/JiraAndLogs/c7-fleet-monitor.log
max="${1:-45}"; end=$(( $(date +%s) + max * 60 ))
sig () { grep 'R/PD/rows' "$LOG" 2>/dev/null | tail -1 | grep -oE 'rows [0-9]+ [0-9]+' | tr '\n' ' '; }  # running + pending per cluster
first=$(sig)
while [ "$(date +%s)" -lt "$end" ]; do
  pgrep -f 'c7_fleet.sh monitor' >/dev/null || { echo "MONITOR IS NOT RUNNING"; break; }
  now=$(sig)
  [ "$now" != "$first" ] && { echo "CHANGE"; break; }
  sleep 60
done
echo "--- last monitor lines"; tail -4 "$LOG"
echo "--- status"; bash ~/c7_fleet.sh status 2>&1 | grep -vE "PENDING" | head -60
