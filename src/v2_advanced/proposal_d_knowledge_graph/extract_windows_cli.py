"""G3 CLI — run LLM extraction on every v2 TEST window, cache per-window.

Currently the knowledge graph has LLM-extracted entities for the 347
Jira tickets, but each live test window emits rule-extracted entities
(services + error types via regex). This asymmetry caused the "RRF
density paradox" in Phase D: LLM-tickets have specific entities (e.g.
'RedisConnectionException') while rule-windows have generic ones
('Unavailable'), so the strings don't overlap and kg_retrieval / hybrid
LLM-graph underperform.

G3 fixes this by LLM-extracting the test windows too. After this script
completes:
  data/derived/global/<id>/v2_kg_extractions_windows/all_extractions.jsonl
    (one row per window)

Re-runs are cheap (cached per-window).

Usage:
    PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_windows_cli \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --split-manifest triage-split-manifest-v2-resplit.json \\
        --target-split test \\
        --out v2_kg_extractions_windows
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from v2_advanced.shared import LMStudioClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig
from .extractor import extract_from_window

log = get_logger("phase_d.extract_windows_cli")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split-manifest", default="triage-split-manifest-v2-resplit.json")
    p.add_argument("--target-split", default="test")
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    p.add_argument("--model", default="local-model")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", type=str, default="v2_kg_extractions_windows")
    args = p.parse_args()

    # Load windows + apply v2 split manifest
    from core.data.loaders import load_dataset
    from core.features.text import build_window_query_text
    from v2_advanced.proposal_a_resplit.window_split import (
        WindowSplitManifest, iter_window_split,
    )

    ds = load_dataset(args.global_dir)
    manifest_path = args.global_dir / args.split_manifest
    log.info("loading v2 manifest", path=str(manifest_path))
    manifest = WindowSplitManifest.from_path(manifest_path)
    target_windows = list(iter_window_split(ds.windows, manifest, args.target_split))
    log.info("windows to extract", n=len(target_windows), split=args.target_split)

    if args.limit > 0:
        target_windows = target_windows[: args.limit]
        log.info("limiting", n=len(target_windows))

    cache_dir = args.global_dir / args.out
    cache_dir.mkdir(parents=True, exist_ok=True)

    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model)
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(
            f"LM Studio is not reachable at {args.lm_studio_url}. "
            "Start LM Studio's local server and load Qwen first."
        )
    log.info("LM Studio reachable", url=args.lm_studio_url)

    extractions: list = []
    t_start = time.time()
    n_failed = 0

    with log_step(log, "extract_windows", n=len(target_windows)):
        for i, w in enumerate(target_windows, start=1):
            evidence = build_window_query_text(w) or ""
            if not evidence:
                log.warning("empty evidence — skipping", window_id=w.window_id)
                continue

            family = getattr(w, "scenario_family", "") or ""
            severity = getattr(w, "severity", "") or ""

            ext = extract_from_window(
                client,
                window_id=w.window_id,
                evidence_text=evidence,
                severity=severity,
                family=family,
                cache_dir=cache_dir,
                max_tokens=600,
            )
            extractions.append(ext)

            if not (ext.affected_services or ext.error_classes or ext.symptoms):
                n_failed += 1

            if i % 10 == 0:
                elapsed = time.time() - t_start
                avg = elapsed / i
                eta_min = (len(target_windows) - i) * avg / 60.0
                log.info(
                    "window extraction progress",
                    done=i,
                    total=len(target_windows),
                    failed_or_empty=n_failed,
                    avg_s_per_window=round(avg, 2),
                    eta_min=round(eta_min, 1),
                )

    # Summary
    n_with_services = sum(1 for e in extractions if e.affected_services)
    n_with_errors = sum(1 for e in extractions if e.error_classes)
    n_with_symptoms = sum(1 for e in extractions if e.symptoms)
    n_empty = sum(1 for e in extractions if not (e.affected_services or e.error_classes or e.symptoms))

    log.info(
        "extraction summary",
        total=len(extractions),
        with_services=n_with_services,
        with_errors=n_with_errors,
        with_symptoms=n_with_symptoms,
        empty=n_empty,
    )

    consolidated = cache_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext.as_dict()) + "\n")
    log.info("consolidated extractions written", path=str(consolidated))


if __name__ == "__main__":
    main()
