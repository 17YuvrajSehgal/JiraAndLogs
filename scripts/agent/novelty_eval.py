"""Phase 3.3 — full-L3 novelty evaluation on WoL OOD queries.

Closes RQ-A5. Mode 2 reported the LOWER BOUND using only the free
signal (max-similarity threshold). This script runs the full L3
disjunction the cascade defines:

    is_novel = agent_novel OR free_signal OR learned_novel

over the 800 WoL OOD queries from
`<global_dir>/novelty-queries/windows.jsonl` and reports:

  - per-signal independent counts (which signal would fire on its own)
  - cumulative disjunction (free → free+agent → full L3)
  - novel precision + recall (against gold_is_novel)
  - per-project stratification (matches Mode 2's table format)

Signal sources:

  - free   — `<global_dir>/mode2_per_query.jsonl` (always present —
             precomputed during Mode 2)
  - agent  — `--agent-signal <path>` (optional; verifier predictions
             JSONL with `is_novel` per row)
  - learned — `--learned-signal <path>` (optional; predictions JSONL
              with `learned_novelty_prob` per row)

When agent or learned signals are omitted, the disjunction reduces to
the free signal alone (matching Mode 2 baseline). On a pure-OOD set
where every query is gold_is_novel, adding signals can only flag MORE
queries, all of which are TP → precision stays at 1.000.

Usage:
    PYTHONPATH=src python scripts/agent/novelty_eval.py \\
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global \\
        [--agent-signal <path>] \\
        [--learned-signal <path>] \\
        [--free-threshold 0.5] \\
        [--output data/agent_runs/wol-l3-novelty.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    DEFAULT_FREE_THRESHOLD,
    DEFAULT_LEARNED_THRESHOLD,
    evaluate_l3_novelty,
    load_agent_signal,
    load_free_signal,
    load_learned_signal,
    load_wol_ood_queries,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True,
                   help="WoL dataset root")
    p.add_argument("--queries", type=Path, default=None,
                   help="override path to novelty-queries/windows.jsonl")
    p.add_argument("--free-signal", type=Path, default=None,
                   help="override path to mode2_per_query.jsonl")
    p.add_argument("--agent-signal", type=Path, default=None,
                   help="verifier predictions JSONL (optional; pure-OOD "
                        "runs typically have no verifier signal because "
                        "RQ-A8 structurally disables the verifier on WoL)")
    p.add_argument("--learned-signal", type=Path, default=None,
                   help="learned-classifier predictions JSONL "
                        "(optional; absent in v1)")
    p.add_argument("--free-threshold", type=float, default=DEFAULT_FREE_THRESHOLD)
    p.add_argument("--learned-threshold", type=float, default=DEFAULT_LEARNED_THRESHOLD)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    queries_path = args.queries or (args.global_dir / "novelty-queries" / "windows.jsonl")
    free_path = args.free_signal or (args.global_dir / "mode2_per_query.jsonl")

    if not queries_path.exists():
        raise SystemExit(f"missing novelty queries: {queries_path}")
    if not free_path.exists():
        raise SystemExit(f"missing free signal: {free_path}")

    print(f"[novelty_eval] loading queries from {queries_path}")
    queries = load_wol_ood_queries(queries_path)
    print(f"[novelty_eval] loaded {len(queries)} queries")

    print(f"[novelty_eval] loading free signal from {free_path}")
    free_signal = load_free_signal(free_path, threshold=args.free_threshold)
    print(f"[novelty_eval] free signal: {len(free_signal)} flags loaded")

    agent_signal = None
    if args.agent_signal:
        agent_signal = load_agent_signal(args.agent_signal)
        print(f"[novelty_eval] agent signal: {len(agent_signal)} flags loaded")

    learned_signal = None
    if args.learned_signal:
        learned_signal = load_learned_signal(
            args.learned_signal, threshold=args.learned_threshold,
        )
        print(f"[novelty_eval] learned signal: {len(learned_signal)} flags loaded")

    report = evaluate_l3_novelty(
        queries=queries,
        free_signal=free_signal,
        agent_signal=agent_signal,
        learned_signal=learned_signal,
        free_threshold=args.free_threshold,
        learned_threshold=args.learned_threshold,
    )

    # ------------------------------------------------------------------ output
    print()
    print("=" * 78)
    print(f"  L3 Novelty Evaluation — RQ-A5")
    print("=" * 78)
    print(f"  n_queries:           {report.n_queries}")
    print(f"  n_gold_novel:        {report.n_gold_novel}")
    print(f"  free_threshold:      {report.free_threshold}")
    print(f"  signals available:   "
          f"free=on  "
          f"agent={'on' if report.agent_signal_present else 'off'}  "
          f"learned={'on' if report.learned_signal_present else 'off'}")
    print()
    print("  Per-signal independent flag counts:")
    print(f"    free_flagged       {report.free_flagged}")
    print(f"    agent_flagged      {report.agent_flagged}")
    print(f"    learned_flagged    {report.learned_flagged}")
    print()
    print("  Cumulative disjunction:")
    print(f"    free alone         {report.flagged_free_only}")
    print(f"    free OR agent      {report.flagged_free_or_agent}")
    print(f"    full L3            {report.flagged_full_l3}")
    print()
    print("  Final L3 metrics:")
    print(f"    novel_precision    {report.novel_precision:.4f}")
    print(f"    novel_recall       {report.novel_recall:.4f}")
    print(f"    n_true_positive    {report.n_true_positive_l3}")
    print(f"    n_false_positive   {report.n_false_positive_l3}")
    print("=" * 78)

    # Per-project breakdown (Mode 2 table reproduction)
    if report.per_project:
        proj_w = max(8, max(len(p) for p in report.per_project) + 2)
        print()
        print(f"  Per-project stratification at threshold={args.free_threshold}:")
        print(f"    {'project':<{proj_w}}  "
              f"{'n':>4} {'novel':>6} {'free':>6} {'agent':>6} "
              f"{'learned':>7} {'L3':>4} {'prec':>6} {'recall':>6}")
        print("    " + "-" * (proj_w + 56))
        for proj in sorted(report.per_project):
            b = report.per_project[proj]
            print(
                f"    {proj:<{proj_w}}  "
                f"{b['n_queries']:>4} {b['n_gold_novel']:>6} "
                f"{b['free_flagged']:>6} {b['agent_flagged']:>6} "
                f"{b['learned_flagged']:>7} {b['flagged_full_l3']:>4} "
                f"{b['precision']:>6.4f} {b['recall']:>6.4f}"
            )

    # RQ-A5 closure check
    print()
    if report.novel_precision >= 0.97:
        print(f"[novelty_eval] RQ-A5: PASS (precision {report.novel_precision:.4f} >= 0.97)")
    else:
        print(f"[novelty_eval] RQ-A5: FAIL (precision {report.novel_precision:.4f} < 0.97)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[novelty_eval] wrote report -> {args.output}")


if __name__ == "__main__":
    main()
