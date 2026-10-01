#!/usr/bin/env bash
# Populate the HuggingFace cache for every model the v2 jobs need.
#
# RUN THIS ON A LOGIN NODE. Compute nodes have no outbound network, which is why
# the jobs set HF_HUB_OFFLINE=1; if the cache is cold they fail immediately with
#   LocalEntryNotFoundError: Cannot find the requested files in the disk cache
#      and outgoing traffic has been disabled
#
# The cache lives under /project, NOT /scratch. Trillium purges scratch, which
# is what emptied the previous /scratch/$USER/hf_cache and caused a multi-seed
# job to fail all 15 seeds in ~9s each.
#
#   ssh trillium
#   cd /scratch/$USER/JiraAndLogs_scratch/JiraAndLogs
#   bash scripts/v2/fetch_models.sh
#
# ~16G, a few minutes. Idempotent -- already-cached models are a no-op.
set -uo pipefail

module load python/3.12 arrow/21.0.0 2>/dev/null
source .venv/bin/activate 2>/dev/null

ACCOUNT="${V2_ACCOUNT_GROUP:-def-naser2}"
export HF_HOME="${V2_HF_HOME:-/project/${ACCOUNT}/$(whoami)/hf_cache}"
mkdir -p "$HF_HOME"
# Must be online here; the jobs run offline against what this leaves behind.
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE

echo "HF_HOME=$HF_HOME"
python - <<'PY'
from huggingface_hub import snapshot_download

MODELS = [
    ("sentence-transformers/all-MiniLM-L6-v2",  "bi-encoder, fine-tuned per seed"),
    ("sentence-transformers/all-mpnet-base-v2", "mpnet baseline"),
    ("BAAI/bge-large-en-v1.5",                  "bge baseline"),
    ("intfloat/e5-large-v2",                    "e5 baseline"),
    ("cross-encoder/ms-marco-MiniLM-L-6-v2",    "cross-encoder reranker"),
    ("naver/splade-cocondenser-ensembledistil", "learned sparse retriever"),
]
failed = []
for name, why in MODELS:
    try:
        snapshot_download(name)
        print(f"  OK   {name:<45} ({why})")
    except Exception as e:
        print(f"  FAIL {name:<45} {type(e).__name__}: {str(e)[:120]}")
        failed.append(name)
if failed:
    raise SystemExit(f"{len(failed)} model(s) failed: {failed}")
PY

echo "--- cache size ---"
du -sh "$HF_HOME"
echo ""
echo "Jobs read this via V2_HF_HOME (default /project/${ACCOUNT}/\$USER/hf_cache)."
