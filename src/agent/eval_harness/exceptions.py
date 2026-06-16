"""eval_harness exceptions — refusals at the apples-to-apples boundary."""

from __future__ import annotations


class ApplesToApplesViolation(Exception):
    """Raised when a contract field is inconsistent with the harness's inputs.

    Example: contract says `gold_relation="strong"` but a case is built
    from coarse gold labels."""


class EvaluationModeMismatch(ApplesToApplesViolation):
    """Raised when a decision's `evaluation_mode` disagrees with the
    contract's `evaluation_mode`.

    This is the §14 WoL framing safeguard — running the agent on WoL
    while the harness is configured for telemetry_diagnosis MUST fail
    rather than silently produce a mis-labelled row in a paper table."""

    def __init__(
        self,
        *,
        bundle_id: str,
        expected: str,
        actual: str,
    ) -> None:
        super().__init__(
            f"evaluation_mode mismatch for bundle {bundle_id!r}: "
            f"contract expects {expected!r}, decision carries {actual!r}",
        )
        self.bundle_id = bundle_id
        self.expected = expected
        self.actual = actual
