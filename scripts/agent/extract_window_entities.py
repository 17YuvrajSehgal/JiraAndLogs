"""Run LLM entity extraction over a dataset's test windows.

Closes the asymmetric-extraction gap from Phase 3.1 of AGENTIC-SYSTEM
(RQ-A6). Reads `<global_dir>/global-triage-examples.jsonl`, filters to
the v2-resplit test split (manifest-aware), and runs
`extract_from_window` on each. Output:

    <global_dir>/v2_kg_extractions_windows/all_extractions.jsonl
        (one JSON row per extracted window — schema matches
         v2_advanced.proposal_d_knowledge_graph.extractor.WindowExtraction)

Per-window caching: the extractor writes one file per window under
`v2_kg_extractions_windows/<window_id>.json`; re-running this script
skips already-extracted windows. Safe to interrupt and resume.

Dataset-agnostic: works on OB, OTel Demo, and WoL (anything that has
`global-triage-examples.jsonl` + the resplit manifest format).

The expensive part is LM Studio inference (~6 hours on WoL with
Qwen3.6-35B-A3B per the conversation summary). Run with LM Studio
serving on http://localhost:1234 + the right model loaded.

Usage:
    PYTHONPATH=src python scripts/agent/extract_window_entities.py \\
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global \\
        --split test \\
        [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders.split_manifest import load_split_manifest, resolve_split


def _iter_test_windows(global_dir: Path, split: str, limit: int | None = None):
    """Yield (window_id, evidence_text, scenario_family, window_type)
    for windows in the given split, applying the v2-resplit manifest
    when present."""
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        raise FileNotFoundError(f"missing {examples_path}")

    manifest = load_split_manifest(global_dir)

    n_kept = 0
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resolve_split(row, manifest) != split:
                continue
            window_id = row.get("window_id")
            text = row.get("triage_evidence_text") or ""
            if not window_id or not text:
                continue
            yield {
                "window_id": window_id,
                "evidence_text": text,
                "family": row.get("scenario_family") or "",
                "severity": row.get("window_type") or "",
            }
            n_kept += 1
            if limit is not None and n_kept >= limit:
                return


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test", choices=["train", "validation", "test"])
    p.add_argument("--lm-studio-url", default="http://localhost:1234",
                   help="Base URL for the OpenAI-compatible chat-completions server. "
                        "Use https://api.openai.com for OpenAI proper.")
    p.add_argument("--model", default="local-model")
    p.add_argument("--api-key-env", default=None,
                   help="Name of env var holding the Bearer API key (e.g. OPENAI_API_KEY). "
                        "Unset → no auth header (local LM Studio).")
    p.add_argument("--max-tokens", type=int, default=600)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="v2_kg_extractions_windows")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("extract_window_entities")

    cache_dir = args.global_dir / args.out_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    log.info("output cache dir: %s", cache_dir)

    # Lazy import — only need v2_advanced when we actually run.
    from v2_advanced.proposal_d_knowledge_graph.extractor import (
        extract_from_window,
    )
    from v2_advanced.shared import LMStudioClient
    from v2_advanced.shared.lm_studio import LMStudioConfig

    import os
    api_key = None
    if args.api_key_env:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(
                f"--api-key-env={args.api_key_env} set, but that env var is empty.",
            )
        log.info("Using API key from env var %s (Bearer auth enabled).", args.api_key_env)
    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model, api_key=api_key)
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(
            f"LLM endpoint not reachable at {args.lm_studio_url}. "
            "If using OpenAI: verify --api-key-env points to a valid key. "
            "If using LM Studio: start the local server with a model loaded first.",
        )
    log.info("LLM endpoint reachable at %s (model=%s)", args.lm_studio_url, args.model)

    windows = list(_iter_test_windows(
        args.global_dir, args.split,
        limit=args.limit if args.limit > 0 else None,
    ))
    log.info(
        "extracting from %d windows (split=%s) — output to %s",
        len(windows), args.split, cache_dir,
    )

    t_start = time.time()
    n_failed_or_empty = 0
    extractions: list[dict] = []

    for i, w in enumerate(windows, start=1):
        try:
            ext = extract_from_window(
                client,
                window_id=w["window_id"],
                evidence_text=w["evidence_text"],
                severity=w["severity"],
                family=w["family"],
                cache_dir=cache_dir,
                max_tokens=args.max_tokens,
            )
        except Exception as e:                                       # noqa: BLE001
            log.warning("extraction failed for %s: %s", w["window_id"], e)
            n_failed_or_empty += 1
            continue

        if not (ext.affected_services or ext.error_classes or ext.symptoms):
            n_failed_or_empty += 1

        extractions.append(ext.as_dict())

        if i % 10 == 0:
            elapsed = time.time() - t_start
            avg = elapsed / i
            eta_min = (len(windows) - i) * avg / 60.0
            log.info(
                "progress: done=%d/%d empty_or_failed=%d avg=%.2fs/w eta=%.1fmin",
                i, len(windows), n_failed_or_empty, avg, eta_min,
            )

    # Consolidated output
    consolidated = cache_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext) + "\n")
    log.info("wrote consolidated: %s (%d rows)",
             consolidated, len(extractions))

    n_with_services = sum(1 for e in extractions if e.get("affected_services"))
    n_with_errors = sum(1 for e in extractions if e.get("error_classes"))
    n_with_symptoms = sum(1 for e in extractions if e.get("symptoms"))
    print()
    print("=" * 70)
    print(f"  Window extraction — {args.global_dir.name} ({args.split})")
    print("=" * 70)
    print(f"  total                  {len(extractions)}")
    print(f"  with affected_services {n_with_services}")
    print(f"  with error_classes     {n_with_errors}")
    print(f"  with symptoms          {n_with_symptoms}")
    print(f"  empty / failed         {n_failed_or_empty}")
    print(f"  output                 {consolidated}")
    print("=" * 70)
    print(f"  Next step: re-run smoke_wol.py — the loader auto-detects")
    print(f"  v2_kg_extractions_windows/ and sets KG_GRAPH_WINDOW=True.")


if __name__ == "__main__":
    main()
