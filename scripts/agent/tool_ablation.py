"""Per-tool ablation sweep — Phase 2 #5 (end-to-end tuning).

The §3.7 budget-curve experiment found a non-monotone Hit@K
response to `max_tool_calls`: tools 2 and 3 hurt, tool 4 recovers.
That tells us "how many tools" is the wrong axis. This script
asks the right question: **which subset of the 4 tools maximises
Hit@1?**

Sweeps all 2^4 = 16 subsets of
    {request_pod_events, request_extended_trace_window,
     request_pod_metrics, request_similar_incident_window}
on the OB test split. The 4 evidence skills are registered or
skipped per subset via the existing `--skip-skill` mechanism.

Usage:
    PYTHONPATH=src python scripts/agent/tool_ablation.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --output results/ob/3.8-tool-ablation/ablation.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/agent/tool_ablation.py` (no PYTHONPATH).
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


# The four evidence-request skill names. Order is the same as the
# controller's `_REACT_TOOLS_ACTIVE_FAULT` so subset indices are
# stable across §3.7 and §3.8.
ALL_TOOLS: tuple[str, ...] = (
    "request_pod_events",
    "request_extended_trace_window",
    "request_pod_metrics",
    "request_similar_incident_window",
)


def _tool_short(name: str) -> str:
    """Compact label for tables."""
    return {
        "request_pod_events": "events",
        "request_extended_trace_window": "trace",
        "request_pod_metrics": "metrics",
        "request_similar_incident_window": "peers",
    }.get(name, name)


def run_one_subset(
    dataset: str,
    global_dir: Path,
    cases,
    subset: tuple[str, ...],
    *,
    use_state: bool,
    per_cell_report_dir: Path | None = None,
) -> dict:
    """Run the harness with only `subset` of the 4 evidence skills active.

    When `per_cell_report_dir` is set, also writes the per-cell
    EvaluationReport (with case_results) for paired-delta-bootstrap
    analysis (RQ-B3 strengthening).
    """
    skip = set(ALL_TOOLS) - set(subset)
    dataset_label, _ = _DATASET_LOADERS[dataset]
    label = "+".join(_tool_short(t) for t in subset) or "none"
    harness, contract = build_harness_for_dataset(
        dataset_label=dataset_label,
        global_dir=global_dir,
        cache_dir=None,
        trace_root=None,
        skip=skip,
        include_verifier=False,
        use_state_layer=use_state,
        experiment_prefix="ablation",
    )
    t0 = time.monotonic()
    report = harness.evaluate(
        cases,
        contract=contract,
        experiment_name=f"ablation-{label}-{global_dir.name}",
    )
    wall_sec = time.monotonic() - t0

    if per_cell_report_dir is not None:
        per_cell_report_dir.mkdir(parents=True, exist_ok=True)
        report.write_to(
            per_cell_report_dir / f"{label}-report.json",
            include_case_results=True,
        )

    return {
        "subset": list(subset),
        "subset_label": label,
        "n_tools": len(subset),
        "hit_at_1": float(report.hit_at_1),
        "hit_at_5": float(report.hit_at_5),
        "mrr": float(report.mrr),
        "triage_accuracy": float(report.triage_accuracy),
        "n_distinct_plan_ids": len(report.plan_ids_seen),
        "wall_seconds": round(wall_sec, 3),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(_DATASET_LOADERS), default="ob")
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--use-state", action="store_true",
                   help="enable cross-window StateLayer (default off — "
                        "state layer affects only triage decision, not "
                        "Hit@K, so disabling keeps Hit@K runs clean)")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--per-cell-report-dir", type=Path, default=None,
                   help="if set, write per-cell EvaluationReport JSONs "
                        "for paired-delta-bootstrap (RQ-B3)")
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

    _, loader = _DATASET_LOADERS[args.dataset]
    print(f"[tool_ablation] loading {args.dataset} cases from {args.global_dir} (split={args.split})")
    cases = loader(args.global_dir, split=args.split, limit=args.limit)
    print(f"[tool_ablation] loaded {len(cases)} cases")

    # Enumerate all 2^4 subsets, in lex order on (size, names).
    all_subsets: list[tuple[str, ...]] = []
    for k in range(len(ALL_TOOLS) + 1):
        for combo in itertools.combinations(ALL_TOOLS, k):
            all_subsets.append(combo)

    rows: list[dict] = []
    for i, subset in enumerate(all_subsets, 1):
        label = "+".join(_tool_short(t) for t in subset) or "none"
        print(f"[tool_ablation] {i:>2}/{len(all_subsets)}  subset={label} ...")
        row = run_one_subset(
            args.dataset, args.global_dir, cases, subset,
            use_state=args.use_state,
            per_cell_report_dir=args.per_cell_report_dir,
        )
        rows.append(row)
        print(
            f"            Hit@1={row['hit_at_1']:.4f}  "
            f"Hit@5={row['hit_at_5']:.4f}  MRR={row['mrr']:.4f}  "
            f"wall={row['wall_seconds']:.2f}s"
        )

    # Identify the best subset by Hit@1 (tie-break: MRR, then n_tools asc)
    rows_ranked = sorted(
        rows,
        key=lambda r: (-r["hit_at_1"], -r["mrr"], r["n_tools"]),
    )

    print()
    print("=" * 78)
    print("  RQ-A5/A6 tool-ablation: top 10 subsets by Hit@1")
    print("=" * 78)
    print(f"  {'rank':<5} {'subset':<45} {'Hit@1':<8} {'MRR':<8} {'wall':<6}")
    for i, r in enumerate(rows_ranked[:10], 1):
        print(
            f"  {i:<5} {r['subset_label']:<45} "
            f"{r['hit_at_1']:.4f}   {r['mrr']:.4f}   {r['wall_seconds']:.2f}s"
        )
    print("=" * 78)
    print(f"  Worst:    {rows_ranked[-1]['subset_label']:<45} "
          f"{rows_ranked[-1]['hit_at_1']:.4f}   "
          f"{rows_ranked[-1]['mrr']:.4f}   "
          f"{rows_ranked[-1]['wall_seconds']:.2f}s")
    baseline = next(r for r in rows if not r["subset"])
    print(f"  Baseline: {baseline['subset_label']:<45} "
          f"{baseline['hit_at_1']:.4f}   "
          f"{baseline['mrr']:.4f}   "
          f"{baseline['wall_seconds']:.2f}s")
    print("=" * 78)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "dataset_id": args.global_dir.name,
            "split": args.split,
            "n_cases": rows[0].get("n_cases") or 0,
            "all_subsets": rows,
            "ranked_by_hit_at_1": [r["subset_label"] for r in rows_ranked],
            "best_subset": rows_ranked[0]["subset"],
            "best_hit_at_1": rows_ranked[0]["hit_at_1"],
            "baseline_hit_at_1": baseline["hit_at_1"],
        }
        args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[tool_ablation] wrote JSON -> {args.output}")


if __name__ == "__main__":
    main()
