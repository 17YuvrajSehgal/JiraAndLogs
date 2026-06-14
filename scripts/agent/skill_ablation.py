"""Skill-ablation grid — RQ-A5 closure.

Where §3.8 (tool_ablation.py) sweeps subsets of the 4 ReAct evidence
tools, this script sweeps the OTHER skills — the cascade-derived
predictions-backed retrievers, the composition skills, and
reformulate_query. The question RQ-A5 asks is **which skills carry
the agent's claims** on each dataset?

For each ablation cell, the harness re-runs the agent over the SAME
case list with ONE skill (or skill group) disabled. The SkillCache
makes the grid 10× cheaper than cold runs (per AGENTIC-SYSTEM §9.4).

This script uses `build_harness_for_dataset` per cell — same wiring
as the production smoke. Each cell's `skip` set drops the named
skills from the registry before the controller emits a Plan; the
remaining skills do whatever the controller asks of them.

Usage:
    PYTHONPATH=src python scripts/agent/skill_ablation.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --output results/ob/4.1-skill-ablation/ablation.json

Datasets supported: "ob" / "wol" / "otel_demo".
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders import load_ob_cases, load_otel_demo_cases, load_wol_cases
from agent.harness_builder import build_harness_for_dataset


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AblationCell:
    """One cell of the skill-ablation grid."""
    label: str                                 # short name for tables
    skip: frozenset[str]                       # skill names to drop
    description: str = ""


# ---------------------------------------------------------------------------
# OB grid — closes RQ-A5 on the headline dataset
# ---------------------------------------------------------------------------


OB_GRID: tuple[AblationCell, ...] = (
    AblationCell(
        label="baseline",
        skip=frozenset(),
        description="full Phase-2 stack — all cascade + 4 ReAct tools + rerank",
    ),
    # ─────────── Cascade-skill ablations ───────────
    AblationCell(
        label="no_verifier",
        skip=frozenset({"verify_with_llm"}),
        description="drop verify_with_llm (DiagnosisAgent)",
    ),
    AblationCell(
        label="no_kg",
        skip=frozenset({"retrieve_knowledge_graph",
                        "retrieve_hybrid_fusion_llm"}),
        description="no knowledge-graph retrievers (rule-based + LLM-graph)",
    ),
    AblationCell(
        label="no_hybrid",
        skip=frozenset({"retrieve_hybrid_fusion",
                        "retrieve_hybrid_fusion_llm"}),
        description="drop Hybrid-RRF (both rule-based and LLM-graph variants)",
    ),
    AblationCell(
        label="no_log_sequence",
        skip=frozenset({"retrieve_log_sequence"}),
        description="drop LogSeq2Vec",
    ),
    AblationCell(
        label="dense_only",
        skip=frozenset({
            "retrieve_log_sequence", "retrieve_hybrid_fusion",
            "retrieve_hybrid_fusion_llm", "retrieve_knowledge_graph",
            "verify_with_llm", "triage_numeric",
        }),
        description="BiEncoder retrieval + composition only (lower bound)",
    ),
    AblationCell(
        label="no_triage_numeric",
        skip=frozenset({"triage_numeric"}),
        description="drop HGB triage scorer (removes cheap-path gate)",
    ),
    # ─────────── ReAct-loop ablations ───────────
    AblationCell(
        label="no_react",
        skip=frozenset({
            "request_pod_events", "request_extended_trace_window",
            "request_pod_metrics", "request_similar_incident_window",
            "rerank_with_evidence",
        }),
        description="disable all 4 ReAct tools + rerank — pre-Phase-2 baseline",
    ),
    AblationCell(
        label="no_reformulate",
        skip=frozenset({"reformulate_query"}),
        description="drop the reformulation skill (RQ-A3 isolation)",
    ),
    AblationCell(
        label="no_compose_novelty",
        skip=frozenset({"compose_novelty"}),
        description="drop novelty disjunction (RQ-A5 / RQ-D2 link)",
    ),
)


# ---------------------------------------------------------------------------
# WoL grid — text-only; smaller skill space
# ---------------------------------------------------------------------------


WOL_GRID: tuple[AblationCell, ...] = (
    AblationCell(label="baseline", skip=frozenset()),
    AblationCell(
        label="no_kg",
        skip=frozenset({"retrieve_knowledge_graph"}),
        description="drop KG-retrieval",
    ),
    AblationCell(
        label="no_hybrid",
        skip=frozenset({"retrieve_hybrid_fusion"}),
        description="drop Hybrid-RRF; BiEncoder + KG only",
    ),
    AblationCell(
        label="no_log_sequence",
        skip=frozenset({"retrieve_log_sequence"}),
        description="drop LogSeq2Vec (already weak on WoL Mode 3 §3.5)",
    ),
    AblationCell(
        label="dense_only",
        skip=frozenset({
            "retrieve_log_sequence", "retrieve_hybrid_fusion",
            "retrieve_knowledge_graph",
        }),
        description="BiEncoder only",
    ),
    AblationCell(
        label="no_react",
        skip=frozenset({
            "request_similar_incident_window", "rerank_with_evidence",
        }),
        description="disable peers-only ReAct on WoL",
    ),
)


# ---------------------------------------------------------------------------
# OTel Demo grid — same telemetry shape as OB
# ---------------------------------------------------------------------------


OTEL_GRID: tuple[AblationCell, ...] = (
    AblationCell(label="baseline", skip=frozenset()),
    AblationCell(
        label="no_hybrid",
        skip=frozenset({"retrieve_hybrid_fusion"}),
        description="drop Hybrid-RRF; BiEncoder only",
    ),
    AblationCell(
        label="dense_only",
        skip=frozenset({"retrieve_hybrid_fusion", "triage_numeric"}),
        description="BiEncoder only",
    ),
    AblationCell(
        label="no_triage_numeric",
        skip=frozenset({"triage_numeric"}),
        description="drop HGB triage scorer",
    ),
    AblationCell(
        label="no_react",
        skip=frozenset({
            "request_pod_events", "request_extended_trace_window",
            "request_pod_metrics", "request_similar_incident_window",
            "rerank_with_evidence",
        }),
        description="disable all 4 ReAct tools + rerank",
    ),
)


GRIDS = {"ob": OB_GRID, "wol": WOL_GRID, "otel_demo": OTEL_GRID}

DATASET_TO_LABEL = {
    "ob": "online_boutique",
    "wol": "wol",
    "otel_demo": "otel_demo",
}


def _load_cases(dataset: str, global_dir: Path, *, split: str, limit: int | None):
    if dataset == "ob":
        return load_ob_cases(global_dir, split=split, limit=limit)
    if dataset == "wol":
        return load_wol_cases(global_dir, split=split, limit=limit)
    if dataset == "otel_demo":
        return load_otel_demo_cases(global_dir, split=split, limit=limit)
    raise ValueError(f"unknown dataset: {dataset!r}")


def run_cell(
    dataset: str,
    global_dir: Path,
    cases,
    cell: AblationCell,
    *,
    use_state: bool,
    include_verifier: bool,
) -> dict:
    """Run one ablation cell."""
    harness, contract = build_harness_for_dataset(
        dataset_label=DATASET_TO_LABEL[dataset],
        global_dir=global_dir,
        cache_dir=None,
        trace_root=None,
        skip=set(cell.skip),
        include_verifier=include_verifier,
        use_state_layer=use_state,
        experiment_prefix=f"skill-ablation-{cell.label}",
    )
    t0 = time.monotonic()
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"ablation-{cell.label}-{global_dir.name}",
    )
    wall_sec = time.monotonic() - t0
    return {
        "cell": cell.label,
        "skip": sorted(cell.skip),
        "description": cell.description,
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


def format_table(rows: list[dict], baseline_label: str = "baseline") -> str:
    """Render an ablation grid as Markdown with Δ vs baseline."""
    baseline = next(r for r in rows if r["cell"] == baseline_label)
    b_h1 = baseline["hit_at_1"]
    b_h5 = baseline["hit_at_5"]
    b_mrr = baseline["mrr"]
    lines: list[str] = []
    lines.append("| Cell | Hit@1 | Δ | Hit@5 | Δ | MRR | Δ | Triage acc | n_plans | wall (s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        dh1 = r["hit_at_1"] - b_h1
        dh5 = r["hit_at_5"] - b_h5
        dmrr = r["mrr"] - b_mrr
        lines.append(
            f"| {r['cell']} | "
            f"{r['hit_at_1']:.4f} | {dh1:+.4f} | "
            f"{r['hit_at_5']:.4f} | {dh5:+.4f} | "
            f"{r['mrr']:.4f} | {dmrr:+.4f} | "
            f"{r['triage_accuracy']:.4f} | "
            f"{r['n_distinct_plan_ids']} | "
            f"{r['wall_seconds']:.2f} |"
        )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(GRIDS), required=True)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--use-state", action="store_true",
                   help="enable cross-window StateLayer (default off — "
                        "state layer affects triage_decision not Hit@K)")
    p.add_argument("--include-verifier", action="store_true",
                   help="register verify_with_llm (off by default)")
    p.add_argument("--output", type=Path, default=None,
                   help="write JSON results here")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    # Force UTF-8 stdout so the Δ in the table renders on Windows
    # (cp1252 default barfs on the symbol).
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # noqa: SLF001
    except Exception:
        pass

    grid = GRIDS[args.dataset]
    print(f"[skill_ablation] loading cases from {args.global_dir} (split={args.split})")
    cases = _load_cases(args.dataset, args.global_dir,
                        split=args.split, limit=args.limit)
    print(f"[skill_ablation] loaded {len(cases)} cases; grid has {len(grid)} cells")

    rows: list[dict] = []
    for i, cell in enumerate(grid, 1):
        print(f"\n[skill_ablation] {i:>2}/{len(grid)}  cell={cell.label} ...")
        row = run_cell(
            args.dataset, args.global_dir, cases, cell,
            use_state=args.use_state, include_verifier=args.include_verifier,
        )
        rows.append(row)
        print(
            f"            Hit@1={row['hit_at_1']:.4f}  "
            f"Hit@5={row['hit_at_5']:.4f}  MRR={row['mrr']:.4f}  "
            f"plans={row['n_distinct_plan_ids']}  "
            f"wall={row['wall_seconds']:.2f}s"
        )

    print()
    print("=" * 110)
    print(f"  RQ-A5 skill-ablation grid — {args.dataset.upper()}")
    print("=" * 110)
    print(format_table(rows))
    print("=" * 110)

    # Rank ablations by negative Hit@1 delta — most damaging first
    baseline = next(r for r in rows if r["cell"] == "baseline")
    ranked = sorted(
        (r for r in rows if r["cell"] != "baseline"),
        key=lambda r: r["hit_at_1"] - baseline["hit_at_1"],
    )
    print("\nAblations ranked by DAMAGE to Hit@1 (most damaging first):")
    for r in ranked:
        delta = r["hit_at_1"] - baseline["hit_at_1"]
        print(f"  {r['cell']:<25} Δ Hit@1 = {delta:+.4f}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "dataset": args.dataset,
            "dataset_id": args.global_dir.name,
            "split": args.split,
            "n_cases": rows[0]["n_cases"] if rows else 0,
            "n_evaluable": rows[0]["n_evaluable"] if rows else 0,
            "baseline": {"hit_at_1": baseline["hit_at_1"],
                         "hit_at_5": baseline["hit_at_5"],
                         "mrr": baseline["mrr"]},
            "rows": rows,
            "ranked_by_damage": [r["cell"] for r in ranked],
        }, indent=2), encoding="utf-8")
        print(f"\n[skill_ablation] wrote JSON -> {args.output}")


if __name__ == "__main__":
    main()
