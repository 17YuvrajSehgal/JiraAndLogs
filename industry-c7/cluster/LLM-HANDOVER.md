# HANDOVER: live LLM endpoint on Trillium — read before touching anything

Audience: Claude agents (or humans) who need to USE the hosted model or
check on it. Written 2026-10-31. Owner: yuvraj17 (Yuvraj Sehgal).

## ⚠️ Rules first

1. **Do NOT cancel SLURM job `1211031`** (Qwen3.8-27B on trig0051,
   wanted until **2026-11-01 20:05 ET**) **or job `1210919`** (GLM-5.3-Flash,
   queued/running 24h). Never run
   `scancel` on it, never submit a duplicate 24h server, never "clean
   up" jobs named `vllm-serve`.
2. Do not delete anything under `/scratch/yuvraj17/c7-llm/` or
   `/scratch/yuvraj17/models/` or `/scratch/yuvraj17/sifs/`.
3. Do not kill the WSL SSH control socket
   (`~/.ssh/sockets/yuvraj17@trillium.alliancecan.ca-22` inside WSL
   Ubuntu) — it carries the only authenticated session (Duo MFA; a new
   login needs the human).

## What is hosted

| | |
|---|---|
| Model | **Qwen3.8-27B** (`Qwen/Qwen3.8-27B`, Alibaba, Aug 2026, Apache 2.0) |
| Kind | dense 27B, hybrid attention (Mamba layers), multimodal (vision), thinking-mode by default |
| Context | 262k native; server caps requests at **131,072 tokens** (`--max-model-len`, confirmed in /v1/models) |
| Served name | `qwen3.8-27b` (use this as `"model"` in API calls) |
| Server | vLLM 0.32.0, OpenAI-compatible API, port 8000, no auth, **native tool calling + reasoning parser enabled** (`--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3`) |
| Hardware | 1x NVIDIA H100 80GB on Trillium GPU node **trig0051** |
| SLURM job | **1211031**, partition `compute`, account `def-naser2`, started 2026-10-31 ~20:05 ET, 24h walltime, ends 2026-11-01 20:05 ET |
| Concurrency | `--max-num-seqs 32` (traded for the 131k context) |

A second, bigger model (GLM-5.3-Flash NVFP4, 320B/A18B on 4x H100, served
name `glm-5.3-flash`, same tool/reasoning flags with parser `glm47`) is
queued as 24h job `1210919`; when it starts, its node appears in
`logs/serve-1210919.out` and tunnel.sh can reach it the same way.

## How to access it

The node is two SSH hops deep: laptop -> trillium login -> trig-login01
-> trig0051. All access rides the authenticated WSL SSH session.

**Option A — tunnel (for laptop-local clients):**
```bash
# from WSL Ubuntu (not PowerShell, not Git Bash):
bash /mnt/c/workplace/JiraAndLogs/industry-c7/cluster/tunnel.sh
# keeps running; then from anywhere on the laptop:
curl http://localhost:8000/v1/models
```
The script auto-discovers the serving node from the newest job log. If
several servers run at once and you need a specific one:
`ssh -J trillium trig-login01 -L 8000:trig0051:8000 -N` (in WSL).

**Option B — call from the cluster (no tunnel):**
```bash
# from WSL; replace the JSON as needed
MSYS_NO_PATHCONV=1 wsl -d Ubuntu ssh trillium "ssh trig-login01 'curl -s http://trig0051:8000/v1/chat/completions \
  -H \"Content-Type: application/json\" -d @- '" <<'EOF'
{"model": "qwen3.8-27b",
 "messages": [{"role": "user", "content": "Say hi"}],
 "max_tokens": 100, "temperature": 0,
 "chat_template_kwargs": {"enable_thinking": false}}
EOF
```

**Python (any OpenAI SDK), through the tunnel:**
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
r = client.chat.completions.create(
    model="qwen3.8-27b",
    messages=[{"role": "user", "content": "..."}],
    max_tokens=600, temperature=0,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

## Capabilities of the live server (each probed on 2026-10-31)

| Feature | Status on job 1211031 | How to use |
|---|---|---|
| Chat completions | ✅ | `POST /v1/chat/completions`, model `qwen3.8-27b` |
| Streaming | ✅ (standard vLLM) | `"stream": true` |
| Thinking mode | ✅ ON, parsed | thinking lands in the message's `reasoning` field; `content` stays clean (verified: "17*23" -> reasoning 125 chars, content "391"). Disable per request with `"chat_template_kwargs": {"enable_thinking": false}` if you want zero reasoning tokens billed to latency. |
| Structured output | ✅ verified | `"response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": {...}}}` — returned valid JSON. Also accepts vLLM `extra_body` guided options (`guided_json`, `guided_regex`, `guided_choice`). |
| Vision | ✅ verified | content parts with `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`. **Base64 data URLs only** — the node has no internet, remote image URLs cannot be fetched. |
| Tool calling (auto) | ✅ verified | standard OpenAI `tools` + `tool_choice:"auto"`; returns populated `tool_calls`, `finish_reason:"tool_calls"`, multi-turn tool-result round-trip verified. Parser is `qwen3_xml` (Qwen3.8 emits XML-style calls; `hermes` silently fails -> null tool_calls). |
| Tool calling (forced function) | ✅ | `tool_choice={"type":"function",...}` |
| Logprobs | ✅ (standard vLLM) | `"logprobs": true, "top_logprobs": k` |
| Embeddings | ❌ | chat model only |

Parser cheat-sheet for restarts (names verified in this vLLM build's
registry): Qwen3.8 -> `--tool-call-parser qwen3_xml --reasoning-parser
qwen3` (NOT hermes: Qwen3.8 emits XML-format tool calls and hermes
returns null tool_calls without erroring). GLM-5.3 -> `--tool-call-parser
glm47 --reasoning-parser glm47` (`glm45` is an alias of the same class).

## Usage gotchas

- **Thinking mode is ON by default.** With small `max_tokens` you get a
  truncated reasoning stream instead of an answer (finish_reason
  `length`). Either pass
  `"chat_template_kwargs": {"enable_thinking": false}` per request, or
  budget `max_tokens` generously and strip the `<think>` block.
- Prompts up to ~128k tokens are fine; longer requests are rejected.
- No API key: anyone on the cluster network can hit the port. Do not put
  secrets in prompts.
- Batch eval? Use
  `/scratch/yuvraj17/c7-llm/eval_client.py` (stdlib-only, one JSONL row
  per prompt, restart-safe) — run it ON the cluster against
  `http://trig0051:8000/v1` rather than hammering the tunnel.

## Health checks (safe, read-only)

```bash
# is the job alive?
MSYS_NO_PATHCONV=1 wsl -d Ubuntu ssh trillium "ssh trig-login01 'squeue -j 1211031 -o \"%.10i %.4t %.9M %.11L %R\"'"
# is the API answering?
MSYS_NO_PATHCONV=1 wsl -d Ubuntu ssh trillium "ssh trig-login01 'curl -s -m 5 http://trig0051:8000/v1/models'"
# server logs
MSYS_NO_PATHCONV=1 wsl -d Ubuntu ssh trillium "ssh trig-login01 'tail -20 /scratch/yuvraj17/c7-llm/logs/vllm-1211031.log'"
```

## If the server dies and you must restart it

Only then, submit a fresh job (new node; tunnel.sh re-discovers it):
```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu ssh trillium "ssh trig-login01 'cd /scratch/yuvraj17/c7-llm && \
  sbatch -p compute -t 24:00:00 --gpus-per-node=1 --cpus-per-task=24 \
    --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,MAXLEN=131072,MAXSEQS=32,EXTRA_ARGS=\"--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3\" \
    serve-llm.sbatch'"
# GLM-5.3-Flash instead: omit -p and gpus/cpus flags; TP=4,
# MODEL_DIR=.../GLM-5.3-Flash-NVFP4, NAME=glm-5.3-flash,
# EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm47"
```

## How it was hosted (so you can reason about it)

- **Cluster**: Trillium (SciNet/UofT, Alliance Canada). GPU subcluster:
  60 usable nodes of 4x H100 SXM 80GB; access via login chain
  `trillium` -> `trig-login01`. Compute nodes have **no internet** and
  **no /home mount**.
- **Stack**: vLLM 0.32.0 in a uv-managed venv at
  `/scratch/yuvraj17/c7-llm/vllm-venv` (standalone CPython 3.12.16 in
  `/scratch/yuvraj17/c7-llm/uv-pythons`), because the Alliance pip
  wheelhouse sabotages `pip install vllm`. FlashInfer kernels come from
  `flashinfer-jit-cache-sm90a` (installed via `vllm download-kernels`).
  All caches (vLLM/HF/Triton/Inductor) are redirected into
  `/scratch/yuvraj17/c7-llm/cache` because there is no /home on compute
  nodes. Everything runs offline (`HF_HUB_OFFLINE=1`).
- **Job**: `/scratch/yuvraj17/c7-llm/serve-llm.sbatch` starts the
  server, health-polls `/v1/models`, runs a smoke completion
  (`logs/smoke-<jobid>.json`), then idles until walltime (or runs
  `eval_client.py` if `EVAL_PROMPTS` is exported, exiting when done).
- **Logs**: `/scratch/yuvraj17/c7-llm/logs/` — `serve-<jobid>.out`
  (job), `vllm-<jobid>.log` (server), `smoke-<jobid>.json`.
- Local mirror of all scripts + the cluster-quirks list:
  `industry-c7/cluster/` in the JiraAndLogs repo (see README.md there
  for the 7 Trillium quirks, each of which cost one failed job).
