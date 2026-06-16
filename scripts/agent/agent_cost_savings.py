"""RQ-B3 — counterfactual cost-savings analysis.

The agent's headline operational claim: "adaptive invocation cuts LLM
inference cost without losing accuracy". This script computes the
counterfactual:

  saved_seconds_per_window = sum over skills NOT invoked by the agent
                              of pipeline_predict_seconds_per_window

So for each window we identify which skills the AGENT skipped (via
capability gates, escalation gates, or verifier calibration), and
multiply by the cascade-side cost per skill per window (recorded by
the runner patch in this same commit series).

Inputs:
  - An EvaluationReport JSON with case_results (the agent's smoke
    output, includes decision.skills_invoked per case).
  - The cascade's per-window-predictions JSONLs (each row has
    `pipeline_predict_seconds_per_window`).

Outputs:
  - Per-skill skip counts + skip rate
  - Per-window saved-seconds distribution
  - Total saved-seconds across the run vs always-on baseline cost

Usage:
    PYTHONPATH=src python scripts/agent/agent_cost_savings.py \\
        --eval-report data/agent_runs/ob-smoke.json \\
        --cascade-predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \\
        --pipeline-jsonl-glob 'data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2*/per-window-predictions.jsonl' \\
        --output data/agent_runs/ob-cost-savings.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# Mapping from cascade pipeline_name → agent skill name. The agent's
# `skills_invoked` uses agent-side names (retrieve_dense, etc.); the
# cascade JSONLs use pipeline_name. This bridges them so we can
# multiply skip rate × cascade cost correctly.
PIPELINE_TO_AGENT_SKILL = {
    "hist_gradient_boosting_numeric":     "triage_numeric",
    "bi_encoder_retrieval":               "retrieve_dense",
    "logseq2vec_retrieval_pretrained":    "retrieve_log_sequence",
    "logseq2vec_retrieval":               "retrieve_log_sequence",
    "hybrid_rrf_retrieval":               "retrieve_hybrid_fusion",
    "hybrid_rrf_retrieval_rule":          "retrieve_hybrid_fusion",
    "hybrid_rrf_retrieval_llm":           "retrieve_hybrid_fusion_llm",
    "kg_retrieval_rulebased":             "retrieve_knowledge_graph",
    "kg_retrieval":                       "retrieve_knowledge_graph",
    "diagnosis_agent":                    "verify_with_llm",
}


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_cascade_costs(jsonl_paths: list[Path]) -> dict[str, float]:
    """Return agent_skill_name → mean per-window predict cost from
    cascade predictions."""
    costs: dict[str, list[float]] = defaultdict(list)
    for path in jsonl_paths:
        for row in _iter_jsonl(path):
            pname = row.get("pipeline_name")
            cost = row.get("pipeline_predict_seconds_per_window")
            if pname is None or cost is None:
                continue
            agent_skill = PIPELINE_TO_AGENT_SKILL.get(pname)
            if agent_skill is None:
                continue
            costs[agent_skill].append(float(cost))

    out: dict[str, float] = {}
    for skill, vals in costs.items():
        if vals:
            out[skill] = statistics.mean(vals)
    return out


def _all_agent_skills() -> list[str]:
    return list(set(PIPELINE_TO_AGENT_SKILL.values()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--eval-report", type=Path, required=True,
                   help="agent smoke / eval JSON with case_results")
    p.add_argument("--pipeline-jsonls", type=Path, nargs="+", required=True,
                   help="cascade per-window-predictions JSONLs")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"[cost_savings] loading agent eval from {args.eval_report}")
    eval_report = json.loads(args.eval_report.read_text(encoding="utf-8"))
    cases = eval_report.get("case_results") or []
    if not cases:
        raise SystemExit("eval report has no case_results — re-run smoke with "
                         "include_case_results=True")
    print(f"[cost_savings] {len(cases)} agent cases")

    print(f"[cost_savings] loading cascade costs from "
          f"{len(args.pipeline_jsonls)} JSONLs")
    skill_costs = _load_cascade_costs(args.pipeline_jsonls)
    if not skill_costs:
        raise SystemExit("no pipeline_predict_seconds_per_window fields found in "
                         "the supplied cascade JSONLs — they may predate the "
                         "Phase 1 patch. Re-run the cascade.")
    print(f"[cost_savings] cascade per-window costs (seconds):")
    for skill, cost in sorted(skill_costs.items(), key=lambda kv: -kv[1]):
        print(f"    {skill:<28} {cost*1000:>8.2f} ms")

    # ----- For each case, identify skipped skills + savings
    all_skills = set(skill_costs.keys())
    n_cases = len(cases)
    skip_counts: dict[str, int] = defaultdict(int)
    invoke_counts: dict[str, int] = defaultdict(int)
    saved_per_window: list[float] = []
    always_on_per_window: list[float] = []

    for c in cases:
        invoked = set(c.get("decision", {}).get("skills_invoked") or [])
        skipped = all_skills - invoked
        for s in invoked:
            invoke_counts[s] += 1
        for s in skipped:
            skip_counts[s] += 1
        saved = sum(skill_costs.get(s, 0.0) for s in skipped)
        always_on = sum(skill_costs.values())
        saved_per_window.append(saved)
        always_on_per_window.append(always_on)

    # ----- Aggregate
    mean_saved = statistics.mean(saved_per_window) if saved_per_window else 0.0
    median_saved = statistics.median(saved_per_window) if saved_per_window else 0.0
    mean_always_on = (
        statistics.mean(always_on_per_window) if always_on_per_window else 0.0
    )
    pct_saved = (mean_saved / mean_always_on * 100) if mean_always_on > 0 else 0.0

    skip_rates = {
        s: skip_counts[s] / n_cases for s in all_skills
    }

    # ----- Print
    print()
    print("=" * 80)
    print(f"  Agent cost savings (counterfactual) — RQ-B3")
    print("=" * 80)
    print(f"  n_cases:             {n_cases}")
    print(f"  always-on baseline:  {mean_always_on*1000:.2f} ms/window mean")
    print(f"  agent (gated):       {(mean_always_on - mean_saved)*1000:.2f} ms/window mean")
    print(f"  saved per window:    {mean_saved*1000:.2f} ms (mean), "
          f"{median_saved*1000:.2f} ms (median)")
    print(f"  saved %:             {pct_saved:.1f}%")
    print(f"  total saved:         {sum(saved_per_window):.2f} s "
          f"across {n_cases} windows")
    print()
    print(f"  Per-skill skip rates:")
    print(f"    {'skill':<28} {'skip%':>7} {'cost/win':>10} {'saved/win':>11}")
    print("    " + "-" * 60)
    for s in sorted(all_skills, key=lambda x: -skip_rates[x] * skill_costs[x]):
        sr = skip_rates[s]
        c = skill_costs[s]
        contrib = sr * c
        print(f"    {s:<28} {sr*100:>6.1f}% {c*1000:>9.2f}ms {contrib*1000:>10.2f}ms")
    print("=" * 80)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "n_cases": n_cases,
            "skill_costs_seconds": skill_costs,
            "skip_counts": dict(skip_counts),
            "invoke_counts": dict(invoke_counts),
            "skip_rates": skip_rates,
            "mean_always_on_seconds": mean_always_on,
            "mean_saved_seconds": mean_saved,
            "median_saved_seconds": median_saved,
            "saved_pct": pct_saved,
            "total_saved_seconds": sum(saved_per_window),
        }, indent=2), encoding="utf-8")
        print(f"\n[cost_savings] wrote -> {args.output}")


if __name__ == "__main__":
    main()
