"""Smoke test: run the agent end-to-end on World of Logs.

WoL is the **text-retrieval generalisation** dataset. The point of this
smoke test is to demonstrate the agent's **capability-adaptive** design:
the SAME RuleController, given the same skill registry, emits a
different Plan on WoL because:

  - `NUMERIC_FEATURES` flag is absent (WoL has no telemetry features)
    → triage_numeric is dropped from the plan.
  - `ORDERED_LOGS` is absent (WoL log_quotes are unordered)
    → retrieve_log_sequence is dropped.
  - `VERIFIER_KNOWN_HELPFUL` is absent (WoL is in
    VerifierCalibration.known_harmful_distributions per Mode 3 §3.9)
    → verify_with_llm is structurally skipped — RQ-A8 closed.

Usage:
    PYTHONPATH=src python scripts/agent/smoke_wol.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        [--limit 100] [--split test] [--cache-dir data/skill_cache] \\
        [--output data/agent_runs/wol-smoke.json]

The smoke also asserts the structural-skip property after the run:
verify_with_llm should be absent from `report.plan_ids_seen`-derived
skill set. Failure means RQ-A8 closure regressed.
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
from agent.controller import RuleController
from agent.data_loaders import WOL_PREDICTIONS_PATHS, load_wol_cases
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
    SkillCache,
    SkillRegistry,
    VerifyWithLLMSkill,
)
from agent.state import StateLayer


# Map agent-skill-class → WoL-side (filename, pipeline_name)
# Sourced from WOL_PREDICTIONS_PATHS for the actual values.
_WOL_REGISTRY_PLAN: list[tuple[type, str]] = [
    (RetrieveDenseSkill,          "retrieve_dense"),
    (RetrieveLogSequenceSkill,    "retrieve_log_sequence"),
    (RetrieveHybridFusionSkill,   "retrieve_hybrid_fusion"),
    (RetrieveKnowledgeGraphSkill, "retrieve_knowledge_graph"),
    (VerifyWithLLMSkill,          "verify_with_llm"),
]


def _build_registry(
    global_dir: Path,
    *,
    skip: set[str],
) -> SkillRegistry:
    reg = SkillRegistry()
    tch_dir = global_dir / "tch-lite-refit"

    for cls, name in _WOL_REGISTRY_PLAN:
        if name in skip:
            continue
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

    # Composition skills run on top of the trace; no JSONL needed.
    for compose_cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        if compose_cls.name in skip:
            continue
        reg.register(compose_cls())

    return reg


def _build_harness(
    global_dir: Path,
    *,
    cache_dir: Path | None,
    skip: set[str],
    use_state_layer: bool,
) -> tuple[EvalHarness, ApplesToApplesContract]:
    dataset_id = global_dir.name
    registry = _build_registry(global_dir, skip=skip)

    cache = SkillCache(root=cache_dir) if cache_dir else None
    runner = AgentRunner(
        registry, cache=cache, experiment=f"smoke:{dataset_id}",
    )
    controller = RuleController(registry)

    # The crux of RQ-A8 closure: WoL is in known_harmful → the observer
    # never sets VERIFIER_KNOWN_HELPFUL → verify_with_llm.can_invoke
    # returns False → it never enters the plan. Verified below.
    calibration = VerifierCalibration(
        known_helpful_distributions=frozenset(),
        known_harmful_distributions=frozenset({dataset_id}),
        default_policy="skip",
    )
    obs_ctx = ObservationContext(
        dataset_id=dataset_id,
        has_memory_text=True,
        has_kg_graph_memory=False,
        has_kg_graph_window=False,
        verifier_calibration=calibration,
    )

    harness = EvalHarness(
        controller=controller, runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer=StateLayer() if use_state_layer else None,
    )
    contract = ApplesToApplesContract(
        dataset_id=dataset_id,
        split="test",
        gold_relation="coarse",
        evaluation_mode="text_retrieval_generalisation",
    )
    return harness, contract


def _assert_verifier_structurally_skipped(report) -> None:
    """Fail loudly if verify_with_llm shows up in any case's invocations.

    This is RQ-A8 closure: WoL must never invoke the verifier."""
    bad = []
    for c in report.case_results:
        if "verify_with_llm" in c.decision.skills_invoked:
            bad.append(c.bundle_id)
    if bad:
        raise AssertionError(
            f"RQ-A8 violation: verify_with_llm ran on {len(bad)} WoL cases "
            f"(first: {bad[0]}). VerifierCalibration may be misconfigured.",
        )
    print("[smoke_wol] RQ-A8 closure verified: verify_with_llm never invoked.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test", choices=["train", "validation", "test"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--no-state", action="store_true")
    p.add_argument("--skip-skill", action="append", default=[], metavar="NAME")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"[smoke_wol] loading cases from {args.global_dir} (split={args.split})")
    cases = load_wol_cases(
        args.global_dir, split=args.split, limit=args.limit,
    )
    print(f"[smoke_wol] loaded {len(cases)} cases")

    harness, contract = _build_harness(
        args.global_dir,
        cache_dir=args.cache_dir,
        skip=set(args.skip_skill),
        use_state_layer=not args.no_state,
    )

    print(f"[smoke_wol] running agent over {len(cases)} cases...")
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"wol-smoke-{args.global_dir.name}",
    )

    # ------------------------------------------------------------------ output
    print()
    print("=" * 70)
    print(f"  Agent smoke test (WoL) - {args.global_dir.name}")
    print("=" * 70)
    print(f"  n_cases (total):                {report.n_cases}")
    print(f"  n_cases (with retrieval gold):  {report.n_evaluable_retrieval_cases}")
    print(f"  Hit@1                           {report.hit_at_1:.4f}")
    print(f"  Hit@5                           {report.hit_at_5:.4f}")
    print(f"  Hit@10                          {report.hit_at_10:.4f}")
    print(f"  MRR                             {report.mrr:.4f}")
    print(f"  Triage accuracy                 {report.triage_accuracy:.4f}")
    print(f"  Novel recall / precision        "
          f"{report.novel_recall:.4f} / {report.novel_precision:.4f}")
    print(f"  Pages emitted                   {report.n_pages_emitted}")
    print(f"  Incidents                       {report.n_incidents}")
    print(f"  Pages-per-incident              {report.pages_per_incident:.3f}")
    print(f"  Suppressions fired              {report.n_suppressions_fired}")
    print(f"  Distinct plan IDs               {len(report.plan_ids_seen)}")
    print(f"  evaluation_mode                 {report.contract.evaluation_mode}")
    print("=" * 70)

    _assert_verifier_structurally_skipped(report)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report.write_to(args.output, include_case_results=True)
        print(f"[smoke_wol] wrote report -> {args.output}")


if __name__ == "__main__":
    main()
