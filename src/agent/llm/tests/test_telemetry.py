"""Offline tests for TokenLogger + telemetry_summary.

Exercises the full path: TokenLogger captures records from a mocked
LLM call, writes JSONL, summariser reads it back, totals match.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.llm import (
    ChatResponse,
    LLMProvider,
    LLMProviderConfig,
    ProviderHealth,
    TokenLogger,
    configure_telemetry,
    load_records,
    register_telemetry_hook,
    summarise,
    write_summary,
)


class _FakeProvider(LLMProvider):
    """Provider that returns canned responses without touching the network."""

    name_const = "fake"
    supports_structured_output = True
    default_context_window = 4096

    def __init__(self, model: str = "fake-model"):
        super().__init__(LLMProviderConfig(
            provider="fake", model=model, base_url="http://localhost",
            api_key="", max_retries=1, retry_backoff_s=(0.01,),
        ))
        self.calls: list[dict] = []

    def is_available(self) -> ProviderHealth:
        return ProviderHealth(reachable=True, authenticated=True, model_loaded=True)

    def _chat_raw(self, *, system, user, schema, temperature, max_tokens, thinking):
        self.calls.append({"system": system, "user": user, "schema": schema})
        # Different responses based on user prompt for parametrised tests
        if schema is None:
            return ChatResponse(
                content="ok",
                raw_text="ok",
                prompt_tokens=12,
                completion_tokens=3,
                total_tokens=15,
                latency_ms=42,
                model=self.model,
                provider=self.name,
            )
        # Structured response
        return ChatResponse(
            content={"answer": "yes"},
            raw_text='{"answer": "yes"}',
            prompt_tokens=20,
            completion_tokens=5,
            total_tokens=25,
            latency_ms=80,
            model=self.model,
            provider=self.name,
        )


class TestTokenLoggerCapturesCalls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        register_telemetry_hook(None)

    def tearDown(self):
        register_telemetry_hook(None)
        self.tmp.cleanup()

    def test_logger_writes_one_record_per_call(self):
        logger = configure_telemetry("test-exp-1", output_dir=self.tmp_path)
        provider = _FakeProvider()

        provider.chat_json(
            system="s", user="u",
            skill="retrieve_dense", phase="predict", bundle_id="w1",
        )
        provider.chat_json(
            system="s", user="u", schema={"type": "object"},
            skill="verify_with_llm", phase="verify", bundle_id="w2",
        )

        logger.uninstall()

        # Verify file written and one JSON line per call
        out = self.tmp_path / "test-exp-1.jsonl"
        self.assertTrue(out.exists())
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

        records = [json.loads(L) for L in lines]
        # First call: free text
        self.assertEqual(records[0]["skill"], "retrieve_dense")
        self.assertEqual(records[0]["provider"], "fake")
        self.assertEqual(records[0]["prompt_tokens"], 12)
        self.assertEqual(records[0]["completion_tokens"], 3)
        self.assertEqual(records[0]["total_tokens"], 15)
        self.assertTrue(records[0]["success"])
        # Second call: structured
        self.assertEqual(records[1]["skill"], "verify_with_llm")
        self.assertEqual(records[1]["prompt_tokens"], 20)
        self.assertEqual(records[1]["completion_tokens"], 5)
        self.assertEqual(records[1]["bundle_id"], "w2")

    def test_logger_counters_match_records(self):
        logger = configure_telemetry("test-exp-counter", output_dir=self.tmp_path)
        provider = _FakeProvider()

        for i in range(5):
            provider.chat_json(system="s", user=f"u{i}", skill="dense")

        logger.uninstall()
        snap = logger.snapshot()
        self.assertEqual(snap["n_calls"], 5)
        self.assertEqual(snap["n_failed"], 0)
        self.assertEqual(snap["total_prompt_tokens"], 60)
        self.assertEqual(snap["total_completion_tokens"], 15)
        self.assertEqual(snap["total_tokens"], 75)

    def test_logger_records_cost_for_hosted_model(self):
        logger = configure_telemetry("test-exp-cost", output_dir=self.tmp_path)
        provider = _FakeProvider(model="gpt-4o-mini")
        # Manually set provider name so cost_table looks up the OpenAI row
        provider.config = LLMProviderConfig(
            provider="openai", model="gpt-4o-mini",
            base_url="http://x", api_key="k",
            max_retries=1, retry_backoff_s=(0.01,),
        )
        provider.name = "openai"

        provider.chat_json(system="s", user="u")

        logger.uninstall()
        records = load_records(self.tmp_path / "test-exp-cost.jsonl")
        self.assertEqual(len(records), 1)
        # gpt-4o-mini: input $0.15/M, output $0.60/M
        # 12 in + 3 out  ->  12*0.15e-6 + 3*0.60e-6  = 1.8e-6 + 1.8e-6 = 3.6e-6
        self.assertAlmostEqual(records[0]["cost_usd"], 0.0000036, places=8)

    def test_self_hosted_records_zero_cost(self):
        logger = configure_telemetry("test-exp-selfhost", output_dir=self.tmp_path)
        provider = _FakeProvider()  # provider name "fake" — unknown
        provider.config = LLMProviderConfig(
            provider="lm_studio", model="qwen/anything",
            base_url="http://x", api_key="",
            max_retries=1, retry_backoff_s=(0.01,),
        )
        provider.name = "lm_studio"

        provider.chat_json(system="s", user="u")
        logger.uninstall()

        records = load_records(self.tmp_path / "test-exp-selfhost.jsonl")
        self.assertEqual(records[0]["cost_usd"], 0.0)


class TestTelemetrySummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        register_telemetry_hook(None)

    def tearDown(self):
        register_telemetry_hook(None)
        self.tmp.cleanup()

    def test_summary_totals(self):
        logger = configure_telemetry("test-summary", output_dir=self.tmp_path)
        provider = _FakeProvider()

        for i in range(3):
            provider.chat_json(system="s", user=f"u{i}", skill="dense")
        for i in range(2):
            provider.chat_json(
                system="s", user="u", schema={"type": "object"},
                skill="verify_with_llm",
            )

        logger.uninstall()

        path = self.tmp_path / "test-summary.jsonl"
        out_path, summary = write_summary(path)
        self.assertTrue(out_path.exists())

        self.assertEqual(summary["n_calls"], 5)
        self.assertEqual(summary["n_failed"], 0)
        # 3 free-text * 12 + 2 schema * 20 = 36 + 40 = 76
        self.assertEqual(summary["total_prompt_tokens"], 76)
        # 3 * 3 + 2 * 5 = 9 + 10 = 19
        self.assertEqual(summary["total_completion_tokens"], 19)
        self.assertEqual(summary["total_tokens"], 95)

        # Per-skill breakdown
        self.assertIn("dense", summary["per_skill"])
        self.assertIn("verify_with_llm", summary["per_skill"])
        self.assertEqual(summary["per_skill"]["dense"]["n_calls"], 3)
        self.assertEqual(summary["per_skill"]["verify_with_llm"]["n_calls"], 2)

    def test_summary_handles_missing_file(self):
        summary = summarise(self.tmp_path / "nonexistent.jsonl")
        self.assertEqual(summary["n_calls"], 0)

    def test_summary_monetary_equivalents_populated(self):
        logger = configure_telemetry("test-eq", output_dir=self.tmp_path)
        provider = _FakeProvider()
        for _ in range(10):
            provider.chat_json(system="s", user="u")
        logger.uninstall()

        _, summary = write_summary(self.tmp_path / "test-eq.jsonl")
        eqs = summary["monetary_equivalent_usd"]
        # The 3 baseline keys from cost_table.yaml
        self.assertIn("openai:gpt-4o", eqs)
        self.assertIn("openai:gpt-4o-mini", eqs)
        self.assertIn("anthropic:claude-haiku-4-5-20251001", eqs)
        # All non-negative
        for k, v in eqs.items():
            self.assertGreaterEqual(v, 0, f"{k} = {v}")


if __name__ == "__main__":
    unittest.main()
