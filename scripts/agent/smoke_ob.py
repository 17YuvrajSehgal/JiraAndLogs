"""Smoke test: run the agent end-to-end on Online Boutique.

Loads OB test windows and dispatches to the shared
`agent.harness_builder.build_harness_for_dataset` factory — this
script's role is now CLI + dataset-loader-glue only. All wiring
lives in `src/agent/harness_builder.py` so OB / WoL / OTel Demo
smokes share one source of truth (Phase 3 task #101).

Usage:
    PYTHONPATH=src python scripts/agent/smoke_ob.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        [--limit 100] \\
        [--split test] \\
        [--cache-dir data/skill_cache] \\
        [--output results/ob/agent-runs/ob-fulltest-2026-06-12.json]

Skip flags:
    --no-verifier        don't even register verify_with_llm (cheap smoke)
    --no-state           run without page-suppression
    --skip-skill <name>  drop a skill from the registry (repeatable)
    --max-tool-calls N   cap per-window ReAct tool budget (RQ-A7)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/agent/smoke_ob.py` (no PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders import load_ob_cases
from agent.harness_builder import build_harness_for_dataset


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
    p.add_argument("--max-tool-calls", type=int, default=None,
                   help="RQ-A7: cap per-window ReAct tool invocations. "
                        "When set to 0, all tool calls are refused with "
                        "BUDGET_EXHAUSTED (effectively disables ReAct). "
                        "Default: skill class default (6 — never hit on OB).")
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

    harness, contract = build_harness_for_dataset(
        dataset_label="online_boutique",
        global_dir=args.global_dir,
        cache_dir=args.cache_dir,
        trace_root=args.trace_root,
        skip=set(args.skip_skill),
        include_verifier=args.include_verifier,
        use_state_layer=not args.no_state,
        max_tool_calls=args.max_tool_calls,
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
    print(f"  Agent smoke test - {args.global_dir.name}")
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
