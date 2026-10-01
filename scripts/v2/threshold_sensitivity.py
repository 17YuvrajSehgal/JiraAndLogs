"""Escalation-threshold sensitivity — answers R2's "how is 0.5 determined?".

R2 asked what `MAXCONF(R)` measures and how its 0.5 threshold was chosen, and
noted that if it were the fused RRF score of Eq. 2 the comparison would be
meaningless (that score tops out near 3/61 = 0.049). It is not: it is the maximum
over retrievers of each retriever's own calibrated ticket-worthiness probability
in [0,1] (`src/agent/controller/rule.py::make_reformulation_gate`).

The paper asserted the thresholds were reasonable but never showed what happens
at other values. This sweeps the escalation threshold over the realized
confidence distribution and reports, at each setting, both what it costs
(fraction of windows escalated) and what it buys (Hit@5), using the per-window
counterfactual from build_escalation_value_set.py.

SCOPE -- read this before quoting the numbers. The shipped controller has TWO
gates, not one: an escalation gate (numeric triage < 0.90, or the dense
retriever returning nothing) that schedules the sparse/graph fusion, and a
reformulation gate (maxconf < 0.5) that schedules query rewriting. On a
text-only corpus the first has no numeric signal to read, so it opens on
essentially every window -- which is why `retrieve_hybrid_fusion` fires on 99.9%
of WoL windows while `reformulate_query` fires on 21%.

This sweep models a single UNIFIED threshold: take the expensive path when the
cheap path's confidence falls below t. That is the counterfactual our ablation
cells actually support (dense_only vs baseline), and it is the design a
revised controller would use, but it is not identical to either shipped gate.
Escalation rates here are therefore not directly comparable to the per-skill
invocation rates reported in the cost breakdown.

Usage
-----
    python scripts/v2/threshold_sensitivity.py \
        --escalation paper-results-v2/escalation --out paper-results-v2/escalation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("evaluable"):
                rows.append(d)
    return rows


def sweep(rows: list[dict], thresholds) -> list[dict]:
    """Escalate a window when its cheap-path confidence is BELOW the threshold.

    That is the shipped gate's rule: low confidence means the cheap answer is
    not trusted, so pay for the expensive path.
    """
    conf = np.array([float(r.get("cheap_confidence") or 0.0) for r in rows])
    cheap = np.array([r["cheap_hit_at_5"] for r in rows], dtype=float)
    esc = np.array([r["escalated_hit_at_5"] for r in rows], dtype=float)
    out = []
    for t in thresholds:
        take = conf < t
        out.append({
            "threshold": float(t),
            "escalation_rate": float(take.mean()),
            "hit_at_5": float(np.where(take, esc, cheap).mean()),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escalation", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--datasets", nargs="+",
                    default=["wol-v3", "online-boutique", "otel-demo"])
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    report = {}
    for ds in args.datasets:
        p = args.escalation / f"escalation-value-{ds}.jsonl"
        if not p.exists():
            continue
        rows = load(p)
        if not rows:
            continue
        conf = np.array([float(r.get("cheap_confidence") or 0.0) for r in rows])
        qs = {f"p{q}": float(np.percentile(conf, q)) for q in (0, 5, 25, 50, 75, 95, 100)}
        print(f"\n=== {ds} (n={len(rows):,} evaluable) ===")
        print("  realized cheap-path confidence: "
              + "  ".join(f"{k}={v:.3f}" for k, v in qs.items()))

        grid = sorted(set(
            [0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0]
            + [round(float(np.percentile(conf, q)), 4) for q in (5, 25, 50, 75, 95)]
        ))
        curve = sweep(rows, grid)
        never = float(np.mean([r["cheap_hit_at_5"] for r in rows]))
        always = float(np.mean([r["escalated_hit_at_5"] for r in rows]))

        print(f"  never-escalate Hit@5={never:.4f}   always-escalate={always:.4f}")
        print(f"\n  {'threshold':>10}{'escalated':>12}{'Hit@5':>10}   note")
        shipped = next((c for c in curve if abs(c["threshold"] - 0.5) < 1e-9), None)
        # Cheapest threshold that still reaches always-escalate accuracy.
        knee = next((c for c in curve if c["hit_at_5"] >= always - 1e-4), None)
        for c in curve:
            note = []
            if shipped and c is shipped:
                note.append("<- 0.5, the shipped reformulation-gate value")
            if knee and c is knee:
                note.append("<- cheapest threshold matching always-escalate")
            print(f"  {c['threshold']:>10.3f}{c['escalation_rate']:>11.1%}"
                  f"{c['hit_at_5']:>10.4f}   {' '.join(note)}")

        if shipped and knee:
            print(f"\n  shipped 0.5 escalates {shipped['escalation_rate']:.1%} "
                  f"for Hit@5 {shipped['hit_at_5']:.4f}; threshold "
                  f"{knee['threshold']:.3f} reaches {knee['hit_at_5']:.4f} at "
                  f"{knee['escalation_rate']:.1%}.")
        report[ds] = {
            "n": len(rows), "confidence_percentiles": qs,
            "never_escalate_hit5": never, "always_escalate_hit5": always,
            "curve": curve,
            "shipped_threshold_0.5": shipped,
            "cheapest_matching_always": knee,
        }

    dest = args.out / "threshold-sensitivity.json"
    dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
