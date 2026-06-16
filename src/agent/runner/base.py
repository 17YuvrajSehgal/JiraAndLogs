"""Runner-side exceptions and shared internals."""

from __future__ import annotations


class RunnerError(Exception):
    """Programmer errors raised at AgentRunner construction.

    Examples:
      - LLM provider health-check failed.
      - Registry is None.
    Distinct from per-skill failures (which are recorded in the Trace as
    skill_failed events, never raised out of `run()`)."""
