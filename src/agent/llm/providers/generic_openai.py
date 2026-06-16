"""Generic OpenAI-compatible provider.

Catch-all for any self-hosted or third-party endpoint that speaks the
OpenAI `/v1/chat/completions` shape. No assumptions about
authentication, schema mechanism, or context window — config-driven.

Use when:
    - The provider isn't one of the named adapters but speaks OpenAI shape.
    - You're testing a new endpoint and don't want to write a new adapter yet.
"""

from __future__ import annotations

from ._openai_compat import OpenAICompatProvider


class GenericOpenAIProvider(OpenAICompatProvider):
    name_const = "generic_openai"
    # Conservative defaults; the specific endpoint may support more
    supports_structured_output = True
    supports_tool_use = False
    default_context_window = 8192
