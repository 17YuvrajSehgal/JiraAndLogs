"""Smoke-test extract_from_window with vs without family/severity context.

For each sample window, calls extract_from_window twice: once with no
family/severity (legacy behavior), once with both populated (new
behavior). Compares the LLM outputs side by side to see if soft context
actually improves entity recovery for thin OTel-style evidence.

Bypasses the on-disk cache by passing cache_dir=None.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from v2_advanced.shared.lm_studio import LMStudioClient, LMStudioConfig
from v2_advanced.proposal_d_knowledge_graph.extractor import extract_from_window


def _print_ext(label: str, ext) -> None:
    print(f"  [{label}]")
    print(f"    services: {ext.affected_services}")
    print(f"    components: {ext.components}")
    print(f"    errors: {ext.error_classes}")
    print(f"    symptoms: {ext.symptoms[:5]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--model", default="qwen/qwen3.6-35b-a3b")
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    args = p.parse_args()

    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model)
    client = LMStudioClient(cfg)
    if not client.is_available():
        print(f"LM Studio not reachable at {args.lm_studio_url}", file=sys.stderr)
        sys.exit(2)

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    # Pick `args.n` ticket_worthy rows with non-trivial evidence + family known
    samples = []
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("triage_label") != "ticket_worthy":
                continue
            if not r.get("triage_evidence_text") or len(r["triage_evidence_text"]) < 100:
                continue
            fam = r.get("scenario_family", "")
            if not fam or fam == "unknown":
                continue
            samples.append(r)
            if len(samples) >= args.n:
                break

    if not samples:
        print("No usable samples found.", file=sys.stderr)
        sys.exit(2)

    diffs = 0
    for r in samples:
        wid = r["window_id"]
        ev = r["triage_evidence_text"]
        fam = r["scenario_family"]
        sev = r.get("window_type", "")
        print(f"\nWINDOW {wid[:80]}")
        print(f"  family={fam}  severity={sev}")
        print(f"  evidence_text ({len(ev)} chars): {ev[:120]}...")

        no_ctx = extract_from_window(
            client, window_id=wid, evidence_text=ev,
            severity="", family="", cache_dir=None,
        )
        with_ctx = extract_from_window(
            client, window_id=wid, evidence_text=ev,
            severity=sev, family=fam, cache_dir=None,
        )
        _print_ext("WITHOUT family/severity", no_ctx)
        _print_ext("WITH    family/severity", with_ctx)

        if (no_ctx.affected_services != with_ctx.affected_services or
            no_ctx.error_classes != with_ctx.error_classes or
            no_ctx.components != with_ctx.components):
            diffs += 1
            print("  -> CHANGED")
        else:
            print("  -> identical")

    print(f"\nSummary: {diffs}/{len(samples)} samples differ between WITH and WITHOUT context")


if __name__ == "__main__":
    main()
