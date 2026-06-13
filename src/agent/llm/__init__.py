"""LLM provider abstraction (Phase 1.2).

Public API:

    >>> from agent.llm import make_provider
    >>> provider = make_provider()                   # reads .env + agent-config.yaml
    >>> health = provider.is_available()
    >>> response = provider.chat_json(
    ...     system="You are an extractor.",
    ...     user="Window evidence: ...",
    ...     schema=MY_SCHEMA,
    ... )
    >>> response.content      # parsed dict
    >>> response.prompt_tokens, response.completion_tokens, response.latency_ms

Spec: DOCS/docs7/AGENTIC-SYSTEM.md §10.
"""

from .base import (
    ChatResponse,
    LLMProvider,
    LLMProviderConfig,
    ProviderHealth,
    register_telemetry_hook,
)
from .cost_table import CostEntry, lookup as lookup_cost, monetary_equivalent_baselines
from .exceptions import (
    ContextOverflowError,
    CostBudgetExceeded,
    LLMProviderError,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderUnauthorized,
    ProviderUnavailable,
    SchemaViolationError,
)
from .factory import PROVIDER_REGISTRY, list_supported_providers, make_provider
from .telemetry import TokenLogger, configure_telemetry, from_env as telemetry_from_env
from .telemetry_summary import load_records, summarise, write_summary

__all__ = [
    # public dataclasses
    "ChatResponse",
    "LLMProvider",
    "LLMProviderConfig",
    "ProviderHealth",
    "CostEntry",
    # factory
    "make_provider",
    "list_supported_providers",
    "PROVIDER_REGISTRY",
    # cost
    "lookup_cost",
    "monetary_equivalent_baselines",
    # telemetry
    "TokenLogger",
    "configure_telemetry",
    "telemetry_from_env",
    "register_telemetry_hook",
    "load_records",
    "summarise",
    "write_summary",
    # exceptions
    "LLMProviderError",
    "ProviderUnavailable",
    "ProviderUnauthorized",
    "ProviderRateLimited",
    "ProviderTimeoutError",
    "ContextOverflowError",
    "CostBudgetExceeded",
    "SchemaViolationError",
]
