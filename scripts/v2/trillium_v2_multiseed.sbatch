#!/usr/bin/env bash
#SBATCH --job-name=v2-multiseed
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=24
#SBATCH --time=20:00:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Task #8 -- multi-seed retriever training on ALL THREE datasets, World of Logs
# included. The submission trained the telemetry retrievers under 3 seeds and
# the real-data retriever ONCE, which is the gap R3 raised: a fixed seed is not
# a substitute for repetition when the only stochastic step is SGD on a GPU.
#
# We measured the stakes before committing the compute (scripts/rebuttal/
# 07_seed_vs_sampling_variance.py): the seed contributes ~1% of Hit@5 variance
# on OTel Demo but ~32% on Online Boutique, so single-seed intervals genuinely
# understate uncertainty on at least one dataset. World of Logs is unmeasured
# and carries the paper's headline claims.
#
# Seeds 42, 1, 2 already exist for the two telemetry datasets; this adds 3 and 4
# there and runs all five on WoL. Existing outputs are skipped, so the job is
# restartable after a timeout or the SciNet switch failures.
#
#   sbatch --account=<your-rap> scripts/v2/trillium_v2_multiseed.sbatch
#
# Budget: WoL retraining dominates (~3h/seed). If the 20h wall clock is tight,
# submit twice with V2_SEEDS="42 1 2" then V2_SEEDS="3 4".
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="${V2_REPO:-/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs}"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
mkdir -p logs

JOBID="${SLURM_JOB_ID:-manual-$(date +%s)}"
LOGFILE="${REPO}/logs/v2_multiseed_${JOBID}.log"
exec > >(stdbuf -oL -eL tee -a "$LOGFILE") 2>&1

module load python/3.12 arrow/21.0.0
source .venv/bin/activate
export PYTHONPATH="src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONUTF8=1
# /project is NOT subject to the scratch purge, which is what removed the
# previous /scratch/$USER/hf_cache and made every seed fail in ~9s with
# LocalEntryNotFoundError. Pre-populate with scripts/v2/fetch_models.sh.
export HF_HOME="${V2_HF_HOME:-/project/def-naser2/${USER}/hf_cache}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export BIENC_BM25_JOBS="${SLURM_CPUS_PER_TASK:-24}" TOKENIZERS_PARALLELISM=false

# Fail fast and loudly rather than "continuing" through every seed. A missing
# cache is a setup error, not a per-seed failure, and burning the whole seed
# grid on it wastes an allocation and looks like a result.
if [[ ! -d "$HF_HOME" ]]; then
  echo "!! HF_HOME does not exist: $HF_HOME"
  echo "!! Run scripts/v2/fetch_models.sh on a LOGIN node first (compute nodes have no outbound network)."
  exit 1
fi
python - <<'PY' || exit 1
import os, sys
from huggingface_hub import snapshot_download
try:
    p = snapshot_download("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)
    print(f"  HF cache OK: {p}")
except Exception as e:
    print(f"!! HF cache unusable at {os.environ.get('HF_HOME')}: {type(e).__name__}")
    sys.exit(1)
PY

SEEDS="${V2_SEEDS:-42 1 2 3 4}"
echo "=== v2 multi-seed  node=$(hostname)  $(date -Is) ==="
echo "  commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "  seeds:  $SEEDS"

# dataset -> "<global-dir-name> <humanized-subdir>"
declare -A SUB=(
  [online-boutique]="2026-05-25-dataset-v5-large-global bulk-20260531"
  [otel-demo]="2026-06-09-otel-demo-v1-global bulk-20260531"
  [wol-v3]="2026-06-17-wol-real-v3-global bulk-20260617"
)

for label in otel-demo online-boutique wol-v3; do
  set -- ${SUB[$label]}
  gdir="data/derived/global/$1"; hsub="$2"
  if [[ ! -d "$gdir" ]]; then
    echo "!! missing $gdir -- skipping $label"; continue
  fi
  for seed in $SEEDS; do
    out="paper-results-v2/multiseed/$label/seed$seed"
    if [[ -f "$out/biencoder-mode3-results.json" ]]; then
      echo "--- [$label seed=$seed] already present, skipping ---"
      continue
    fi
    mkdir -p "$out"
    echo ""
    echo "--- [$label seed=$seed] $(date -Is) ---"
    python scripts/research-lab/run_biencoder_wol_mode3.py \
        --global-dir "$gdir" \
        --humanized-subdir "$hsub" \
        --out-dir "$out" \
        --seed "$seed" \
      || echo "!! FAILED $label seed=$seed (continuing)"
  done
done

echo ""
echo "=== seed summary ==="
python - <<'PY'
import json, pathlib, statistics
root = pathlib.Path("paper-results-v2/multiseed")
for ds in sorted(p.name for p in root.glob("*") if p.is_dir()):
    vals = {}
    for s in sorted((root / ds).glob("seed*")):
        f = s / "biencoder-mode3-results.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        c = d.get("coarse") or {}
        if c.get("hit_at_5") is not None:
            vals[s.name] = c["hit_at_5"]
    if not vals:
        continue
    v = list(vals.values())
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    print(f"  {ds:<18} n={len(v)}  Hit@5 mean={statistics.mean(v):.4f} "
          f"sd={sd:.4f}  range={max(v)-min(v):.4f}")
    for k, x in vals.items():
        print(f"      {k:<8} {x:.4f}")
PY

echo ""
echo "=== done: $(date -Is) ==="
