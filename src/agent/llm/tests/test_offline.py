"""Offline unit tests for `agent.llm`.

Runs without a live LLM server — exercises imports, registry, cost table,
factory resolution, and schema parsing logic.

Run:
    PYTHONPATH=src python -m unittest src.agent.llm.tests.test_offline -v
"""

from __future__ import annotations

import os
import unittest

from agent.llm import (
    LLMProvider,
    LLMProviderConfig,
    LLMProviderError,
    PROVIDER_REGISTRY,
    list_supported_providers,
    lookup_cost,
    make_provider,
    monetary_equivalent_baselines,
)
from agent.llm.providers.anthropic_provider import AnthropicProvider
from agent.llm.providers.lm_studio import LMStudioProvider
from agent.llm.providers.openai_provider import OpenAIProvider


class TestRegistry(unittest.TestCase):
    def test_all_supported_providers_in_registry(self):
        expected = {
            "lm_studio", "openai", "anthropic", "ollama",
            "vllm", "generic_openai",
        }
        self.assertEqual(set(list_supported_providers()), expected)

    def test_every_provider_is_llmprovider_subclass(self):
        for name, cls in PROVIDER_REGISTRY.items():
            with self.subTest(provider=name):
                self.assertTrue(
                    issubclass(cls, LLMProvider),
                    f"{name} -> {cls} is not an LLMProvider subclass",
                )


class TestCostTable(unittest.TestCase):
    def test_lookup_exact_match(self):
        e = lookup_cost("openai", "gpt-4o-mini")
        self.assertEqual(e.provider, "openai")
        self.assertEqual(e.model, "gpt-4o-mini")
        self.assertGreater(e.input_per_M_usd, 0)

    def test_lookup_wildcard_fallback(self):
        e = lookup_cost("lm_studio", "any-model-name")
        self.assertEqual(e.provider, "lm_studio")
        self.assertEqual(e.input_per_M_usd, 0.0)
        self.assertIn("self-hosted", e.note)

    def test_lookup_unknown_returns_zero_with_note(self):
        e = lookup_cost("nonexistent_provider", "nope")
        self.assertEqual(e.input_per_M_usd, 0.0)
        self.assertIn("unknown_cost", e.note)

    def test_cost_computation(self):
        e = lookup_cost("openai", "gpt-4o-mini")
        # 1M input tokens at $0.15 = $0.15
        self.assertAlmostEqual(e.cost_usd(1_000_000, 0), 0.15, places=6)
        # 1M output tokens at $0.60 = $0.60
        self.assertAlmostEqual(e.cost_usd(0, 1_000_000), 0.60, places=6)

    def test_monetary_baselines_present(self):
        baselines = monetary_equivalent_baselines()
        self.assertGreater(len(baselines), 0)
        for b in baselines:
            self.assertGreater(b.input_per_M_usd + b.output_per_M_usd, 0)


class TestFactory(unittest.TestCase):
    def setUp(self):
        # Save + clear all LLM_* env vars so each test starts clean
        self._saved = {
            k: os.environ.pop(k, None)
            for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL",
                      "LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                      "OLLAMA_API_KEY", "VLLM_API_KEY")
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_default_is_lm_studio(self):
        os.environ["LLM_MODEL"] = "test-model"
        p = make_provider()
        self.assertIsInstance(p, LMStudioProvider)
        self.assertEqual(p.model, "test-model")
        self.assertEqual(p.config.base_url, "http://localhost:1234")
        self.assertEqual(p.config.api_key, "")

    def test_env_var_overrides_default(self):
        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        p = make_provider()
        self.assertIsInstance(p, OpenAIProvider)
        self.assertEqual(p.config.api_key, "sk-test")
        self.assertEqual(p.config.base_url, "https://api.openai.com")

    def test_anthropic_provider_distinct_protocol(self):
        os.environ["LLM_PROVIDER"] = "anthropic"
        os.environ["LLM_MODEL"] = "claude-haiku-4-5-20251001"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        p = make_provider()
        self.assertIsInstance(p, AnthropicProvider)
        self.assertTrue(p.supports_tool_use)
        self.assertEqual(p.default_context_window, 200_000)

    def test_kwarg_overrides_env(self):
        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["LLM_MODEL"] = "gpt-4o"
        p = make_provider(provider="lm_studio", model="qwen/test")
        self.assertIsInstance(p, LMStudioProvider)
        self.assertEqual(p.model, "qwen/test")

    def test_unknown_provider_raises(self):
        os.environ["LLM_PROVIDER"] = "definitely_not_a_provider"
        os.environ["LLM_MODEL"] = "x"
        with self.assertRaises(LLMProviderError) as ctx:
            make_provider()
        self.assertIn("definitely_not_a_provider", str(ctx.exception))

    def test_missing_model_raises(self):
        # No LLM_MODEL set
        with self.assertRaises(LLMProviderError) as ctx:
            make_provider(provider="lm_studio")
        self.assertIn("LLM_MODEL", str(ctx.exception))

    def test_config_dict_provides_defaults(self):
        os.environ["LLM_MODEL"] = "test-model"
        p = make_provider(config={
            "provider": "ollama",
            "base_url": "http://cluster-node:11434",
            "timeout_s": 300.0,
        })
        from agent.llm.providers.ollama_provider import OllamaProvider
        self.assertIsInstance(p, OllamaProvider)
        self.assertEqual(p.config.base_url, "http://cluster-node:11434")
        self.assertEqual(p.config.timeout_s, 300.0)


class TestJSONParser(unittest.TestCase):
    """Test the static _try_parse_json helper on common LLM emission quirks."""

    def setUp(self):
        # Build a provider so we can use its static helper
        os.environ["LLM_MODEL"] = "test"
        os.environ.pop("LLM_PROVIDER", None)
        self.p = make_provider()

    def test_parse_clean_json(self):
        out = self.p._try_parse_json('{"a": 1, "b": "two"}')
        self.assertEqual(out, {"a": 1, "b": "two"})

    def test_parse_markdown_fenced(self):
        out = self.p._try_parse_json('```json\n{"x": 42}\n```')
        self.assertEqual(out, {"x": 42})

    def test_parse_bare_markdown_fence(self):
        out = self.p._try_parse_json('```\n{"y": [1,2]}\n```')
        self.assertEqual(out, {"y": [1, 2]})

    def test_parse_with_whitespace(self):
        out = self.p._try_parse_json('   \n  {"z": null}  \n')
        self.assertEqual(out, {"z": None})

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(self.p._try_parse_json("not json at all"))

    def test_parse_empty_returns_none(self):
        self.assertIsNone(self.p._try_parse_json(""))


class TestProviderHealthDataclass(unittest.TestCase):
    def test_health_ok_requires_all_three(self):
        from agent.llm import ProviderHealth
        self.assertTrue(ProviderHealth(
            reachable=True, authenticated=True, model_loaded=True
        ).ok)
        self.assertFalse(ProviderHealth(
            reachable=False, authenticated=True, model_loaded=True
        ).ok)
        self.assertFalse(ProviderHealth(
            reachable=True, authenticated=False, model_loaded=True
        ).ok)
        self.assertFalse(ProviderHealth(
            reachable=True, authenticated=True, model_loaded=False
        ).ok)


if __name__ == "__main__":
    unittest.main()
