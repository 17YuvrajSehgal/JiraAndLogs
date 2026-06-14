"""Per-window cost breakdown for the agent.

Aggregates three sources into a single per-window cost record:
  1. Agent traces — `data/agent_traces/<exp>/<window_id>.json` — per-skill
     duration_ms + LLM tokens from `SkillCallCost`.
  2. LLM telemetry — `data/llm_telemetry/<exp>.jsonl` — every LLM call with
     prompt_tokens + completion_tokens + model + backend.
  3. Per-pipeline counterfactual costs — predictions JSONLs carry
     `pipeline_predict_seconds_per_window` from the §1 patch.

The output is the evidence for RQ-B1 (agent vs always-everything) and
feeds RQ-B2 (Hit@K vs $cost Pareto).

Schema (output): see `_emit_summary` below.

Usage:
    PYTHONPATH=src python scripts/agent/cost_breakdown.py \\
        --traces data/agent_traces/smoke-<dataset_id> \\
        --predictions data/derived/global/<dataset_id>/comparison/v2*/per-window-predictions.jsonl \\
        --llm-telemetry data/llm_telemetry/<experiment>.jsonl \\
        --output data/agent_runs/<dataset>-cost-breakdown.json
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


# Skill cost classes per AGENTIC-SYSTEM.md §5.1. Used to map skill names
# to default cost categories when telemetry doesn't carry one explicitly.
_DEFAULT_COST_CLASS = {
    "triage_numeric":            "cheap",
    "retrieve_dense":            "cheap",
    "retrieve_log_sequence":     "medium",
    "retrieve_hybrid_fusion":    "medium",
    "retrieve_hybrid_fusion_llm":"medium",
    "retrieve_knowledge_graph":  "medium",
    "verify_with_llm":           "expensive_llm",
    "reformulate_query":         "expensive_llm",
    "extract_entities_llm":      "expensive_llm",
    "compose_l2":                "cheap",
    "compose_triage":            "cheap",
    "compose_novelty":           "cheap",
}


def _read_traces(traces_dir: Path) -> list[dict]:
    """One dict per window with the per-skill cost rollup."""
    out = []
    for f in sorted(traces_dir.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        wid = t.get("bundle_id") or t.get("window_id") or f.stem
        per_skill_ms: dict[str, float] = defaultdict(float)
        per_skill_n: Counter = Counter()
        n_llm_calls = 0
        total_tokens = 0
        for e in t.get("events", []):
            if e.get("kind") == "skill_end":
                skill = e.get("skill") or ""
                if not skill:
                    continue
                dur = float(e.get("duration_ms") or 0.0)
                per_skill_ms[skill] += dur
                per_skill_n[skill] += 1
                # LLM cost is on output.cost if recorded
                output = e.get("output") or {}
                cost = output.get("cost") or {}
                n_llm_calls += int(cost.get("n_calls", 0))
                total_tokens += int(cost.get("llm_tokens", 0))
        out.append({
            "window_id": wid,
            "plan_id": t.get("plan_id"),
            "skills_invoked": list(per_skill_n.keys()),
            "per_skill_ms": dict(per_skill_ms),
            "per_skill_n": dict(per_skill_n),
            "total_wall_ms": sum(per_skill_ms.values()),
            "n_llm_calls": n_llm_calls,
            "total_tokens": total_tokens,
        })
    return out


def _read_predictions(paths: list[str]) -> dict[str, dict[str, float]]:
    """Read every pipeline's predictions.jsonl, collect per-window
    `pipeline_predict_seconds_per_window` keyed by pipeline_name.

    Output: {window_id: {pipeline_name: seconds}}
    """
    per_window: dict[str, dict[str, float]] = defaultdict(dict)
    for path_glob in paths:
        for p in glob.glob(path_glob):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    wid = r.get("window_id")
                    pipe = r.get("pipeline_name")
                    sec = r.get("pipeline_predict_seconds_per_window")
                    if wid and pipe and sec is not None:
                        per_window[wid][pipe] = float(sec)
    return per_window


def _counterfactual_cost(
    per_window_pipes: dict[str, dict[str, float]],
) -> float:
    """Mean per-window 'if every pipeline always ran' cost in seconds."""
    if not per_window_pipes:
        return 0.0
    totals = [sum(d.values()) for d in per_window_pipes.values()]
    return statistics.fmean(totals)


def _emit_summary(
    *,
    traces: list[dict],
    counterfactual_seconds_per_window: float,
    output_path: Path,
) -> None:
    n = len(traces)
    if n == 0:
        print("ERROR: no traces found", file=sys.stderr)
        sys.exit(2)

    # Per-window distributions
    agent_ms = [t["total_wall_ms"] for t in traces]
    n_skill_calls = [sum(t["per_skill_n"].values()) for t in traces]
    n_llm_calls = [t["n_llm_calls"] for t in traces]
    tokens = [t["total_tokens"] for t in traces]

    def _pct(xs, p):
        xs_sorted = sorted(xs)
        if not xs_sorted: return 0.0
        idx = max(0, min(len(xs_sorted) - 1, int(p * (len(xs_sorted) - 1))))
        return float(xs_sorted[idx])

    def _stats(xs):
        if not xs:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "mean": float(statistics.fmean(xs)),
            "p50":  float(statistics.median(xs)),
            "p95":  _pct(xs, 0.95),
            "max":  float(max(xs)),
        }

    # Per-skill aggregate
    per_skill_n: Counter = Counter()
    per_skill_ms_total: dict[str, float] = defaultdict(float)
    plan_id_counts: Counter = Counter()
    for t in traces:
        for skill, n_calls in t["per_skill_n"].items():
            per_skill_n[skill] += n_calls
        for skill, ms in t["per_skill_ms"].items():
            per_skill_ms_total[skill] += ms
        if t["plan_id"]:
            plan_id_counts[t["plan_id"]] += 1

    per_skill = {}
    for skill, total_n in per_skill_n.most_common():
        total_ms = per_skill_ms_total[skill]
        per_skill[skill] = {
            "n_invocations": int(total_n),
            "mean_ms":       round(total_ms / max(total_n, 1), 4),
            "total_ms":      round(total_ms, 2),
            "n_windows_used": int(total_n),
            "cost_class": _DEFAULT_COST_CLASS.get(skill, "unknown"),
        }

    # Savings vs counterfactual
    agent_mean_seconds = statistics.fmean(agent_ms) / 1000.0 if agent_ms else 0.0
    savings_pct_seconds = (
        100.0 * (1.0 - agent_mean_seconds / counterfactual_seconds_per_window)
        if counterfactual_seconds_per_window > 0 else None
    )

    out = {
        "n_windows": n,
        "n_distinct_plan_ids": len(plan_id_counts),
        "plan_id_distribution": dict(plan_id_counts.most_common()),
        "per_window_distribution": {
            "agent_total_wall_ms":     _stats(agent_ms),
            "agent_n_skill_calls":     _stats(n_skill_calls),
            "agent_n_llm_calls":       _stats(n_llm_calls),
            "agent_total_tokens":      _stats(tokens),
        },
        "per_skill": per_skill,
        "counterfactual": {
            "cascade_always_seconds_per_window_mean": counterfactual_seconds_per_window,
            "agent_seconds_per_window_mean":          agent_mean_seconds,
            "savings_pct_seconds":                    savings_pct_seconds,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    # Print a human-readable summary
    print(f"\n[cost_breakdown] wrote -> {output_path}")
    print(f"  n_windows: {n}")
    print(f"  n_distinct_plan_ids: {len(plan_id_counts)}")
    print(f"  agent mean wall: {agent_mean_seconds*1000:.2f} ms ({agent_mean_seconds:.4f} s)")
    print(f"  counterfactual mean wall: {counterfactual_seconds_per_window*1000:.2f} ms")
    if savings_pct_seconds is not None:
        print(f"  wall-time savings: {savings_pct_seconds:+.1f}%")
    print(f"\n  Per-skill invocation count (top 12):")
    for skill, info in list(per_skill.items())[:12]:
        print(f"    {skill:<32} n={info['n_invocations']:>5d}  "
              f"mean={info['mean_ms']:>6.2f} ms  "
              f"cost={info['cost_class']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--traces", type=Path, required=True,
                   help="Per-experiment traces dir, e.g. "
                        "data/agent_traces/smoke-<dataset_id>")
    p.add_argument("--predictions", nargs="*", default=[],
                   help="Glob(s) of per-pipeline predictions.jsonl files. "
                        "Used to compute the counterfactual cost.")
    p.add_argument("--llm-telemetry", type=Path, default=None,
                   help="Optional per-experiment LLM telemetry JSONL")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    if not args.traces.is_dir():
        raise SystemExit(f"missing traces dir: {args.traces}")

    traces = _read_traces(args.traces)
    if not traces:
        raise SystemExit(f"no traces in {args.traces}")

    per_window_pipes = _read_predictions(args.predictions)
    counterfactual = _counterfactual_cost(per_window_pipes)

    _emit_summary(
        traces=traces,
        counterfactual_seconds_per_window=counterfactual,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
