# Using the hosted LLM from another project (handover)

Written 2026-11-03 17:45 ET. Owner: Yuvraj (yuvraj17 on Nibi). Give this file to any Claude
Code session or script in another repo that wants to use the model.

## What is running

| | |
|---|---|
| Model | **Qwen3.8-27B** (BF16), served by vLLM 0.32.0, OpenAI-compatible API |
| Served model name | `qwen3.8-27b` (use exactly this as `model`) |
| Where | SHARCNET **Nibi** cluster, GPU node `g1`, one H100 80 GB, SLURM job **26073466** |
| Ends | **2026-11-03 22:15 ET** (8 h interactive allocation; `squeue -j 26073466` shows the time left) |
| Context | 131,072 tokens; prefix caching on; up to 32 concurrent sequences |
| Features | chat completions, native tool calling (`tools=[...]`, parser `qwen3_xml`), reasoning parser `qwen3` (thinking comes back in `reasoning_content`, the answer in `content`) |
| Auth | none; pass any string as the API key (we use `unused`) |

## How to reach it

**From this laptop (Windows or WSL): it is already on `http://localhost:8000/v1`.** A port
forward from the laptop to the GPU node is up and was checked at 17:40 from both Windows and WSL.

```bash
curl http://localhost:8000/v1/models                      # must list "qwen3.8-27b"
curl http://localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "qwen3.8-27b", "messages": [{"role": "user", "content": "Say hi in five words."}],
  "temperature": 0, "max_tokens": 64 }'
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
r = client.chat.completions.create(model="qwen3.8-27b",
        messages=[{"role": "user", "content": "Say hi in five words."}], temperature=0)
print(r.choices[0].message.content)
```

Environment variables that most libraries pick up:

```
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=unused
```

LangChain / LangGraph: `ChatOpenAI(model="qwen3.8-27b", base_url="http://localhost:8000/v1", api_key="unused")`.

**From a Nibi login node** (if the other project runs there): `http://g1:8000/v1`, no tunnel.

**If `localhost:8000` stops answering on the laptop** (the forward dropped, the job is still
running): in a WSL shell, `ssh -O forward -L 8000:g1:8000 nibi`. This rides the existing
authenticated SSH session; no password or Duo. If that says the control socket is gone, run
`ssh nibi` once in a WSL terminal (Duo prompt), leave it open, then repeat the `-O forward`.

## Rules - please read

1. **Do not cancel the job.** No `scancel 26073466`, no `scancel -u yuvraj17`. It is shared;
   it ends by itself at 22:15 ET. Other work is scheduled around it.
2. **Do not kill SSH processes on the laptop.** In WSL there are two long-lived SSH control
   masters (`~/.ssh/sockets/yuvraj17@nibi...`, `...@trillium...`) and a tunnel loop. They carry
   the only authenticated sessions (Duo MFA done by a human). `pkill ssh`, `ssh -O exit`, or
   closing the WSL window that owns them breaks every access path at once. Never run `pkill -f`
   with a pattern that could match `ssh`.
3. **Do not touch `/scratch/yuvraj17/c7-llm/` or `/scratch/yuvraj17/stratatrace/` on Nibi**
   (the server's venv, models, logs; another project's runner). Read-only is fine.
4. **Do not submit or cancel other SLURM jobs under `yuvraj17`** unless the owner asks.
5. Load: the server handled 5 parallel agent runs (1-2 M input tokens each) without trouble.
   Keep concurrency at or below ~8 requests at a time and it stays responsive for everyone.
6. Keep `temperature` explicit (we use 0 for reproducible runs). Reasoning is on by default;
   if you only want the final answer, read `message.content` and ignore `reasoning_content`.

## Health check

```bash
curl -s -m 5 http://localhost:8000/v1/models | head -c 200      # laptop side
wsl ssh nibi 'squeue -j 26073466 -o "%.10i %.10M %.10L %R"'      # job side (TIME_LEFT)
```

A `curl` that hangs with the job still in `squeue` is a dropped forward (fix above). A job
missing from `squeue` means it ended; see "After 22:15".

## After 22:15 ET

The server is gone and `localhost:8000` answers nothing. Re-hosting is the owner's call
(`Blueprint/latency/docs/NIBI-HANDOVER.md` in the microservice-trace-dataset repo: `submit-qwen.sh`
for a 12 h batch job, or the interactive `srun --qos=interac` recipe that starts within ~10 min).
A new job lands on a different node; the forward then needs that node name instead of `g1`.
