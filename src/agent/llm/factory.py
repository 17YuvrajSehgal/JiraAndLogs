"""Factory: build an `LLMProvider` from env vars + agent-config.yaml.

Single entry point for the rest of the agent. Skills receive a built
provider via the AgentContext; nothing inside skills knows or cares
which concrete class is behind it.

Resolution order (later overrides earlier):
    1. Built-in defaults.
    2. `agent-config.yaml > llm` block.
    3. Environment variables (LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL,
       LLM_API_KEY plus provider-specific *_API_KEY).
    4. Function arguments to `make_provider(...)`.
"""

from __future__ import annotations

import os
from typing import Type

from .base import LLMProvider, LLMProviderConfig
from .exceptions import LLMProviderError
from .providers.anthropic_provider import AnthropicProvider
from .providers.generic_openai import GenericOpenAIProvider
from .providers.lm_studio import LMStudioProvider
from .providers.ollama_provider import OllamaProvider
from .providers.openai_provider import OpenAIProvider
from .providers.vllm_provider import VLLMProvider


# Registry of supported providers, keyed by the LLM_PROVIDER env-var value
PROVIDER_REGISTRY: dict[str, Type[LLMProvider]] = {
    "lm_studio":      LMStudioProvider,
    "openai":         OpenAIProvider,
    "anthropic":      AnthropicProvider,
    "ollama":         OllamaProvider,
    "vllm":           VLLMProvider,
    "generic_openai": GenericOpenAIProvider,
}


# Default base_url per provider when LLM_BASE_URL is unset
_DEFAULT_BASE_URLS: dict[str, str] = {
    "lm_studio":      "http://localhost:1234",
    "openai":         "https://api.openai.com",
    "anthropic":      "https://api.anthropic.com",
    "ollama":         "http://localhost:11434",
    "vllm":           "http://localhost:8000",
    "generic_openai": "http://localhost:8080",
}


# Provider-specific API key env var
_API_KEY_VARS: dict[str, str] = {
    "lm_studio":      "",                  # unauthenticated
    "openai":         "OPENAI_API_KEY",
    "anthropic":      "ANTHROPIC_API_KEY",
    "ollama":         "OLLAMA_API_KEY",
    "vllm":           "VLLM_API_KEY",
    "generic_openai": "LLM_API_KEY",
}


def make_provider(
    *,
    config: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_s: float | None = None,
    max_retries: int | None = None,
    extra: dict | None = None,
) -> LLMProvider:
    """Build an `LLMProvider`.

    Args:
        config: optional dict from `agent-config.yaml > llm`. Provides
            defaults; env vars override.
        provider / model / base_url / api_key / timeout_s / max_retries:
            explicit overrides (highest precedence).
        extra: provider-specific options merged into LLMProviderConfig.extra.

    Returns:
        A concrete LLMProvider subclass instance.

    Raises:
        LLMProviderError: if the requested provider is unknown or the
            API key is missing for a provider that requires one.
    """
    cfg_block = config or {}

    # Resolve provider name (highest precedence wins)
    provider_name = (
        provider
        or os.environ.get("LLM_PROVIDER")
        or cfg_block.get("provider")
        or "lm_studio"
    ).strip()

    if provider_name not in PROVIDER_REGISTRY:
        raise LLMProviderError(
            f"Unknown LLM_PROVIDER={provider_name!r}. "
            f"Supported: {sorted(PROVIDER_REGISTRY)}",
            provider=provider_name,
        )

    # Resolve model
    model_name = (
        model
        or os.environ.get("LLM_MODEL")
        or cfg_block.get("model")
        or ""
    ).strip()
    if not model_name:
        raise LLMProviderError(
            "No LLM model specified. Set LLM_MODEL env var or "
            "agent-config.yaml > llm.model.",
            provider=provider_name,
        )

    # Resolve base_url
    base = (
        base_url
        or os.environ.get("LLM_BASE_URL")
        or cfg_block.get("base_url")
        or _DEFAULT_BASE_URLS[provider_name]
    ).rstrip("/")

    # Resolve api_key (per-provider env var, falling back to generic LLM_API_KEY)
    if api_key is None:
        env_var = _API_KEY_VARS[provider_name]
        if env_var:
            api_key = os.environ.get(env_var, "") or os.environ.get("LLM_API_KEY", "")
        else:
            api_key = ""

    # Resolve timeout + retries
    timeout = float(
        timeout_s
        if timeout_s is not None
        else cfg_block.get("timeout_s", 120.0)
    )
    retries = int(
        max_retries
        if max_retries is not None
        else (cfg_block.get("retry") or {}).get("max_attempts", 3)
    )
    backoff = tuple(
        float(x)
        for x in (cfg_block.get("retry") or {}).get("backoff_s", [1.0, 4.0, 16.0])
    )

    provider_config = LLMProviderConfig(
        provider=provider_name,
        model=model_name,
        base_url=base,
        api_key=api_key,
        timeout_s=timeout,
        max_retries=retries,
        retry_backoff_s=backoff,
        extra=extra or {},
    )

    cls = PROVIDER_REGISTRY[provider_name]
    return cls(provider_config)


def list_supported_providers() -> list[str]:
    """Public helper for CLI / diagnostics."""
    return sorted(PROVIDER_REGISTRY)
