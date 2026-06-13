"""Verify the configured LLM provider is reachable + authenticated + has the model.

Run before any long agent experiment to fail fast on misconfiguration.

Usage:
    python scripts/agent/check_llm_provider.py
    # respects LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, etc. from env

    python scripts/agent/check_llm_provider.py --probe-chat
    # additionally issues a tiny chat call and a tiny schema-constrained call
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `python scripts/agent/check_llm_provider.py` from repo root
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-chat", action="store_true",
                        help="Issue a small chat call (and a schema-constrained one).")
    args = parser.parse_args()

    from agent.llm import (
        list_supported_providers,
        make_provider,
        LLMProviderError,
    )

    print(f"Supported providers: {list_supported_providers()}")
    print()
    print(f"LLM_PROVIDER = {os.environ.get('LLM_PROVIDER', '<unset>')}")
    print(f"LLM_BASE_URL = {os.environ.get('LLM_BASE_URL', '<unset>')}")
    print(f"LLM_MODEL    = {os.environ.get('LLM_MODEL', '<unset>')}")
    print()

    try:
        provider = make_provider()
    except LLMProviderError as e:
        print(f"FAILED to build provider: {e}", file=sys.stderr)
        return 1

    print(f"Built: {provider!r}")
    print()

    print("Health check ...")
    health = provider.is_available()
    print(f"  reachable      = {health.reachable}")
    print(f"  authenticated  = {health.authenticated}")
    print(f"  model_loaded   = {health.model_loaded}")
    print(f"  detail         = {health.detail}")
    print()
    if not health.ok:
        print("PROVIDER NOT READY. Fix configuration and re-run.", file=sys.stderr)
        return 2

    if not args.probe_chat:
        print("OK. (re-run with --probe-chat to also test a real call.)")
        return 0

    print("Probing free-text chat ...")
    r = provider.chat_json(
        system="You answer in one word.",
        user="Reply OK and nothing else.",
        max_tokens=10,
    )
    print(f"  content       = {r.content!r}")
    print(f"  tokens        = prompt {r.prompt_tokens} / completion {r.completion_tokens}")
    print(f"  latency_ms    = {r.latency_ms}")
    print(f"  finish_reason = {r.finish_reason}")
    print()

    print("Probing schema-constrained chat ...")
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok", "fail"]},
            "reason": {"type": "string"},
        },
        "required": ["status", "reason"],
        "additionalProperties": False,
    }
    r = provider.chat_json(
        system="Return JSON only.",
        user="Set status=ok and reason='probe successful'.",
        schema=schema,
        max_tokens=100,
    )
    print(f"  content_type  = {type(r.content).__name__}")
    print(f"  content       = {r.content}")
    print(f"  tokens        = prompt {r.prompt_tokens} / completion {r.completion_tokens}")
    print(f"  latency_ms    = {r.latency_ms}")

    if not isinstance(r.content, dict):
        print("Schema-constrained call did NOT return structured output.", file=sys.stderr)
        return 3

    print()
    print("OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
