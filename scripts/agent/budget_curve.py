"""Budget-bounded Hit@K curve — RQ-A7 closure.

Sweeps `max_tool_calls` ∈ {0, 1, 2, 3, 4} on the OB test split and
reports how Hit@1 / Hit@5 / MRR scale with the per-window ReAct
budget cap.

Each iteration reuses the same harness + cases (loaded once) but
swaps the tool-call cap on each registered EvidenceRequestSkill
between runs. The 4 evidence skills always fire on the gate, but
with cap=N only the first N actually invoke `_fetch_evidence`; the
remaining (4 − N) get refused with `failure_mode = budget_exhausted`.

Usage:
    PYTHONPATH=src python scripts/agent/budget_curve.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --budgets 0,1,2,3,4 \\
        --output results/ob/3.7-budget-curve/curve.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/agent/budget_curve.py` (no PYTHONPATH).
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


log = logging.getLogger(__name__)


def _parse_budgets(arg: str) -> list[int]:
    return [int(x.strip()) for x in arg.split(",") if x.strip()]


def run_one_budget(
    dataset: str,
    global_dir: Path,
    cases,
    budget: int,
    *,
    use_state: bool,
) -> dict:
    """Run the harness on `cases` with `max_tool_calls = budget`,
    return a per-budget summary dict."""
    dataset_label, _ = _DATASET_LOADERS[dataset]
    harness, contract = build_harness_for_dataset(
        dataset_label=dataset_label,
        global_dir=global_dir,
        cache_dir=None,                  # don't pollute cache across sweeps
        trace_root=None,                 # don't dump traces; just need the report
        skip=set(),
        include_verifier=False,
        use_state_layer=use_state,
        max_tool_calls=budget,
        experiment_prefix="budget",
    )
    t0 = time.monotonic()
    report = harness.evaluate(
        cases,
        contract=contract,
        experiment_name=f"budget-{budget}-{global_dir.name}",
    )
    wall_sec = time.monotonic() - t0
    return {
        "max_tool_calls": int(budget),
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
        "wall_seconds": round(wall_sec, 3),
    }


def format_curve(rows: list[dict]) -> str:
    """Pretty-print the curve as a Markdown table."""
    lines: list[str] = []
    lines.append("| max_tool_calls | Hit@1  | Hit@5  | MRR    | Triage acc | wall (s) |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['max_tool_calls']} | "
            f"{r['hit_at_1']:.4f} | "
            f"{r['hit_at_5']:.4f} | "
            f"{r['mrr']:.4f} | "
            f"{r['triage_accuracy']:.4f} | "
            f"{r['wall_seconds']:.2f} |"
        )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(_DATASET_LOADERS), default="ob")
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--budgets", type=_parse_budgets, default=[0, 1, 2, 3, 4],
                   help="Comma-separated list of max_tool_calls values "
                        "(default: 0,1,2,3,4 — RQ-A7's plan-spec range)")
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--use-state", action="store_true",
                   help="Enable the cross-window StateLayer for each "
                        "sweep iteration (default: off — keeps each run "
                        "independent of suppression).")
    p.add_argument("--output", type=Path, default=None,
                   help="Write JSON curve here")
    p.add_argument("--csv-output", type=Path, default=None,
                   help="Also write a CSV here")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    _, loader = _DATASET_LOADERS[args.dataset]
    print(f"[budget_curve] loading {args.dataset} cases from {args.global_dir} (split={args.split})")
    cases = loader(args.global_dir, split=args.split, limit=args.limit)
    print(f"[budget_curve] loaded {len(cases)} cases")

    rows: list[dict] = []
    for budget in args.budgets:
        print(f"\n[budget_curve] running max_tool_calls = {budget} ...")
        row = run_one_budget(
            args.dataset, args.global_dir, cases, budget, use_state=args.use_state,
        )
        rows.append(row)
        print(
            f"  -> Hit@1={row['hit_at_1']:.4f}  Hit@5={row['hit_at_5']:.4f}  "
            f"MRR={row['mrr']:.4f}  wall={row['wall_seconds']:.2f}s"
        )

    print()
    print("=" * 70)
    print("  RQ-A7 budget-bounded curve (OB)")
    print("=" * 70)
    print(format_curve(rows))
    print("=" * 70)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "dataset_id": args.global_dir.name,
            "split": args.split,
            "n_cases": rows[0]["n_cases"] if rows else 0,
            "n_evaluable": rows[0]["n_evaluable"] if rows else 0,
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print(f"[budget_curve] wrote JSON -> {args.output}")
    if args.csv_output is not None:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        header = "max_tool_calls,hit_at_1,hit_at_5,mrr,triage_accuracy,wall_seconds\n"
        lines = "".join(
            f"{r['max_tool_calls']},"
            f"{r['hit_at_1']:.6f},{r['hit_at_5']:.6f},{r['mrr']:.6f},"
            f"{r['triage_accuracy']:.6f},{r['wall_seconds']:.3f}\n"
            for r in rows
        )
        args.csv_output.write_text(header + lines, encoding="utf-8")
        print(f"[budget_curve] wrote CSV  -> {args.csv_output}")


if __name__ == "__main__":
    main()
