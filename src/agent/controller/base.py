"""Controller ABC — emits a Plan; doesn't execute anything.

The Controller is the policy layer. Given a bundle's Capabilities and
the current cross-window state, it returns a `Plan` (an ordered list
of `SkillInvocation`s + budget caps + fallback chains). The Runner
takes that Plan and executes it deterministically.

Two implementations are planned:
  - `RuleController` (Phase 1.9) — hand-tuned threshold rule.
  - `LearnedController` (v2) — small LogReg/MLP over the cheap-skill
    outputs. Same Plan-shape output; the Runner doesn't know the
    difference.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..capabilities import Capabilities
from ..plan import Plan
from ..types import InputBundle


class Controller(ABC):
    """Abstract base. Implementations return a Plan for one bundle."""

    #: Human-readable controller id; carried into Plan.controller_name and
    #: useful for debugging "which controller produced this plan?".
    name: str = "abstract"

    @abstractmethod
    def plan(
        self,
        bundle: InputBundle,
        capabilities: Capabilities,
        *,
        state: Any | None = None,        # WindowState; Any to avoid Phase 1.12 dep
        config: dict[str, Any] | None = None,
    ) -> Plan:
        """Produce a Plan for one bundle.

        Args:
            bundle: the InputBundle being processed.
            capabilities: output of the CapabilitiesObserver — what
                evidence is available + verifier-helpfulness flag.
            state: optional cross-window state (Phase 1.12); v1 ignores.
            config: optional runtime config dict — typically the
                `controller:` block from agent-config.yaml.

        Returns:
            A Plan whose `invocations` reference skill names that exist
            in the controller's registry.

        Must be deterministic and idempotent: same inputs always yield
        the same Plan (and therefore the same plan_id).
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
