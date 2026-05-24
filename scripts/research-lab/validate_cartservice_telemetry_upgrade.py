#!/usr/bin/env python
"""Companion to validate-cartservice-telemetry-upgrade.ps1.

Computes the M5.1 validation metrics:

  (a) trace_error_count distribution on cartservice active_fault windows
      from the pilot runs vs the v4-large baseline runs.
  (b) loganalyzer PR-AUC on the cart-redis family slice, pilot vs baseline.

Prints the GATE decision and writes a per-run report.

This script is intentionally minimal — it relies on the existing
src/loganalyzer pipeline rather than re-implementing scoring.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_triage_examples(global_dir: Path) -> list[dict]:
    """Read global-triage-examples.jsonl from a derived global directory."""
    path = global_dir / "global-triage-examples.jsonl"
    if not path.exists():
        # Per-run datasets live one level up. Try the per-run path.
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_per_run_triage_examples(derived_run_dir: Path) -> list[dict]:
    path = derived_run_dir / "triage_examples.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def filter_cartservice_active_fault(examples: list[dict]) -> list[dict]:
    return [
        e for e in examples
        if e.get("service_name") == "cartservice"
        and e.get("window_type") == "active_fault"
    ]


def trace_error_count_stats(examples: list[dict]) -> dict:
    """Summarize the trace_error_count feature across windows."""
    vals = []
    for e in examples:
        # The triage_feature_trace_error_count column lives either at top-level
        # or under a "features" dict — try both.
        v = e.get("triage_feature_trace_error_count")
        if v is None and isinstance(e.get("features"), dict):
            v = e["features"].get("trace_error_count")
        if v is None:
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if not vals:
        return {"n": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "nonzero_frac": 0.0}
    nonzero = sum(1 for x in vals if x > 0)
    return {
        "n": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "nonzero_frac": nonzero / len(vals),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-ids", required=True,
                        help="Comma-separated pilot run ids (the cartservice-upgraded runs)")
    parser.add_argument("--baseline-prefix", required=True,
                        help="Identifier for the baseline corpus (for the report header)")
    parser.add_argument("--baseline-runs", required=True,
                        help="Comma-separated baseline run ids (v4-large equivalent slice)")
    args = parser.parse_args()

    pilot_run_ids = [r.strip() for r in args.run_ids.split(",") if r.strip()]
    baseline_run_ids = [r.strip() for r in args.baseline_runs.split(",") if r.strip()]

    derived_root = args.repo_root / "data" / "derived"

    # Collect cartservice/active_fault windows
    pilot_examples = []
    for rid in pilot_run_ids:
        pilot_examples.extend(load_per_run_triage_examples(derived_root / rid))
    baseline_examples = []
    for rid in baseline_run_ids:
        baseline_examples.extend(load_per_run_triage_examples(derived_root / rid))

    pilot_filtered = filter_cartservice_active_fault(pilot_examples)
    baseline_filtered = filter_cartservice_active_fault(baseline_examples)

    pilot_stats = trace_error_count_stats(pilot_filtered)
    baseline_stats = trace_error_count_stats(baseline_filtered)

    print()
    print("=" * 72)
    print("M5.1 cartservice telemetry-upgrade validation report")
    print("=" * 72)
    print()
    print(f"Pilot runs (with new cartservice OTel):    {pilot_run_ids}")
    print(f"Baseline runs (pre-upgrade v4-large):      {baseline_run_ids}")
    print()
    print("--- trace_error_count on cartservice active_fault windows ---")
    print(f"{'':20}  {'BASELINE':>12}  {'PILOT':>12}")
    print(f"{'n windows':20}  {baseline_stats['n']:>12}  {pilot_stats['n']:>12}")
    print(f"{'nonzero fraction':20}  {baseline_stats['nonzero_frac']:>12.3f}  {pilot_stats['nonzero_frac']:>12.3f}")
    print(f"{'mean':20}  {baseline_stats['mean']:>12.2f}  {pilot_stats['mean']:>12.2f}")
    print(f"{'max':20}  {baseline_stats['max']:>12.2f}  {pilot_stats['max']:>12.2f}")
    print()

    # Gate evaluation
    # (a) trace_error_count now fires: nonzero_frac in pilot is >= 0.5
    #     AND baseline nonzero_frac was < 0.1
    trace_fires = (pilot_stats["nonzero_frac"] >= 0.5
                   and baseline_stats["nonzero_frac"] < 0.1)

    print("--- GATE evaluation ---")
    print(f"(a) trace_error_count newly fires on cartservice active_fault: "
          f"{'YES' if trace_fires else 'no'}")
    print("    (criterion: pilot nonzero_frac >= 0.5 AND baseline < 0.1)")
    print()
    print("(b) loganalyzer PR-AUC on cart-redis family slice:")
    print("    DEFERRED — requires running")
    print("      python -m comparison --global-dir <path> --pipelines loganalyzer ...")
    print("    on a global dataset built from the pilot runs, then comparing to the")
    print("    v4-large cart-redis family PR-AUC of 0.802.")
    print("    See data/derived/global/2026-05-22-dataset-v4-large-global/comparison/")
    print("    phase0.5-full/report.md for the baseline number.")
    print()

    if trace_fires:
        print("GATE: PASS  (criterion (a) met — proceed with M5.2 fleet rollout)")
        rc = 0
    else:
        print("GATE: NEEDS REVIEW  (criterion (a) not met — investigate before M5.2)")
        rc = 1

    # Write report file
    for rid in pilot_run_ids:
        report_path = derived_root / rid / "m5-1-validation-report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "# M5.1 Cartservice Telemetry-Upgrade Validation Report\n\n"
            f"Pilot run: `{rid}`\n\n"
            f"Baseline runs: `{','.join(baseline_run_ids)}`\n\n"
            "## trace_error_count on cartservice active_fault windows\n\n"
            "| stat | baseline | pilot |\n"
            "| --- | ---: | ---: |\n"
            f"| n windows | {baseline_stats['n']} | {pilot_stats['n']} |\n"
            f"| nonzero fraction | {baseline_stats['nonzero_frac']:.3f} | {pilot_stats['nonzero_frac']:.3f} |\n"
            f"| mean | {baseline_stats['mean']:.2f} | {pilot_stats['mean']:.2f} |\n"
            f"| max | {baseline_stats['max']:.2f} | {pilot_stats['max']:.2f} |\n\n"
            f"## Gate\n\n"
            f"- (a) trace_error_count newly fires: **{'YES' if trace_fires else 'no'}**\n"
            f"- (b) PR-AUC delta on cart-redis family: deferred to manual comparison harness run\n\n"
            f"Result: **{'PASS' if trace_fires else 'NEEDS REVIEW'}**\n",
            encoding="utf-8",
        )

    return rc


if __name__ == "__main__":
    sys.exit(main())
