"""Cost-vs-cascade baseline — RQ-A2 / B1 / B2 closure.

Where the cascade ALWAYS invokes every skill on every window, the
agent's controller emits a Plan that gates expensive skills behind
the cheap-path consensus check. RQ-A2's headline claim is that
this adaptive selection cuts cost (LLM calls, $cost, wall) without
losing accuracy.

This script measures **what the gates actually saved** by reading
the per-window traces from a smoke run and counting:

  - n_skill_invocations_actual  — skills that emitted skill_end
  - n_skill_invocations_baseline — skills that would have run if
    every gate had returned True (= count of all SkillInvocation
    entries in the plan)
  - per_window_savings = baseline - actual

The cascade-counterfactual cost layers on top: assuming a fixed
per-skill cost (loaded from agent-config-like config), we estimate
$cost / LLM-tokens saved per window. v1 uses a conservative cost
table (Diagnosis Agent ~15s wall, ~1969 tokens per call per Mode 3
§3.5 §3.9 telemetry).

Usage:
    PYTHONPATH=src python scripts/agent/cost_vs_cascade.py \\
        --trace-root data/agent_runs/v6/traces/smoke-2026-05-25-... \\
        --output results/ob/4.5-cost-vs-cascade/breakdown.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median, quantiles
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


log = logging.getLogger(__name__)


# Per-skill cost model — conservative LLM rates per Mode 3 telemetry
# + cheap-skill wall times from the §3.5 v5 run. The point is to
# give a defensible counterfactual; not to claim exact $cost.
# Values: (mean_wall_ms, mean_llm_tokens, usd_per_call)
PER_SKILL_COST: dict[str, tuple[float, int, float]] = {
    # Cheap (predictions-backed or pure computation)
    "triage_numeric":                (1.0,    0, 0.0),
    "retrieve_dense":                (1.0,    0, 0.0),
    "retrieve_log_sequence":         (1.0,    0, 0.0),
    "retrieve_hybrid_fusion":        (1.0,    0, 0.0),
    "retrieve_hybrid_fusion_llm":    (1.0,    0, 0.0),
    "retrieve_knowledge_graph":      (1.0,    0, 0.0),
    "compose_l2":                    (0.5,    0, 0.0),
    "compose_triage":                (0.5,    0, 0.0),
    "compose_novelty":               (0.5,    0, 0.0),
    # Expensive LLM-backed (or potentially so)
    "verify_with_llm":               (15400.0, 1969, 0.00050),   # Mode 3 §3.9 telemetry
    "reformulate_query":             (300.0,    400, 0.00010),    # estimated
    "extract_entities_llm":          (8000.0,  1500, 0.00040),    # KG extractor
    # ReAct tools (data lake reads — wall a few ms, no LLM)
    "request_pod_events":            (5.0,     0, 0.0),
    "request_extended_trace_window": (10.0,    0, 0.0),
    "request_pod_metrics":           (5.0,     0, 0.0),
    "request_similar_incident_window": (3.0,   0, 0.0),
    "rerank_with_evidence":          (1.0,     0, 0.0),
}


def _cost_for(skill_name: str) -> tuple[float, int, float]:
    return PER_SKILL_COST.get(skill_name, (1.0, 0, 0.0))


def _aggregate_per_window(trace_dir: Path) -> dict[str, Any]:
    """Walk every per-window trace; emit aggregated cost stats."""
    n_traces = 0
    per_window_rows: list[dict] = []

    for tf in sorted(trace_dir.rglob("*.json")):
        try:
            with open(tf, encoding="utf-8") as f:
                trace = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("skipping unreadable trace %s: %s", tf, e)
            continue
        n_traces += 1

        invoked: list[str] = []
        skipped: list[str] = []
        for ev in trace.get("events") or []:
            kind = ev.get("kind")
            skill = ev.get("skill")
            if not skill:
                continue
            if kind == "skill_end":
                invoked.append(skill)
            elif kind == "skill_skipped_by_gate":
                skipped.append(skill)

        # Counterfactual: every gated skill would have run too
        counterfactual = invoked + skipped

        actual_wall = sum(_cost_for(s)[0] for s in invoked)
        actual_tokens = sum(_cost_for(s)[1] for s in invoked)
        actual_usd = sum(_cost_for(s)[2] for s in invoked)

        cf_wall = sum(_cost_for(s)[0] for s in counterfactual)
        cf_tokens = sum(_cost_for(s)[1] for s in counterfactual)
        cf_usd = sum(_cost_for(s)[2] for s in counterfactual)

        per_window_rows.append({
            "window_id": trace.get("bundle_id") or tf.stem,
            "plan_id": trace.get("plan_id"),
            "n_invoked": len(invoked),
            "n_skipped_by_gate": len(skipped),
            "actual_wall_ms": actual_wall,
            "actual_tokens": actual_tokens,
            "actual_usd": actual_usd,
            "counterfactual_wall_ms": cf_wall,
            "counterfactual_tokens": cf_tokens,
            "counterfactual_usd": cf_usd,
            "savings_wall_ms": cf_wall - actual_wall,
            "savings_tokens": cf_tokens - actual_tokens,
            "savings_usd": cf_usd - actual_usd,
        })

    return {"n_traces": n_traces, "rows": per_window_rows}


def _summarise(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n_windows": 0}

    def _stats(key: str) -> dict[str, float]:
        vals = [r[key] for r in rows]
        if all(v == 0 for v in vals):
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "total": 0.0}
        quants = quantiles(vals, n=100) if len(vals) >= 100 else None
        return {
            "mean": round(mean(vals), 4),
            "median": round(median(vals), 4),
            "p95": round(quants[94], 4) if quants else round(max(vals), 4),
            "max": round(max(vals), 4),
            "total": round(sum(vals), 4),
        }

    total_actual_wall = sum(r["actual_wall_ms"] for r in rows)
    total_cf_wall = sum(r["counterfactual_wall_ms"] for r in rows)
    total_actual_tokens = sum(r["actual_tokens"] for r in rows)
    total_cf_tokens = sum(r["counterfactual_tokens"] for r in rows)
    total_actual_usd = sum(r["actual_usd"] for r in rows)
    total_cf_usd = sum(r["counterfactual_usd"] for r in rows)

    wall_savings_pct = (
        100.0 * (total_cf_wall - total_actual_wall) / total_cf_wall
        if total_cf_wall else 0.0
    )
    tokens_savings_pct = (
        100.0 * (total_cf_tokens - total_actual_tokens) / total_cf_tokens
        if total_cf_tokens else 0.0
    )
    usd_savings_pct = (
        100.0 * (total_cf_usd - total_actual_usd) / total_cf_usd
        if total_cf_usd else 0.0
    )

    # Per-skill invocation counts
    skill_inv_counts = Counter()
    skill_skip_counts = Counter()
    for r in rows:
        # We re-derive from row would require trace; just count what we have
        pass

    return {
        "n_windows": n,
        "actual_wall_ms": _stats("actual_wall_ms"),
        "counterfactual_wall_ms": _stats("counterfactual_wall_ms"),
        "savings_wall_ms": _stats("savings_wall_ms"),
        "actual_tokens": _stats("actual_tokens"),
        "counterfactual_tokens": _stats("counterfactual_tokens"),
        "savings_tokens": _stats("savings_tokens"),
        "actual_usd": _stats("actual_usd"),
        "counterfactual_usd": _stats("counterfactual_usd"),
        "savings_usd": _stats("savings_usd"),
        "totals": {
            "actual_wall_seconds": round(total_actual_wall / 1000.0, 3),
            "cascade_wall_seconds": round(total_cf_wall / 1000.0, 3),
            "actual_llm_tokens": int(total_actual_tokens),
            "cascade_llm_tokens": int(total_cf_tokens),
            "actual_usd": round(total_actual_usd, 4),
            "cascade_usd": round(total_cf_usd, 4),
        },
        "savings_pct": {
            "wall": round(wall_savings_pct, 2),
            "tokens": round(tokens_savings_pct, 2),
            "usd": round(usd_savings_pct, 2),
        },
    }


def _per_skill_breakdown(trace_dir: Path) -> dict[str, dict[str, int]]:
    """Per-skill invoked/skipped counts across all traces."""
    invoked = Counter()
    skipped = Counter()
    for tf in trace_dir.rglob("*.json"):
        with open(tf, encoding="utf-8") as f:
            trace = json.load(f)
        for ev in trace.get("events") or []:
            skill = ev.get("skill")
            kind = ev.get("kind")
            if not skill:
                continue
            if kind == "skill_end":
                invoked[skill] += 1
            elif kind == "skill_skipped_by_gate":
                skipped[skill] += 1

    breakdown = {}
    for skill in sorted(set(invoked) | set(skipped)):
        breakdown[skill] = {
            "invoked": invoked.get(skill, 0),
            "skipped_by_gate": skipped.get(skill, 0),
            "would_have_run": invoked.get(skill, 0) + skipped.get(skill, 0),
            "save_rate_pct": round(
                100.0 * skipped.get(skill, 0)
                / (invoked.get(skill, 0) + skipped.get(skill, 0))
                if (invoked.get(skill, 0) + skipped.get(skill, 0)) > 0 else 0.0,
                2,
            ),
        }
    return breakdown


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace-root", type=Path, required=True,
                   help="Trace directory (e.g. data/agent_runs/v6/traces/smoke-...)")
    p.add_argument("--output", type=Path, default=None,
                   help="Write JSON breakdown here")
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

    if not args.trace_root.is_dir():
        raise SystemExit(f"trace root not found: {args.trace_root}")

    agg = _aggregate_per_window(args.trace_root)
    summary = _summarise(agg["rows"])
    per_skill = _per_skill_breakdown(args.trace_root)

    # Write the JSON FIRST so a pretty-print formatting bug can never prevent
    # the result file from being produced.
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "trace_root": str(args.trace_root),
            "summary": summary,
            "per_skill": per_skill,
        }, indent=2), encoding="utf-8")
        print(f"[cost_vs_cascade] wrote JSON -> {args.output}")

    # Human-readable summary — best-effort (never fatal; JSON is already written).
    try:
        print("=" * 80)
        print("  RQ-A2 / B1 / B2 — cost vs cascade-counterfactual")
        print(f"  Trace root: {args.trace_root}   n_windows: {summary.get('n_windows')}")
        for k in ("actual_wall_ms", "counterfactual_wall_ms", "savings_wall_ms"):
            s = summary.get(k)
            if isinstance(s, dict):
                print(f"    {k:<24} mean={s.get('mean')} median={s.get('median')} p95={s.get('p95')}")
        if isinstance(summary.get("totals"), dict):
            print(f"    totals: {summary['totals']}")
        if isinstance(summary.get("savings_pct"), dict):
            print(f"    savings_pct: {summary['savings_pct']}")
        print("  Per-skill gate-save rates:")
        for skill, counts in sorted(per_skill.items(), key=lambda x: -x[1].get("save_rate_pct", 0)):
            if counts.get("would_have_run", 0) == 0:
                continue
            print(f"    {skill:<35} invoked={counts.get('invoked')} "
                  f"gated={counts.get('skipped_by_gate')} save={counts.get('save_rate_pct')}%")
        print("=" * 80)
    except Exception as e:                                            # noqa: BLE001
        print(f"[cost_vs_cascade] (summary print skipped: {e})")


if __name__ == "__main__":
    main()
