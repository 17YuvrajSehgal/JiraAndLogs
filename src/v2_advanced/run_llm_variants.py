"""Run every v2 LLM-powered variant against the v2 in-distribution split.

Sequence (each step is idempotent / cached):
  1. Verify LM Studio is reachable (informational only — pipelines
     fall back to rules if not).
  2. Reload Neo4j from the LLM extractions if present.
  3. Run the LLM-variant comparison:
       kg_retrieval                  (LLM ticket entities, rule-based window)
       hybrid_rrf_retrieval          (BiE+SPLADE+LLM-graph via RRF)
       diagnosis_agent               (LLM hypothesize+verify if available)

Output: data/derived/global/<id>/comparison/v2-llm-final/

Usage:
    PYTHONPATH=src python -m v2_advanced.run_llm_variants \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --runs-root data/runs
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from v2_advanced.shared import LMStudioClient, get_logger, log_step

log = get_logger("run_llm_variants")


_DEFAULT_PIPELINES = [
    "kg_retrieval",
    "hybrid_rrf_retrieval",
    "diagnosis_agent",
]


def _reload_neo4j(global_dir: Path) -> None:
    """Try to reload Neo4j from the LLM extractions file. If not yet
    written by extract_tickets_cli, silently keep whatever's loaded.
    """
    cache = global_dir / "v2_kg_extractions" / "all_extractions.jsonl"
    if not cache.exists():
        log.warning(
            "LLM extractions not found; Neo4j will keep whatever's "
            "currently loaded (probably the rule-based extractions)",
            expected_at=str(cache),
        )
        return

    log.info("reloading Neo4j from LLM extractions", path=str(cache))
    cmd = [
        sys.executable, "-m",
        "v2_advanced.proposal_d_knowledge_graph.reload_neo4j",
        "--global-dir", str(global_dir),
        "--source", "llm",
    ]
    result = subprocess.run(
        cmd, env={**__import__("os").environ, "PYTHONPATH": "src"},
    )
    if result.returncode != 0:
        raise SystemExit(f"reload_neo4j failed with exit {result.returncode}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--runs-root", type=Path, required=True)
    p.add_argument(
        "--pipelines", type=str,
        default=",".join(_DEFAULT_PIPELINES),
        help="comma-separated pipeline names",
    )
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument(
        "--output-dir", type=Path,
        default=Path("data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2-llm-final"),
    )
    args = p.parse_args()

    # 1) LM Studio info
    cli = LMStudioClient()
    log.info("LM Studio reachable", available=cli.is_available())

    # 2) Neo4j reload
    with log_step(log, "reload_neo4j"):
        _reload_neo4j(args.global_dir)

    # 3) Comparison run
    cmd = [
        sys.executable, "-W", "ignore",
        "-m", "v2_advanced.proposal_a_resplit.run_v2_comparison",
        "--global-dir", str(args.global_dir),
        "--runs-root", str(args.runs_root),
        "--pipelines", args.pipelines,
        "--no-ensemble", "--no-lofo",
        "--n-bootstrap", str(args.n_bootstrap),
        "--output-dir", str(args.output_dir),
    ]
    log.info("launching comparison", out=str(args.output_dir))
    with log_step(log, "comparison_subprocess"):
        result = subprocess.run(
            cmd, env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        if result.returncode != 0:
            raise SystemExit(f"comparison failed with exit {result.returncode}")

    log.info("v2 LLM-variant panel done", output_dir=str(args.output_dir))


if __name__ == "__main__":
    main()
