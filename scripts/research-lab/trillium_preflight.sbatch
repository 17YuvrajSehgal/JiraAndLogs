#!/usr/bin/env bash
#SBATCH --account=def-naser2
#SBATCH --job-name=hybrid-preflight
#SBATCH --partition=debug
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --time=00:30:00
#SBATCH --output=logs/slurm-%x-%j.out
# ---------------------------------------------------------------------------
# Cheap preflight for the Hybrid-RRF job: validates the GPU + offline-model +
# Neo4j-in-Apptainer integration on a real compute node WITHOUT doing the heavy
# training. If this passes, the full 23h job is very likely to run clean.
# ---------------------------------------------------------------------------
set -uo pipefail
REPO="/scratch/${USER}/JiraAndLogs_scratch/JiraAndLogs"
cd "$REPO"; mkdir -p logs

module load python/3.12
source .venv/bin/activate
export PYTHONPATH=src PYTHONUNBUFFERED=1
export HF_HOME="/scratch/${USER}/hf_cache" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export NEO4J_BASE="/scratch/${USER}/neo4j-preflight"

echo "=== node: $(hostname) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 | head

echo "=== [1/3] torch sees GPU ==="
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda_available", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA NOT available on this node!"
print("device:", torch.cuda.get_device_name(0))
x = torch.randn(1024, 1024, device="cuda"); print("matmul ok:", (x@x).sum().item() != 0)
PY

echo "=== [2/3] offline HuggingFace models load (SPLADE + MiniLM) ==="
python - <<'PY'
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForMaskedLM, AutoTokenizer
m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cuda")
v = m.encode(["hybrid rrf smoke test"], convert_to_numpy=True)
print("MiniLM encode ok, dim:", v.shape)
tok = AutoTokenizer.from_pretrained("naver/splade-cocondenser-ensembledistil")
mdl = AutoModelForMaskedLM.from_pretrained("naver/splade-cocondenser-ensembledistil").to("cuda")
print("SPLADE loaded ok:", mdl.config.model_type)
PY

echo "=== [3/3] Neo4j via Apptainer on this node ==="
trap 'bash deploy/research-lab/neo4j_apptainer.sh stop || true' EXIT
NEO4J_HEAP=4G NEO4J_PAGECACHE=4G bash deploy/research-lab/neo4j_apptainer.sh start
python - <<'PY'
from neo4j import GraphDatabase
d = GraphDatabase.driver("neo4j://127.0.0.1:7687", auth=("neo4j","123456789"))
with d.session() as s:
    s.run("CREATE (n:Probe {k:'ok'})")
    print("neo4j readback:", s.run("MATCH (n:Probe) RETURN n.k AS k").single()["k"])
    s.run("MATCH (n:Probe) DELETE n")
d.close()
PY
echo "=== PREFLIGHT OK ==="
