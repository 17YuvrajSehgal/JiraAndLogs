"""Phase 3.2 — WoL agent run with KG_GRAPH_WINDOW comparison.

Runs the same WoL test split twice:

  - **baseline**: `has_kg_graph_window=False` even if extractions exist
  - **with-kg-window**: `has_kg_graph_window=True` when extractions exist

Reports a side-by-side delta. When the extractions JSONL is missing,
prints baseline only + a clear note that running
`extract_window_entities.py` is the next step.

Key behaviour:
  - The agent's predictions-backed retrievers don't currently re-rank
    on the window-side extractions (they're keyed by window_id in
    pre-computed JSONLs). So the "with-kg-window" delta in v1 will
    mainly come from any SKILLS whose required_flags include
    KG_GRAPH_WINDOW. None currently do — Phase 3.2's first commit
    builds the store + plumbing; Phase 3.3+ wires the new skill that
    uses it.

This runner is the canonical "did adding window extractions change
WoL numbers?" smoke. As skills consume KG_GRAPH_WINDOW, the delta
becomes non-zero.

Usage:
    PYTHONPATH=src python scripts/agent/compare_wol_kg_window.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        [--output data/agent_runs/wol-kg-window-compare.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.capabilities_observer import (
    CapabilitiesObserver,
    ObservationContext,
    VerifierCalibration,
)
from agent.controller import RuleController
from agent.data_loaders import (
    WindowExtractionsStore,
    WOL_PREDICTIONS_PATHS,
    load_wol_cases,
)
from agent.eval_harness import ApplesToApplesContract, EvalHarness
from agent.runner import AgentRunner
from agent.skills import (
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
    RetrieveDenseSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    SkillRegistry,
    VerifyWithLLMSkill,
)
from agent.state import StateLayer


_WOL_REGISTRY_PLAN: list[tuple[type, str]] = [
    (RetrieveDenseSkill,          "retrieve_dense"),
    (RetrieveLogSequenceSkill,    "retrieve_log_sequence"),
    (RetrieveHybridFusionSkill,   "retrieve_hybrid_fusion"),
    (RetrieveKnowledgeGraphSkill, "retrieve_knowledge_graph"),
    (VerifyWithLLMSkill,          "verify_with_llm"),
]


def _build_registry(global_dir: Path) -> SkillRegistry:
    reg = SkillRegistry()
    tch_dir = global_dir / "tch-lite-refit"
    for cls, name in _WOL_REGISTRY_PLAN:
        if name not in WOL_PREDICTIONS_PATHS:
            continue
        filename, pipeline_name = WOL_PREDICTIONS_PATHS[name]
        preds_path = tch_dir / filename
        if not preds_path.exists():
            logging.warning("skipping %s — missing %s", name, preds_path)
            continue
        reg.register(cls(
            predictions_path=preds_path,
            predictions_pipeline_name=pipeline_name,
        ))
    for compose_cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(compose_cls())
    return reg


def _run_once(
    *,
    global_dir: Path,
    has_kg_graph_window: bool,
    label: str,
):
    dataset_id = global_dir.name
    registry = _build_registry(global_dir)
    runner = AgentRunner(
        registry, experiment=f"wol-compare:{label}",
    )
    controller = RuleController(registry)

    calibration = VerifierCalibration(
        known_harmful_distributions=frozenset({dataset_id}),
        default_policy="skip",
    )
    obs_ctx = ObservationContext(
        dataset_id=dataset_id,
        has_memory_text=True,
        has_kg_graph_memory=False,
        has_kg_graph_window=has_kg_graph_window,
        verifier_calibration=calibration,
    )
    harness = EvalHarness(
        controller=controller, runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer=StateLayer(),
    )
    contract = ApplesToApplesContract(
        dataset_id=dataset_id,
        split="test",
        gold_relation="coarse",
        evaluation_mode="text_retrieval_generalisation",
    )
    cases = load_wol_cases(global_dir, split="test")
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"wol-compare-{label}",
    )
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    store = WindowExtractionsStore.from_global_dir(args.global_dir)
    extractions_present = store.exists_on_disk() and len(store) > 0

    print(f"[compare_wol] global_dir = {args.global_dir.name}")
    print(f"[compare_wol] window extractions file:")
    print(f"    {store.path}")
    print(f"[compare_wol]   present: {store.exists_on_disk()}")
    print(f"[compare_wol]   n_entries: {len(store)}")

    print(f"\n[compare_wol] running baseline (has_kg_graph_window=False)...")
    baseline = _run_once(
        global_dir=args.global_dir,
        has_kg_graph_window=False,
        label="baseline",
    )

    if not extractions_present:
        print()
        print("=" * 70)
        print(f"  Baseline WoL — {args.global_dir.name}")
        print("=" * 70)
        _print_report_row("baseline", baseline)
        print("=" * 70)
        print()
        print("  Window extractions not yet generated. To produce the")
        print("  side-by-side comparison:")
        print("    1. Start LM Studio with Qwen3.6-35B-A3B loaded.")
        print("    2. Run scripts/agent/extract_window_entities.py")
        print("       --global-dir <this dir> --split test  (~6h)")
        print("    3. Re-run this script.")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({
                "baseline": baseline.to_dict(include_case_results=False),
                "with_kg_window": None,
                "extractions_present": False,
            }, indent=2, default=str), encoding="utf-8")
            print(f"\n[compare_wol] wrote partial report -> {args.output}")
        return

    print(f"\n[compare_wol] running with_kg_window (has_kg_graph_window=True)...")
    with_kg = _run_once(
        global_dir=args.global_dir,
        has_kg_graph_window=True,
        label="with_kg_window",
    )

    # Coverage report — fraction of the evaluated cases that the
    # extractions cover. A low number means the run might be unfair.
    case_ids = [c.bundle_id for c in baseline.case_results]
    coverage = store.coverage_fraction(case_ids)

    print()
    print("=" * 90)
    print(f"  WoL with vs without KG_GRAPH_WINDOW — {args.global_dir.name}")
    print("=" * 90)
    print(f"  extraction coverage: {coverage * 100:.1f}% of evaluated windows")
    print(f"  {'metric':<25} {'baseline':>10}  {'with_kg':>10}  {'delta':>10}")
    print("  " + "-" * 60)
    rows = [
        ("hit_at_1", baseline.hit_at_1, with_kg.hit_at_1),
        ("hit_at_5", baseline.hit_at_5, with_kg.hit_at_5),
        ("hit_at_10", baseline.hit_at_10, with_kg.hit_at_10),
        ("mrr", baseline.mrr, with_kg.mrr),
        ("triage_accuracy", baseline.triage_accuracy, with_kg.triage_accuracy),
        ("novel_recall", baseline.novel_recall, with_kg.novel_recall),
        ("pages_per_incident",
         baseline.pages_per_incident, with_kg.pages_per_incident),
    ]
    for name, b, w in rows:
        delta = w - b
        sign = "+" if delta >= 0 else ""
        print(f"  {name:<25} {b:>10.4f}  {w:>10.4f}  {sign}{delta:>9.4f}")
    print("=" * 90)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "baseline": baseline.to_dict(include_case_results=False),
            "with_kg_window": with_kg.to_dict(include_case_results=False),
            "extractions_present": True,
            "n_extractions": len(store),
            "coverage_fraction": coverage,
        }, indent=2, default=str), encoding="utf-8")
        print(f"\n[compare_wol] wrote report -> {args.output}")


def _print_report_row(label: str, report) -> None:
    print(f"  {label:<14}  "
          f"Hit@5={report.hit_at_5:.4f}  "
          f"MRR={report.mrr:.4f}  "
          f"n_eval={report.n_evaluable_retrieval_cases}")


if __name__ == "__main__":
    main()
