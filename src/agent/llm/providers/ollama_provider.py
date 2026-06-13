"""Ollama provider.

Ollama exposes two API surfaces:
    - OpenAI-compatible `/v1/chat/completions`
    - Native `/api/chat` with richer options

This adapter uses the OpenAI-compatible surface for consistency with the
other providers. For schema-constrained output, Ollama 0.5+ accepts the
JSON schema at the top-level `format` field (not nested in
`response_format`).

Default base_url: `http://localhost:11434` (Ollama's standard port).
Auth: unauthenticated by default; an optional `OLLAMA_API_KEY` can be
set when running behind a reverse proxy.
"""

from __future__ import annotations

from typing import Any

from ._openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    name_const = "ollama"
    supports_structured_output = True
    supports_tool_use = False  # Some Ollama models support tools; conservative default
    default_context_window = 8192  # Per-model; override via config.extra

    def _inject_schema(self, payload: dict[str, Any], schema: dict) -> None:
        """Ollama 0.5+: top-level `format` carries the JSON schema directly.

        Older Ollama versions accept only `format: "json"` (basic JSON
        mode, no schema). If the cluster's Ollama is older, the base
        `chat_json` will catch the schema-violation and re-prompt.
        """
        payload["format"] = schema
