"""Tests for the 5 tool-use failure modes — Phase 2 §5.4 / RQ-D6.

One synthetic test per failure mode + an integration test that
confirms detection events flow through to ToolResult.failure_mode.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_failure_modes -v
"""

from __future__ import annotations

import unittest
from typing import Any

from agent.skills.base import AgentContext, MemoryView
from agent.skills.evidence_request import EvidenceRequestSkill
from agent.tool_protocol import (
    DEFAULT_MAX_TOOL_CALLS,
    FAILURE_BUDGET_EXHAUSTED,
    FAILURE_EMPTY,
    FAILURE_HALLUCINATED,
    FAILURE_LOOPING,
    FAILURE_LOOPING_THRESHOLD,
    FAILURE_MODES,
    FAILURE_TOOL_ERROR,
    ToolRequest,
    args_hash,
    count_tool_call_repeats,
    record_tool_call,
    validate_tool_request,
)
from agent.types import InputBundle


# ---------------------------------------------------------------------------
# Test skills — synthetic subclasses to drive each failure path
# ---------------------------------------------------------------------------


class _SyntheticRequest(EvidenceRequestSkill):
    """Configurable test skill — returns whatever its constructor was given."""

    name = "synthetic_test_tool"
    version = "1.0.0"
    tool_name = "synthetic_test_tool"
    required_flags = frozenset()

    def __init__(
        self,
        *,
        result: dict | None = None,
        raise_exc: type[Exception] | None = None,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    ) -> None:
        self._configured_result = result if result is not None else {"hits": ["x"]}
        self._raise_exc = raise_exc
        self.max_tool_calls = max_tool_calls

    def _fetch_evidence(self, bundle, ctx):
        if self._raise_exc is not None:
            raise self._raise_exc("synthetic failure")
        return dict(self._configured_result)

    def _is_evidence_useful(self, result):
        return bool(result.get("hits"))


def _bundle() -> InputBundle:
    return InputBundle(window_id="w1", dataset="test")


def _ctx() -> AgentContext:
    return AgentContext(bundle_id="w1", experiment="t", extra={})


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


class TestArgsHash(unittest.TestCase):
    def test_stable_across_dict_order(self) -> None:
        a = args_hash({"window_id": "w1", "top_k": 3})
        b = args_hash({"top_k": 3, "window_id": "w1"})
        self.assertEqual(a, b)

    def test_distinguishes_different_args(self) -> None:
        a = args_hash({"window_id": "w1"})
        b = args_hash({"window_id": "w2"})
        self.assertNotEqual(a, b)


class TestRecordAndCount(unittest.TestCase):
    def test_record_appends_and_count_matches(self) -> None:
        extra: dict[str, Any] = {}
        for _ in range(3):
            extra = record_tool_call(extra, "tool_a", {"x": 1})
        self.assertEqual(count_tool_call_repeats(extra, "tool_a", {"x": 1}), 3)
        self.assertEqual(count_tool_call_repeats(extra, "tool_a", {"x": 2}), 0)
        self.assertEqual(count_tool_call_repeats(extra, "tool_b", {"x": 1}), 0)

    def test_record_does_not_mutate_input(self) -> None:
        before = {"foo": "bar"}
        after = record_tool_call(before, "tool_a", {"x": 1})
        self.assertNotIn("tool_call_history", before)
        self.assertIn("tool_call_history", after)


# ---------------------------------------------------------------------------
# Per-failure-mode tests
# ---------------------------------------------------------------------------


class TestEmptyFailureMode(unittest.TestCase):
    def test_useful_signal_marks_no_failure(self) -> None:
        skill = _SyntheticRequest(result={"hits": ["a", "b"]})
        out = skill.invoke(_bundle(), MemoryView(issues=[]), _ctx())
        self.assertIsNone(out.extra["failure_mode"])
        self.assertTrue(out.extra["is_useful"])

    def test_empty_result_marks_empty_mode(self) -> None:
        skill = _SyntheticRequest(result={"hits": []})
        out = skill.invoke(_bundle(), MemoryView(issues=[]), _ctx())
        self.assertEqual(out.extra["failure_mode"], FAILURE_EMPTY)
        self.assertFalse(out.extra["is_useful"])


class TestToolErrorFailureMode(unittest.TestCase):
    def test_exception_marks_tool_error(self) -> None:
        skill = _SyntheticRequest(raise_exc=RuntimeError)
        out = skill.invoke(_bundle(), MemoryView(issues=[]), _ctx())
        self.assertEqual(out.extra["failure_mode"], FAILURE_TOOL_ERROR)
        tr = out.extra["tool_result"]
        self.assertEqual(tr["failure_mode"], FAILURE_TOOL_ERROR)
        self.assertIn("RuntimeError", tr["error"])


class TestLoopingFailureMode(unittest.TestCase):
    def test_third_repeat_refused(self) -> None:
        skill = _SyntheticRequest()
        ctx = _ctx()
        # First two succeed (threshold = 3)
        for i in range(FAILURE_LOOPING_THRESHOLD):
            out = skill.invoke(_bundle(), MemoryView(issues=[]), ctx)
            self.assertNotEqual(out.extra["failure_mode"], FAILURE_LOOPING,
                                f"call #{i+1} should not be a loop")
        # The (threshold+1)th invocation should be refused
        out = skill.invoke(_bundle(), MemoryView(issues=[]), ctx)
        self.assertEqual(out.extra["failure_mode"], FAILURE_LOOPING)
        self.assertTrue(out.extra["refused"])

    def test_different_args_does_not_loop(self) -> None:
        skill = _SyntheticRequest()
        ctx = _ctx()
        for i in range(FAILURE_LOOPING_THRESHOLD + 1):
            b = InputBundle(window_id=f"w{i}", dataset="test")  # different args
            out = skill.invoke(b, MemoryView(issues=[]), ctx)
            self.assertNotEqual(out.extra["failure_mode"], FAILURE_LOOPING)


class TestBudgetExhaustedMode(unittest.TestCase):
    def test_budget_exhausted_refuses(self) -> None:
        skill = _SyntheticRequest(max_tool_calls=2)
        ctx = _ctx()
        # 2 calls (each with different args) should succeed
        for i in range(2):
            b = InputBundle(window_id=f"w{i}", dataset="test")
            out = skill.invoke(b, MemoryView(issues=[]), ctx)
            self.assertIsNone(out.extra["failure_mode"])
        # 3rd call should be refused (budget = 2)
        b = InputBundle(window_id="w99", dataset="test")
        out = skill.invoke(b, MemoryView(issues=[]), ctx)
        self.assertEqual(out.extra["failure_mode"], FAILURE_BUDGET_EXHAUSTED)


class TestHallucinationGuard(unittest.TestCase):
    def test_valid_request_returns_none(self) -> None:
        req = ToolRequest(tool_name="known_tool", args={})
        result = validate_tool_request(req, {"known_tool", "other_tool"})
        self.assertIsNone(result)

    def test_unknown_tool_returns_refusal(self) -> None:
        req = ToolRequest(tool_name="ghost_tool", args={"x": 1})
        result = validate_tool_request(req, {"known_tool"})
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "ghost_tool")
        self.assertEqual(result.failure_mode, FAILURE_HALLUCINATED)
        self.assertIn("hallucinated", result.error)


# ---------------------------------------------------------------------------
# Integration — failure modes appear on ctx.extra["tool_results"]
# ---------------------------------------------------------------------------


class TestFailureModeFlowsToContext(unittest.TestCase):
    """The tool result (including failure_mode) must propagate to
    ctx.extra so the rerank skill — and the failure-mode catalog —
    can see it."""

    def test_loop_refusal_recorded_on_ctx(self) -> None:
        skill = _SyntheticRequest()
        ctx = _ctx()
        for _ in range(FAILURE_LOOPING_THRESHOLD + 1):
            skill.invoke(_bundle(), MemoryView(issues=[]), ctx)
        tool_results = ctx.extra.get("tool_results") or []
        modes = [tr.get("failure_mode") for tr in tool_results]
        # Should have N successes + one refusal
        self.assertEqual(modes.count(FAILURE_LOOPING), 1)
        self.assertEqual(modes.count(None), FAILURE_LOOPING_THRESHOLD)

    def test_tool_error_recorded_on_ctx(self) -> None:
        skill = _SyntheticRequest(raise_exc=FileNotFoundError)
        ctx = _ctx()
        skill.invoke(_bundle(), MemoryView(issues=[]), ctx)
        tool_results = ctx.extra.get("tool_results") or []
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["failure_mode"], FAILURE_TOOL_ERROR)


class TestFailureModeCanonicalSet(unittest.TestCase):
    """Catch typos: every named constant must be in FAILURE_MODES."""

    def test_all_modes_in_canonical_tuple(self) -> None:
        for mode in (
            FAILURE_HALLUCINATED,
            FAILURE_EMPTY,
            FAILURE_LOOPING,
            FAILURE_BUDGET_EXHAUSTED,
            FAILURE_TOOL_ERROR,
        ):
            self.assertIn(mode, FAILURE_MODES)


if __name__ == "__main__":
    unittest.main()
