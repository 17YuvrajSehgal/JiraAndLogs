#!/usr/bin/env bash
# WoL Phase 3 analysis playbook — one-shot runner.
#
# Pre-requisite: WoL cascade predictions in
#   data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/
# must exist (at minimum: biencoder-predictions.jsonl).
#
# Run this AFTER the WoL cascade re-gen lands. It executes every
# Phase-3 analysis we ran on OB + OTel, with --dataset wol selected.
# Pace: smoke + 8 analyses, ~5 min total wall (predictions-backed
# skills are sub-millisecond).
#
# Usage:
#   bash scripts/agent/run_wol_phase3_analyses.sh

set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root
export PYTHONPATH=src

GLOBAL_DIR="data/derived/global/2026-06-11-wol-real-global"
DATASET_ID="2026-06-11-wol-real-global"
WOL_RESULTS="results/wol"
WOL_RUNS="data/agent_runs/wol"

mkdir -p "$WOL_RUNS"
mkdir -p \
  "$WOL_RESULTS/4.0-baseline" \
  "$WOL_RESULTS/3.6-failure-mode-catalog" \
  "$WOL_RESULTS/3.7-budget-curve" \
  "$WOL_RESULTS/3.8-tool-ablation" \
  "$WOL_RESULTS/4.1-skill-ablation" \
  "$WOL_RESULTS/4.3-bootstrap-cis" \
  "$WOL_RESULTS/4.4-capability-mask" \
  "$WOL_RESULTS/4.5-cost-vs-cascade" \
  "$WOL_RESULTS/4.8-failure-categories"

# ============================================================
# Pre-check — refuse to proceed if predictions are missing.
# ============================================================
if [[ ! -f "$GLOBAL_DIR/tch-lite-refit/biencoder-predictions.jsonl" ]]; then
  echo "FATAL: WoL BiEncoder predictions missing at:"
  echo "  $GLOBAL_DIR/tch-lite-refit/biencoder-predictions.jsonl"
  echo ""
  echo "Run the cascade first:"
  echo "  PYTHONPATH=src python scripts/research-lab/run_biencoder_wol_mode3.py --use-all-golds"
  exit 1
fi
echo "[wol-phase3] cascade predictions located ✓"

# ============================================================
# Stage 3 — baseline smoke
# ============================================================
echo ""
echo "=== [1/9] Baseline smoke ==="
python scripts/agent/smoke_wol.py \
  --global-dir "$GLOBAL_DIR" \
  --output "$WOL_RUNS/wol-smoke.json" \
  --trace-root "$WOL_RUNS/traces"

cp "$WOL_RUNS/wol-smoke.json" "$WOL_RESULTS/4.0-baseline/wol-smoke.json"
cp "$WOL_RUNS/wol-smoke.json" "$WOL_RESULTS/4.3-bootstrap-cis/wol-smoke.json"

TRACE_DIR="$WOL_RUNS/traces/smoke-$DATASET_ID"

# ============================================================
# Stage 4 — per-RQ analyses
# ============================================================
echo ""
echo "=== [2/9] §3.6 — failure-mode catalog ==="
python scripts/agent/failure_mode_catalog.py \
  --trace-root "$TRACE_DIR" \
  --output "$WOL_RESULTS/3.6-failure-mode-catalog/catalog.json"

echo ""
echo "=== [3/9] §3.7 — budget curve ==="
python scripts/agent/budget_curve.py \
  --dataset wol \
  --global-dir "$GLOBAL_DIR" \
  --output "$WOL_RESULTS/3.7-budget-curve/curve.json"

echo ""
echo "=== [4/9] §3.8 — tool subset ablation ==="
python scripts/agent/tool_ablation.py \
  --dataset wol \
  --global-dir "$GLOBAL_DIR" \
  --output "$WOL_RESULTS/3.8-tool-ablation/ablation.json"

echo ""
echo "=== [5/9] §4.1 — skill ablation ==="
python scripts/agent/skill_ablation.py \
  --dataset wol \
  --global-dir "$GLOBAL_DIR" \
  --output "$WOL_RESULTS/4.1-skill-ablation/ablation.json"

echo ""
echo "=== [6/9] §4.3 — bootstrap CIs ==="
python scripts/agent/bootstrap_headlines.py \
  --reports "$WOL_RESULTS/4.3-bootstrap-cis/wol-smoke.json"

echo ""
echo "=== [7/9] §4.4 — capability-mask sweep ==="
python scripts/agent/capability_mask_sweep.py \
  --dataset wol \
  --global-dir "$GLOBAL_DIR" \
  --output "$WOL_RESULTS/4.4-capability-mask/sweep.json"

echo ""
echo "=== [8/9] §4.5 — cost vs cascade ==="
python scripts/agent/cost_vs_cascade.py \
  --trace-root "$TRACE_DIR" \
  --output "$WOL_RESULTS/4.5-cost-vs-cascade/breakdown.json"

echo ""
echo "=== [9/9] §4.8 — failure categories ==="
python scripts/agent/failure_categories.py \
  --reports "$WOL_RESULTS/4.3-bootstrap-cis/wol-smoke.json" \
  --output "$WOL_RESULTS/4.8-failure-categories/categories.json"

echo ""
echo "=== All WoL Phase-3 analyses complete ==="
echo "Outputs at $WOL_RESULTS/"
ls -1 "$WOL_RESULTS/"
