"""LM Studio provider — our research default.

LM Studio exposes an OpenAI-compatible `/v1/chat/completions` on
`http://localhost:1234` by default. No authentication. Structured
output via `response_format` with a JSON schema. Supports Qwen3's
`enable_thinking` toggle via `chat_template_kwargs`.

Known limitation: grammar-constrained inference is **single-threaded** —
concurrent requests under the same schema produce HTTP 400 (observed
during WoL KG extraction). The agent's controller serialises grammar
calls when LM Studio is the active provider.
"""

from __future__ import annotations

from ._openai_compat import OpenAICompatProvider


class LMStudioProvider(OpenAICompatProvider):
    name_const = "lm_studio"
    supports_structured_output = True
    supports_tool_use = False
    default_context_window = 16384

    # LM Studio is unauthenticated by default; the base class handles
    # the empty-api_key case cleanly.
    # Inherits _chat_raw, _build_chat_payload, _inject_schema (default
    # `response_format` shape works), _build_auth_headers, is_available.
