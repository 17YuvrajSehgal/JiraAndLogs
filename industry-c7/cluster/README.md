# Hosting an open LLM on Trillium (SciNet)

## What the cluster has (checked 2026-10-31)

| Resource | Detail |
|---|---|
| H100 subcluster | 60 usable nodes, 4x H100 SXM 80GB each (320GB/node), 96 Genoa cores, 768GB RAM, partitions `debug` (2h) / `compute` (24h), account `def-naser2`, per-GPU scheduling |
| H200 node | 1 node (trig0063), usually allocated |
| B200 expansion | 52 nodes x 8 B200 (1.5TB GPU mem/node) — **reserved for SciNet staff** (`Accounts=scinet`, reservations `b200` + `AI_inference-nodes`). Email trillium@tech.alliancecan.ca to ask for access. |
| Queue pressure | ~1,800 pending jobs on `compute`; 1-GPU jobs schedule much faster than full nodes; pilot on `debug` |
| Scratch | `/scratch/yuvraj17`, 25TiB quota (~10TiB free) |
| Software | no vLLM/pytorch module -> Apptainer 1.4.5 + official `vllm/vllm-openai:latest` image (SIF in `/scratch/yuvraj17/sifs/`) |
| Internet | login nodes yes; compute nodes no -> models staged in /scratch, `HF_HUB_OFFLINE=1` |

GPU login node: `trig-login01` (reachable only from `tri-login*`).

## Model plan (two-step)

1. **Pilot: Qwen3.8-27B** (`Qwen/Qwen3.8-27B`, Aug 2026, Apache 2.0,
   dense 27B + vision, 262k native context, ~56GB BF16). Fits ONE H100,
   so it rides the fast 1-GPU queue. Gets the whole pipeline working.
2. **Real runs: GLM-5.3-Flash NVFP4** (`RedHatAI/GLM-5.3-Flash-NVFP4`,
   320B/A18B MoE, ~170GB 4-bit). Near-frontier coding/agentic quality
   (reported approaching Claude Opus 4.8 on those benchmarks); fits one
   4xH100 node with ~150GB KV headroom; 18B active params decode fast.
   Caveat: NVFP4 on Hopper goes through vLLM's Marlin w4a16 path (works,
   not Blackwell-fast); verified in the pilot before committing.

Rejected: zai-org FP8 (331GB > 320GB node), Qwen3-235B-A22B-2507-FP8
(previous-generation, superseded by GLM-5.3-Flash at the same footprint),
Kimi K3.1 / GLM-5.3 full / Qwen3.8-Max (multi-node territory on a
default-priority allocation).

## Files

- `serve-llm.sbatch` — parameterized job: vLLM server (OpenAI API, port
  8000) + optional eval; exits when the eval finishes.
- `eval_client.py` — stdlib-only client; one JSONL row per prompt;
  restart-safe (resumes from the output file).

## Runbook

```bash
# 0. one-time staging on trig-login01 (kicked off 2026-10-31, see logs/):
#    - SIF: apptainer pull /scratch/yuvraj17/sifs/vllm-openai.sif docker://vllm/vllm-openai:latest
#    - models: hf download Qwen/Qwen3.8-27B  +  RedHatAI/GLM-5.3-Flash-NVFP4

# 1. copy scripts up (from WSL, which holds the SSH session)
scp serve-llm.sbatch eval_client.py README.md trillium:/scratch/yuvraj17/c7-llm/

# 2. pilot: Qwen3.8-27B on 1 GPU, debug partition
ssh trillium "ssh trig-login01 'cd /scratch/yuvraj17/c7-llm && \
  sbatch -p debug -t 1:00:00 --gpus-per-node=1 --cpus-per-task=24 --mem=180G \
    --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/Qwen3.8-27B,NAME=qwen3.8-27b,TP=1 \
    serve-llm.sbatch'"
# logs/serve-<jobid>.out must show SERVING_OK

# 3. pilot GLM on debug the same way (TP=4, drop the gpus/cpus/mem overrides)

# 4. real run with an eval file (24h compute partition)
ssh trillium "ssh trig-login01 'cd /scratch/yuvraj17/c7-llm && \
  sbatch --export=ALL,MODEL_DIR=/scratch/yuvraj17/models/GLM-5.3-Flash-NVFP4,NAME=glm-5.3-flash,TP=4,EVAL_PROMPTS=/scratch/yuvraj17/c7-llm/prompts.jsonl \
    serve-llm.sbatch'"
```

## Talking to the server from the laptop (optional)

```bash
ssh -J trillium trig-login01 -L 8000:<nodename>:8000 -N
# then: curl http://localhost:8000/v1/models
```

`<nodename>` is in the job log (`node: trigXXXX`).

## Trillium quirks (each cost one failed job — all baked into serve-llm.sbatch)

1. `--mem` is forbidden; memory follows the GPU/CPU share.
2. GPU compute nodes do NOT mount `/home` — every cache (vLLM model-info,
   HF, Triton, Inductor) must point into /scratch, or vLLM dies at
   model-architecture inspection with a cryptic "failed to be inspected".
3. Whole-node (4-GPU) jobs must OMIT `--partition`; Trillium auto-routes
   them to `compute_full_node`/`debug_full_node`. Only 1-GPU jobs name
   `-p debug` / `-p compute`. Debug walltime cap is 1h, one job per user.
4. The Alliance pip wheelhouse hijacks `pip install vllm` with a dummy
   opencv wheel that errors on purpose. Bypass: `uv` with its own
   standalone CPython in /scratch (uv python install 3.12; uv venv).
5. flashinfer-cubin on PyPI lags flashinfer-python and the version check
   kills the engine. Fix: `vllm download-kernels` on the login node,
   which installs the version-matched `flashinfer-jit-cache-sm90a`.
6. Qwen3.8's hybrid-Mamba layers cap concurrent sequences (357 blocks at
   64k ctx on one H100); vLLM's default max_num_seqs=1024 aborts CUDA
   graph capture. The script sets `--max-num-seqs 256` (MAXSEQS env).
7. Qwen3.8 defaults to thinking mode: short max_tokens returns the
   reasoning stream cut off mid-thought. Disable per request
   (`chat_template_kwargs: {"enable_thinking": false}`) or budget tokens.

## Notes

- Walltime cap 24h; the eval client checkpoints per prompt, so a killed
  job resumes with the same `--out`.
- `MAXLEN` default 65536 covers our longest prompts (~57k tokens); both
  models have >=128k native context if more is ever needed.
- If NVFP4 fails on Hopper in the pilot, fallbacks in order: a W4A16/AWQ
  community quant of GLM-5.3-Flash, or Qwen3.8-27B for everything.
