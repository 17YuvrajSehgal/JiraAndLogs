# Serve Qwen on the login node for a short debugging pilot. TP=2 because no
# single login GPU has the ~58 GiB free that one-GPU serving at 65536 needs.
S=/scratch/$USER; BASE=$S/c7-data; ENVF=$BASE/logs/login-pilot.env
mkdir -p $BASE/logs
if [ -f $ENVF ] && kill -0 "$(grep PID= $ENVF | cut -d= -f2)" 2>/dev/null; then echo "already running: $(cat $ENVF)"; else
  # two GPUs with the most free memory
  read -r G1 F1 G2 F2 <<< "$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | sort -t, -k2 -nr | head -2 | tr -d ' ' | tr ',\n' '  ')"
  echo "gpus $G1 (${F1} MiB free) and $G2 (${F2} MiB free)"
  UTIL=$(python3 -c "print(round(min(0.45, ($F2 - 3000) / 81559), 2))")
  echo "gpu-memory-utilization=$UTIL"
  python3 -c "import sys; sys.exit(0 if $UTIL >= 0.40 else 1)" || { echo "NOT ENOUGH FREE GPU MEMORY for TP=2"; exit 1; }
  PORT=$(for p in $(seq 8765 8800); do (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null || { echo $p; break; }; done)
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
  CACHE=$S/c7-llm/cache
  export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf XDG_CACHE_HOME=$CACHE/xdg
  export TRITON_CACHE_DIR=$CACHE/triton TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor
  # The login node caps a user at 1024 processes+threads and has 192 cores.
  # OpenMP starts one thread per core in every vLLM process, so the second
  # TP worker died with "libgomp: Thread creation failed". Cap the pools.
  export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8
  export RAYON_NUM_THREADS=8 TOKENIZERS_PARALLELISM=false
  ulimit -u "$(ulimit -Hu)" 2>/dev/null; echo "max user processes: $(ulimit -u)"
  module load python/3.12.4 >/dev/null 2>&1
  CUDA_VISIBLE_DEVICES=$G1,$G2 nohup $S/c7-llm/vllm-venv/bin/vllm serve $S/models/Qwen3.8-27B \
    --served-model-name qwen3.8-27b --host 127.0.0.1 \
    --tensor-parallel-size 2 --max-model-len 65536 --max-num-seqs 8 \
    --gpu-memory-utilization $UTIL --port $PORT \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --reasoning-parser qwen3 --enable-prefix-caching \
    > $BASE/logs/vllm-login-pilot.log 2>&1 &
  echo "PID=$!" > $ENVF; echo "PORT=$PORT" >> $ENVF; echo "GPUS=$G1,$G2" >> $ENVF
  cat $ENVF
fi
. $ENVF
for i in $(seq 1 90); do
  curl -s -m 2 http://127.0.0.1:$PORT/v1/models | grep -q qwen3.8-27b && { echo "SERVER UP after ~$((i*10))s on port $PORT"; break; }
  kill -0 $PID 2>/dev/null || { echo "vLLM DIED:"; tail -25 $BASE/logs/vllm-login-pilot.log; exit 1; }
  sleep 10
done
grep -h -E "KV cache size|Model loading took" $BASE/logs/vllm-login-pilot.log | tail -2
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
