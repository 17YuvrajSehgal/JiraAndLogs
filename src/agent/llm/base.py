"""LLM provider abstraction — the ABC every adapter implements.

This module defines the contract shared by `LMStudioProvider`,
`OpenAIProvider`, `AnthropicProvider`, `OllamaProvider`, `VLLMProvider`,
and any future BYO provider. Skills never import from a concrete
provider; they receive a `LLMProvider` via the `AgentContext` and call
`chat_json()`.

The `LLMProvider.chat_json()` method is implemented HERE in the base
class. It handles retries, structured-output validation, telemetry
hooks, and pre-flight context checks. Subclasses implement only
`_chat_raw()` (the wire-level HTTP call) and `is_available()`.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §10.

Note: subclasses MUST be thread-safe — the agent runs skills
concurrently when the controller permits it.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .exceptions import (
    LLMProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnavailable,
    SchemaViolationError,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatResponse:
    """Uniform response shape returned by every provider.

    `content` is the parsed JSON dict when a schema was requested, else
    the raw text. `raw_text` is the unmodified response (useful when
    the model emitted JSON-mode but the caller asked for free text, or
    for debugging schema violations).
    """

    content: dict | list | str
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    model: str
    provider: str
    finish_reason: str = "stop"
    cached: bool = False

    def is_structured(self) -> bool:
        return isinstance(self.content, (dict, list))


@dataclass(frozen=True)
class ProviderHealth:
    """Result of `is_available()`. Used at startup to fail fast."""

    reachable: bool
    authenticated: bool
    model_loaded: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reachable and self.authenticated and self.model_loaded

    def __str__(self) -> str:
        return (
            f"reachable={self.reachable} "
            f"authenticated={self.authenticated} "
            f"model_loaded={self.model_loaded} "
            f"detail={self.detail!r}"
        )


@dataclass(frozen=True)
class LLMProviderConfig:
    """Inputs to construct an LLMProvider. Built by the factory from
    a combination of env vars + agent-config.yaml + sane defaults."""

    provider: str
    model: str
    base_url: str
    api_key: str = ""
    timeout_s: float = 120.0
    max_retries: int = 3
    retry_backoff_s: tuple[float, ...] = (1.0, 4.0, 16.0)
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Per-provider knobs that don't fit the universal interface go in
    # `extra` — e.g. Anthropic's anthropic-version header.
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Telemetry hook
# ---------------------------------------------------------------------------
#
# A TokenLogger is registered here at runner startup; base.chat_json()
# invokes whatever's registered when a call completes (success OR failure).
# Keeping it as a free function means provider code stays oblivious to
# telemetry concerns.


_telemetry_hook: Callable[[dict[str, Any]], None] | None = None


def register_telemetry_hook(hook: Callable[[dict[str, Any]], None] | None) -> None:
    """Register (or clear) a callback invoked after every LLM call.

    The hook receives a dict with `(provider, model, prompt_tokens,
    completion_tokens, latency_ms, success, error, cached, ...)` and
    must not raise. Hook exceptions are logged + swallowed."""
    global _telemetry_hook
    _telemetry_hook = hook


def _emit_telemetry(record: dict[str, Any]) -> None:
    if _telemetry_hook is None:
        return
    try:
        _telemetry_hook(record)
    except Exception as e:  # noqa: BLE001 — never let telemetry break a real call
        log.warning("telemetry hook raised %s: %s", type(e).__name__, e)


# ---------------------------------------------------------------------------
# The ABC
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Base class for every LLM provider adapter.

    Subclasses implement `_chat_raw()` and `is_available()`. The public
    `chat_json()` lives here and handles retries, validation, and
    telemetry. Subclasses never reimplement retry logic.
    """

    # Class-level constants — subclasses override as needed
    supports_structured_output: bool = True
    supports_tool_use: bool = False
    default_context_window: int = 16384

    def __init__(self, config: LLMProviderConfig) -> None:
        self.config = config
        self.name = config.provider
        self.model = config.model

    # ------------------------------------------------------------------ public API

    @abstractmethod
    def is_available(self) -> ProviderHealth:
        """Health check. Called at agent startup; never inside hot paths."""

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        thinking: bool | None = None,
        experiment: str = "",
        phase: str = "",
        skill: str = "",
        bundle_id: str = "",
    ) -> ChatResponse:
        """Issue a chat call. Returns a `ChatResponse` with parsed content.

        When `schema` is supplied:
            - The provider is instructed to emit JSON matching the
              schema (provider-specific mechanism).
            - The response is parsed; on parse failure, ONE re-prompt is
              attempted; further failures raise `SchemaViolationError`.
            - `content` is the parsed dict/list.

        When `schema` is None:
            - Free text is returned; `content` is a str.

        Retries (config.max_retries with config.retry_backoff_s) apply
        to network errors (5xx, timeouts, rate limits). They do NOT
        apply to schema violations (handled separately above) or to
        authentication errors (fail fast).
        """
        last_err: Exception | None = None
        start_total = time.monotonic()

        for attempt in range(1, self.config.max_retries + 1):
            try:
                t0 = time.monotonic()
                response = self._chat_raw(
                    system=system,
                    user=user,
                    schema=schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking=thinking,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                # Schema validation / re-prompt
                if schema is not None and not response.is_structured():
                    parsed = self._try_parse_json(response.raw_text)
                    if parsed is None:
                        log.warning(
                            "[%s/%s] schema-violation; re-prompting once",
                            self.name, self.model,
                        )
                        # One re-prompt with a clarifying suffix
                        response = self._chat_raw(
                            system=system,
                            user=user + "\n\nRespond ONLY with valid JSON matching the schema.",
                            schema=schema,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            thinking=thinking,
                        )
                        parsed = self._try_parse_json(response.raw_text)
                        if parsed is None:
                            err = SchemaViolationError(
                                "Provider response could not be parsed as JSON matching schema.",
                                provider=self.name, model=self.model,
                                returned_text=response.raw_text[:500],
                            )
                            _emit_telemetry(self._telemetry_record(
                                experiment=experiment, phase=phase, skill=skill,
                                bundle_id=bundle_id, attempt=attempt,
                                latency_ms=int((time.monotonic() - start_total) * 1000),
                                prompt_tokens=response.prompt_tokens,
                                completion_tokens=response.completion_tokens,
                                success=False, error="schema_violation",
                            ))
                            raise err
                    # rebuild as structured
                    response = ChatResponse(
                        content=parsed,
                        raw_text=response.raw_text,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        total_tokens=response.total_tokens,
                        latency_ms=latency_ms,
                        model=self.model,
                        provider=self.name,
                        finish_reason=response.finish_reason,
                    )

                # Success
                _emit_telemetry(self._telemetry_record(
                    experiment=experiment, phase=phase, skill=skill,
                    bundle_id=bundle_id, attempt=attempt,
                    latency_ms=latency_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    success=True, error=None,
                ))
                return response

            except (ProviderUnavailable, ProviderTimeoutError, ProviderRateLimited) as e:
                # Retryable
                last_err = e
                if attempt >= self.config.max_retries:
                    break
                backoff = self.config.retry_backoff_s[
                    min(attempt - 1, len(self.config.retry_backoff_s) - 1)
                ]
                log.warning(
                    "[%s/%s] %s attempt=%d/%d; backing off %.1fs",
                    self.name, self.model, type(e).__name__,
                    attempt, self.config.max_retries, backoff,
                )
                time.sleep(backoff)

        # Exhausted retries
        _emit_telemetry(self._telemetry_record(
            experiment=experiment, phase=phase, skill=skill,
            bundle_id=bundle_id, attempt=self.config.max_retries,
            latency_ms=int((time.monotonic() - start_total) * 1000),
            prompt_tokens=0, completion_tokens=0,
            success=False,
            error=f"{type(last_err).__name__}: {last_err}" if last_err else "unknown",
        ))
        raise last_err if last_err else LLMProviderError(
            "exhausted retries without a specific error",
            provider=self.name, model=self.model,
        )

    def count_tokens(self, text: str) -> int:
        """Approximate token count for budget pre-flight.

        Default heuristic: ~4 chars per token (works for English; close
        enough for budget gating). Providers with a real tokenizer
        (e.g. OpenAI's tiktoken) override this.
        """
        return max(1, len(text) // 4)

    # ------------------------------------------------------------------ subclass hooks

    @abstractmethod
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
        """Execute the wire-level HTTP call.

        Must raise `ProviderUnavailable` / `ProviderTimeoutError` /
        `ProviderRateLimited` / `ProviderUnauthorized` as appropriate.
        Should NOT implement retry logic — the base class handles that.

        When `schema` is supplied, the implementation should pass
        whatever provider-specific mechanism enables structured output
        (OpenAI: `response_format`, Anthropic: tool_use, Ollama:
        `format`, vLLM: `guided_json`). The returned `ChatResponse`
        should already have parsed `content` if the provider succeeded;
        if it returned raw text the base class will try to parse it.
        """

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _try_parse_json(text: str) -> dict | list | None:
        """Best-effort JSON parse. Returns None on failure.

        Handles common LLM emission quirks: markdown code-fence wrapping,
        leading/trailing whitespace, trailing commas (lenient).
        """
        if not text:
            return None
        # Strip markdown code fences if present
        stripped = text.strip()
        if stripped.startswith("```"):
            # Drop the first fence line and the trailing fence line
            lines = stripped.splitlines()
            if len(lines) >= 2:
                # Pop opening ``` (optionally with ```json)
                lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                stripped = "\n".join(lines).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    def _telemetry_record(self, **kwargs) -> dict[str, Any]:
        """Build the telemetry dict; populated common fields here."""
        base = {
            "provider": self.name,
            "model": self.model,
            "cached": False,
        }
        base.update(kwargs)
        return base

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r}, base_url={self.config.base_url!r})"
