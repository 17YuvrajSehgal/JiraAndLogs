# LLM Configuration — Qwen3.6 35B-A3B in LM Studio

This doc captures every model-side decision for the LLM-powered v2 pipelines (Phase D `kg_retrieval`, Phase E `diagnosis_agent`). It is the source of truth for what the user loads and how our client talks to it.

---

## 1. Model choice

**Loaded:** `Qwen3.6 35B-A3B` (GGUF, Q4_K_M quantization)

Why this fits our problem:

| Property | Why we want it |
|---|---|
| Mixture-of-Experts (35B total, ~3B active per token) | Acts like a 3B-fast model with 35B-quality outputs for our extraction workload. |
| Q4_K_M quantization | Best balance of quality vs VRAM at ~22 GB total weights. |
| Native "Thinking Preservation" (Qwen3 reasoning mode) | Lets us turn structured chain-of-thought ON for the DiagnosisAgent verify stage, OFF for extraction. |
| 262K context length supported | We only need ~16K but the headroom matters for future agentic loops. |
| Agentic coding posture in the post-training | Trained on tool-use traces; better at constrained JSON than a generic instruct model. |

---

## 2. LM Studio load-time settings (Load tab)

### Required values

| Setting | Value | Reason |
|---|---|---|
| Context Length | **16384** | Largest single prompt (DiagnosisAgent verify) is ~3K tokens; 16K is safe headroom without wasting KV-cache VRAM. |
| GPU Offload | **22 layers** (start) | RTX 5060 has 8 GB. ~22 layers fits; if loading fails, drop to 18. If load is comfortable, push to 26. Do NOT set to 40 (the default slider position would OOM). |
| CPU Thread Pool Size | **9** | Matches the box's available cores. |
| Evaluation Batch Size | **2048** | Default. Prompt-processing parallelism. |
| Physical Batch Size | **512** | Default. Token-chunk size for processing. |
| Max Concurrent Predictions | **2** | Lower from default 4 — our pipelines call sequentially. Frees VRAM. |
| Unified KV Cache | **ON** | Better cache utilization. |
| RoPE Frequency Base | **Auto** | Don't override. |
| RoPE Frequency Scale | **Auto** | Don't override. |
| Offload KV Cache to GPU Memory | **ON** | Faster generation. If loading fails, turn OFF first before reducing GPU Offload. |
| Keep Model in Memory | **ON** | Don't swap; we hit the model 347+ times. |
| Try mmap() | **ON** | Faster initial load. |
| Seed | **42** (check the box) | Reproducibility — the paper needs deterministic outputs. Don't leave "Random Seed". |
| Number of Experts | **8** | Don't change — model architecture. |
| Number of layers to force MoE weights onto CPU | **0** | Try first. Only raise if model still OOMs at load with GPU Offload=18. |
| Flash Attention | **ON** | Free speedup + memory savings. |
| K Cache Quantization | **OFF** | Default. Q8 K-cache can slightly hurt structured-JSON quality on Qwen3. |
| V Cache Quantization | **OFF** | Same reasoning. |

### Why these numbers

Total model size at Q4_K_M ≈ 22 GB. With LM Studio's reported estimate of 21.73 GB GPU need vs the 8 GB physically available:

```
22 GB total weights
- ~7 GB usable on the RTX 5060 (8 GB total - 1 GB OS/desktop)
= ~15 GB needs to go to system RAM via MoE offload
```

The 22-layer GPU offload puts the most-frequently-active layers on the GPU. Less-touched MoE experts (the model has 8, only a few routed per token) stay on CPU. With Flash Attention + Unified KV Cache, inference is ~5–10 tokens/sec — slow but acceptable for our batched workflow.

If you have any of these issues during load, the fix is in this order:

1. Reduce GPU Offload from 22 → 20 → 18
2. Turn OFF "Offload KV Cache to GPU Memory"
3. Raise "Number of layers to force MoE weights onto CPU" to 5, 10, 15
4. Reduce Context Length from 16384 to 8192

---

## 3. LM Studio Inference tab settings

### Custom Fields (Qwen3-specific)

| Setting | Value | Reason |
|---|---|---|
| **Enable Thinking** | **ON** | Server default. Our client overrides per-call: OFF for extraction, ON for diagnosis-verify. The server-default-ON gives a safe fallback if a caller forgets to specify. |
| **Preserve Thinking** | **OFF** | Our calls are stateless — we never reuse conversation history. Preserving thinking across turns would bloat context. |

### Settings

| Setting | Value | Reason |
|---|---|---|
| Temperature | **0** | Deterministic outputs for extraction. |
| Limit Response Length | unchecked | Per-call `max_tokens` already bounds this. |
| Context Overflow | **Truncate Middle** | If a prompt exceeds context, drop the middle. Our prompts are short so this rarely triggers. |
| Stop Strings | empty | Do NOT add `</think>` — it would break thinking mode. |
| CPU Threads | 9 | Same as Load tab. |

### Sampling

| Setting | Value | Reason |
|---|---|---|
| Top K Sampling | **20** | Irrelevant at temp=0; safe fallback. |
| Repeat Penalty | **unchecked** | **Critical:** penalizing repetition on JSON would penalize repeated keys like `"ticket_id"` across calls. |
| Presence Penalty | **unchecked** | Same reasoning. |
| Top P Sampling | **1** (enabled) | Irrelevant at temp=0; safe. |
| Min P Sampling | **unchecked** | Off. |

### Structured Output

| Setting | Value | Reason |
|---|---|---|
| **Structured Output** | **ON** | Critical for JSON extraction reliability. With this ON, when our client sends a `response_format` schema, the model's generation is grammar-constrained to a valid instance of that schema. |
| Schema (in the UI text box) | **Empty / not required** | We send per-call schemas from our client — see §4. The UI schema, if any, would act as a default for calls that don't send their own; we don't need that fallback. |

### Speculative Decoding

Leave at defaults (no draft model). Speculative decoding needs a separate small draft model loaded at the same time; not configured.

---

## 4. Per-call JSON schemas (the actual contract our code sends)

All four schemas live in `src/v2_advanced/shared/json_schemas.py`. Each is wrapped in an OpenAI / LM Studio `response_format` envelope:

```python
{
    "type": "json_schema",
    "json_schema": {
        "name": "<short name>",
        "strict": true,
        "schema": <the JSON Schema>,
    },
}
```

The `strict: true` flag tells LM Studio to grammar-constrain generation — the model can only emit tokens that lead to a valid instance of the schema. This eliminates prose wrapping (`"Sure, here's the JSON: …"`) and missing fields.

### 4.1 Ticket extraction (Phase D — 347 calls)

**Name:** `ticket_extraction`. Used by `extract_from_ticket` in `extractor.py`.

```json
{
  "type": "object",
  "properties": {
    "affected_services": { "type": "array", "items": { "type": "string" } },
    "components":        { "type": "array", "items": { "type": "string" } },
    "error_classes":     { "type": "array", "items": { "type": "string" } },
    "root_cause":        { "type": "string" },
    "fix":               { "type": "string" },
    "fix_kind": {
      "type": "string",
      "enum": ["config_change", "restart", "scale_up",
               "code_fix", "rollback", "other"]
    },
    "symptoms":          { "type": "array", "items": { "type": "string" } }
  },
  "required": ["affected_services", "components", "error_classes",
               "root_cause", "fix", "fix_kind", "symptoms"],
  "additionalProperties": false
}
```

Thinking: **OFF**. Extraction is structured-pattern matching, not reasoning. Saves ~70% of runtime.

### 4.2 Window extraction (Phase D — up to 1008 calls)

**Name:** `window_extraction`. Used by `extract_from_window`.

Same as ticket extraction MINUS `root_cause`, `fix`, `fix_kind` (we haven't resolved the live incident yet). Thinking: **OFF**.

### 4.3 DiagnosisAgent Stage 1 — hypothesize (Phase E — 200 calls in our subsample)

**Name:** `diagnosis_hypothesize`. Used by `DiagnosisAgent.diagnose` Stage 1.

```json
{
  "type": "object",
  "properties": {
    "root_cause_hypothesis": { "type": "string" },
    "key_symptoms":          { "type": "array", "items": { "type": "string" } },
    "suspected_services":    { "type": "array", "items": { "type": "string" } }
  },
  "required": ["root_cause_hypothesis", "key_symptoms", "suspected_services"],
  "additionalProperties": false
}
```

Thinking: **OFF**. This stage is "what do you observe" — fast, no reasoning needed.

### 4.4 DiagnosisAgent Stage 3 — verify and rank (Phase E — 200 calls)

**Name:** `diagnosis_verify`. Used by `DiagnosisAgent.diagnose` Stage 3.

```json
{
  "type": "object",
  "properties": {
    "ranked": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "ticket_id":   { "type": "string" },
          "confidence":  { "type": "number", "minimum": 0.0, "maximum": 1.0 },
          "consistent":  { "type": "boolean" },
          "reason":      { "type": "string" }
        },
        "required": ["ticket_id", "confidence", "consistent", "reason"],
        "additionalProperties": false
      }
    },
    "novel": { "type": "boolean" }
  },
  "required": ["ranked"],
  "additionalProperties": false
}
```

Thinking: **ON**. This is the actual reasoning step — judging consistency of 10 candidates against the hypothesis. `max_tokens` is raised to 1500 to accommodate the `<think>...</think>` block.

---

## 5. How our client sends these

`src/v2_advanced/shared/lm_studio.py`'s `LMStudioClient.chat_json` accepts both a per-call schema and a thinking-mode flag:

```python
from v2_advanced.shared.json_schemas import TICKET_EXTRACTION_RF
from v2_advanced.shared import LMStudioClient

client = LMStudioClient()
obj = client.chat_json(
    system="You are an SRE knowledge engineer ...",
    user="TICKET ID: shadow-xyz\n\n<ticket text>",
    response_format=TICKET_EXTRACTION_RF,
    enable_thinking=False,
    temperature=0.0,
    max_tokens=800,
)
```

Under the hood, this becomes a POST to `http://localhost:1234/v1/chat/completions` with body:

```jsonc
{
  "model": "local-model",
  "messages": [
    { "role": "system", "content": "You are an SRE knowledge engineer ..." },
    { "role": "user",   "content": "TICKET ID: shadow-xyz\n\n..." }
  ],
  "temperature": 0.0,
  "max_tokens": 800,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "ticket_extraction",
      "strict": true,
      "schema": { /* the schema above */ }
    }
  },
  "chat_template_kwargs": { "enable_thinking": false }
}
```

LM Studio honors both the `response_format` (constrains generation to the schema) and the `chat_template_kwargs` (suppresses Qwen3's `<think>` block).

The salvage parser still strips any leaked `<think>...</think>` block before parsing, in case the template doesn't honor the flag — defense in depth.

---

## 6. Latency expectations

On the RTX 5060 with the load settings above:

| Call type | Tokens/call | Thinking | Wall time per call | 347-batch total |
|---|---|---|---|---|
| Ticket extraction | 600–800 in, 300–500 out | OFF | ~3–5 s | ~25 min |
| Ticket extraction (if thinking were ON) | 600–800 in, 1500–2500 out | ON | ~12–25 s | ~90 min |
| Window extraction | 200–400 in, 200 out | OFF | ~1–2 s | ~30 min (for 1008 windows) |
| DiagnosisAgent Stage 1 | 800 in, 200 out | OFF | ~1–2 s | n/a (paired with Stage 3) |
| DiagnosisAgent Stage 3 | 1500 in, 1000 out (incl. thinking) | ON | ~15–30 s | ~70 min (for 200 windows) |

These are estimates for Qwen3.6 35B-A3B on RTX 5060 at the load settings above. MoE active-param count (~3B) makes the effective speed close to a small dense model.

---

## 7. Operational checklist (the user's path)

1. Load the model with the §2 settings.
2. Apply the §3 Inference-tab settings. Save preset as `qwen3-jira-triage` so you don't lose them.
3. Start the local server on port 1234.
4. Run the connectivity check from our side:
   ```powershell
   PYTHONPATH=src python -m v2_advanced.check_lm_studio
   ```
   You should see `OK: LM Studio reachable at http://localhost:1234` and `OK: JSON mode works`.
5. Smoke-test with 5 tickets to confirm the schema-constrained extraction is clean:
   ```powershell
   PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli `
       --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
       --limit 5
   ```
6. Run the full batch:
   ```powershell
   PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli `
       --global-dir data\derived\global\2026-05-25-dataset-v5-large-global
   ```
7. Load the new (LLM) extractions into Neo4j and re-run the v2 KG pipeline.
8. Run the DiagnosisAgent with real LLM verification.

The pipelines auto-fall-back to rule-based extraction if LM Studio is unavailable, so steps 5–8 are safe to retry.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Model fails to load (OOM) | GPU Offload too high | Drop from 22 → 18 → 16. Then turn off Offload KV Cache. Then raise CPU-MoE layers. |
| Empty responses | Server still warming up; first call is cold | Re-run; cached after first call. |
| `"could not parse JSON"` errors | Structured Output not enabled, or schema not honored | Confirm Structured Output is ON in the Inference tab. Confirm `enable_thinking=False` is being sent for extraction. |
| Long `<think>` blocks in extraction output | `enable_thinking=False` not honored by template | The salvage parser strips them; not fatal. Update LM Studio (template fix shipped 2024-Q4) if it persists. |
| 10× slower than expected | Thinking accidentally ON for extraction | Confirm `enable_thinking=False` is in the request body. Check our client's `chat()` call site. |
| Generation hangs at high tokens/s but never returns | Stop strings + `</think>` collision | Confirm Stop Strings is empty (the §3 setting). |
| `chat_template_kwargs` rejected by LM Studio | Older LM Studio version | Update LM Studio to >= 0.3.x. Or remove the kwarg and accept always-on thinking (with 3× cost). |

---

## 9. Cost ceiling for the paper

A complete v2 LLM run (assuming Qwen3.6 settings above):

| Pass | Wall time | Energy on RTX 5060 (~80 W avg) |
|---|---|---|
| 347 ticket extractions | ~25 min | ~33 Wh |
| 1008 window extractions (only if `kg_retrieval` runs all windows) | ~30 min | ~40 Wh |
| 200 DiagnosisAgent diagnoses (Stage 1 + Stage 3) | ~70 min | ~93 Wh |
| **Total LLM pass** | **~2 hours** | **~166 Wh** |

That's roughly the energy of running a laptop on battery for 2 hours, or about 550 Google web searches' worth. All energy is on the local RTX 5060 — no cloud cost.
