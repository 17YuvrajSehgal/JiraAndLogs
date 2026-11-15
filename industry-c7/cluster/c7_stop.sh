B=/scratch/$USER/c7-data/logs; . $B/login-pilot.env
kill $PID 2>/dev/null; sleep 8
# only this user's vLLM processes, by name; nothing else is touched
left=$(pgrep -u $USER -f "vllm serve|VLLM|vllm-venv" | tr '\n' ' ')
[ -n "$left" ] && { echo "still alive: $left -> SIGTERM"; kill $left 2>/dev/null; sleep 6; }
echo "my vllm processes left: $(pgrep -u $USER -f 'vllm serve|vllm-venv' | wc -l)"
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | while IFS=, read p m; do [ "$(ps -o user= -p $p 2>/dev/null)" = "$USER" ] && echo "MINE on gpu: $p $m"; done
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
