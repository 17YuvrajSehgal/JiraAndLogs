"""Controller ABC — emits a Plan; doesn't execute anything.

The Controller is the policy layer. Given a bundle's Capabilities and
the current cross-window state, it returns a `Plan` (an ordered list
of `SkillInvocation`s + budget caps + fallback chains). The Runner
takes that Plan and executes it deterministically.

Shipped subclasses:
  - `RuleController` — hand-tuned cheap-first / escalate-on-uncertainty
    policy emitting a single Plan with runtime gates.
  - `CapabilityAwareRuleController` — subclass of RuleController that
    branches on `(window_type, scenario_family, state, capabilities)`
    to emit structurally distinct Plans per window-type.

Future hook: a `LearnedController` (small LogReg/MLP over cheap-skill
outputs) would emit the same Plan-shape output; the Runner does not
need to know the difference.
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
        state: Any | None = None,        # ServiceStateView; Any to avoid state-layer import here
        config: dict[str, Any] | None = None,
    ) -> Plan:
        """Produce a Plan for one bundle.

        Args:
            bundle: the InputBundle being processed.
            capabilities: output of the CapabilitiesObserver — what
                evidence is available + verifier-helpfulness flag.
            state: optional cross-window state (`ServiceStateView`).
                `RuleController` ignores it; `CapabilityAwareRuleController`
                consults it to detect page-suppression and to short-circuit
                the plan when the same incident has been retrieved for
                several consecutive windows.
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
