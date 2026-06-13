"""RQ-C3 / RQ-A9 — per-window latency + cost summary.

Reads one or more EvaluationReport JSONs and aggregates
`decision.cost` (a SkillCallCost: llm_tokens, wall_seconds, usd, n_calls)
across all cases. Reports the distribution that lands in the paper's
cost table:

  - mean / median / p95 / max per-window wall_seconds
  - mean per-window llm_tokens, usd, n_calls
  - per-skill invocation frequency (how often each skill fires)
  - cache hit rate (when available from `cache_hit_rate`)
  - total run cost (sum across cases)

The smokes don't currently set `trace_root`, so per-skill PER-WINDOW
cost breakdown isn't available — we report per-skill invocation
COUNTS (which skill fired on how many windows) instead. For per-skill
cost, persist traces with `--trace-root data/agent_traces/` and rerun.

Usage:
    PYTHONPATH=src python scripts/agent/cost_summary.py \\
        --reports data/agent_runs/ob-smoke-full.json \\
                  data/agent_runs/wol-smoke.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarise_one(report_dict: dict) -> dict:
    cases = report_dict.get("case_results") or []
    if not cases:
        return {"warning": "no case_results in report"}

    wall_seconds: list[float] = []
    llm_tokens: list[int] = []
    usd: list[float] = []
    n_calls: list[int] = []
    skill_invocation_counts: Counter = Counter()

    for c in cases:
        d = c.get("decision") or {}
        cost = d.get("cost") or {}
        wall_seconds.append(float(cost.get("wall_seconds", 0.0)))
        llm_tokens.append(int(cost.get("llm_tokens", 0)))
        usd.append(float(cost.get("usd", 0.0)))
        n_calls.append(int(cost.get("n_calls", 0)))
        for skill in (d.get("skills_invoked") or []):
            skill_invocation_counts[skill] += 1

    summary = {
        "n_cases": len(cases),
        "wall_seconds": {
            "mean": statistics.mean(wall_seconds),
            "median": statistics.median(wall_seconds),
            "p95": _quantile(wall_seconds, 0.95),
            "max": max(wall_seconds) if wall_seconds else 0.0,
            "total": sum(wall_seconds),
        },
        "llm_tokens": {
            "mean": statistics.mean(llm_tokens) if llm_tokens else 0.0,
            "max": max(llm_tokens) if llm_tokens else 0,
            "total": sum(llm_tokens),
        },
        "usd": {
            "mean": statistics.mean(usd) if usd else 0.0,
            "total": sum(usd),
        },
        "n_calls": {
            "mean": statistics.mean(n_calls) if n_calls else 0.0,
            "max": max(n_calls) if n_calls else 0,
            "total": sum(n_calls),
        },
        "skill_invocation_counts": dict(skill_invocation_counts),
        "skill_invocation_frequency": {
            s: round(c / len(cases), 4)
            for s, c in skill_invocation_counts.items()
        },
        "cache_hit_rate": report_dict.get("cache_hit_rate"),
    }
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, default=None,
                   help="combined summary JSON")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    combined: dict[str, dict] = {}
    for path in args.reports:
        if not path.exists():
            print(f"[cost_summary] skipping missing {path}")
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        name = d.get("name") or path.stem
        summary = _summarise_one(d)
        combined[name] = summary

        print()
        print("=" * 80)
        print(f"  Cost summary — {name}")
        print("=" * 80)
        if "warning" in summary:
            print(f"  {summary['warning']}")
            continue

        print(f"  n_cases:           {summary['n_cases']}")
        w = summary["wall_seconds"]
        print(f"  wall_seconds/window  "
              f"mean={w['mean']*1000:.3f}ms  "
              f"median={w['median']*1000:.3f}ms  "
              f"p95={w['p95']*1000:.3f}ms  "
              f"max={w['max']*1000:.3f}ms")
        print(f"  total wall          {w['total']:.3f}s")
        t = summary["llm_tokens"]
        if t["total"] > 0:
            print(f"  llm_tokens/window   mean={t['mean']:.1f}  max={t['max']}  total={t['total']}")
        u = summary["usd"]
        if u["total"] > 0:
            print(f"  usd/window          mean=${u['mean']:.6f}  total=${u['total']:.4f}")
        nc = summary["n_calls"]
        print(f"  skill_calls/window  mean={nc['mean']:.2f}  max={nc['max']}  total={nc['total']}")
        if summary.get("cache_hit_rate") is not None:
            print(f"  cache_hit_rate:    {summary['cache_hit_rate']:.3f}")

        # Skill invocation frequency
        print()
        print(f"  Per-skill invocation frequency:")
        sk_freq = summary["skill_invocation_frequency"]
        for skill in sorted(sk_freq, key=lambda s: -sk_freq[s]):
            count = summary["skill_invocation_counts"][skill]
            freq = sk_freq[skill]
            bar = "#" * int(freq * 30)
            print(f"    {skill:<26} {count:>5} ({freq*100:>5.1f}%)  {bar}")

    print("=" * 80)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(combined, indent=2, default=str),
                                encoding="utf-8")
        print(f"\n[cost_summary] wrote -> {args.output}")


if __name__ == "__main__":
    main()
