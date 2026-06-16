"""LLM call telemetry — every provider call lands in a JSONL log.

Implements `IMPROVEMENTS.md` §6 and `AGENTIC-SYSTEM.md` §11.

Use:

    >>> from agent.llm.telemetry import configure_telemetry
    >>> logger = configure_telemetry("my-experiment-2026-06-13")
    >>> # ... run the agent ...
    >>> logger.n_calls, logger.n_failed, logger.total_cost_usd
    (1842, 11, 0.27)

The TokenLogger registers itself with `base.register_telemetry_hook`,
so every successful or failed `provider.chat_json(...)` call lands in
`data/llm_telemetry/<experiment>.jsonl` as one JSON line per call. The
per-call record carries everything needed to compute monetary
equivalents at hosted-model rates (see `cost_table.yaml`).

Thread-safety: the file write is serialised by an internal `Lock`, so
concurrent skills calling `chat_json` from multiple threads don't
corrupt the JSONL.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import register_telemetry_hook
from .cost_table import lookup as lookup_cost

log = logging.getLogger(__name__)

# Default directory for telemetry JSONL files. Matches the env-var
# `AGENT_LLM_TELEMETRY_DIR` documented in .env.example.
DEFAULT_OUTPUT_DIR = Path("data/llm_telemetry")


class TokenLogger:
    """Sink for every LLM provider call.

    Wires to `base.register_telemetry_hook` when `install()` is called.
    Records are enriched with experiment metadata + computed USD cost
    before being appended to the JSONL file.

    A single TokenLogger handles one experiment at a time. Switching
    experiments means uninstalling the old logger and installing a new
    one.
    """

    def __init__(
        self,
        experiment: str,
        *,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        ablation: str = "",
    ) -> None:
        if not experiment:
            raise ValueError("experiment name is required (non-empty)")
        self.experiment = experiment
        self.ablation = ablation
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = self.output_dir / f"{experiment}.jsonl"

        self._lock = threading.Lock()
        self._n_calls = 0
        self._n_failed = 0
        self._total_cost_usd = 0.0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0

    # ------------------------------------------------------------------ install / uninstall

    def install(self) -> "TokenLogger":
        """Register this logger as the active telemetry hook. Returns self."""
        register_telemetry_hook(self)
        log.info(
            "TokenLogger installed: experiment=%r output=%s",
            self.experiment, self.output_path,
        )
        return self

    def uninstall(self) -> None:
        register_telemetry_hook(None)
        log.info("TokenLogger uninstalled: experiment=%r", self.experiment)

    def __enter__(self) -> "TokenLogger":
        return self.install()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.uninstall()

    # ------------------------------------------------------------------ hook callback

    def __call__(self, record: dict[str, Any]) -> None:
        """Called by `base.chat_json` after every call (success or failure).

        Must not raise — base.py catches exceptions from telemetry hooks
        and swallows them, but we'd rather not produce log spam either.
        """
        try:
            enriched = self._enrich(record)
            line = json.dumps(enriched, default=str, ensure_ascii=False) + "\n"
            with self._lock:
                with self.output_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                self._n_calls += 1
                if not enriched.get("success"):
                    self._n_failed += 1
                self._total_cost_usd += float(enriched.get("cost_usd", 0.0))
                self._total_prompt_tokens += int(enriched.get("prompt_tokens", 0))
                self._total_completion_tokens += int(enriched.get("completion_tokens", 0))
        except Exception as e:  # noqa: BLE001 — never break a real call
            log.warning("TokenLogger.__call__ swallowed %s: %s", type(e).__name__, e)

    # ------------------------------------------------------------------ enrichment

    def _enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Add timestamp, experiment context, computed cost to the raw record.

        The raw record from base.chat_json carries:
            provider, model, prompt_tokens, completion_tokens,
            latency_ms, success, error, cached, attempt,
            experiment (or empty), phase, skill, bundle_id
        """
        provider = str(record.get("provider", ""))
        model = str(record.get("model", ""))
        prompt_tokens = int(record.get("prompt_tokens", 0) or 0)
        completion_tokens = int(record.get("completion_tokens", 0) or 0)

        cost_entry = lookup_cost(provider, model)
        cost_usd = cost_entry.cost_usd(prompt_tokens, completion_tokens)

        # Experiment / ablation: per-call override > logger default
        experiment = str(record.get("experiment") or self.experiment)
        ablation = str(record.get("ablation") or self.ablation)

        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "experiment": experiment,
            "ablation": ablation,
            "provider": provider,
            "model": model,
            "skill": str(record.get("skill", "")),
            "phase": str(record.get("phase", "")),
            "bundle_id": str(record.get("bundle_id", "")),
            "attempt": int(record.get("attempt", 1) or 1),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": round(cost_usd, 8),
            "cost_input_per_M_usd": cost_entry.input_per_M_usd,
            "cost_output_per_M_usd": cost_entry.output_per_M_usd,
            "latency_ms": int(record.get("latency_ms", 0) or 0),
            "success": bool(record.get("success", False)),
            "error": record.get("error"),
            "cached": bool(record.get("cached", False)),
        }

    # ------------------------------------------------------------------ stats accessors

    @property
    def n_calls(self) -> int:
        with self._lock:
            return self._n_calls

    @property
    def n_failed(self) -> int:
        with self._lock:
            return self._n_failed

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return round(self._total_cost_usd, 6)

    @property
    def total_prompt_tokens(self) -> int:
        with self._lock:
            return self._total_prompt_tokens

    @property
    def total_completion_tokens(self) -> int:
        with self._lock:
            return self._total_completion_tokens

    def snapshot(self) -> dict[str, Any]:
        """In-memory counters; useful for end-of-run printing."""
        with self._lock:
            return {
                "experiment": self.experiment,
                "ablation": self.ablation,
                "output_path": str(self.output_path),
                "n_calls": self._n_calls,
                "n_failed": self._n_failed,
                "total_prompt_tokens": self._total_prompt_tokens,
                "total_completion_tokens": self._total_completion_tokens,
                "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
                "total_cost_usd": round(self._total_cost_usd, 6),
            }

    def __repr__(self) -> str:
        return (
            f"TokenLogger(experiment={self.experiment!r}, "
            f"ablation={self.ablation!r}, "
            f"n_calls={self._n_calls}, n_failed={self._n_failed}, "
            f"cost_usd={self._total_cost_usd:.4f})"
        )


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def configure_telemetry(
    experiment: str,
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    ablation: str = "",
) -> TokenLogger:
    """Build + install a TokenLogger in one call.

    Returns the logger; the caller holds it for end-of-run inspection.

    Typical usage from an experiment script::

        logger = configure_telemetry("ob-baseline-2026-06-13")
        try:
            # ... run the agent ...
        finally:
            logger.uninstall()
            print(json.dumps(logger.snapshot(), indent=2))
    """
    return TokenLogger(experiment, output_dir=output_dir, ablation=ablation).install()


def from_env() -> TokenLogger | None:
    """Build a TokenLogger from env vars (`AGENT_EXPERIMENT` +
    `AGENT_LLM_TELEMETRY_DIR`). Returns None if AGENT_EXPERIMENT is
    unset — meaning "don't auto-install telemetry; let the experiment
    script configure it explicitly".
    """
    experiment = os.environ.get("AGENT_EXPERIMENT", "").strip()
    if not experiment:
        return None
    output_dir = Path(os.environ.get("AGENT_LLM_TELEMETRY_DIR", str(DEFAULT_OUTPUT_DIR)))
    ablation = os.environ.get("AGENT_ABLATION", "").strip()
    return configure_telemetry(experiment, output_dir=output_dir, ablation=ablation)
