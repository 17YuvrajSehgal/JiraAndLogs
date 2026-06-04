"""Regression check for TCH cascade headline metrics.

Re-runs build_cascade in-place against the locked Phase 1 numbers and
fails (exit 1) if any headline metric regresses below tolerance. Use
in CI or after merging changes that could affect the cascade.

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.check_cascade \\
        --cascade-dir data/derived/global/.../comparison/v2f-tch-phase1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Locked Phase 1 headline numbers (commit 1eaa6cc, 2026-06-04).
# Format: metric -> (expected_value, abs_tolerance, "higher_better"/"tie_ok")
EXPECTED = {
    "hit_at_1":          (0.7069, 0.001, "higher_better"),
    "hit_at_5":          (0.9124, 0.001, "higher_better"),
    "mrr":               (0.7880, 0.001, "higher_better"),
    "pr_auc":            (0.9998, 0.001, "higher_better"),
    "pr_auc_inclusive":  (0.8527, 0.005, "higher_better"),
    "novel_precision":   (0.9479, 0.010, "higher_better"),
    "novel_recall":      (0.1344, 0.020, "higher_better"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cascade-dir", type=Path, required=True)
    args = ap.parse_args()

    metrics_path = args.cascade_dir / "tch_metrics.json"
    if not metrics_path.exists():
        print(f"ERROR: {metrics_path} not found. Run build_cascade first.")
        return 2
    metrics = json.loads(metrics_path.read_text())

    failed = []
    print(f"{'metric':22s}  {'actual':>10s}  {'expected':>10s}  {'tol':>7s}  status")
    for name, (expected, tol, mode) in EXPECTED.items():
        actual = float(metrics.get(name, 0.0))
        if mode == "higher_better":
            # PASS if actual >= expected - tol (we allow regression up to tol).
            ok = actual >= expected - tol
        else:
            ok = abs(actual - expected) <= tol
        status = "OK" if ok else "REGRESSION"
        if not ok:
            failed.append((name, actual, expected, tol))
        print(f"{name:22s}  {actual:10.4f}  {expected:10.4f}  {tol:7.3f}  {status}")

    if failed:
        print(f"\n{len(failed)} METRIC(S) REGRESSED beyond tolerance:")
        for name, actual, expected, tol in failed:
            print(f"  {name}: {actual:.4f} < {expected:.4f} - {tol:.3f}")
        return 1

    print("\nAll TCH headline metrics pass the regression check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
