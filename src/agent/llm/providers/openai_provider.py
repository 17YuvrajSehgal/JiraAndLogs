"""OpenAI provider — BYO key.

Hits `https://api.openai.com/v1/chat/completions`. Auth via Bearer
`OPENAI_API_KEY`. Structured output via `response_format` with JSON
schema (gpt-4o / gpt-4o-mini / o-series support this natively).

Token counting uses `tiktoken` when available; falls back to the
4-chars-per-token heuristic otherwise.
"""

from __future__ import annotations

import logging

from ._openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)


class OpenAIProvider(OpenAICompatProvider):
    name_const = "openai"
    supports_structured_output = True
    supports_tool_use = True
    default_context_window = 128_000  # gpt-4o / gpt-4o-mini

    def count_tokens(self, text: str) -> int:
        """Use tiktoken when available; else fall back to heuristic."""
        try:
            import tiktoken
            try:
                enc = tiktoken.encoding_for_model(self.model)
            except KeyError:
                # Unknown model — use a reasonable default
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            log.debug("tiktoken not installed; using char-count heuristic")
            return super().count_tokens(text)
