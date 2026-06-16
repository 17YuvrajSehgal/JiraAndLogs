"""Anthropic Claude provider.

Anthropic's `/v1/messages` API differs structurally from OpenAI's
`/v1/chat/completions`:

  - `system` is a TOP-LEVEL parameter, not in `messages`.
  - `max_tokens` is REQUIRED on every call (not optional).
  - Auth is `x-api-key: <key>` + `anthropic-version: 2023-06-01`.
  - Structured output uses the **tool_use** mechanism:
        tools = [{
            "name": "extract_response",
            "description": "Return the answer as a structured JSON",
            "input_schema": <our_schema>,
        }]
        tool_choice = {"type": "tool", "name": "extract_response"}
    The model's response then carries `content[0].type == "tool_use"`
    and `content[0].input == <parsed JSON dict>`.
  - Token usage in `usage.input_tokens` / `usage.output_tokens`
    (not `prompt_tokens` / `completion_tokens`).

This adapter hides ALL of that behind the same `chat_json` contract.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
)

from ..base import ChatResponse, LLMProvider, ProviderHealth
from ..exceptions import (
    LLMProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnauthorized,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)

# Default Anthropic API version. Override via config.extra["anthropic_version"]
# if the user pins a different one.
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

# The internal tool name used to coax structured JSON output.
_STRUCTURED_TOOL_NAME = "structured_response"


class AnthropicProvider(LLMProvider):
    name_const = "anthropic"
    supports_structured_output = True
    supports_tool_use = True
    default_context_window = 200_000  # Claude 3.5+ extended-context

    # ------------------------------------------------------------------ health

    def is_available(self) -> ProviderHealth:
        """Probe `/v1/models`. Anthropic returns the list under `data`."""
        url = self.config.base_url.rstrip("/") + "/v1/models"
        try:
            resp = requests.get(
                url, headers=self._auth_headers(),
                timeout=min(10.0, self.config.timeout_s),
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return ProviderHealth(
                reachable=False, authenticated=False, model_loaded=False,
                detail=f"{type(e).__name__}: {e}",
            )
        if resp.status_code in (401, 403):
            return ProviderHealth(
                reachable=True, authenticated=False, model_loaded=False,
                detail=f"HTTP {resp.status_code}",
            )
        if resp.status_code != 200:
            return ProviderHealth(
                reachable=True, authenticated=False, model_loaded=False,
                detail=f"HTTP {resp.status_code}",
            )
        try:
            body = resp.json()
        except ValueError:
            return ProviderHealth(
                reachable=True, authenticated=True, model_loaded=False,
                detail="Anthropic /v1/models returned non-JSON",
            )
        model_ids = [m.get("id") for m in (body.get("data") or [])]
        return ProviderHealth(
            reachable=True, authenticated=True,
            model_loaded=self.model in model_ids,
            detail=f"n_models_listed={len(model_ids)}",
        )

    # ------------------------------------------------------------------ chat

    def _chat_raw(
        self,
        *,
        system: str,
        user: str,
        schema: dict | None,
        temperature: float,
        max_tokens: int,
        thinking: bool | None,
    ) -> ChatResponse:
        url = self.config.base_url.rstrip("/") + "/v1/messages"
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        if schema is not None:
            # Use tool_use mechanism to coerce structured JSON
            payload["tools"] = [{
                "name": _STRUCTURED_TOOL_NAME,
                "description": "Return the structured response as required by the calling code.",
                "input_schema": schema,
            }]
            payload["tool_choice"] = {"type": "tool", "name": _STRUCTURED_TOOL_NAME}

        # `thinking` is supported on Claude 3.7+ via extended-thinking;
        # ignored on older models. Mapped to `thinking` block when True.
        if thinking is True:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 1024}

        headers = {"Content-Type": "application/json", **self._auth_headers()}

        t0 = time.monotonic()
        try:
            resp = requests.post(
                url, headers=headers,
                data=json.dumps(payload).encode("utf-8"),
                timeout=self.config.timeout_s,
            )
        except RequestsTimeout as e:
            raise ProviderTimeoutError(
                str(e), provider=self.name, model=self.model,
            ) from e
        except RequestsConnectionError as e:
            raise ProviderUnavailable(
                str(e), provider=self.name, model=self.model,
            ) from e

        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code in (401, 403):
            raise ProviderUnauthorized(
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                provider=self.name, model=self.model,
            )
        if resp.status_code == 429:
            raise ProviderRateLimited(
                f"HTTP 429: {resp.text[:200]}",
                provider=self.name, model=self.model,
            )
        if resp.status_code >= 500:
            raise ProviderUnavailable(
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                provider=self.name, model=self.model,
            )
        if resp.status_code != 200:
            raise LLMProviderError(
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                provider=self.name, model=self.model,
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise LLMProviderError(
                f"Anthropic returned non-JSON: {resp.text[:200]}",
                provider=self.name, model=self.model,
            ) from e

        return self._parse_response(body, latency_ms, schema is not None)

    # ------------------------------------------------------------------ helpers

    def _auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise ProviderUnauthorized(
                "ANTHROPIC_API_KEY not set",
                provider=self.name, model=self.model,
            )
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.extra.get(
                "anthropic_version", DEFAULT_ANTHROPIC_VERSION,
            ),
            **self.config.extra_headers,
        }

    def _parse_response(self, body: dict, latency_ms: int, schema_requested: bool) -> ChatResponse:
        """Translate Anthropic's response shape into the uniform ChatResponse.

        - body["content"] is a list of blocks: text, tool_use, thinking, etc.
        - When schema_requested: find the tool_use block whose name matches
          _STRUCTURED_TOOL_NAME; its `input` is the parsed dict.
        - When free text: concatenate the text blocks.
        - body["usage"] has input_tokens / output_tokens.
        """
        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = prompt_tokens + completion_tokens
        stop_reason = body.get("stop_reason") or "stop"
        # Normalize stop reason to OpenAI-style finish_reason
        finish_reason = {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_use",
            "stop_sequence": "stop",
        }.get(stop_reason, stop_reason)

        content_blocks = body.get("content") or []
        raw_text_parts: list[str] = []
        structured: Any = None

        for block in content_blocks:
            btype = block.get("type")
            if btype == "tool_use" and block.get("name") == _STRUCTURED_TOOL_NAME:
                structured = block.get("input")
            elif btype == "text":
                raw_text_parts.append(str(block.get("text") or ""))
            # thinking blocks are silently dropped (we don't expose them)

        raw_text = "\n".join(raw_text_parts) or (
            json.dumps(structured) if structured is not None else ""
        )

        if schema_requested:
            if structured is None:
                # Model returned text instead of tool_use; base.chat_json
                # will see is_structured()==False and trigger a re-prompt.
                content: Any = raw_text
            else:
                content = structured
        else:
            content = raw_text

        return ChatResponse(
            content=content,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            model=self.model,
            provider=self.name,
            finish_reason=finish_reason,
        )
