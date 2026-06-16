"""Offline tests for Phase 3.1: ExtractEntitiesLLMSkill.

Covers:
  - Stub mode returns empty extractions (no LLM needed).
  - Custom extractor_fn invoked with the right args (dataset-agnostic).
  - Extracted fields surface into SkillOutput.extra.
  - Extractor exceptions degrade to empty output (no skill failure).
  - cost_class is expensive_llm so the controller knows to gate it.
  - required_flags={TEXT_EVIDENCE}.

The skill is intended for indexing-time use; we don't exercise it via
the runtime controller in these tests (the RuleController explicitly
does NOT include it in its per-bundle plan).

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_extract_entities_llm -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agent import Capabilities, InputBundle, TEXT_EVIDENCE
from agent.skills import (
    AgentContext,
    ExtractEntitiesLLMSkill,
    MemoryView,
)


def _bundle(text: str = "redis connection failed in cartservice") -> InputBundle:
    return InputBundle(
        window_id="w-x", dataset="online_boutique",
        text_evidence=text,
        service_name="cartservice",
        scenario_family="redis_oom",
        window_type="active_fault",
    )


# Minimal stand-in for WindowExtraction's shape.
class _Extraction:
    def __init__(
        self,
        affected_services=(),
        components=(),
        error_classes=(),
        symptoms=(),
    ):
        self.affected_services = list(affected_services)
        self.components = list(components)
        self.error_classes = list(error_classes)
        self.symptoms = list(symptoms)


class TestSkillIdentity(unittest.TestCase):
    def test_name_and_metadata(self):
        s = ExtractEntitiesLLMSkill(use_llm=False)
        self.assertEqual(s.name, "extract_entities_llm")
        self.assertEqual(s.cost_class, "expensive_llm")
        self.assertEqual(s.required_flags, frozenset({TEXT_EVIDENCE}))

    def test_can_invoke_requires_text_evidence(self):
        s = ExtractEntitiesLLMSkill(use_llm=False)
        self.assertTrue(s.can_invoke(
            Capabilities(flags=frozenset({TEXT_EVIDENCE}))))
        self.assertFalse(s.can_invoke(Capabilities()))


class TestStubMode(unittest.TestCase):
    def test_use_llm_false_returns_empty(self):
        s = ExtractEntitiesLLMSkill(use_llm=False)
        out = s.invoke(_bundle(), MemoryView([]),
                       AgentContext(bundle_id="w-x"))
        self.assertEqual(out.extra["n_entities"], 0)
        self.assertTrue(out.extra["noop"])
        self.assertEqual(out.extra["reason"], "no_text_or_stub_mode")

    def test_empty_text_returns_empty(self):
        s = ExtractEntitiesLLMSkill(use_llm=True)
        bundle = InputBundle(window_id="w", dataset="ob", text_evidence=None)
        out = s.invoke(bundle, MemoryView([]),
                       AgentContext(bundle_id="w", llm=MagicMock()))
        self.assertEqual(out.extra["n_entities"], 0)
        self.assertTrue(out.extra["noop"])


class TestCustomExtractor(unittest.TestCase):
    def test_extractor_called_with_window_args(self):
        captured = {}

        def _fn(*, client, window_id, evidence_text, severity, family, cache_dir):
            captured["client"] = client
            captured["window_id"] = window_id
            captured["evidence_text"] = evidence_text
            captured["severity"] = severity
            captured["family"] = family
            return _Extraction(
                affected_services=["cartservice"],
                error_classes=["RedisConnectionException"],
                symptoms=["timeout"],
            )

        s = ExtractEntitiesLLMSkill(use_llm=True, extractor_fn=_fn)
        out = s.invoke(_bundle(), MemoryView([]),
                       AgentContext(bundle_id="w-x", llm=MagicMock()))

        self.assertEqual(captured["window_id"], "w-x")
        self.assertEqual(captured["family"], "redis_oom")
        self.assertEqual(captured["severity"], "active_fault")
        # Output carries the entities
        self.assertEqual(out.extra["affected_services"], ["cartservice"])
        self.assertEqual(out.extra["error_classes"], ["RedisConnectionException"])
        self.assertEqual(out.extra["symptoms"], ["timeout"])
        # n_entities counts across all fields (1 + 0 + 1 + 1 = 3)
        self.assertEqual(out.extra["n_entities"], 3)
        # Confidence > 0 when something was extracted
        self.assertGreater(out.confidence, 0.0)

    def test_extractor_exception_degrades_gracefully(self):
        def _bad(**kwargs):
            raise RuntimeError("LM Studio down")
        s = ExtractEntitiesLLMSkill(use_llm=True, extractor_fn=_bad)
        out = s.invoke(_bundle(), MemoryView([]),
                       AgentContext(bundle_id="w-x", llm=MagicMock()))
        # No exception propagated; empty output with reason
        self.assertEqual(out.extra["n_entities"], 0)
        self.assertIn("extractor_exception", out.extra["reason"])

    def test_no_llm_in_ctx_with_default_extractor_is_noop(self):
        """The default extractor expects ctx.llm; if None, the skill
        emits an empty output rather than raising."""
        s = ExtractEntitiesLLMSkill(use_llm=True)               # default extractor
        out = s.invoke(_bundle(), MemoryView([]),
                       AgentContext(bundle_id="w-x", llm=None))
        self.assertEqual(out.extra["n_entities"], 0)
        self.assertEqual(out.extra["reason"], "no_llm_client_in_ctx")


class TestEmptyExtractionStillReturnsValid(unittest.TestCase):
    def test_extractor_returns_no_entities(self):
        s = ExtractEntitiesLLMSkill(
            use_llm=True,
            extractor_fn=lambda **kw: _Extraction(),  # all fields empty
        )
        out = s.invoke(_bundle(), MemoryView([]),
                       AgentContext(bundle_id="w-x", llm=MagicMock()))
        self.assertEqual(out.extra["n_entities"], 0)
        self.assertEqual(out.confidence, 0.0)
        # Fields are still present + empty (not missing)
        for f in ("affected_services", "components", "error_classes", "symptoms"):
            self.assertEqual(out.extra[f], [])


if __name__ == "__main__":
    unittest.main()
