"""LLM provider exception hierarchy.

All provider adapters raise subclasses of `LLMProviderError`. Catchers
upstream (Skill.invoke, AgentRunner) inspect the type to decide
fallback / retry / abort behaviour.
"""

from __future__ import annotations


class LLMProviderError(Exception):
    """Base class for all LLM provider errors.

    Carries `provider` (provider name) and `model` (model id) so logs and
    telemetry can attribute the failure correctly.
    """

    def __init__(self, message: str, *, provider: str = "", model: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


class ProviderUnavailable(LLMProviderError):
    """The provider's HTTP endpoint is unreachable or returned 5xx.

    Distinct from authentication errors — the service is up but the
    request didn't get through (network glitch, server overload, etc.).
    Retry-with-backoff is the appropriate response.
    """


class ProviderUnauthorized(LLMProviderError):
    """HTTP 401 / 403 from the provider.

    No point retrying — the API key is missing, invalid, or revoked.
    The agent should fail fast at startup so this surfaces before a
    multi-hour run.
    """


class ProviderRateLimited(LLMProviderError):
    """HTTP 429.

    Retry with a longer backoff than the default. If hit repeatedly,
    the experiment is over budget and the run should abort.
    """


class ContextOverflowError(LLMProviderError):
    """Prompt + max_tokens > model context window.

    Caught at pre-flight when the provider supports `count_tokens`. The
    skill's `on_failure` policy decides whether to skip the window
    (recording a `context_overflow` telemetry event) or to truncate +
    retry.
    """

    def __init__(self, message: str, *, prompt_tokens: int, max_tokens: int,
                 context_window: int, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.prompt_tokens = prompt_tokens
        self.max_tokens = max_tokens
        self.context_window = context_window


class SchemaViolationError(LLMProviderError):
    """The provider returned content that didn't match the requested JSON schema.

    The base `chat_json` will attempt one re-prompt before raising. If
    the re-prompt also violates, this is raised; the calling skill's
    fallback chain takes over.
    """

    def __init__(self, message: str, *, returned_text: str = "", **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.returned_text = returned_text


class ProviderTimeoutError(LLMProviderError):
    """The provider didn't respond within the configured timeout."""


class CostBudgetExceeded(LLMProviderError):
    """The Budget would be exceeded by this call.

    Pre-flight check uses the cost table + expected output tokens to
    decide whether to make the call. When raised, the call is NOT made.
    """

    def __init__(self, message: str, *, projected_cost_usd: float,
                 remaining_budget_usd: float, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.projected_cost_usd = projected_cost_usd
        self.remaining_budget_usd = remaining_budget_usd
