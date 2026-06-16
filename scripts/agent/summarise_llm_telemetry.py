"""Summarise an experiment's LLM telemetry JSONL into a .summary.json.

Reads `data/llm_telemetry/<experiment>.jsonl`, aggregates into a single
JSON with totals, per-skill / per-provider breakdown, and monetary
equivalents at hosted-model rates.

Usage:
    python scripts/agent/summarise_llm_telemetry.py <experiment_id>
    python scripts/agent/summarise_llm_telemetry.py wol-mode3-kg-extraction
    python scripts/agent/summarise_llm_telemetry.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from agent.llm.telemetry import DEFAULT_OUTPUT_DIR
from agent.llm.telemetry_summary import write_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_id", nargs="?",
        help="Experiment id (matches the JSONL filename stem). "
             "If omitted, --all must be set.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Summarise every *.jsonl in the telemetry directory.",
    )
    parser.add_argument(
        "--telemetry-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Override telemetry root (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--print", action="store_true",
        help="Also print the summary to stdout.",
    )
    args = parser.parse_args()

    if not args.all and not args.experiment_id:
        parser.error("either provide <experiment_id> or pass --all")

    if args.all:
        jsonl_paths = sorted(args.telemetry_dir.glob("*.jsonl"))
        if not jsonl_paths:
            print(f"No telemetry JSONLs under {args.telemetry_dir}", file=sys.stderr)
            return 1
    else:
        p = args.telemetry_dir / f"{args.experiment_id}.jsonl"
        if not p.exists():
            print(f"Telemetry file not found: {p}", file=sys.stderr)
            return 1
        jsonl_paths = [p]

    for jsonl_path in jsonl_paths:
        out_path, summary = write_summary(jsonl_path)
        print(f"wrote {out_path}", file=sys.stderr)
        if args.print:
            print(json.dumps(summary, indent=2))
        else:
            # Compact one-line summary to stderr
            tot = summary.get("total_tokens", 0)
            n = summary.get("n_calls", 0)
            failed = summary.get("n_failed", 0)
            cost = summary.get("total_cost_usd", 0.0)
            wall = summary.get("wall_seconds", 0.0)
            print(
                f"  {summary.get('experiment')}: n_calls={n} n_failed={failed} "
                f"total_tokens={tot} cost_usd=${cost} wall={wall}s",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
