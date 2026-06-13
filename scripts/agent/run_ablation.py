"""Run an ablation grid on a dataset.

Spec is hard-coded for now (Phase 2.5 ships a canonical OB ablation
set; YAML-driven configs land in Phase 2.6). Each ablation re-runs the
agent over the SAME case list — the SkillCache makes the grid 10× cheaper
than cold runs (§9.4).

Usage:
    PYTHONPATH=src python scripts/agent/run_ablation.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --output data/agent_runs/ob-ablation.json \\
        [--limit 500]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.capabilities_observer import (
    CapabilitiesObserver,
    ObservationContext,
    VerifierCalibration,
)
from agent.data_loaders import load_ob_cases, load_wol_cases, WOL_PREDICTIONS_PATHS
from agent.eval_harness import (
    AblationConfig,
    AblationHarness,
    AblationSpec,
    ApplesToApplesContract,
)
from agent.skills import (
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
    RetrieveDenseSkill,
    RetrieveHybridFusionLLMSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    SkillRegistry,
    TriageNumericSkill,
    VerifyWithLLMSkill,
)
from agent.state import StateLayer


# Default OB ablation grid — answers the headline RQ-C5 questions.
DEFAULT_OB_GRID = AblationConfig(
    name="ob-skill-ablation",
    baseline_name="baseline",
    ablations=(
        AblationSpec(
            name="no_verifier",
            disable_skills=("verify_with_llm",),
            description="What if we never invoked the diagnosis agent?",
        ),
        AblationSpec(
            name="no_kg",
            disable_skills=("retrieve_knowledge_graph",
                            "retrieve_hybrid_fusion_llm"),
            description="No knowledge graph; rule-based hybrid only.",
        ),
        AblationSpec(
            name="no_hybrid",
            disable_skills=("retrieve_hybrid_fusion",
                            "retrieve_hybrid_fusion_llm"),
            description="Drop Hybrid-RRF entirely.",
        ),
        AblationSpec(
            name="no_log_sequence",
            disable_skills=("retrieve_log_sequence",),
            description="Drop the log-sequence retriever.",
        ),
        AblationSpec(
            name="dense_only",
            enable_skills_exact=(
                "retrieve_dense", "compose_l2",
                "compose_triage", "compose_novelty",
            ),
            description="BiEncoder + composition only; the lower bound.",
        ),
        AblationSpec(
            name="no_numeric_telemetry",
            mask_capabilities=("NUMERIC_FEATURES",),
            description="What if there were no Prometheus features?",
        ),
    ),
)

# WoL ablation grid — text-only by construction; smaller skill space.
DEFAULT_WOL_GRID = AblationConfig(
    name="wol-skill-ablation",
    baseline_name="baseline",
    ablations=(
        AblationSpec(
            name="no_hybrid",
            disable_skills=("retrieve_hybrid_fusion",),
            description="Drop Hybrid-RRF; BiEncoder + KG only.",
        ),
        AblationSpec(
            name="no_kg",
            disable_skills=("retrieve_knowledge_graph",),
            description="Drop KG-retrieval.",
        ),
        AblationSpec(
            name="dense_only",
            enable_skills_exact=(
                "retrieve_dense", "compose_l2",
                "compose_triage", "compose_novelty",
            ),
            description="BiEncoder + composition only.",
        ),
    ),
)


_OB_PREDICTIONS_BACKED = [
    (TriageNumericSkill,             "v2a-resplit"),
    (RetrieveDenseSkill,             "v2a-resplit"),
    (RetrieveLogSequenceSkill,       "v2b-logseq2vec"),
    (RetrieveHybridFusionSkill,      "v2c-hybrid"),
    (RetrieveHybridFusionLLMSkill,   "v2c-hybrid-llm"),
    (RetrieveKnowledgeGraphSkill,    "v2d-kg-rulebased"),
]


def _build_ob_registry(global_dir: Path) -> SkillRegistry:
    reg = SkillRegistry()
    for cls, subdir in _OB_PREDICTIONS_BACKED:
        p = global_dir / "comparison" / subdir / "per-window-predictions.jsonl"
        if not p.exists():
            logging.warning("missing %s; skipping %s", p, cls.name)
            continue
        reg.register(cls(predictions_path=p))
    # Verifier — only register if file exists (smoke test skipped it).
    verifier_p = global_dir / "comparison" / "v2e-agent-llm" / "per-window-predictions.jsonl"
    if verifier_p.exists():
        reg.register(VerifyWithLLMSkill(predictions_path=verifier_p))
    for cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(cls())
    return reg


def _build_wol_registry(global_dir: Path) -> SkillRegistry:
    reg = SkillRegistry()
    tch_dir = global_dir / "tch-lite-refit"
    for cls, name in [
        (RetrieveDenseSkill,          "retrieve_dense"),
        (RetrieveLogSequenceSkill,    "retrieve_log_sequence"),
        (RetrieveHybridFusionSkill,   "retrieve_hybrid_fusion"),
        (RetrieveKnowledgeGraphSkill, "retrieve_knowledge_graph"),
        (VerifyWithLLMSkill,          "verify_with_llm"),
    ]:
        if name not in WOL_PREDICTIONS_PATHS:
            continue
        filename, pipeline_name = WOL_PREDICTIONS_PATHS[name]
        p = tch_dir / filename
        if not p.exists():
            logging.warning("missing %s; skipping %s", p, name)
            continue
        reg.register(cls(predictions_path=p,
                         predictions_pipeline_name=pipeline_name))
    for cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(cls())
    return reg


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["ob", "wol"], required=True)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    dataset_id = args.global_dir.name

    if args.dataset == "ob":
        cases = load_ob_cases(args.global_dir, split="test", limit=args.limit)
        registry = _build_ob_registry(args.global_dir)
        config = DEFAULT_OB_GRID
        obs_ctx = ObservationContext(
            dataset_id=dataset_id,
            has_memory_text=True,
        )
        contract = ApplesToApplesContract(
            dataset_id=dataset_id, split="test",
            gold_relation="coarse",
            evaluation_mode="telemetry_diagnosis",
        )
    else:
        cases = load_wol_cases(args.global_dir, split="test", limit=args.limit)
        registry = _build_wol_registry(args.global_dir)
        config = DEFAULT_WOL_GRID
        obs_ctx = ObservationContext(
            dataset_id=dataset_id,
            has_memory_text=True,
            verifier_calibration=VerifierCalibration(
                known_harmful_distributions=frozenset({dataset_id}),
            ),
        )
        contract = ApplesToApplesContract(
            dataset_id=dataset_id, split="test",
            gold_relation="coarse",
            evaluation_mode="text_retrieval_generalisation",
        )

    print(f"[run_ablation] {args.dataset}: {len(cases)} cases, "
          f"{len(config.ablations)} ablations")

    harness = AblationHarness(
        registry,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer_factory=lambda: StateLayer(),
    )
    result = harness.run_grid(cases, config, contract=contract)

    # ------------------------------------------------------------------ output
    rows = result.to_summary_rows()
    name_w = max(len(r["ablation"]) for r in rows)
    print()
    print("=" * 88)
    print(f"  Ablation grid: {args.dataset} ({dataset_id})")
    print("=" * 88)
    header = (
        f"  {'ablation':<{name_w}}  "
        f"{'Hit@1':>6}  {'Hit@5':>6}  {'MRR':>6}  "
        f"{'Triage':>6}  {'dH@5':>7}  {'pages':>6}  {'PPI':>6}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        print(
            f"  {row['ablation']:<{name_w}}  "
            f"{row['hit_at_1']:>6.3f}  {row['hit_at_5']:>6.3f}  "
            f"{row['mrr']:>6.3f}  {row['triage_accuracy']:>6.3f}  "
            f"{row['delta_hit_at_5']:>+7.3f}  "
            f"{row['n_pages_emitted']:>6d}  {row['pages_per_incident']:>6.2f}"
        )
    print("=" * 88)

    if args.output is not None:
        result.write_to(args.output, include_case_results=False)
        print(f"[run_ablation] wrote -> {args.output}")


if __name__ == "__main__":
    main()
