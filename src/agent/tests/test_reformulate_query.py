"""Offline tests for Phase 2.2: ReformulateQuerySkill.

Covers:
  - REFORMULATION_ACTIONS vocab and the JSON schema's enum
  - Deterministic stub path (use_llm=False):
      - add_service preferred when bundle.service_name is missing from query
      - drop_token fallback when a "noisy" token is present
      - true no-op when nothing matches
  - LLM path (mocked provider):
      - chat_json receives our system prompt + schema
      - LLM's chosen action is applied to the query
      - exceptions degrade to stub action (no skill failure)
  - Action validation (security boundary):
      - add_service rejects service outside vocabulary
      - substitute_synonym rejects replacement outside controlled vocab
      - drop_token rejects tokens absent from the query
      - unknown action type degrades to no-op
  - Action application:
      - drop_token removes case-insensitively
      - add_service appends the name
      - substitute_synonym swaps a token
  - retry_count cap (max_reformulations_per_window) emits noop
  - Cache key includes retry_count so retries don't collide

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_reformulate_query -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agent import InputBundle, SkillOutput, TEXT_EVIDENCE, Trace, TraceEvent
from agent.skills import (
    AgentContext,
    MemoryView,
    REFORMULATION_ACTIONS,
    ReformulateQuerySkill,
    make_cost,
)
from agent.skills.reformulate_query import _REFORMULATION_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle(text: str = "the cart service failed with redis timeout",
            service: str | None = "cartservice") -> InputBundle:
    return InputBundle(
        window_id="w1", dataset="online_boutique",
        text_evidence=text, service_name=service,
    )


def _ctx(
    *,
    retry_count: int = 0,
    llm: object | None = None,
    trace: Trace | None = None,
) -> AgentContext:
    extra: dict = {"retry_count": retry_count}
    if trace is not None:
        extra["trace"] = trace
    return AgentContext(
        bundle_id="w1", llm=llm, extra=extra,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestActionVocabulary(unittest.TestCase):
    def test_three_actions_only(self):
        self.assertEqual(
            set(REFORMULATION_ACTIONS),
            {"drop_token", "add_service", "substitute_synonym"},
        )

    def test_schema_constrains_enum(self):
        self.assertEqual(
            sorted(_REFORMULATION_SCHEMA["properties"]["action"]["enum"]),
            sorted(REFORMULATION_ACTIONS),
        )
        # action + argument + reason are required
        self.assertEqual(
            set(_REFORMULATION_SCHEMA["required"]),
            {"action", "argument", "reason"},
        )


# ---------------------------------------------------------------------------
# Deterministic stub path (use_llm=False)
# ---------------------------------------------------------------------------


class TestStubReformulator(unittest.TestCase):
    def test_add_service_when_service_missing_from_query(self):
        skill = ReformulateQuerySkill(use_llm=False)
        # Query has 'cart' but not 'paymentservice'
        bundle = InputBundle(
            window_id="w1", dataset="online_boutique",
            text_evidence="the cart got slow",
            service_name="paymentservice",
        )
        out = skill.invoke(bundle, MemoryView([]), _ctx())
        self.assertEqual(out.extra["action_applied"]["action"], "add_service")
        self.assertEqual(out.extra["action_applied"]["argument"], "paymentservice")
        self.assertIn("paymentservice", out.extra["reformulated_query"])

    def test_drop_token_when_noisy_token_present(self):
        skill = ReformulateQuerySkill(use_llm=False)
        # Service is in query → no add_service candidate → fall to drop
        bundle = _bundle(
            text="cartservice error redis timeout",
            service="cartservice",
        )
        out = skill.invoke(bundle, MemoryView([]), _ctx())
        action = out.extra["action_applied"]
        self.assertEqual(action["action"], "drop_token")
        self.assertEqual(action["argument"], "error")
        self.assertNotIn("error", out.extra["reformulated_query"])

    def test_noop_when_nothing_to_change(self):
        skill = ReformulateQuerySkill(use_llm=False)
        # No noisy tokens, no missing service
        bundle = _bundle(
            text="cartservice redis timeout",
            service="cartservice",
        )
        out = skill.invoke(bundle, MemoryView([]), _ctx())
        # Stub falls through to "drop_token with empty argument" → noop
        self.assertEqual(out.extra["reformulated_query"], bundle.text_evidence)
        self.assertEqual(out.confidence, 0.0)


# ---------------------------------------------------------------------------
# LLM path (mocked)
# ---------------------------------------------------------------------------


class TestLLMReformulator(unittest.TestCase):
    def _make_llm(self, action: dict) -> MagicMock:
        llm = MagicMock()
        resp = MagicMock()
        resp.content = action
        resp.total_tokens = 50
        llm.chat_json.return_value = resp
        return llm

    def test_chat_json_called_with_schema(self):
        skill = ReformulateQuerySkill(use_llm=True)
        llm = self._make_llm({
            "action": "drop_token", "argument": "the",
            "reason": "stop word",
        })
        out = skill.invoke(_bundle(), MemoryView([]), _ctx(llm=llm))

        llm.chat_json.assert_called_once()
        kwargs = llm.chat_json.call_args.kwargs
        self.assertEqual(kwargs["schema"], _REFORMULATION_SCHEMA)
        self.assertIn("bounded action", kwargs["system"])
        self.assertEqual(kwargs["temperature"], 0.0)
        # The action got applied
        self.assertNotIn(" the ", " " + out.extra["reformulated_query"] + " ")

    def test_llm_action_applied(self):
        skill = ReformulateQuerySkill(use_llm=True)
        llm = self._make_llm({
            "action": "add_service", "argument": "redisservice",
            "reason": "missing service",
        })
        out = skill.invoke(
            _bundle(text="cart broke", service="redisservice"),
            MemoryView([]), _ctx(llm=llm),
        )
        self.assertIn("redisservice", out.extra["reformulated_query"])

    def test_llm_exception_falls_back_to_stub(self):
        skill = ReformulateQuerySkill(use_llm=True)
        llm = MagicMock()
        llm.chat_json.side_effect = RuntimeError("provider down")
        # Service NOT in query → stub picks add_service for the bundle's service
        bundle = _bundle(text="the cart broke", service="cartservice")
        out = skill.invoke(bundle, MemoryView([]), _ctx(llm=llm))
        # No exception propagated; a SkillOutput came back with a stub action
        self.assertEqual(out.skill, "reformulate_query")
        self.assertEqual(out.extra["action_applied"]["action"], "add_service")
        self.assertEqual(out.extra["action_applied"]["argument"], "cartservice")

    def test_llm_cost_recorded(self):
        skill = ReformulateQuerySkill(use_llm=True)
        llm = self._make_llm({
            "action": "drop_token", "argument": "the",
            "reason": "x",
        })
        out = skill.invoke(_bundle(), MemoryView([]), _ctx(llm=llm))
        self.assertEqual(out.cost.llm_tokens, 50)


# ---------------------------------------------------------------------------
# Validation (security boundary)
# ---------------------------------------------------------------------------


class TestActionValidation(unittest.TestCase):
    def test_add_service_outside_vocabulary_becomes_noop(self):
        skill = ReformulateQuerySkill(
            use_llm=True,
            service_vocabulary=("cartservice", "paymentservice"),
        )
        llm = MagicMock()
        resp = MagicMock()
        resp.content = {
            "action": "add_service",
            "argument": "drop_table_students",        # hostile / outside vocab
            "reason": "injection attempt",
        }
        resp.total_tokens = 10
        llm.chat_json.return_value = resp

        out = skill.invoke(
            _bundle(service="cartservice"), MemoryView([]),
            _ctx(llm=llm),
        )
        # Argument was wiped; reformulated_query unchanged.
        self.assertEqual(out.extra["action_applied"]["argument"], "")
        self.assertEqual(out.extra["reformulated_query"], _bundle().text_evidence)

    def test_substitute_synonym_outside_vocab_becomes_noop(self):
        skill = ReformulateQuerySkill(
            use_llm=True,
            controlled_synonyms={"cart": ["shopping_cart", "basket"]},
        )
        llm = MagicMock()
        resp = MagicMock()
        resp.content = {
            "action": "substitute_synonym",
            "argument": "cart",
            "replacement": "DROP_TABLE",              # not in controlled vocab
            "reason": "injection",
        }
        resp.total_tokens = 10
        llm.chat_json.return_value = resp

        out = skill.invoke(_bundle(), MemoryView([]), _ctx(llm=llm))
        self.assertEqual(out.extra["action_applied"]["argument"], "")
        self.assertEqual(out.extra["reformulated_query"], _bundle().text_evidence)

    def test_substitute_synonym_allowed_replacement(self):
        skill = ReformulateQuerySkill(
            use_llm=True,
            controlled_synonyms={"cart": ["shopping_cart", "basket"]},
        )
        llm = MagicMock()
        resp = MagicMock()
        resp.content = {
            "action": "substitute_synonym",
            "argument": "cart",
            "replacement": "basket",
            "reason": "synonym",
        }
        resp.total_tokens = 10
        llm.chat_json.return_value = resp

        out = skill.invoke(
            _bundle(text="the cart broke"), MemoryView([]),
            _ctx(llm=llm),
        )
        self.assertIn("basket", out.extra["reformulated_query"])
        self.assertNotIn(" cart ", " " + out.extra["reformulated_query"] + " ")

    def test_drop_token_not_in_query_becomes_noop(self):
        skill = ReformulateQuerySkill(use_llm=True)
        llm = MagicMock()
        resp = MagicMock()
        resp.content = {
            "action": "drop_token",
            "argument": "xyzzyzz",                    # not in query
            "reason": "irrelevant",
        }
        resp.total_tokens = 10
        llm.chat_json.return_value = resp

        out = skill.invoke(_bundle(), MemoryView([]), _ctx(llm=llm))
        self.assertEqual(out.extra["action_applied"]["argument"], "")
        self.assertEqual(out.extra["reformulated_query"], _bundle().text_evidence)


# ---------------------------------------------------------------------------
# Retry cap
# ---------------------------------------------------------------------------


class TestRetryCap(unittest.TestCase):
    def test_max_reformulations_caps_at_configured_limit(self):
        skill = ReformulateQuerySkill(
            use_llm=False,
            max_reformulations_per_window=2,
        )
        # ctx says we've already done 2 retries
        out = skill.invoke(_bundle(), MemoryView([]), _ctx(retry_count=2))
        self.assertTrue(out.extra.get("noop"))
        self.assertEqual(out.extra["reformulated_query"], _bundle().text_evidence)

    def test_retry_count_bumped_in_output(self):
        skill = ReformulateQuerySkill(use_llm=False)
        out = skill.invoke(_bundle(), MemoryView([]), _ctx(retry_count=0))
        self.assertEqual(out.extra["retry_count"], 1)


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------


class TestApplyAction(unittest.TestCase):
    def test_drop_token_case_insensitive(self):
        out = ReformulateQuerySkill._apply_action(
            "Cart Error Redis timeout",
            {"action": "drop_token", "argument": "error"},
        )
        self.assertEqual(out, "Cart Redis timeout")

    def test_add_service_appends(self):
        out = ReformulateQuerySkill._apply_action(
            "cart broke",
            {"action": "add_service", "argument": "redisservice"},
        )
        self.assertEqual(out, "cart broke redisservice")

    def test_substitute_synonym_swaps(self):
        out = ReformulateQuerySkill._apply_action(
            "the cart broke",
            {"action": "substitute_synonym", "argument": "cart",
             "replacement": "basket"},
        )
        self.assertEqual(out, "the basket broke")

    def test_empty_argument_is_noop(self):
        out = ReformulateQuerySkill._apply_action(
            "the cart broke",
            {"action": "drop_token", "argument": ""},
        )
        self.assertEqual(out, "the cart broke")


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


class TestCacheKey(unittest.TestCase):
    def test_retry_count_changes_cache_key(self):
        skill = ReformulateQuerySkill(use_llm=False)
        bundle = _bundle()
        memory = MemoryView([])
        k0 = skill.cache_key(bundle, memory, extra_inputs={"retry_count": 0})
        k1 = skill.cache_key(bundle, memory, extra_inputs={"retry_count": 1})
        self.assertNotEqual(k0, k1)

    def test_default_retry_count_zero(self):
        skill = ReformulateQuerySkill(use_llm=False)
        bundle = _bundle()
        memory = MemoryView([])
        k_default = skill.cache_key(bundle, memory)
        k_zero = skill.cache_key(bundle, memory, extra_inputs={"retry_count": 0})
        self.assertEqual(k_default, k_zero)


# ---------------------------------------------------------------------------
# Capability gating
# ---------------------------------------------------------------------------


class TestCapabilityGating(unittest.TestCase):
    def test_requires_text_evidence(self):
        skill = ReformulateQuerySkill(use_llm=False)
        from agent import Capabilities
        self.assertTrue(skill.can_invoke(
            Capabilities(flags=frozenset({TEXT_EVIDENCE}))))
        self.assertFalse(skill.can_invoke(Capabilities()))


if __name__ == "__main__":
    unittest.main()
