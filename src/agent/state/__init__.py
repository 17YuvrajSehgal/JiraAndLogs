"""State package — cross-window memory of recent decisions, per service.

Public API:
  - `WindowState` — one decision's snapshot (frozen).
  - `ServiceStateView` — read-only window list the Controller consumes.
  - `PageSuppressionResult` — outcome of `StateLayer.check_page_suppression`.
  - `StateLayer` — mutable per-service ring buffer + page-suppression
    rule + optional disk persistence.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §7; original rule in
`DOCS/docs6/XX_AGENTIC_IDEA.md` §4.3.
"""

from .state_layer import (
    PageSuppressionResult,
    ServiceStateView,
    StateLayer,
)
from .window_state import WindowState

__all__ = [
    "WindowState",
    "ServiceStateView",
    "PageSuppressionResult",
    "StateLayer",
]
