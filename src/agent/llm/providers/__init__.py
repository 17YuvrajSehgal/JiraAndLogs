"""LLM provider adapters.

Each module implements `LLMProvider` for one wire-protocol family:

    lm_studio         — local LM Studio (OpenAI-compatible)
    openai_provider   — OpenAI cloud (auth, gpt-4o, o-series)
    ollama_provider   — Ollama (local or cluster)
    vllm_provider     — vLLM (cluster-grade throughput)
    generic_openai    — any other OpenAI-compatible endpoint
    anthropic_provider — Claude (different wire protocol: /v1/messages + tool_use)
"""
