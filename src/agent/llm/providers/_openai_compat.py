"""Shared scaffolding for OpenAI-compatible providers.

LM Studio, OpenAI, Ollama (via /v1/chat/completions), vLLM, and the
generic catch-all all speak the same wire shape:

    POST {base_url}/v1/chat/completions
    {
        "model": ...,
        "messages": [{"role": "system", "content": ...},
                     {"role": "user",   "content": ...}],
        "temperature": ...,
        "max_tokens": ...,
        "response_format": {"type": "json_schema", "json_schema": {...}}   # optional
    }

Differences between concrete providers:
    - Auth header (none for local, Bearer for hosted).
    - Schema parameter shape (response_format vs format vs extra_body).
    - Token-usage field naming (universal: prompt_tokens, completion_tokens).
    - Vendor-specific extras (Qwen3 thinking mode, etc.).

The `OpenAICompatProvider` base implements the common `_chat_raw` and
lets subclasses override the small surface that differs.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    Timeout as RequestsTimeout,
)

from ..base import ChatResponse, LLMProvider, LLMProviderConfig, ProviderHealth
from ..exceptions import (
    LLMProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnauthorized,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """Shared base for providers that speak OpenAI's chat-completions shape.

    Subclasses override:
        - `_build_auth_headers()`   — provider-specific auth
        - `_build_schema_payload()` — provider-specific schema wrapper
        - `default_context_window` — class attr per model family
    """

    # Subclasses may override
    chat_endpoint: str = "/v1/chat/completions"
    health_endpoint: str = "/v1/models"

    def is_available(self) -> ProviderHealth:
        """Probe `/v1/models`. Distinguishes reachable vs auth vs model-missing."""
        url = self.config.base_url.rstrip("/") + self.health_endpoint
        try:
            resp = requests.get(
                url, headers=self._build_auth_headers(),
                timeout=min(10.0, self.config.timeout_s),
            )
        except (RequestsConnectionError, RequestsTimeout) as e:
            return ProviderHealth(
                reachable=False, authenticated=False, model_loaded=False,
                detail=f"{type(e).__name__}: {e}",
            )
        if resp.status_code == 401 or resp.status_code == 403:
            return ProviderHealth(
                reachable=True, authenticated=False, model_loaded=False,
                detail=f"HTTP {resp.status_code}",
            )
        if resp.status_code >= 500:
            return ProviderHealth(
                reachable=False, authenticated=False, model_loaded=False,
                detail=f"HTTP {resp.status_code}",
            )
        if resp.status_code != 200:
            return ProviderHealth(
                reachable=True, authenticated=False, model_loaded=False,
                detail=f"HTTP {resp.status_code}",
            )
        # Check the model is listed
        try:
            body = resp.json()
        except ValueError:
            return ProviderHealth(
                reachable=True, authenticated=True, model_loaded=False,
                detail="health endpoint returned non-JSON",
            )
        models = body.get("data") or body.get("models") or []
        model_ids = [m.get("id") if isinstance(m, dict) else str(m) for m in models]
        model_present = self.model in model_ids
        if not model_present and model_ids:
            return ProviderHealth(
                reachable=True, authenticated=True, model_loaded=False,
                detail=f"model {self.model!r} not in served list "
                       f"(first 5: {model_ids[:5]})",
            )
        # Some endpoints (Ollama via /v1/models) may not list the
        # currently-loaded model the same way; we accept reachable+auth
        # and let the first real call surface a 404 if any.
        return ProviderHealth(
            reachable=True, authenticated=True, model_loaded=True,
            detail=f"model_present={model_present}; n_models={len(model_ids)}",
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
        payload = self._build_chat_payload(
            system=system, user=user, schema=schema,
            temperature=temperature, max_tokens=max_tokens, thinking=thinking,
        )
        url = self.config.base_url.rstrip("/") + self.chat_endpoint
        headers = {"Content-Type": "application/json", **self._build_auth_headers()}

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

        # Status handling
        if resp.status_code == 401 or resp.status_code == 403:
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
                f"Provider returned non-JSON: {resp.text[:200]}",
                provider=self.name, model=self.model,
            ) from e

        return self._parse_chat_response(body, latency_ms, schema is not None)

    # ------------------------------------------------------------------ payload assembly

    def _build_chat_payload(
        self,
        *,
        system: str,
        user: str,
        schema: dict | None,
        temperature: float,
        max_tokens: int,
        thinking: bool | None,
    ) -> dict[str, Any]:
        """Assemble the JSON body. Subclasses can override `_build_schema_payload`
        to change just the structured-output bit."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            self._inject_schema(payload, schema)
        if thinking is not None:
            # Qwen3 family convention; harmless on providers that ignore it
            payload["chat_template_kwargs"] = {"enable_thinking": bool(thinking)}
        return payload

    def _inject_schema(self, payload: dict[str, Any], schema: dict) -> None:
        """Default: OpenAI-style `response_format`. Override in subclasses
        that use a different parameter (Ollama 0.5+'s top-level `format`,
        vLLM's `extra_body.guided_json`)."""
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema, "strict": True},
        }

    def _build_auth_headers(self) -> dict[str, str]:
        """Default: Bearer token if api_key is set, else nothing. Override
        for providers needing different auth schemes."""
        if self.config.api_key:
            return {
                "Authorization": f"Bearer {self.config.api_key}",
                **self.config.extra_headers,
            }
        return dict(self.config.extra_headers)

    # ------------------------------------------------------------------ response parsing

    def _parse_chat_response(
        self, body: dict, latency_ms: int, schema_requested: bool,
    ) -> ChatResponse:
        """OpenAI-style: `body["choices"][0]["message"]["content"]` + `body["usage"]`."""
        try:
            choice = body["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMProviderError(
                f"Provider response missing choices/message: {str(body)[:200]}",
                provider=self.name, model=self.model,
            ) from e

        content = msg.get("content") or ""
        # Qwen3-style: response in `reasoning_content` when thinking ON
        if not str(content).strip():
            content = msg.get("reasoning_content") or ""

        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        finish_reason = choice.get("finish_reason") or "stop"

        # If schema was requested AND content looks like valid JSON, parse it now
        parsed: Any
        raw_text = str(content)
        if schema_requested:
            parsed_dict = self._try_parse_json(raw_text)
            parsed = parsed_dict if parsed_dict is not None else raw_text
        else:
            parsed = raw_text

        return ChatResponse(
            content=parsed,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            model=self.model,
            provider=self.name,
            finish_reason=finish_reason,
        )
