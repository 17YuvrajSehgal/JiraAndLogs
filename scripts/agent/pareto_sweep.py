"""Pareto sweep over `cheap_path_threshold` — RQ-B2 closure.

Sweeps the controller's `cheap_path_threshold` ∈ {0.50, 0.60, 0.70,
0.80, 0.90, 0.95}. At each setting, re-runs the harness and
collects (Hit@K, MRR, triage_accuracy, n_skill_invocations,
estimated $cost) — the data points for the Pareto plot.

Mechanism: the threshold controls when the cheap-path-escalation
gate considers triage_numeric's confidence "high enough" to skip
the expensive retrievers + verifier. Lower threshold = cheap path
closes the gate more easily = more skills get skipped = cheaper
but potentially lower Hit@K. Higher = stricter cheap-path criterion
= more skills fire = more expensive.

For each cell we report:
  - Hit@1 / Hit@5 / MRR / triage_accuracy
  - skill_calls_total + total_wall_seconds (from traces)
  - cost-counterfactual: $cost the cascade-always-on would have spent

Outputs a JSON with all cells + a Markdown table.

Usage:
    PYTHONPATH=src python scripts/agent/pareto_sweep.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --include-verifier \\
        --output results/ob/4.11-pareto-sweep/sweep.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders import (
    load_ob_cases, load_otel_demo_cases, load_wol_cases,
)
from agent.harness_builder import build_harness_for_dataset


_DATASET_LOADERS = {
    "ob": ("online_boutique", load_ob_cases),
    "otel_demo": ("otel_demo", load_otel_demo_cases),
    "wol": ("wol", load_wol_cases),
}


# Re-use the per-skill cost model from cost_vs_cascade.py.
# (Tuple of (mean_wall_ms, mean_llm_tokens, usd_per_call).)
PER_SKILL_COST: dict[str, tuple[float, int, float]] = {
    "triage_numeric":                (1.0,    0, 0.0),
    "retrieve_dense":                (1.0,    0, 0.0),
    "retrieve_log_sequence":         (1.0,    0, 0.0),
    "retrieve_hybrid_fusion":        (1.0,    0, 0.0),
    "retrieve_hybrid_fusion_llm":    (1.0,    0, 0.0),
    "retrieve_knowledge_graph":      (1.0,    0, 0.0),
    "compose_l2":                    (0.5,    0, 0.0),
    "compose_triage":                (0.5,    0, 0.0),
    "compose_novelty":               (0.5,    0, 0.0),
    "verify_with_llm":               (15400.0, 1969, 0.00050),
    "reformulate_query":             (300.0,    400, 0.00010),
    "extract_entities_llm":          (8000.0,  1500, 0.00040),
    "request_pod_events":            (5.0,     0, 0.0),
    "request_extended_trace_window": (10.0,    0, 0.0),
    "request_pod_metrics":           (5.0,     0, 0.0),
    "request_similar_incident_window": (3.0,   0, 0.0),
    "rerank_with_evidence":          (1.0,     0, 0.0),
}


def _aggregate_trace_cost(trace_dir: Path) -> dict[str, float | int]:
    """Walk traces; sum actual + counterfactual cost."""
    actual_wall = 0.0
    actual_tokens = 0
    actual_usd = 0.0
    cf_wall = 0.0
    cf_tokens = 0
    cf_usd = 0.0
    n_traces = 0

    for tf in trace_dir.glob("*.json"):
        try:
            with open(tf, encoding="utf-8") as f:
                trace = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        n_traces += 1
        for ev in trace.get("events") or []:
            skill = ev.get("skill")
            kind = ev.get("kind")
            if not skill or skill not in PER_SKILL_COST:
                continue
            wall, tokens, usd = PER_SKILL_COST[skill]
            if kind == "skill_end":
                actual_wall += wall
                actual_tokens += tokens
                actual_usd += usd
                cf_wall += wall
                cf_tokens += tokens
                cf_usd += usd
            elif kind == "skill_skipped_by_gate":
                cf_wall += wall
                cf_tokens += tokens
                cf_usd += usd
    return {
        "n_traces": n_traces,
        "actual_wall_seconds": round(actual_wall / 1000.0, 3),
        "cascade_wall_seconds": round(cf_wall / 1000.0, 3),
        "actual_llm_tokens": int(actual_tokens),
        "cascade_llm_tokens": int(cf_tokens),
        "actual_usd": round(actual_usd, 4),
        "cascade_usd": round(cf_usd, 4),
        "savings_pct_wall": round(
            100.0 * (cf_wall - actual_wall) / cf_wall, 2,
        ) if cf_wall else 0.0,
        "savings_pct_usd": round(
            100.0 * (cf_usd - actual_usd) / cf_usd, 2,
        ) if cf_usd else 0.0,
    }


def run_one_threshold(
    dataset: str,
    global_dir: Path,
    cases,
    threshold: float,
    *,
    use_state: bool,
    include_verifier: bool,
    trace_root: Path,
) -> dict:
    """Run the harness at one cheap_path_threshold setting."""
    dataset_label, _ = _DATASET_LOADERS[dataset]
    cell_trace_root = trace_root / f"th-{threshold:.2f}"
    harness, contract = build_harness_for_dataset(
        dataset_label=dataset_label,
        global_dir=global_dir,
        cache_dir=None,
        trace_root=cell_trace_root,
        skip=set(),
        include_verifier=include_verifier,
        use_state_layer=use_state,
        cheap_path_threshold=threshold,
        experiment_prefix="pareto",
    )
    t0 = time.monotonic()
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"pareto-th{threshold:.2f}-{global_dir.name}",
    )
    wall_sec = time.monotonic() - t0

    # Aggregate cost from the traces
    trace_subdir = cell_trace_root / f"pareto-{global_dir.name}"
    cost_breakdown = _aggregate_trace_cost(trace_subdir)

    return {
        "cheap_path_threshold": float(threshold),
        "n_cases": report.n_cases,
        "n_evaluable": report.n_evaluable_retrieval_cases,
        "hit_at_1": float(report.hit_at_1),
        "hit_at_5": float(report.hit_at_5),
        "hit_at_10": float(report.hit_at_10),
        "mrr": float(report.mrr),
        "triage_accuracy": float(report.triage_accuracy),
        "novel_recall": float(report.novel_recall),
        "novel_precision": float(report.novel_precision),
        "n_distinct_plan_ids": len(report.plan_ids_seen),
        "harness_wall_seconds": round(wall_sec, 3),
        **cost_breakdown,
    }


def format_table(rows: list[dict]) -> str:
    lines: list[str] = []
    lines.append("| threshold | Hit@1 | Hit@5 | MRR | Triage | $cost actual | $cost cascade | wall save % |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['cheap_path_threshold']:.2f} | "
            f"{r['hit_at_1']:.4f} | "
            f"{r['hit_at_5']:.4f} | "
            f"{r['mrr']:.4f} | "
            f"{r['triage_accuracy']:.4f} | "
            f"${r['actual_usd']:.4f} | "
            f"${r['cascade_usd']:.4f} | "
            f"{r['savings_pct_wall']:.1f}% |"
        )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(_DATASET_LOADERS), default="ob")
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--thresholds", type=str, default="0.50,0.60,0.70,0.80,0.90,0.95",
                   help="Comma-separated thresholds. Default sweeps the realistic operating range.")
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--use-state", action="store_true")
    p.add_argument("--include-verifier", action="store_true",
                   help="Register verify_with_llm. STRONGLY recommended for "
                        "the Pareto plot — the verifier's cost dominates the USD axis.")
    p.add_argument("--trace-dir", type=Path, default=Path("data/agent_runs/pareto-sweep"),
                   help="Root for per-cell trace dirs.")
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

    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    _, loader = _DATASET_LOADERS[args.dataset]

    print(f"[pareto] loading {args.dataset} cases from {args.global_dir} (split={args.split})")
    cases = loader(args.global_dir, split=args.split, limit=args.limit)
    print(f"[pareto] loaded {len(cases)} cases; {len(thresholds)} threshold cells")

    args.trace_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for i, th in enumerate(thresholds, 1):
        print(f"\n[pareto] {i:>2}/{len(thresholds)}  threshold={th:.2f} ...")
        row = run_one_threshold(
            args.dataset, args.global_dir, cases, th,
            use_state=args.use_state, include_verifier=args.include_verifier,
            trace_root=args.trace_dir,
        )
        rows.append(row)
        print(
            f"  -> Hit@1={row['hit_at_1']:.4f}  Hit@5={row['hit_at_5']:.4f}  "
            f"$actual={row['actual_usd']:.4f}  $cascade={row['cascade_usd']:.4f}  "
            f"save={row['savings_pct_usd']:.1f}%"
        )

    print()
    print("=" * 100)
    print(f"  RQ-B2 Pareto sweep — {args.dataset.upper()} ({'verifier-ON' if args.include_verifier else 'verifier-OFF'})")
    print("=" * 100)
    print(format_table(rows))
    print("=" * 100)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "dataset": args.dataset,
            "dataset_id": args.global_dir.name,
            "split": args.split,
            "include_verifier": args.include_verifier,
            "n_cases": rows[0]["n_cases"] if rows else 0,
            "n_evaluable": rows[0]["n_evaluable"] if rows else 0,
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print(f"\n[pareto] wrote JSON -> {args.output}")


if __name__ == "__main__":
    main()
