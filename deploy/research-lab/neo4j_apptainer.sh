#!/usr/bin/env bash
# Start / wait / stop a single-node Neo4j Community instance via Apptainer.
#
# Trillium has no Docker, so the Hybrid-RRF graph retriever's Neo4j backend
# runs from an Apptainer sandbox built from docker://neo4j:5.26-community
# (a sandbox dir, not a .sif — the login node's mksquashfs segfaults).
# The DB data persists under $NEO4J_BASE/data so the v3 graph survives across
# jobs: load it once with reload_neo4j.py, reuse thereafter.
#
# Verified working pattern: `apptainer run <sandbox> &` launches the neo4j
# docker-entrypoint (CMD=neo4j -> `neo4j console`) in the foreground, which we
# background and track via a pidfile. Bolt comes up on 127.0.0.1:7687.
#
# Usage:
#   neo4j_apptainer.sh start     # launch neo4j + block until bolt is ready
#   neo4j_apptainer.sh wait      # just block until bolt answers
#   neo4j_apptainer.sh stop      # kill the neo4j process
#
# Config via env (sensible defaults):
#   NEO4J_SANDBOX   sandbox dir (default /scratch/$USER/apptainer/neo4j-sandbox)
#   NEO4J_BASE      persistent data/logs root (default /scratch/$USER/neo4j-v3)
#   NEO4J_PASSWORD  bolt password (default 123456789 — matches the codebase)
#   NEO4J_HEAP      JVM heap (default 16G)
#   NEO4J_PAGECACHE page cache (default 16G)
set -uo pipefail

NEO4J_SANDBOX="${NEO4J_SANDBOX:-/scratch/$USER/apptainer/neo4j-sandbox}"
NEO4J_BASE="${NEO4J_BASE:-/scratch/$USER/neo4j-v3}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-123456789}"
NEO4J_HEAP="${NEO4J_HEAP:-16G}"
NEO4J_PAGECACHE="${NEO4J_PAGECACHE:-16G}"
PIDFILE="$NEO4J_BASE/neo4j.pid"

start() {
    mkdir -p "$NEO4J_BASE/data" "$NEO4J_BASE/logs" "$NEO4J_BASE/import"
    echo "[neo4j] launching from sandbox $NEO4J_SANDBOX"
    echo "[neo4j] data dir: $NEO4J_BASE/data (heap=$NEO4J_HEAP pagecache=$NEO4J_PAGECACHE)"
    # --cleanenv is REQUIRED: without it apptainer forwards the host's NEO4J_*
    # vars (NEO4J_URI / NEO4J_DATABASE / NEO4J_BASE / NEO4J_HEAP / ...) into the
    # container, where neo4j's entrypoint parses every NEO4J_* var as a config
    # setting and aborts ("No declared setting with name: ..."). With cleanenv
    # only the explicit --env settings below reach neo4j.
    apptainer run --cleanenv --writable-tmpfs \
        --bind "$NEO4J_BASE/data:/data" \
        --bind "$NEO4J_BASE/logs:/logs" \
        --bind "$NEO4J_BASE/import:/import" \
        --env NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
        --env NEO4J_server_default__listen__address=127.0.0.1 \
        --env NEO4J_server_bolt_listen__address=127.0.0.1:7687 \
        --env NEO4J_server_http_listen__address=127.0.0.1:7474 \
        --env NEO4J_server_memory_heap_initial__size="${NEO4J_HEAP}" \
        --env NEO4J_server_memory_heap_max__size="${NEO4J_HEAP}" \
        --env NEO4J_server_memory_pagecache_size="${NEO4J_PAGECACHE}" \
        "$NEO4J_SANDBOX" > "$NEO4J_BASE/logs/console.out" 2>&1 &
    echo $! > "$PIDFILE"
    echo "[neo4j] pid=$(cat "$PIDFILE") (console: $NEO4J_BASE/logs/console.out)"
    wait_ready
}

wait_ready() {
    echo "[neo4j] waiting for bolt on 127.0.0.1:7687 ..."
    for i in $(seq 1 120); do   # up to ~10 min
        if python - <<PY 2>/dev/null
import sys
from neo4j import GraphDatabase
try:
    d = GraphDatabase.driver("neo4j://127.0.0.1:7687",
                             auth=("neo4j", "${NEO4J_PASSWORD}"))
    d.verify_connectivity(); d.close()
except Exception:
    sys.exit(1)
PY
        then
            echo "[neo4j] ready after ~$((i*5))s"
            return 0
        fi
        sleep 5
    done
    echo "[neo4j] ERROR: bolt not ready in time. Console tail:" >&2
    tail -40 "$NEO4J_BASE/logs/console.out" 2>/dev/null >&2 || true
    return 1
}

stop() {
    if [[ -f "$PIDFILE" ]]; then
        pid=$(cat "$PIDFILE")
        echo "[neo4j] stopping pid=$pid"
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 12); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$PIDFILE"
    else
        echo "[neo4j] no pidfile at $PIDFILE; nothing to stop"
    fi
}

case "${1:-}" in
    start) start ;;
    wait)  wait_ready ;;
    stop)  stop ;;
    *) echo "usage: $0 {start|wait|stop}" >&2; exit 2 ;;
esac
