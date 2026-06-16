"""Phase 3.5 — bootstrap CIs for every headline (RQ-C1 closure).

Reads one or more existing EvaluationReport JSONs (the smokes + the
ablation grid) and adds 95% percentile CIs via 1,000-resample paired
bootstrap (seed=42, the §12 contract).

For each input report:
  - Loads case_results from the JSON
  - Bootstraps Hit@1, Hit@5, Hit@10, MRR, triage_accuracy
  - Writes a *-bootstrap.json alongside the input

For ablation grid JSONs (multiple reports inside one file):
  - Bootstraps each ablation row independently
  - Plus paired bootstrap of baseline vs each ablation for delta-CIs
    (using the same case window_ids in each pair)

Usage:
    PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \\
        --reports data/agent_runs/ob-smoke-full.json \\
                  data/agent_runs/wol-smoke.json \\
        [--ablation-grids data/agent_runs/ob-ablation.json \\
                          data/agent_runs/wol-ablation.json] \\
        [--n-resamples 1000] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    CaseResult,
    DEFAULT_CONFIDENCE,
    DEFAULT_N_RESAMPLES,
    DEFAULT_SEED,
    bootstrap_eval_report,
    metric_hit_at_1,
    metric_hit_at_5,
    metric_mrr,
    metric_triage_accuracy,
    paired_bootstrap_delta,
)


def _load_case_results(report_dict: dict) -> list[CaseResult]:
    return [CaseResult.from_dict(c) for c in (report_dict.get("case_results") or [])]


def _bootstrap_single(
    report_dict: dict,
    *,
    report_label: str,
    n_resamples: int,
    seed: int,
    confidence: float,
) -> dict:
    cases = _load_case_results(report_dict)
    bs = bootstrap_eval_report(
        cases,
        name=report_label,
        n_resamples=n_resamples,
        seed=seed,
        confidence=confidence,
    )
    return bs.to_dict()


def _print_metric_row(name: str, bs_dict: dict) -> None:
    width = bs_dict["ci_high"] - bs_dict["ci_low"]
    print(f"    {name:<22} "
          f"{bs_dict['point_estimate']:>8.4f}  "
          f"[{bs_dict['ci_low']:>7.4f}, {bs_dict['ci_high']:>7.4f}]  "
          f"width={width:.4f}")


def _print_report_header(label: str, report_dict: dict) -> None:
    print()
    print("=" * 78)
    print(f"  Bootstrap CIs — {label}")
    print(f"  n_cases={report_dict['n_cases']}  "
          f"n_resamples={report_dict['n_resamples']}  "
          f"seed={report_dict['seed']}  conf={report_dict['confidence']:.2f}")
    print("=" * 78)
    print(f"    {'metric':<22} {'point':>8}  {'95% CI':>20}")
    print("    " + "-" * 55)


# ---------------------------------------------------------------------------
# Single-report handler
# ---------------------------------------------------------------------------


def handle_single_report(
    path: Path,
    *,
    n_resamples: int,
    seed: int,
    confidence: float,
) -> dict:
    print(f"\n[bootstrap] loading {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("case_results"):
        print(f"  {path.name}: no case_results in report — skipping.")
        return {}

    name = data.get("name") or path.stem
    bs = _bootstrap_single(
        data, report_label=name,
        n_resamples=n_resamples, seed=seed, confidence=confidence,
    )

    _print_report_header(name, bs)
    for metric_name, metric_bs in bs["metrics"].items():
        _print_metric_row(metric_name, metric_bs)

    out = path.with_name(path.stem + "-bootstrap.json")
    out.write_text(json.dumps(bs, indent=2), encoding="utf-8")
    print(f"  wrote -> {out}")
    return bs


# ---------------------------------------------------------------------------
# Ablation-grid handler (paired bootstrap baseline-vs-each-ablation)
# ---------------------------------------------------------------------------


def handle_ablation_grid(
    path: Path,
    *,
    n_resamples: int,
    seed: int,
    confidence: float,
) -> dict:
    print(f"\n[bootstrap] loading {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    baseline_report = data.get("baseline_report")
    ablation_reports = data.get("ablation_reports") or {}
    if not baseline_report or not ablation_reports:
        print(f"  {path.name}: missing baseline_report or ablation_reports — "
              f"may be missing case_results too. Skipping.")
        return {}

    baseline_cases = _load_case_results(baseline_report)
    if not baseline_cases:
        print(f"  {path.name}: baseline has no case_results — re-run the "
              f"ablation harness with keep_case_details=True. Skipping.")
        return {}

    # 1. Per-row CI
    grid_out: dict = {"per_row": {}, "paired_deltas": {}}

    print()
    print("=" * 90)
    print(f"  Ablation grid bootstrap — {path.stem}")
    print(f"  baseline n={len(baseline_cases)}  "
          f"n_resamples={n_resamples}  seed={seed}  conf={confidence:.2f}")
    print("=" * 90)

    print(f"    {'row':<22} {'metric':<10} {'point':>8}  {'95% CI':>20}")
    print("    " + "-" * 67)

    # Baseline row
    bs_base = _bootstrap_single(
        baseline_report, report_label="baseline",
        n_resamples=n_resamples, seed=seed, confidence=confidence,
    )
    grid_out["per_row"]["baseline"] = bs_base
    for m, mbs in bs_base["metrics"].items():
        print(f"    {'baseline':<22} {m:<10} "
              f"{mbs['point_estimate']:>8.4f}  "
              f"[{mbs['ci_low']:>7.4f}, {mbs['ci_high']:>7.4f}]")

    # Ablation rows + paired delta-CIs vs baseline
    baseline_by_wid = {c.bundle_id: c for c in baseline_cases}

    for ablation_name, ablation_report in ablation_reports.items():
        ablation_cases = _load_case_results(ablation_report)
        bs_a = _bootstrap_single(
            ablation_report, report_label=ablation_name,
            n_resamples=n_resamples, seed=seed, confidence=confidence,
        )
        grid_out["per_row"][ablation_name] = bs_a
        print()
        for m, mbs in bs_a["metrics"].items():
            print(f"    {ablation_name:<22} {m:<10} "
                  f"{mbs['point_estimate']:>8.4f}  "
                  f"[{mbs['ci_low']:>7.4f}, {mbs['ci_high']:>7.4f}]")

        # Paired delta-CIs: align baseline_cases ↔ ablation_cases by window_id
        ablation_by_wid = {c.bundle_id: c for c in ablation_cases}
        common_ids = [
            wid for wid in baseline_by_wid
            if wid in ablation_by_wid
        ]
        a_rows = [baseline_by_wid[wid] for wid in common_ids]
        b_rows = [ablation_by_wid[wid] for wid in common_ids]
        if not common_ids:
            continue

        deltas_for_row: dict[str, dict] = {}
        for m_name, m_fn in (
            ("hit_at_1", metric_hit_at_1),
            ("hit_at_5", metric_hit_at_5),
            ("mrr", metric_mrr),
            ("triage_accuracy", metric_triage_accuracy),
        ):
            pbr = paired_bootstrap_delta(
                a_rows, b_rows, m_fn,
                metric_name=m_name,
                a_label="baseline", b_label=ablation_name,
                n_resamples=n_resamples, seed=seed,
                confidence=confidence,
            )
            deltas_for_row[m_name] = pbr.to_dict()
        grid_out["paired_deltas"][ablation_name] = deltas_for_row

    # Print the paired-delta table
    print()
    print(f"  Paired delta-CIs vs baseline (Hit@5):")
    print(f"    {'ablation':<22} {'delta_point':>9}  {'95% delta-CI':>22} {'fraction_better':>16}")
    print("    " + "-" * 70)
    for name, deltas in grid_out["paired_deltas"].items():
        dh5 = deltas["hit_at_5"]
        sig = "*" if (dh5["delta_ci_low"] > 0 or dh5["delta_ci_high"] < 0) else " "
        print(f"    {name:<22} "
              f"{dh5['delta_point']:>+9.4f}  "
              f"[{dh5['delta_ci_low']:>+7.4f}, {dh5['delta_ci_high']:>+7.4f}] "
              f"{sig}  "
              f"{dh5['fraction_b_better']:>14.3f}")
    print("    (* = 95% CI excludes zero)")

    out = path.with_name(path.stem + "-bootstrap.json")
    out.write_text(json.dumps(grid_out, indent=2), encoding="utf-8")
    print(f"\n  wrote -> {out}")
    return grid_out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports", type=Path, nargs="*", default=[],
                   help="EvaluationReport JSONs to bootstrap individually")
    p.add_argument("--ablation-grids", type=Path, nargs="*", default=[],
                   help="AblationGridResult JSONs to bootstrap (per-row + paired)")
    p.add_argument("--n-resamples", type=int, default=DEFAULT_N_RESAMPLES)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.reports and not args.ablation_grids:
        raise SystemExit("supply at least one --reports or --ablation-grids path")

    for r in args.reports:
        if not r.exists():
            print(f"[bootstrap] skipping missing {r}")
            continue
        handle_single_report(
            r, n_resamples=args.n_resamples,
            seed=args.seed, confidence=args.confidence,
        )

    for g in args.ablation_grids:
        if not g.exists():
            print(f"[bootstrap] skipping missing {g}")
            continue
        handle_ablation_grid(
            g, n_resamples=args.n_resamples,
            seed=args.seed, confidence=args.confidence,
        )


if __name__ == "__main__":
    main()
