"""Compute per-metric delta between a candidate cascade and the locked
v2f-tch-phase1 baseline. Used after each G-phase to quantify improvement.

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.delta_vs_baseline \\
        --candidate-dir data/derived/global/.../v2g-final-models/g1-bienc-hard-negatives \\
        --baseline-dir   data/derived/global/.../v2f-tch-phase1 \\
        --output delta-vs-phase1.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_metrics(d: Path) -> dict[str, Any]:
    return json.loads((d / "tch_metrics.json").read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-dir", type=Path, required=True)
    ap.add_argument("--baseline-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    cand = _load_metrics(args.candidate_dir)
    base = _load_metrics(args.baseline_dir)

    metrics = ("hit_at_1", "hit_at_5", "mrr", "pr_auc",
               "pr_auc_inclusive", "novel_precision", "novel_recall")

    rows = []
    print(f"{'metric':22s}  {'baseline':>10s}  {'candidate':>10s}  {'delta':>10s}  {'rel %':>8s}")
    for m in metrics:
        b = float(base.get(m, 0.0))
        c = float(cand.get(m, 0.0))
        d = c - b
        rel = (d / b * 100) if b else 0.0
        rows.append({"metric": m, "baseline": b, "candidate": c, "delta": d, "delta_rel_pct": rel})
        print(f"{m:22s}  {b:>10.4f}  {c:>10.4f}  {d:>+10.4f}  {rel:>+7.1f}%")

    args.output.write_text(json.dumps({
        "candidate_dir": str(args.candidate_dir),
        "baseline_dir": str(args.baseline_dir),
        "deltas": rows,
    }, indent=2))
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
