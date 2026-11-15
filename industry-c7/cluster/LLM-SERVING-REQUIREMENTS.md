# What the Blueprint agent needs from the hosted LLM (re-hosting spec)

Audience: whoever (human or Claude session) re-hosts the vLLM server on Trillium.
Written 2026-10-31. Counterpart of `Blueprint/LLM-HANDOVER.md` (the current server),
which lacks three things the Blueprint selector agent needs. Owner: yuvraj17.

Why: `Blueprint/agent/agent_v2.py` drives the model through the OpenAI-compatible
API with **native tool calling**. The current server (job 1210606) returns 400 on
tool calls, so the agent cannot run against it at all.

## Must-have server flags

| # | Need | Qwen3.8-27B | GLM-5.3-Flash |
|---|---|---|---|
| 1 | Native tool calling (agent dies without it) | `--enable-auto-tool-choice --tool-call-parser hermes` | same, parser from the GLM family (`glm45` in recent vLLM — confirm the exact name with `vllm serve --help` in the venv; it shifts between versions) |
| 2 | Reasoning parser — `<think>` text must land in the `reasoning` field, not `content` (leaked think-blocks break tool-call parsing) | `--reasoning-parser qwen3` | the matching GLM entry from the same help listing |
| 3 | Context: `--max-model-len 131072` if VRAM allows | agent thread budget is 150k; at 128k we cap it to ~120k and lose little. If memory forces 65k, that also works (we cap at ~55k) — just report which it ended up being | same |

## Sizing

- `--max-num-seqs 32` — the eval runs at most ~20–24 cells in parallel. The 256
  seqs provisioned before are not needed; trading them away funds the longer
  context in (3).
- Walltime 24h is enough for the pending 20-cell run. The ICSE seeded campaign
  (hundreds of cells) will need a resubmit chain later — separate conversation.

Example submit (adjust quoting to how serve-llm.sbatch passes EXTRA_ARGS):

```bash
cd /scratch/yuvraj17/c7-llm && \
sbatch -p compute -t 24:00:00 --gpus-per-node=1 --cpus-per-task=24 \
  --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1,EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 --max-model-len 131072 --max-num-seqs 32" \
  serve-llm.sbatch
```

For GLM-5.3-Flash: 4x H100 (`--gpus-per-node=4`), `TP=4`,
`MODEL_DIR=/scratch/yuvraj17/models/GLM-5.3-Flash-NVFP4`, and the GLM parsers.

## Which model

**Prefer GLM-5.3-Flash (320B/A18B) if it validates.** Selection quality is what we
are measuring; a 27B model risks confounding "weak model" with "weak selector".
Qwen3.8-27B is fine as a smoke target and for cheap sweeps.

## Keep as-is (already right on the current server)

- OpenAI-compatible API on port 8000, no auth — the trillium login node reaches
  the GPU node directly (verified: `curl http://trig0012:8000/v1/models` works
  from the login node), so no tunnel is needed for the eval.
- Structured output / guided decoding — keep, not critical.
- Vision and embeddings — not needed.

## Handled on the agent side (no server action)

- Wiring: `RCA_PROVIDER=openai OPENAI_BASE_URL=http://<node>:8000/v1
  OPENAI_API_KEY=unused RCA_MODEL=<served-name>` — zero code changes.
- Thinking-mode default ON is fine once the reasoning parser is set; if it still
  burns the 4096-token output budget per step, a 3-line `extra_body` hook in
  `Blueprint/agent/config.py` sends `enable_thinking: false` per request.
- `ABL_THREAD_BUDGET` gets capped to match the final `max-model-len`.

## Handshake — report back after hosting

1. Node name (e.g. `trig0042`)
2. Served model name (the `"model"` string for API calls)
3. The `max-model-len` the server came up with

First action on our side is a one-request smoke test of a native tool call;
only then do the 20 pending selector cells relaunch against it.

---

## ✅ HOSTED — handshake (2026-10-31, by the hosting session)

**Qwen3.8-27B — LIVE and smoke-tested:**

1. Node: **`trig0051`** (SLURM job **1211031**, 24h, ends 2026-11-01 ~20:05 ET)
2. Served model name: **`qwen3.8-27b`**
3. `max-model-len`: **131072** (confirmed via `/v1/models`) — set
   `ABL_THREAD_BUDGET` for ~120k

Base URL from the login node: `http://trig0051:8000/v1` (no tunnel needed,
as you expected). Verified live, not assumed: auto tool call returns
populated `tool_calls` with `finish_reason:"tool_calls"`; multi-turn
tool-result round-trip gives a clean final answer; `<think>` lands in the
message `reasoning` field, `content` stays clean; `--max-num-seqs 32`.

⚠️ One correction to this spec: the Qwen tool parser is **`qwen3_xml`**,
not `hermes`. Qwen3.8 emits XML-format tool calls; with `hermes` the
server starts fine but returns `tool_calls: null` silently. The reasoning
parser `qwen3` was correct as written.

**GLM-5.3-Flash — queued, same flags with parser `glm47`** (both tool and
reasoning; `glm45` is an alias of the same class). SLURM job **1210919**
(4x H100 full node, 24h walltime), waiting on the busy full-node queue.
When it starts, its node is printed in
`/scratch/yuvraj17/c7-llm/logs/serve-1210919.out`; served name
`glm-5.3-flash`, same 131072 max len requested. Smoke-test a native tool
call yourself before pointing the selector at it — NVFP4-on-Hopper and
the glm47 parser have not been live-verified yet.
