"""Master driver — run every v2 pipeline on the v2 in-distribution split.

This script orchestrates the full v2 panel:
  1. (Pre-requisite) The v2 split manifest must exist
     (run `make_resplit.py` once if not).
  2. (Pre-requisite) Rule-based ticket extractions must exist
     (run `extract_rulebased_cli.py` once).
  3. (Optional) LLM-based ticket extractions if LM Studio is up.
  4. Runs all registered v2 pipelines:
       - kg_retrieval_rulebased   (no LLM)
       - kg_retrieval             (needs LLM)
       - hybrid_rrf_no_graph
       - hybrid_rrf_retrieval
       - logseq2vec_retrieval
       - diagnosis_agent          (needs LLM)
  5. Writes a single consolidated comparison/report.json with all
     pipelines for head-to-head scoring.

Usage:
    PYTHONPATH=src python -m v2_advanced.run_all_v2 \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --runs-root data/runs

By default this excludes pipelines requiring LM Studio if LM Studio is
not reachable. Pass --require-llm to fail fast if you want all-or-nothing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from v2_advanced.shared import LMStudioClient, get_logger, log_step

log = get_logger("run_all_v2")


# Which pipelines we run, and which require LM Studio.
DEFAULT_PIPELINES = [
    # v1 baselines for direct comparison
    ("hgb",                                 False),
    ("tab_transformer",                     False),
    ("memorygraph_v2_sota_nw080",           False),
    ("bi_encoder_retrieval",                False),
    # v2 phase D
    ("kg_retrieval_rulebased",              False),
    ("kg_retrieval",                        True),   # LLM for window extraction
    # v2 phase C
    ("hybrid_rrf_no_graph",                 False),
    ("hybrid_rrf_retrieval",                False),  # graph already loaded; rule-based windows
    # v2 phase B
    ("logseq2vec_retrieval",                False),
    # v2 phase E
    ("diagnosis_agent",                     True),   # LLM-heavy
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--runs-root", type=Path, required=True)
    p.add_argument(
        "--pipelines", default="",
        help="comma-separated subset of pipeline names to run (default: all)",
    )
    p.add_argument(
        "--exclude-llm", action="store_true",
        help="skip pipelines that require LM Studio",
    )
    p.add_argument(
        "--require-llm", action="store_true",
        help="fail fast if LM Studio is not reachable",
    )
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument(
        "--manifest", default="triage-split-manifest-v2-resplit.json",
        help="window-level v2 manifest filename inside global-dir",
    )
    p.add_argument(
        "--output-base", type=str,
        default="data/derived/global/2026-05-25-dataset-v5-large-global/comparison",
    )
    p.add_argument(
        "--phase-run-id", default="v2-final",
        help="subdir under output-base for this run",
    )
    args = p.parse_args()

    # Detect LM Studio
    lm_available = LMStudioClient().is_available()
    log.info("LM Studio status", available=lm_available, url="http://localhost:1234")

    if args.require_llm and not lm_available:
        raise SystemExit("--require-llm set but LM Studio is unreachable.")

    # Pick pipelines
    if args.pipelines:
        requested = [s.strip() for s in args.pipelines.split(",") if s.strip()]
        pipeline_specs = [(n, needs_llm) for n, needs_llm in DEFAULT_PIPELINES if n in requested]
    else:
        pipeline_specs = DEFAULT_PIPELINES

    runnable = []
    skipped = []
    for name, needs_llm in pipeline_specs:
        if needs_llm and (args.exclude_llm or not lm_available):
            skipped.append(name)
        else:
            runnable.append(name)

    log.info("plan", will_run=runnable, will_skip=skipped)

    if not runnable:
        raise SystemExit("no pipelines to run; check --pipelines and LM Studio")

    out_dir = Path(args.output_base) / args.phase_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Delegate to the v2 split driver (already monkey-patches iter_split)
    cmd = [
        sys.executable, "-W", "ignore",
        "-m", "v2_advanced.proposal_a_resplit.run_v2_comparison",
        "--global-dir", str(args.global_dir),
        "--runs-root", str(args.runs_root),
        "--pipelines", ",".join(runnable),
        "--no-ensemble", "--no-lofo",
        "--n-bootstrap", str(args.n_bootstrap),
        "--manifest", args.manifest,
        "--output-dir", str(out_dir),
    ]
    log.info("running master comparison", n_pipelines=len(runnable), out=str(out_dir))
    with log_step(log, "comparison_subprocess"):
        result = subprocess.run(cmd, env={**__import__("os").environ, "PYTHONPATH": "src"})
        if result.returncode != 0:
            raise SystemExit(f"comparison subprocess failed with exit code {result.returncode}")

    log.info("v2 panel done", output_dir=str(out_dir))


if __name__ == "__main__":
    main()
