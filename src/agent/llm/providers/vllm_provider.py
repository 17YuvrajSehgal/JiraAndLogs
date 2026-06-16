"""vLLM provider — cluster-grade throughput.

vLLM exposes an OpenAI-compatible HTTP server with continuous batching
that gives ~5-10× the throughput of single-stream inference on the same
GPU. For our research scale (2,000-ticket extraction at ~16 sec/window
on LM Studio) the expected wall-time drop is from ~8 h to ~30-60 min.

Structured output uses `extra_body: {guided_json: <schema>}` (vLLM's
guided-decoding mechanism). Bearer auth optional.

Typical deployment: launched as a SLURM job on Compute Canada with
`vllm serve qwen/qwen3.6-35b-a3b --port 8000`.
"""

from __future__ import annotations

from typing import Any

from ._openai_compat import OpenAICompatProvider


class VLLMProvider(OpenAICompatProvider):
    name_const = "vllm"
    supports_structured_output = True
    supports_tool_use = True
    default_context_window = 16384  # Per-model

    def _inject_schema(self, payload: dict[str, Any], schema: dict) -> None:
        """vLLM's guided-decoding API uses `extra_body.guided_json`."""
        extra_body = payload.setdefault("extra_body", {})
        extra_body["guided_json"] = schema
        # Some vLLM versions also accept the OpenAI-shape; we set both
        # to maximise compatibility across versions.
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema, "strict": True},
        }
