"""Thin LM Studio (OpenAI-compatible) client.

LM Studio exposes a /v1/chat/completions endpoint at http://localhost:1234
by default. This client wraps it with sensible defaults for our
structured-extraction workload: low temperature, retries, structured-JSON
output via the response_format parameter when the model supports it.

The existing comparison.retrievers.chat_via_lm_studio helper is too
minimal for our use case (no JSON mode, no retry, no streaming, no
typed errors). Rather than expand it (which would impact the v1 panel),
we ship a clean v2 client here.
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


class LMStudioClient:
    """OpenAI-compatible chat-completions client for the local LM Studio
    server. Stateless; safe to share across threads (one urllib request
    per call).
    """

    def __init__(self, config: LMStudioConfig | None = None) -> None:
        self.config = config or LMStudioConfig()

    def is_available(self) -> bool:
        """Quick health-check (HEAD /v1/models). Returns True if the
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
        json_mode: bool = False,
        stop: list[str] | None = None,
    ) -> str:
        """Issue a chat-completion call; return the assistant message
        content string. Raises LMStudioError on persistent failure.

        json_mode=True attempts to coax the model into emitting valid JSON
        via the response_format hint. LM Studio honors this on most
        instruct models but quietly degrades for older ones; callers
        should still json.loads() the output defensively.
        """
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
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
        raise LMStudioError(f"LM Studio failed after {self.config.max_retries} retries: {last_err!r}")

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Convenience: chat with json_mode and parse the result.

        Falls back to extracting the first {...} block from the response
        if json_mode produced something with surrounding prose.
        """
        raw = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        # Try strict parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Salvage: find the first {...} substring
        s = raw.strip()
        i = s.find("{")
        j = s.rfind("}")
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                pass
        raise LMStudioError(f"could not parse JSON from LM Studio response: {raw[:200]!r}")
