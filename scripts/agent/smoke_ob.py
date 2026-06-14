"""Smoke test: run the agent end-to-end on Online Boutique.

Loads OB test windows, builds the full agent (RuleController +
AgentRunner + EvalHarness + StateLayer + predictions-backed skills),
runs evaluate(), and prints the first real Hit@K / MRR /
pages-per-incident numbers the agent produces.

This is **Phase 1.15** in the build plan — the first time we observe
the agent's behaviour on real data rather than stubs. Numbers should
roughly track the locked cascade (TCH Final: Hit@5 0.912) because the
agent consumes the same per-window predictions and applies the same
composition math; the agent contribution is the *adaptive
invocation* layer, not new model fits.

Usage:
    PYTHONPATH=src python scripts/agent/smoke_ob.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        [--limit 100] \\
        [--split test] \\
        [--cache-dir data/skill_cache] \\
        [--output data/agent_runs/ob-smoke-2026-06-12.json]

Skip flags:
    --no-verifier        don't even register verify_with_llm (cheap smoke)
    --no-state           run without page-suppression
    --skip-skill <name>  drop a skill from the registry (repeatable)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/agent/smoke_ob.py` (no PYTHONPATH) to work locally.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.capabilities_observer import CapabilitiesObserver, ObservationContext
from agent.controller import RuleController
from agent.data_loaders import load_ob_cases
from agent.eval_harness import ApplesToApplesContract, EvalHarness
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
    SkillCache,
    SkillRegistry,
    TriageNumericSkill,
)
from agent.state import StateLayer


_PREDICTIONS_BACKED = [
    (TriageNumericSkill, "v2a-resplit"),
    (RetrieveDenseSkill, "v2a-resplit"),
    (RetrieveLogSequenceSkill, "v2b-logseq2vec"),
    (RetrieveHybridFusionSkill, "v2c-hybrid"),
    (RetrieveHybridFusionLLMSkill, "v2c-hybrid-llm"),
    (RetrieveKnowledgeGraphSkill, "v2d-kg-rulebased"),
]


def _build_registry(
    global_dir: Path,
    *,
    skip: set[str],
    include_verifier: bool,
) -> SkillRegistry:
    """Construct a registry pointing at the OB comparison dir."""
    reg = SkillRegistry()

    for cls, subdir in _PREDICTIONS_BACKED:
        if cls.name in skip:
            continue
        preds_path = global_dir / "comparison" / subdir / "per-window-predictions.jsonl"
        if not preds_path.exists():
            logging.warning(
                "skipping %s — predictions JSONL not found at %s",
                cls.name, preds_path,
            )
            continue
        reg.register(cls(predictions_path=preds_path))

    # The verifier needs VERIFIER_KNOWN_HELPFUL in the observation
    # context. We register it conditionally so the smoke test stays
    # cheap by default.
    if include_verifier:
        from agent.skills import VerifyWithLLMSkill                        # noqa: WPS433
        if VerifyWithLLMSkill.name not in skip:
            preds_path = (
                global_dir / "comparison" / "v2e-agent-llm"
                / "per-window-predictions.jsonl"
            )
            if preds_path.exists():
                reg.register(VerifyWithLLMSkill(predictions_path=preds_path))

    # Composition skills — no JSONL backing; pure trace-readers.
    for compose_cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        if compose_cls.name in skip:
            continue
        reg.register(compose_cls())

    return reg


def _build_harness(
    global_dir: Path,
    *,
    cache_dir: Path | None,
    trace_root: Path | None,
    skip: set[str],
    include_verifier: bool,
    use_state_layer: bool,
) -> tuple[EvalHarness, ApplesToApplesContract]:
    dataset_id = global_dir.name
    registry = _build_registry(
        global_dir, skip=skip, include_verifier=include_verifier,
    )

    cache = SkillCache(root=cache_dir) if cache_dir else None
    runner = AgentRunner(
        registry,
        cache=cache,
        trace_root=trace_root,
        # `-` not `:` — Windows can't have colons in directory names and
        # trace_root creates a subdir per experiment.
        experiment=f"smoke-{dataset_id}",
    )
    controller = RuleController(registry)

    # ObservationContext: tell the observer that the OB memory side
    # has memory_text + (optionally) KG_GRAPH_WINDOW. The smoke test
    # leaves KG_GRAPH_MEMORY off — predictions-backed skills don't
    # actually query Neo4j, so the memory-side KG flag is moot here.
    # KG_GRAPH_WINDOW is auto-detected: when window extractions exist,
    # we surface the capability (Phase 3.1 — RQ-A6 closure path).
    window_ext_path = (
        global_dir / "v2_kg_extractions_windows" / "all_extractions.jsonl"
    )
    has_kg_graph_window = window_ext_path.exists()
    if has_kg_graph_window:
        logging.info("KG_GRAPH_WINDOW: window extractions found at %s",
                     window_ext_path)
    obs_ctx = ObservationContext(
        dataset_id=dataset_id,
        has_memory_text=True,
        has_kg_graph_memory=False,
        has_kg_graph_window=has_kg_graph_window,
    )

    harness = EvalHarness(
        controller=controller,
        runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer=StateLayer() if use_state_layer else None,
    )

    contract = ApplesToApplesContract(
        dataset_id=dataset_id,
        split="test",
        gold_relation="coarse",
        memory_pool_size=0,                  # populated by the v2 loader; smoke = 0
        evaluation_mode="telemetry_diagnosis",
    )
    return harness, contract


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True,
                   help="OB dataset root")
    p.add_argument("--split", default="test", choices=["train", "validation", "test"])
    p.add_argument("--limit", type=int, default=None,
                   help="cap number of cases (smoke convenience)")
    p.add_argument("--trace-root", type=Path, default=None,
                   help="Persist per-window traces to "
                        "<trace-root>/<experiment>/<window_id>.json. "
                        "Needed for C7 multi-window suppression analysis.")
    p.add_argument("--cache-dir", type=Path, default=None,
                   help="SkillCache root (default: no cache, every skill runs)")
    p.add_argument("--output", type=Path, default=None,
                   help="write the EvaluationReport JSON here")
    p.add_argument("--include-verifier", action="store_true",
                   help="register verify_with_llm (off by default — needs "
                        "VERIFIER_KNOWN_HELPFUL flag from agent-config)")
    p.add_argument("--no-state", action="store_true",
                   help="disable the cross-window state layer + page-suppression")
    p.add_argument("--skip-skill", action="append", default=[],
                   metavar="NAME",
                   help="drop a skill from the registry; repeatable")
    p.add_argument("--order-by-incident-time", action="store_true",
                   help="sort cases by (service, episode, start_time) so "
                        "the StateLayer sees multi-window incident sequences "
                        "(closes RQ-C7 page-suppression)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"[smoke_ob] loading cases from {args.global_dir} (split={args.split})")
    cases = load_ob_cases(
        args.global_dir, split=args.split, limit=args.limit,
        order_by_incident_time=args.order_by_incident_time,
    )
    print(f"[smoke_ob] loaded {len(cases)} cases")

    harness, contract = _build_harness(
        args.global_dir,
        cache_dir=args.cache_dir,
        trace_root=args.trace_root,
        skip=set(args.skip_skill),
        include_verifier=args.include_verifier,
        use_state_layer=not args.no_state,
    )

    print(f"[smoke_ob] running agent over {len(cases)} cases...")
    report = harness.evaluate(
        cases,
        contract=contract,
        experiment_name=f"ob-smoke-{args.global_dir.name}",
    )

    # ------------------------------------------------------------------ output
    print()
    print("=" * 70)
    print(f"  Agent smoke test — {args.global_dir.name}")
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
    print(f"  Cache hit rate                  {report.cache_hit_rate:.3f}")
    print(f"  Distinct plan IDs               {len(report.plan_ids_seen)}")
    print(f"  Total cost: tokens={report.total_cost.llm_tokens} "
          f"usd={report.total_cost.usd:.4f} "
          f"sec={report.total_cost.wall_seconds:.2f}")
    print("=" * 70)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report.write_to(args.output, include_case_results=True)
        print(f"[smoke_ob] wrote report -> {args.output}")


if __name__ == "__main__":
    main()
