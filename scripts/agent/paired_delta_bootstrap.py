"""Paired-delta bootstrap CIs across ablation cells — RQ-B3 strengthening.

The single-report CIs in §4.3 (Hit@1 width ±5% on OB, ±9% on OTel)
are conservative because they don't account for window-level
correlation between baseline and ablation. A paired bootstrap
resamples the SAME window_ids in BOTH cells and computes the
per-resample delta — that distribution is much tighter because
windows that score identically in both arms cancel out.

This script:
  1. Loads N EvaluationReport JSONs (each with case_results)
  2. Picks one as the BASELINE (`--baseline-name baseline`)
  3. For every other report, computes:
       - paired Δ Hit@1 with 95% bootstrap CI (1000 resamples)
       - paired Δ Hit@5, MRR, triage_accuracy
       - p-value for "delta != 0"
  4. Emits a JSON + Markdown table

Designed to consume the output of `skill_ablation.py --per-cell-report-dir DIR`,
`tool_ablation.py --per-cell-report-dir DIR`, and the same pattern
for future sweeps.

Usage:
    PYTHONPATH=src python scripts/agent/paired_delta_bootstrap.py \\
        --reports-dir results/ob/4.1-skill-ablation/per-cell-reports \\
        --baseline-name baseline \\
        --output results/ob/4.12-paired-delta-cis/deltas.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


log = logging.getLogger(__name__)


def _load_report(path: Path) -> dict:
    """Load an EvaluationReport JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _hit_at_k(case: dict, k: int) -> int | None:
    """Read hit_at_k from a case_result. Returns None if no gold."""
    field = f"hit_at_{k}"
    v = case.get(field)
    if v is None:
        return None
    return 1 if v else 0


def _rr(case: dict) -> float | None:
    return case.get("reciprocal_rank")


def _triage_correct(case: dict) -> int | None:
    v = case.get("triage_correct")
    if v is None:
        return None
    return 1 if v else 0


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = max(0, min(len(sorted_vals) - 1, int(q * len(sorted_vals))))
    return sorted_vals[idx]


def paired_bootstrap_delta(
    baseline_cases: dict[str, dict],
    treatment_cases: dict[str, dict],
    *,
    n_resamples: int = 1000,
    seed: int = 42,
    confidence: float = 0.95,
) -> dict:
    """Paired-delta bootstrap on shared window_ids.

    For each of 4 metrics (hit_at_1, hit_at_5, mrr, triage_accuracy):
    take the common window_ids, resample them with replacement,
    compute (mean_treatment − mean_baseline), repeat n_resamples times,
    emit (point_estimate, ci_lo, ci_hi, p_value_two_sided).
    """
    common = set(baseline_cases) & set(treatment_cases)
    if not common:
        return {"error": "no shared window_ids", "n_paired": 0}
    common_list = sorted(common)
    rng = random.Random(seed)

    # Build per-window numeric vectors (None on either side → drop the window)
    metrics = {
        "hit_at_1": [],
        "hit_at_5": [],
        "mrr": [],
        "triage_accuracy": [],
    }
    extractors = {
        "hit_at_1": lambda c: _hit_at_k(c, 1),
        "hit_at_5": lambda c: _hit_at_k(c, 5),
        "mrr": _rr,
        "triage_accuracy": _triage_correct,
    }
    per_metric_wids: dict[str, list[str]] = defaultdict(list)
    per_metric_b: dict[str, list[float]] = defaultdict(list)
    per_metric_t: dict[str, list[float]] = defaultdict(list)
    for wid in common_list:
        bc = baseline_cases[wid]
        tc = treatment_cases[wid]
        for m, fn in extractors.items():
            bv = fn(bc)
            tv = fn(tc)
            if bv is None or tv is None:
                continue
            per_metric_wids[m].append(wid)
            per_metric_b[m].append(float(bv))
            per_metric_t[m].append(float(tv))

    out: dict = {"n_paired_max": len(common_list)}
    alpha = (1 - confidence) / 2

    for m in metrics:
        b = per_metric_b[m]
        t = per_metric_t[m]
        n = len(b)
        if n == 0:
            out[m] = {"n_paired": 0, "point": None, "ci_lo": None, "ci_hi": None}
            continue
        # Per-window deltas
        deltas = [tx - bx for tx, bx in zip(t, b)]
        point_delta = mean(deltas) if deltas else 0.0

        # Bootstrap mean(delta)
        boots: list[float] = []
        for _ in range(n_resamples):
            sample = [deltas[rng.randrange(0, n)] for _ in range(n)]
            boots.append(mean(sample))
        boots.sort()
        ci_lo = _percentile(boots, alpha)
        ci_hi = _percentile(boots, 1 - alpha)

        # Two-sided p-value: fraction of bootstrap deltas with opposite sign
        if point_delta == 0:
            p = 1.0
        elif point_delta > 0:
            tail = sum(1 for d in boots if d <= 0) / len(boots)
            p = min(1.0, 2 * tail)
        else:
            tail = sum(1 for d in boots if d >= 0) / len(boots)
            p = min(1.0, 2 * tail)

        out[m] = {
            "n_paired": n,
            "point": round(point_delta, 6),
            "ci_lo": round(ci_lo, 6),
            "ci_hi": round(ci_hi, 6),
            "ci_width": round(ci_hi - ci_lo, 6),
            "p_value": round(p, 4),
        }
    return out


def _key_by_window(report: dict) -> dict[str, dict]:
    cases = report.get("case_results") or []
    return {c.get("bundle_id"): c for c in cases if c.get("bundle_id")}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports-dir", type=Path, required=True,
                   help="Directory of per-cell EvaluationReport JSONs")
    p.add_argument("--baseline-name", default="baseline",
                   help="Which report (by filename stem prefix) is the baseline")
    p.add_argument("--n-resamples", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not args.reports_dir.is_dir():
        raise SystemExit(f"reports-dir not found: {args.reports_dir}")

    report_paths = sorted(args.reports_dir.glob("*-report.json"))
    if not report_paths:
        raise SystemExit(f"no *-report.json files in {args.reports_dir}")

    # Find baseline
    baseline_path = None
    for p_ in report_paths:
        if p_.stem.startswith(args.baseline_name):
            baseline_path = p_
            break
    if baseline_path is None:
        raise SystemExit(
            f"baseline report not found in {args.reports_dir} "
            f"(looking for files starting with '{args.baseline_name}-')"
        )

    print(f"[paired_delta] baseline: {baseline_path.name}")
    baseline_report = _load_report(baseline_path)
    baseline_cases = _key_by_window(baseline_report)
    print(f"[paired_delta] baseline cases: {len(baseline_cases)}")

    results: list[dict] = []
    for p_ in report_paths:
        if p_ == baseline_path:
            continue
        cell = p_.stem.removesuffix("-report")
        print(f"\n[paired_delta] vs {cell} ...")
        tr_report = _load_report(p_)
        tr_cases = _key_by_window(tr_report)
        delta = paired_bootstrap_delta(
            baseline_cases, tr_cases,
            n_resamples=args.n_resamples,
            seed=args.seed,
            confidence=args.confidence,
        )
        h1 = delta.get("hit_at_1", {})
        h5 = delta.get("hit_at_5", {})
        mrr = delta.get("mrr", {})
        print(f"  Δ Hit@1: {h1.get('point'):+.4f}  "
              f"[{h1.get('ci_lo'):+.4f}, {h1.get('ci_hi'):+.4f}]  "
              f"p={h1.get('p_value'):.3f}")
        print(f"  Δ Hit@5: {h5.get('point'):+.4f}  "
              f"[{h5.get('ci_lo'):+.4f}, {h5.get('ci_hi'):+.4f}]  "
              f"p={h5.get('p_value'):.3f}")
        print(f"  Δ MRR:   {mrr.get('point'):+.4f}  "
              f"[{mrr.get('ci_lo'):+.4f}, {mrr.get('ci_hi'):+.4f}]  "
              f"p={mrr.get('p_value'):.3f}")
        results.append({"cell": cell, "delta": delta})

    # Markdown summary
    print()
    print("=" * 105)
    print(f"  RQ-B3 paired-delta CIs (vs {args.baseline_name})")
    print("=" * 105)
    print(f"{'cell':<35} {'Δ Hit@1':>10} {'CI Hit@1':>22} {'p':>6} {'Δ MRR':>10}")
    print("-" * 105)
    for r in results:
        h1 = r["delta"].get("hit_at_1", {})
        mrr = r["delta"].get("mrr", {})
        if h1.get('point') is None:
            continue
        ci_str = f"[{h1['ci_lo']:+.4f},{h1['ci_hi']:+.4f}]"
        print(f"{r['cell']:<35} {h1['point']:>+10.4f} {ci_str:>22} {h1['p_value']:>6.3f} {mrr.get('point', 0):>+10.4f}")
    print("=" * 105)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "baseline_path": str(baseline_path),
            "n_baseline_cases": len(baseline_cases),
            "n_resamples": args.n_resamples,
            "seed": args.seed,
            "confidence": args.confidence,
            "results": results,
        }, indent=2), encoding="utf-8")
        print(f"\n[paired_delta] wrote JSON -> {args.output}")


if __name__ == "__main__":
    main()
