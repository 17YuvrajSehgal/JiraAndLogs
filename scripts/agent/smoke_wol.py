"""Smoke test: run the agent end-to-end on World of Logs.

WoL is the **text-retrieval generalisation** dataset
(`evaluation_mode = "text_retrieval_generalisation"`). The point of
this smoke is to demonstrate the agent's **capability-adaptive**
design: the SAME `CapabilityAwareRuleController`, given the same
skill registry, emits a different Plan on WoL because:

  - `NUMERIC_FEATURES` flag is absent → `triage_numeric` is dropped.
  - `ORDERED_LOGS` is absent → `retrieve_log_sequence` is dropped.
  - `VERIFIER_KNOWN_HELPFUL` is absent (WoL is in
    `VerifierCalibration.known_harmful_distributions` per Mode 3
    §3.9) → `verify_with_llm` is structurally skipped (RQ-A8).
  - The 3 telemetry ReAct tools (`request_pod_events`,
    `request_extended_trace_window`, `request_pod_metrics`) are
    dropped because their capability flags (`K8S_EVENTS`,
    `TRACE_SUMMARY`, `METRIC_SNAPSHOTS`) aren't surfaced — the
    loader deliberately omits the corresponding fetchable markers.
  - `request_similar_incident_window` IS available (no required
    flags; reads the in-memory corpus) — so peers-only ReAct fires.

This smoke uses `agent.harness_builder.build_harness_for_dataset`
with `dataset_label="wol"` — same source of truth as `smoke_ob.py`
and `smoke_otel_demo.py`, per Phase 3 task #101.

Usage:
    PYTHONPATH=src python scripts/agent/smoke_wol.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        [--limit 100] [--split test] [--cache-dir data/skill_cache] \\
        [--output results/wol-v2/agent-runs/wol-fulltest.json]

The smoke asserts the RQ-A8 structural-skip property after the run:
`verify_with_llm` must NOT appear in any case's invocations.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders import load_wol_cases
from agent.harness_builder import build_harness_for_dataset


def _assert_verifier_structurally_skipped(report) -> None:
    """Fail loudly if `verify_with_llm` shows up in any case's
    invocations. This is the RQ-A8 closure check: WoL must never
    invoke the verifier."""
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
    p.add_argument("--split", default="test",
                   choices=["train", "validation", "test"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--trace-root", type=Path, default=None,
                   help="Persist per-window traces to "
                        "<trace-root>/<experiment>/<window_id>.json.")
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--include-verifier", action="store_true",
                   help="register verify_with_llm (still capability-gated so "
                        "it cannot actually run on WoL — useful for asserting "
                        "the structural skip on a fully-registered controller)")
    p.add_argument("--no-state", action="store_true")
    p.add_argument("--skip-skill", action="append", default=[], metavar="NAME")
    p.add_argument("--order-by-incident-time", action="store_true",
                   help="sort cases by (service, episode, start_time) so "
                        "the StateLayer sees multi-window incident sequences "
                        "(closes RQ-C7 page-suppression)")
    p.add_argument("--max-tool-calls", type=int, default=None,
                   help="RQ-A7: cap per-window ReAct tool invocations.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"[smoke_wol] loading cases from {args.global_dir} (split={args.split})")
    cases = load_wol_cases(
        args.global_dir, split=args.split, limit=args.limit,
        order_by_incident_time=args.order_by_incident_time,
    )
    print(f"[smoke_wol] loaded {len(cases)} cases")

    harness, contract = build_harness_for_dataset(
        dataset_label="wol",
        global_dir=args.global_dir,
        cache_dir=args.cache_dir,
        trace_root=args.trace_root,
        skip=set(args.skip_skill),
        include_verifier=args.include_verifier,
        use_state_layer=not args.no_state,
        max_tool_calls=args.max_tool_calls,
    )

    print(f"[smoke_wol] running agent over {len(cases)} cases...")
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"wol-smoke-{args.global_dir.name}",
    )

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
