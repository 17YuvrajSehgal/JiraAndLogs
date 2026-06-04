"""One-shot TCH finalization: rebuild cascade, run regression check,
analyze stratified metrics. Use after Phase 2 (or any agent run) writes
new predictions to `comparison/v2e-agent-phase2/` — the EXTRA_AGENT_FILES
wiring auto-picks it up.

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.finalize \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> int:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument(
        "--output-dir", type=Path,
        default=None,
        help="defaults to <global-dir>/comparison/v2f-tch-phase1",
    )
    args = ap.parse_args()
    output_dir = args.output_dir or (args.global_dir / "comparison/v2f-tch-phase1")

    env = {"PYTHONPATH": "src"}
    import os as _os
    full_env = {**_os.environ, **env}

    # 1) Rebuild cascade (auto-merges EXTRA_AGENT_FILES if present)
    rc = subprocess.run([
        sys.executable, "-m", "v2_advanced.tch.build_cascade",
        "--global-dir", str(args.global_dir),
        "--output-dir", str(output_dir),
    ], env=full_env).returncode
    if rc != 0:
        print(f"\nbuild_cascade exited {rc}")
        return rc

    # 2) Regression check (will fail if any metric drops)
    rc = subprocess.run([
        sys.executable, "-m", "v2_advanced.tch.check_cascade",
        "--cascade-dir", str(output_dir),
    ], env=full_env).returncode
    if rc != 0:
        print(f"\ncheck_cascade exited {rc} — METRIC REGRESSION DETECTED")
        return rc

    # 3) Re-run analyzer (bootstrap CIs + per-stratum + failure analysis)
    rc = subprocess.run([
        sys.executable, "-m", "v2_advanced.tch.analyze_cascade",
        "--cascade-dir", str(output_dir),
        "--comparison-base", str(args.global_dir / "comparison"),
    ], env=full_env).returncode
    if rc != 0:
        print(f"\nanalyze_cascade exited {rc}")
        return rc

    print(f"\nTCH finalize complete. Output: {output_dir}")
    print("Run `git status` to see what changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
