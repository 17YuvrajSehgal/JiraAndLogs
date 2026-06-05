"""Reload Neo4j from the LLM-extracted ticket facts.

After `extract_tickets_cli` finishes writing `v2_kg_extractions/all_extractions.jsonl`,
run this script to flush the graph and load the LLM extractions instead
of the rule-based ones.

Usage:
    PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        [--source llm|rules]    default: llm (prefers v2_kg_extractions/, falls back
                                            to v2_kg_extractions_rules/)
        [--no-clear]            don't wipe before loading (MERGE will dedup but
                                stale nodes from a previous load may linger)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2_advanced.shared import Neo4jClient, get_logger, log_step

from .loader import load_extractions
from .schema import IncidentExtraction

log = get_logger("phase_d.reload_neo4j")


_SOURCE_DIRS = {
    "llm":   "v2_kg_extractions",
    "rules": "v2_kg_extractions_rules",
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--source", choices=["llm", "rules"], default="llm")
    p.add_argument("--no-clear", action="store_true",
                   help="skip clearing the graph before loading")
    args = p.parse_args()

    src_dir = args.global_dir / _SOURCE_DIRS[args.source]
    cache = src_dir / "all_extractions.jsonl"
    if not cache.exists():
        # Fall back to the other source if LLM file isn't there yet.
        other = "rules" if args.source == "llm" else "llm"
        alt = args.global_dir / _SOURCE_DIRS[other] / "all_extractions.jsonl"
        if alt.exists():
            log.warning(
                "requested source missing; falling back",
                requested=args.source, used=other, path=str(alt),
            )
            cache = alt
        else:
            raise SystemExit(
                f"No extractions at {cache} or {alt}. "
                "Run extract_tickets_cli (or extract_rulebased_cli) first."
            )

    with log_step(log, "load_jsonl", path=str(cache)):
        extractions = []
        with cache.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                extractions.append(IncidentExtraction.from_dict(json.loads(line)))
        log.info("extractions loaded", n=len(extractions))

    with Neo4jClient() as neo:
        counts = load_extractions(
            neo, extractions,
            clear_first=not args.no_clear,
            batch_size=50,
        )
        log.info("post-load counts", **counts)


if __name__ == "__main__":
    main()
