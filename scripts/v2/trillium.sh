#!/usr/bin/env bash
# Driver for the v2 Trillium runs. Everything goes over one shared SSH
# connection (ControlPersist), so the Duo MFA prompt is answered once.
#
# First, from an interactive terminal, open the master connection:
#     ssh trillium            # answer the Duo prompt, then leave it open or exit
#
# After that the socket at ~/.ssh/sockets/ is reused for 12h and every command
# below runs without prompting.
#
# Usage:
#   scripts/v2/trillium.sh check          # connectivity, repo state, quota, GPU queue
#   scripts/v2/trillium.sh sync           # push v2 scripts + branch to the cluster
#   scripts/v2/trillium.sh submit <job>   # retrieval | multiseed
#   scripts/v2/trillium.sh status         # squeue for this user
#   scripts/v2/trillium.sh tail <jobid>   # follow a running job's log
#   scripts/v2/trillium.sh fetch          # pull paper-results-v2 back to the laptop
#
# ACCOUNT: the committed sbatch files carry no --account (the repo is
# double-blind). Export V2_ACCOUNT before submitting, e.g.
#     export V2_ACCOUNT=def-xxxxx
set -uo pipefail

HOST="${V2_HOST:-trillium}"
REMOTE="${V2_REPO:-/scratch/yuvraj17/JiraAndLogs_scratch/JiraAndLogs}"
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ssh_ok() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" true 2>/dev/null
}

require_conn() {
  if ! ssh_ok; then
    cat >&2 <<EOF
No shared SSH connection to '$HOST'.

Trillium uses Duo MFA, which cannot be answered non-interactively. Open the
master connection once from your own terminal:

    ssh $HOST

Answer the Duo prompt. The connection is then shared for 12h via ControlPersist
and this script will work without prompting. You can close that terminal; the
socket survives in ~/.ssh/sockets/.
EOF
    exit 1
  fi
}

case "${1:-}" in

check)
  require_conn
  echo "=== connection ==="
  ssh "$HOST" 'echo "  host: $(hostname)"; echo "  user: $(whoami)"'
  echo ""
  echo "=== repo ==="
  ssh "$HOST" "cd '$REMOTE' 2>/dev/null && \
      echo '  path:   $REMOTE' && \
      echo \"  branch: \$(git rev-parse --abbrev-ref HEAD 2>/dev/null)\" && \
      echo \"  commit: \$(git rev-parse --short HEAD 2>/dev/null)\" && \
      echo \"  dirty:  \$(git status --porcelain 2>/dev/null | wc -l) file(s)\" \
      || echo '  !! repo not found at $REMOTE'"
  echo ""
  echo "=== datasets present ==="
  ssh "$HOST" "cd '$REMOTE' 2>/dev/null && ls -d data/derived/global/*/ 2>/dev/null | sed 's/^/  /' || true"
  echo ""
  echo "=== allocation / quota ==="
  ssh "$HOST" 'command -v sshare >/dev/null && sshare -U 2>/dev/null | head -5; diskusage_report 2>/dev/null | head -8 || true'
  echo ""
  echo "=== my jobs ==="
  ssh "$HOST" 'squeue -u $USER -o "%.10i %.16j %.8T %.10M %.6D %R" 2>/dev/null || echo "  (squeue unavailable)"'
  ;;

sync)
  require_conn
  echo "=== syncing v2 scripts to $HOST:$REMOTE ==="
  # Only the things the jobs need. Never sync data/ or paper-results/.
  tar -C "$LOCAL" -cf - \
      scripts/v2 \
      scripts/research-lab/run_baseline_retrievers.py \
      scripts/research-lab/run_biencoder_wol_mode3.py \
    | ssh "$HOST" "mkdir -p '$REMOTE' && tar -C '$REMOTE' -xf - && echo '  extracted'"
  ssh "$HOST" "cd '$REMOTE' && chmod +x scripts/v2/*.sh scripts/v2/*.sbatch 2>/dev/null; \
      echo '  scripts/v2:'; ls scripts/v2 | sed 's/^/    /'"
  ;;

submit)
  require_conn
  job="${2:-}"
  case "$job" in
    retrieval) script="scripts/v2/trillium_v2_retrieval_rerun.sbatch" ;;
    multiseed) script="scripts/v2/trillium_v2_multiseed.sbatch" ;;
    *) echo "usage: $0 submit {retrieval|multiseed}" >&2; exit 2 ;;
  esac
  acct="${V2_ACCOUNT:-}"
  if [[ -z "$acct" ]]; then
    echo "!! V2_ACCOUNT is not set. Find yours with:  ssh $HOST sshare -U" >&2
    echo "   then:  export V2_ACCOUNT=def-xxxxx" >&2
    exit 2
  fi
  echo "=== submitting $script (account=$acct) ==="
  ssh "$HOST" "cd '$REMOTE' && sbatch --account='$acct' '$script'"
  ;;

status)
  require_conn
  ssh "$HOST" 'squeue -u $USER -o "%.10i %.18j %.8T %.10M %.10L %.6D %R"'
  ;;

tail)
  require_conn
  jid="${2:?usage: $0 tail <jobid>}"
  ssh "$HOST" "cd '$REMOTE' && tail -f -n 200 logs/slurm-*-${jid}.out"
  ;;

fetch)
  require_conn
  echo "=== fetching paper-results-v2 from $HOST ==="
  mkdir -p "$LOCAL/paper-results-v2"
  # Exclude the bulky per-window prediction dumps unless explicitly asked.
  ssh "$HOST" "cd '$REMOTE' && tar -cf - paper-results-v2 2>/dev/null" \
    | tar -C "$LOCAL" -xf - && echo "  done"
  find "$LOCAL/paper-results-v2" -name "*.json" -newermt '-1 day' | head -20
  ;;

*)
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
