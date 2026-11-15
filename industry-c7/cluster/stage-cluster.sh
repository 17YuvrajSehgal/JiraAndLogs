#!/bin/bash
# One-time staging of a cluster for the C7 agent run. Login node only: it
# needs internet, and GPU compute nodes have none.
#
# Adapted from setup_nibi.sh, which is the reference path, with three
# changes:
#
#   1. Only Qwen3.8-27B. setup_nibi.sh also pulls GLM-5.3-Flash-NVFP4,
#      which this work does not use and which costs another large download.
#   2. UV_PYTHON_INSTALL_DIR is forced onto /scratch. setup_nibi.sh leaves
#      the standalone CPython under ~/.local/share/uv and notes in a comment
#      that this is safe "because home is mounted on Nibi compute nodes".
#      That is a per-cluster fact, not a general one, and a venv whose base
#      interpreter is not mounted fails at job start after the queue wait.
#      On /scratch the question does not arise.
#   3. It also stages the dataset side: the 37 bare repos, which are public
#      and clone far faster from GitHub here than they copy from a laptop.
#
# Idempotent: every step drops a marker in $BASE/.done and is skipped next
# time, so re-running after a failure resumes.
#
#   nohup bash stage-cluster.sh > /dev/null 2>&1 &
#   tail -f /scratch/$USER/c7-llm/logs/stage.log
set -uo pipefail

S=/scratch/$USER
BASE=$S/c7-llm
DATA=$S/c7-data
REPOS=$DATA/data/c7-repos
VLLM_VERSION=${VLLM_VERSION:-0.32.0}      # the version Trillium and Nibi serve
MODEL=${MODEL:-Qwen/Qwen3.8-27B}
JOBS=${JOBS:-3}                           # concurrent clones; polite on a login node

mkdir -p "$BASE"/{logs,.done,models,cache} "$DATA"/logs "$REPOS"
exec >> "$BASE/logs/stage.log" 2>&1
echo "=== stage start $(date) on $(hostname)"

export PATH=$HOME/.local/bin:$PATH
export UV_CACHE_DIR=$BASE/cache/uv
export UV_PYTHON_INSTALL_DIR=$BASE/uv-pythons
export HF_HOME=$BASE/cache/hf HF_HUB_ENABLE_HF_TRANSFER=1

step() { [ -f "$BASE/.done/$1" ] && { echo "skip $1"; return 1; }; echo "--- $1 $(date +%T)"; return 0; }
ok()   { touch "$BASE/.done/$1"; echo "    ok $1 $(date +%T)"; }

# 0. uv itself
if step uv; then
  command -v uv >/dev/null 2>&1 \
    || curl -LsSf https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null 2>&1 && ok uv
fi
hash -r 2>/dev/null

# 1. standalone CPython. The Alliance wheelhouse hijacks `pip install vllm`
#    and serves its own build; uv sidesteps that.
if step python; then uv python install 3.12 && ok python; fi

# 2. venv + vLLM
if step venv; then uv venv --python 3.12 "$BASE/vllm-venv" && ok venv; fi
if step vllm; then
  uv pip install --python "$BASE/vllm-venv/bin/python" \
      "vllm==$VLLM_VERSION" "huggingface_hub[cli,hf_transfer]" \
    && "$BASE/vllm-venv/bin/python" -c "import vllm; print('vllm', vllm.__version__)" \
    && ok vllm
fi

# 3. flashinfer kernels. REQUIRED, not an optimisation.
#
#    flashinfer JIT-compiles a kernel during model warm-up. That needs nvcc,
#    and the compute nodes have no CUDA toolkit: no /usr/local/cuda, nothing
#    on PATH. So without prebuilt kernels vLLM does not start at all, it
#    dies in compile_or_warm_up_model with
#
#      RuntimeError: Could not find nvcc and default
#      cuda_home='/usr/local/cuda' doesn't exist
#
#    This step used to call `vllm download-kernels`, which probes the local
#    GPU to pick an architecture. A login node has no GPU, so it failed with
#    "Can't initialize NVML" and the old code printed
#    "non-fatal: JIT fallback" and carried on. There is no JIT fallback
#    here. Rorqual staged clean that way, sat in the queue for 26 hours and
#    would have failed all seven of its jobs four minutes after starting.
#
#    The jit-cache wheels carry prebuilt kernels for every architecture, so
#    they install from a login node with no GPU and no nvcc. Pinned to the
#    flashinfer that vLLM 0.32.0 brings in, because a mismatched cubin kills
#    the engine at start.
if step kernels; then
  FI_VER=$("$BASE/vllm-venv/bin/python" -c \
    "import importlib.metadata as m; print(m.version('flashinfer-python'))" \
    2>/dev/null)
  if [ -z "$FI_VER" ]; then
    echo "    REFUSING: flashinfer-python is not installed; vLLM step must run first" >&2
    exit 1
  fi
  echo "    flashinfer-python $FI_VER; fetching matching jit-cache wheels"
  if uv pip install --python "$BASE/vllm-venv/bin/python" \
       "flashinfer-jit-cache==${FI_VER}+cu130" \
       --extra-index-url https://flashinfer.ai/whl/cu130/; then
    # Prove it, per architecture. sm90a is H100, sm80 A100, sm100a B200.
    if "$BASE/vllm-venv/bin/python" - <<'PY'
import importlib.metadata as md
import sys
# sm90a is H100 (nibi, fir, rorqual, trillium), sm80 is A100 (narval),
# sm100a is B200. Require the two we actually run on.
need = ["flashinfer-jit-cache-sm80", "flashinfer-jit-cache-sm90a"]
bad = []
for n in need:
    try:
        print("      ", n, md.version(n))
    except Exception:
        print("      ", n, "MISSING")
        bad.append(n)
sys.exit(1 if bad else 0)
PY
    then ok kernels
    else echo "    REFUSING: jit-cache installed but an arch wheel is missing" >&2; exit 1
    fi
  else
    echo "    REFUSING: could not install flashinfer-jit-cache." >&2
    echo "    Without it vLLM cannot start on a node with no nvcc." >&2
    exit 1
  fi
fi

# 4. the model
d=$BASE/models/$(basename "$MODEL")
if step "model-$(basename "$MODEL")"; then
  "$BASE/vllm-venv/bin/hf" download "$MODEL" --local-dir "$d" \
    && du -sh "$d" && ok "model-$(basename "$MODEL")"
fi

# 5. the 37 bare repos. --mirror, not --bare: a bare clone takes only the
#    default branch and would silently lose commits the instances point at.
#    Verified on Nibi afterwards: all 76,533 referenced SHAs resolved.
cat > "$BASE/.repo-list" <<'LIST'
ambari-full.git https://github.com/apache/ambari.git
beam-full.git https://github.com/apache/beam.git
camel-full.git https://github.com/apache/camel.git
cassandra-full.git https://github.com/apache/cassandra.git
derby-full.git https://github.com/apache/derby.git
drill-full.git https://github.com/apache/drill.git
flink-full.git https://github.com/apache/flink.git
geode-full.git https://github.com/apache/geode.git
groovy-full.git https://github.com/apache/groovy.git
hadoop-full.git https://github.com/apache/hadoop.git
hbase-full.git https://github.com/apache/hbase.git
hive-full.git https://github.com/apache/hive.git
ignite-full.git https://github.com/apache/ignite.git
impala-full.git https://github.com/apache/impala.git
infinispan-full.git https://github.com/infinispan/infinispan.git
kafka-full.git https://github.com/apache/kafka.git
kafka.git https://github.com/apache/kafka.git
keycloak-full.git https://github.com/keycloak/keycloak.git
mariadb-full.git https://github.com/MariaDB/server.git
mariadb-server.git https://github.com/MariaDB/server.git
mongo-full.git https://github.com/mongodb/mongo.git
mongo-meta.git https://github.com/mongodb/mongo.git
pdfbox-full.git https://github.com/apache/pdfbox.git
phoenix-full.git https://github.com/apache/phoenix.git
pig-full.git https://github.com/apache/pig.git
qtbase-full.git https://github.com/qt/qtbase.git
qtbase-meta.git https://github.com/qt/qtbase.git
qtbase_extra-full.git https://github.com/qt-creator/qt-creator.git
qtdeclarative-full.git https://github.com/qt/qtdeclarative.git
qtmultimedia-full.git https://github.com/qt/qtmultimedia.git
qtquickcontrols2-full.git https://github.com/qt/qtquickcontrols2.git
qttools-full.git https://github.com/qt/qttools.git
qtwebengine-full.git https://github.com/qt/qtwebengine.git
sakai-full.git https://github.com/sakaiproject/sakai.git
solr-full.git https://github.com/apache/solr.git
spark-full.git https://github.com/apache/spark.git
wildfly-full.git https://github.com/wildfly/wildfly.git
LIST

clone_one () {
  d=$1; u=$2
  if [ -d "$d" ] && git --git-dir="$d" rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "    have   $d"; return 0
  fi
  rm -rf "$d.part"
  if git clone --mirror --quiet "$u" "$d.part"; then
    mv "$d.part" "$d"; echo "    cloned $d"
  else
    echo "    FAILED $d"; rm -rf "$d.part"
  fi
}
export -f clone_one

if step repos; then
  cd "$REPOS" || exit 1
  xargs -P "$JOBS" -n 2 bash -c 'clone_one "$0" "$1"' < "$BASE/.repo-list"
  n=$(ls -1d "$REPOS"/*.git 2>/dev/null | wc -l)
  echo "    repos present: $n of 37"
  [ "$n" = "37" ] && ok repos || echo "    NOT marking done: $n of 37"
fi

echo "=== stage end $(date)"
echo "--- markers ---"
ls "$BASE/.done"
echo "--- sizes ---"
du -sh "$BASE/models" "$BASE/vllm-venv" "$REPOS" 2>/dev/null
