"""Thin LM Studio (OpenAI-compatible) client.

LM Studio exposes a /v1/chat/completions endpoint at http://localhost:1234
by default. This client wraps it with sensible defaults for our
structured-extraction workload: low temperature, retries, per-call JSON
schemas, and thinking-mode control for Qwen3-family models.

Per-call JSON schemas (recommended):

    from v2_advanced.shared.json_schemas import TICKET_EXTRACTION_RF
    obj = client.chat_json(
        system="...",
        user="...",
        response_format=TICKET_EXTRACTION_RF,
        enable_thinking=False,    # fast structured extraction
    )

Generic JSON mode (backward compatible):

    obj = client.chat_json(system="...", user="...")   # `response_format`
                                                       # defaults to
                                                       # {"type": "json_object"}

Thinking-mode control:

  enable_thinking=False  — Qwen3 emits a direct answer (~25 min for our
                           347-ticket extraction batch).
  enable_thinking=True   — Qwen3 emits chain-of-thought before the answer
                           (~90 min for the same batch but better
                           reasoning for verification calls).

When `enable_thinking=False`, we pass
    chat_template_kwargs={"enable_thinking": false}
in the request body. LM Studio forwards this to the chat template which,
for Qwen3 templates, prevents the <think>...</think> block.

The existing comparison.retrievers.chat_via_lm_studio helper is too
minimal for our use case (no JSON mode, no schemas, no retry, no
thinking control). Rather than expand it (which would impact the v1
panel), we ship a clean v2 client here.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .logging import get_logger

log = get_logger("lm_studio")


@dataclass
class LMStudioConfig:
    base_url: str = "http://localhost:1234"
    model: str = "local-model"   # LM Studio picks the loaded model regardless
    timeout_s: float = 120.0
    max_retries: int = 3
    retry_backoff_s: float = 2.0


class LMStudioError(RuntimeError):
    pass


# Default generic JSON envelope used when caller doesn't supply a schema.
_GENERIC_JSON_RF: dict[str, Any] = {"type": "json_object"}


class LMStudioClient:
    """OpenAI-compatible chat-completions client for the local LM Studio
    server. Stateless; safe to share across threads (one urllib request
    per call).
    """

    def __init__(self, config: LMStudioConfig | None = None) -> None:
        self.config = config or LMStudioConfig()

    def is_available(self) -> bool:
        """Quick health-check (GET /v1/models). Returns True if the
        local server is up."""
        try:
            req = urllib.request.Request(
                f"{self.config.base_url}/v1/models", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
        stop: list[str] | None = None,
    ) -> str:
        """Issue a chat-completion call; return the assistant message content.

        Parameters:
          response_format
              Direct override for the `response_format` request field. Pass
              a per-call schema envelope from `json_schemas.py`
              (e.g. `TICKET_EXTRACTION_RF`) for grammar-constrained output.
              When set, takes precedence over `json_mode`.

          json_mode
              Backward-compatible shortcut. If True and no `response_format`
              is supplied, requests generic JSON output via
              `{"type": "json_object"}`. Equivalent to passing
              `response_format=LM_STUDIO_GENERIC_JSON_RF`.

          enable_thinking
              For Qwen3-family models:
                None  — let the server default decide (whatever is in
                        the LM Studio Inference tab; usually ON).
                False — force-off via `chat_template_kwargs.enable_thinking=False`.
                        Use for fast extraction (Phase D).
                True  — force-on. Use for DiagnosisAgent verify (Phase E).

          stop
              Optional stop sequences.

        Raises LMStudioError on persistent failure.
        """
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        elif json_mode:
            payload["response_format"] = _GENERIC_JSON_RF

        if enable_thinking is not None:
            # Qwen3 / instruct-template convention. LM Studio forwards
            # these kwargs into the model's chat template, which honors
            # the `enable_thinking` flag.
            payload["chat_template_kwargs"] = {"enable_thinking": bool(enable_thinking)}

        if stop:
            payload["stop"] = stop

        body = json.dumps(payload).encode("utf-8")
        url = f"{self.config.base_url}/v1/chat/completions"

        last_err: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                    obj = json.loads(resp.read().decode("utf-8"))
                content = obj["choices"][0]["message"]["content"]
                if not content or not str(content).strip():
                    raise LMStudioError("empty response from LM Studio")
                return content
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last_err = e
                log.warning(
                    "lm_studio call failed",
                    attempt=attempt,
                    max=self.config.max_retries,
                    error=type(e).__name__,
                )
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_backoff_s * attempt)
        raise LMStudioError(
            f"LM Studio failed after {self.config.max_retries} retries: {last_err!r}"
        )

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        """Convenience: chat with structured-JSON output and parse the result.

        When a per-call `response_format` schema envelope is supplied, the
        server is grammar-constrained to a valid instance of the schema and
        salvage parsing is rarely needed. Falls back to extracting the first
        {...} block if necessary.
        """
        raw = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=response_format is None,
            enable_thinking=enable_thinking,
        )
        # Try strict parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Strip any leading <think>...</think> chain-of-thought block that
        # leaked into the response when thinking mode was on but the
        # template didn't suppress it.
        s = raw
        if "<think>" in s and "</think>" in s:
            s = s.split("</think>", 1)[1]
        # Salvage: find the first {...} substring
        s = s.strip()
        i = s.find("{")
        j = s.rfind("}")
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                pass
        raise LMStudioError(
            f"could not parse JSON from LM Studio response: {raw[:200]!r}"
        )
