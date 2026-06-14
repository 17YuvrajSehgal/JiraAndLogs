"""Controller package — produces Plans from (bundle, capabilities, state).

Public API:
  - `Controller` — abstract base class.
  - `RuleController` — v1 hand-tuned cheap-first / escalate policy.
  - `make_escalation_gate` — factory for the cheap-path-confidence gate
    used by expensive retrievers + the verifier.
"""

from .base import Controller
from .capability_aware import CapabilityAwareRuleController
from .rule import (
    RuleController,
    make_escalation_gate,
    make_reformulation_gate,
)

__all__ = [
    "Controller",
    "RuleController",
    "CapabilityAwareRuleController",
    "make_escalation_gate",
    "make_reformulation_gate",
]
