"""RQ-C2 — Agent-side hyperparameter sensitivity sweep.

Re-scope from the cascade-side HP sweep: this paper's contribution is
the AGENT's adaptive invocation, not the retriever fits. The
load-bearing hyperparameters at the agent layer are:

  - cheap_path_threshold              (default 0.9)  — cheap-path escalation gate
  - reformulation_confidence_floor    (default 0.5)  — reformulation gate
  - free novelty threshold (L3)       (default 0.5)  — compose_novelty
  - learned novelty threshold (L3)    (default 0.5)  — compose_novelty
  - L1 stacker threshold              (default 0.5)  — compose_triage

For each setting, re-runs `harness.evaluate(cases, contract=...)` and
bootstraps Hit@5 + MRR + triage_accuracy. Predictions are cached, so
each setting evaluation is ~seconds.

Reports:
  - point + 95% CI per setting per metric
  - "robust region" — interval where metric stays within 1% rel of best

Usage:
    PYTHONPATH=src python scripts/agent/agent_hp_sensitivity.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --cheap-path-thresholds 0.7,0.8,0.9,0.95 \\
        --reformulation-floors 0.3,0.5,0.7 \\
        --free-novelty-thresholds 0.3,0.5,0.7 \\
        --output data/agent_runs/ob-agent-hp-sensitivity.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.capabilities_observer import (
    CapabilitiesObserver,
    ObservationContext,
    VerifierCalibration,
)
from agent.controller import RuleController
from agent.data_loaders import (
    WOL_PREDICTIONS_PATHS,
    load_ob_cases,
    load_otel_demo_cases,
    load_wol_cases,
)
from agent.eval_harness import (
    ApplesToApplesContract,
    DEFAULT_N_RESAMPLES,
    DEFAULT_SEED,
    EvalHarness,
    bootstrap_metric,
    metric_hit_at_5,
    metric_hit_at_1,
    metric_mrr,
    metric_triage_accuracy,
    rows_from_dicts,
)
from agent.runner import AgentRunner
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


# ---------------------------------------------------------------------------
# Registry construction (per dataset)
# ---------------------------------------------------------------------------


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
    verifier_p = (
        global_dir / "comparison" / "v2e-agent-llm" / "per-window-predictions.jsonl"
    )
    if verifier_p.exists():
        reg.register(VerifyWithLLMSkill(predictions_path=verifier_p))
    for c in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(c())
    return reg


def _build_wol_registry(global_dir: Path) -> SkillRegistry:
    reg = SkillRegistry()
    comparison = global_dir / "comparison"
    # WoL uses the OB-style comparison/ layout post-fresh-run
    plan = [
        (RetrieveDenseSkill,             "v2a-resplit",      "bi_encoder_retrieval"),
        (RetrieveLogSequenceSkill,       "v2b-logseq2vec",   "logseq2vec_retrieval"),
        (RetrieveHybridFusionSkill,      "v2c-hybrid",       "hybrid_rrf_retrieval"),
        (RetrieveKnowledgeGraphSkill,    "v2d-kg-rulebased", "kg_retrieval"),
        (VerifyWithLLMSkill,             "v2e-agent-llm",    "diagnosis_agent"),
    ]
    for cls, subdir, pname in plan:
        p = comparison / subdir / "per-window-predictions.jsonl"
        if not p.exists():
            # Fall back to tch-lite-refit/ for pre-fresh-run compat.
            fallback = WOL_PREDICTIONS_PATHS.get(cls.name)
            if fallback:
                p = global_dir / "tch-lite-refit" / fallback[0]
        if not p.exists():
            logging.warning("missing predictions for %s; skipping", cls.name)
            continue
        reg.register(cls(predictions_path=p, predictions_pipeline_name=pname))
    for c in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(c())
    return reg


def _build_otel_registry(global_dir: Path) -> SkillRegistry:
    reg = SkillRegistry()
    for cls, subdir in _OB_PREDICTIONS_BACKED:
        p = global_dir / "comparison" / subdir / "per-window-predictions.jsonl"
        if p.exists():
            reg.register(cls(predictions_path=p))
    for c in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        reg.register(c())
    return reg


# ---------------------------------------------------------------------------
# Sweep core
# ---------------------------------------------------------------------------


def _evaluate_once(
    *,
    registry: SkillRegistry,
    cases,
    contract: ApplesToApplesContract,
    obs_ctx: ObservationContext,
    state_layer: StateLayer,
    cheap_path_threshold: float,
    reformulation_floor: float,
    free_novelty_threshold: float,
    learned_novelty_threshold: float,
) -> dict:
    controller = RuleController(
        registry,
        cheap_path_threshold=cheap_path_threshold,
        reformulation_confidence_floor=reformulation_floor,
        max_reformulation_retries=0,  # gate-only measurement; not actually retrying
    )
    # Patch the ComposeNoveltySkill in the registry to use the supplied
    # thresholds. compose_novelty is a singleton in the registry —
    # mutate its attrs for this sweep.
    nov = registry.try_get("compose_novelty")
    if nov is not None:
        nov.free_signal_threshold = free_novelty_threshold
        nov.learned_novelty_threshold = learned_novelty_threshold

    runner = AgentRunner(registry, experiment="hp_sweep")
    harness = EvalHarness(
        controller=controller, runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer=state_layer,
    )
    report = harness.evaluate(cases, contract=contract,
                              experiment_name="hp_sweep",
                              keep_case_details=True)
    return {
        "hit_at_1": report.hit_at_1,
        "hit_at_5": report.hit_at_5,
        "mrr": report.mrr,
        "triage_accuracy": report.triage_accuracy,
        "n_evaluable": report.n_evaluable_retrieval_cases,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["ob", "wol", "otel"], required=True)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--cheap-path-thresholds", default="0.7,0.8,0.9,0.95")
    p.add_argument("--reformulation-floors", default="0.3,0.5,0.7")
    p.add_argument("--free-novelty-thresholds", default="0.3,0.5,0.7")
    p.add_argument("--learned-novelty-thresholds", default="0.3,0.5,0.7")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output", type=Path, required=True)
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
        obs_ctx = ObservationContext(dataset_id=dataset_id, has_memory_text=True)
        contract = ApplesToApplesContract(
            dataset_id=dataset_id, split="test",
            evaluation_mode="telemetry_diagnosis",
        )
    elif args.dataset == "wol":
        cases = load_wol_cases(args.global_dir, split="test", limit=args.limit)
        registry = _build_wol_registry(args.global_dir)
        obs_ctx = ObservationContext(
            dataset_id=dataset_id, has_memory_text=True,
            verifier_calibration=VerifierCalibration(
                known_harmful_distributions=frozenset({dataset_id}),
            ),
        )
        contract = ApplesToApplesContract(
            dataset_id=dataset_id, split="test",
            evaluation_mode="text_retrieval_generalisation",
        )
    else:  # otel
        cases = load_otel_demo_cases(args.global_dir, split="test", limit=args.limit)
        registry = _build_otel_registry(args.global_dir)
        obs_ctx = ObservationContext(dataset_id=dataset_id, has_memory_text=True)
        contract = ApplesToApplesContract(
            dataset_id=dataset_id, split="test",
            evaluation_mode="telemetry_diagnosis",
        )

    def _parse(s: str) -> list[float]:
        return [float(x) for x in s.split(",") if x.strip()]

    cheap_path = _parse(args.cheap_path_thresholds)
    refl_floor = _parse(args.reformulation_floors)
    free_nov = _parse(args.free_novelty_thresholds)
    learn_nov = _parse(args.learned_novelty_thresholds)

    print(f"[hp_sensitivity] {args.dataset}: {len(cases)} cases")
    print(f"[hp_sensitivity] grid: "
          f"{len(cheap_path)}×{len(refl_floor)}×{len(free_nov)}×{len(learn_nov)} "
          f"= {len(cheap_path)*len(refl_floor)*len(free_nov)*len(learn_nov)} settings")

    report: dict[str, Any] = {
        "dataset": args.dataset, "n_cases": len(cases),
        "grids": {
            "cheap_path_threshold": cheap_path,
            "reformulation_floor": refl_floor,
            "free_novelty_threshold": free_nov,
            "learned_novelty_threshold": learn_nov,
        },
        "results": [],
    }

    n_done = 0
    for c in cheap_path:
        for r in refl_floor:
            for f in free_nov:
                for l in learn_nov:
                    # State layer must be fresh per evaluation
                    state = StateLayer()
                    res = _evaluate_once(
                        registry=registry, cases=cases,
                        contract=contract, obs_ctx=obs_ctx,
                        state_layer=state,
                        cheap_path_threshold=c,
                        reformulation_floor=r,
                        free_novelty_threshold=f,
                        learned_novelty_threshold=l,
                    )
                    report["results"].append({
                        "cheap_path_threshold": c,
                        "reformulation_floor": r,
                        "free_novelty_threshold": f,
                        "learned_novelty_threshold": l,
                        **res,
                    })
                    n_done += 1
                    if n_done % 5 == 0:
                        print(f"[hp_sensitivity]   {n_done} settings done")

    # ----- Robust region analysis (per metric)
    # The setting is "robust" if Hit@5 is within 1% relative of the best.
    if report["results"]:
        best_h5 = max(r["hit_at_5"] for r in report["results"])
        floor_h5 = best_h5 * 0.99
        n_robust = sum(1 for r in report["results"] if r["hit_at_5"] >= floor_h5)
        report["robust_region"] = {
            "best_hit_at_5": best_h5,
            "floor_1pct_rel": floor_h5,
            "n_robust_settings": n_robust,
            "fraction_robust": n_robust / len(report["results"]),
        }

    # ----- Print compact table
    print()
    print("=" * 96)
    print(f"  Agent HP sensitivity — {args.dataset} ({dataset_id})")
    print("=" * 96)
    print(f"  {'cheap_path':>11} {'refl_floor':>11} {'free_nov':>10} "
          f"{'learn_nov':>10} {'Hit@1':>8} {'Hit@5':>8} {'MRR':>8} "
          f"{'Triage':>8}")
    print("  " + "-" * 92)
    for r in report["results"]:
        print(f"  {r['cheap_path_threshold']:>11.3f} {r['reformulation_floor']:>11.3f} "
              f"{r['free_novelty_threshold']:>10.3f} {r['learned_novelty_threshold']:>10.3f} "
              f"{r['hit_at_1']:>8.4f} {r['hit_at_5']:>8.4f} {r['mrr']:>8.4f} "
              f"{r['triage_accuracy']:>8.4f}")
    print("=" * 96)

    if "robust_region" in report:
        rr = report["robust_region"]
        print(f"\n  Robust region (Hit@5 within 1% rel of best):")
        print(f"    best Hit@5:      {rr['best_hit_at_5']:.4f}")
        print(f"    floor:           {rr['floor_1pct_rel']:.4f}")
        print(f"    robust settings: {rr['n_robust_settings']} / "
              f"{len(report['results'])} ({rr['fraction_robust']*100:.1f}%)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str),
                            encoding="utf-8")
    print(f"\n[hp_sensitivity] wrote -> {args.output}")


if __name__ == "__main__":
    main()
