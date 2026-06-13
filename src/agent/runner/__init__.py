"""Runner package — executes a Plan and produces an AgentDecision.

Public API:
  - `AgentRunner` — the single Plan executor.
  - `RunnerError` — programmer-error sentinel (raised in __init__).
"""

from .base import RunnerError
from .runner import AgentRunner

__all__ = [
    "AgentRunner",
    "RunnerError",
]
