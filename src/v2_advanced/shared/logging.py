"""Structured logging for v2_advanced pipelines.

Goal: every model-building / training / inference / evaluation step
emits a uniformly-formatted line that's easy to grep, easy to follow
during long runs, and machine-parseable for post-hoc analysis.

Format:
    [HH:MM:SS] [LEVEL] [phase] [step] message  key1=val1 key2=val2

Usage:
    from v2_advanced.shared import get_logger, log_step
    log = get_logger("phase_d.extractor")
    log.info("starting extraction", n_tickets=347)
    with log_step(log, "build_graph"):
        ...
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Any


_INITIALIZED = False


def _ensure_initialized() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("v2_advanced")
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers if get_logger is called many times.
    if not root.handlers:
        root.addHandler(handler)
    root.propagate = False
    _INITIALIZED = True


class _KwargsLogger(logging.LoggerAdapter):
    """LoggerAdapter that lets callers pass keyword=value kwargs and
    formats them as 'key1=val1 key2=val2' at the end of the message.

    Standard logger.info() takes positional args for %-formatting. We
    want a cleaner kwarg-style API for emitting structured data.
    """

    def process(self, msg, kwargs):
        # Pull out structured fields; everything else passes through.
        extras = {}
        for k in list(kwargs.keys()):
            # Only intercept user kwargs; leave standard logging kwargs alone.
            if k in {"exc_info", "stack_info", "stacklevel", "extra"}:
                continue
            extras[k] = kwargs.pop(k)
        if extras:
            tail = " ".join(f"{k}={_fmt_value(v)}" for k, v in extras.items())
            return f"{msg}  {tail}", kwargs
        return msg, kwargs


def _fmt_value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4f}" if abs(v) < 100 else f"{v:.2f}"
    if isinstance(v, (list, tuple)) and len(v) > 5:
        return f"[{len(v)} items]"
    if isinstance(v, dict) and len(v) > 5:
        return f"<{len(v)} keys>"
    return str(v)


def get_logger(name: str) -> _KwargsLogger:
    """Get a logger under the v2_advanced namespace with kwargs support."""
    _ensure_initialized()
    raw = logging.getLogger(f"v2_advanced.{name}")
    return _KwargsLogger(raw, {})


@contextmanager
def log_step(log: _KwargsLogger, step_name: str, **start_kwargs: Any):
    """Time and log a named block of work.

    Logs `step=<name> start` on entry and `step=<name> done elapsed_s=N` on
    exit. Any keyword args passed in become structured fields on the start
    line.
    """
    t0 = time.time()
    log.info(f"step={step_name} start", **start_kwargs)
    try:
        yield
        log.info(
            f"step={step_name} done",
            elapsed_s=round(time.time() - t0, 2),
        )
    except Exception as e:
        log.error(
            f"step={step_name} FAILED",
            elapsed_s=round(time.time() - t0, 2),
            error=type(e).__name__,
            msg=str(e)[:200],
        )
        raise
