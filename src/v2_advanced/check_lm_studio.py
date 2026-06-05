"""Health-check for LM Studio.

Usage:
    PYTHONPATH=src python -m v2_advanced.check_lm_studio
"""
from v2_advanced.shared import LMStudioClient
from v2_advanced.shared.lm_studio import LMStudioConfig


def main() -> int:
    cfg = LMStudioConfig()
    cli = LMStudioClient(cfg)
    if not cli.is_available():
        print(f"FAIL: LM Studio not reachable at {cfg.base_url}")
        print("Action: start LM Studio's local server and load a model.")
        return 1
    print(f"OK: LM Studio reachable at {cfg.base_url}")
    try:
        # Test JSON mode. Force thinking OFF and give enough tokens for
        # the JSON answer + any chain-of-thought spillover (defense in depth).
        obj = cli.chat_json(
            system="Reply only with valid JSON.",
            user='Return exactly: {"hello": "world"}',
            temperature=0.0, max_tokens=400,
            enable_thinking=False,
        )
        print(f"OK: JSON mode works. Got: {obj}")
    except Exception as e:
        print(f"WARN: JSON mode failed: {e}")
        print("Action: Make sure a JSON-capable instruct model is loaded.")
        return 1
    print()
    print("Everything looks good. You can now run:")
    print()
    print("  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli \\")
    print("      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
