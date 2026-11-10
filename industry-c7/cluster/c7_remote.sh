#!/bin/bash
# Run a local script on trig-login01 through the trillium hop.
#   wsl bash c7_remote.sh <script-on-windows-side.sh>
sed 's/\r$//' "$1" | ssh trillium 'ssh trig-login01 bash -s'
