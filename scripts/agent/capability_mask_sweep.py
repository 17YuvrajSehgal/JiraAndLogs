"""Capability-mask robustness sweep — RQ-C4 closure.

The agent's adaptive design declares "capabilities, not datasets"
(AGENTIC-SYSTEM-V3 §7). RQ-C4 tests that claim: if we run the OB
test split with telemetry capabilities artificially stripped,
does the agent **gracefully degrade** rather than crash, and does
the Hit@K degradation match what we observe on datasets that
genuinely lack those modalities (e.g. WoL ≈ text-only mask)?

Mechanism: wrap the harness's `CapabilitiesObserver` in a masking
shim that drops the specified flags AFTER observation. The skills
that need those flags then auto-drop via `can_invoke()`; the
controller emits a different Plan.

Usage:
    PYTHONPATH=src python scripts/agent/capability_mask_sweep.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --output results/ob/4.4-capability-mask/sweep.json
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

from agent.capabilities import Capabilities
from agent.capabilities_observer import CapabilitiesObserver, ObservationContext
from agent.data_loaders import load_ob_cases, load_otel_demo_cases, load_wol_cases
from agent.harness_builder import build_harness_for_dataset


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskCell:
    """One cell of the capability-mask sweep."""
    label: str
    drop_flags: frozenset[str]
    description: str = ""


# ---------------------------------------------------------------------------
# Masking observer wrapper
# ---------------------------------------------------------------------------


class CapabilityMaskingObserver:
    """Wraps a CapabilitiesObserver to drop named flags from its output.

    Used by RQ-C4 to simulate "what if this dataset didn't have
    NUMERIC_FEATURES" without re-collecting the underlying data.
    """

    def __init__(
        self,
        inner: CapabilitiesObserver,
        drop_flags: frozenset[str],
    ) -> None:
        self._inner = inner
        self._drop_flags = frozenset(drop_flags)

    def observe(
        self,
        bundle,
        ctx: ObservationContext | None = None,
    ) -> Capabilities:
        caps = self._inner.observe(bundle, ctx)
        if not self._drop_flags:
            return caps
        return caps.mask(self._drop_flags)


# ---------------------------------------------------------------------------
# Sweep cells — one mask per cell
# ---------------------------------------------------------------------------


OB_GRID: tuple[MaskCell, ...] = (
    MaskCell(label="baseline", drop_flags=frozenset(),
             description="full capabilities — reference point"),
    MaskCell(label="no_numeric",
             drop_flags=frozenset({"NUMERIC_FEATURES"}),
             description="no Prometheus features — kills triage_numeric"),
    MaskCell(label="no_trace_summary",
             drop_flags=frozenset({"TRACE_SUMMARY"}),
             description="no Tempo — kills request_extended_trace_window"),
    MaskCell(label="no_k8s",
             drop_flags=frozenset({"K8S_EVENTS"}),
             description="no k8s events — kills request_pod_events"),
    MaskCell(label="no_metric_snapshots",
             drop_flags=frozenset({"METRIC_SNAPSHOTS"}),
             description="no Prometheus snapshots — kills request_pod_metrics"),
    MaskCell(label="text_only",
             drop_flags=frozenset({
                 "NUMERIC_FEATURES", "ORDERED_LOGS", "TRACE_SUMMARY",
                 "K8S_EVENTS", "METRIC_SNAPSHOTS",
             }),
             description="all telemetry stripped — approximates WoL"),
    MaskCell(label="logs_text_only",
             drop_flags=frozenset({
                 "NUMERIC_FEATURES", "TRACE_SUMMARY",
                 "K8S_EVENTS", "METRIC_SNAPSHOTS",
             }),
             description="keep logs+text; strip metrics/traces/k8s"),
    MaskCell(label="numeric_text_only",
             drop_flags=frozenset({
                 "ORDERED_LOGS", "TRACE_SUMMARY",
                 "K8S_EVENTS", "METRIC_SNAPSHOTS",
             }),
             description="keep numeric+text; strip logs/traces/k8s"),
)


GRIDS = {"ob": OB_GRID}            # WoL/OTel grids when their data lands

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
    cell: MaskCell,
    *,
    use_state: bool,
) -> dict:
    """Run one mask cell. Wraps the harness's observer."""
    harness, contract = build_harness_for_dataset(
        dataset_label=DATASET_TO_LABEL[dataset],
        global_dir=global_dir,
        cache_dir=None,
        trace_root=None,
        skip=set(),
        include_verifier=False,
        use_state_layer=use_state,
        experiment_prefix=f"caps-mask-{cell.label}",
    )
    # Swap in the masking observer (EvalHarness.observer attribute)
    harness.observer = CapabilityMaskingObserver(
        harness.observer, cell.drop_flags,
    )

    t0 = time.monotonic()
    report = harness.evaluate(
        cases, contract=contract,
        experiment_name=f"caps-mask-{cell.label}-{global_dir.name}",
    )
    wall_sec = time.monotonic() - t0
    return {
        "cell": cell.label,
        "drop_flags": sorted(cell.drop_flags),
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
    baseline = next(r for r in rows if r["cell"] == baseline_label)
    b_h1 = baseline["hit_at_1"]
    b_h5 = baseline["hit_at_5"]
    b_mrr = baseline["mrr"]
    b_tr = baseline["triage_accuracy"]
    lines: list[str] = []
    lines.append("| Mask | Hit@1 | Δ | Hit@5 | Δ | MRR | Δ | Triage acc | Δ |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['cell']} | "
            f"{r['hit_at_1']:.4f} | {r['hit_at_1'] - b_h1:+.4f} | "
            f"{r['hit_at_5']:.4f} | {r['hit_at_5'] - b_h5:+.4f} | "
            f"{r['mrr']:.4f} | {r['mrr'] - b_mrr:+.4f} | "
            f"{r['triage_accuracy']:.4f} | {r['triage_accuracy'] - b_tr:+.4f} |"
        )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(GRIDS), required=True)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--use-state", action="store_true")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    grid = GRIDS[args.dataset]
    print(f"[caps_mask] loading cases from {args.global_dir} (split={args.split})")
    cases = _load_cases(args.dataset, args.global_dir,
                        split=args.split, limit=args.limit)
    print(f"[caps_mask] loaded {len(cases)} cases; grid has {len(grid)} cells")

    rows: list[dict] = []
    for i, cell in enumerate(grid, 1):
        print(f"\n[caps_mask] {i:>2}/{len(grid)}  mask={cell.label} "
              f"({sorted(cell.drop_flags) if cell.drop_flags else 'none'}) ...")
        row = run_cell(args.dataset, args.global_dir, cases, cell,
                       use_state=args.use_state)
        rows.append(row)
        print(
            f"            Hit@1={row['hit_at_1']:.4f}  "
            f"Hit@5={row['hit_at_5']:.4f}  MRR={row['mrr']:.4f}  "
            f"plans={row['n_distinct_plan_ids']}  "
            f"wall={row['wall_seconds']:.2f}s"
        )

    print()
    print("=" * 100)
    print(f"  RQ-C4 capability-mask sweep — {args.dataset.upper()}")
    print("=" * 100)
    print(format_table(rows))
    print("=" * 100)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "dataset": args.dataset,
            "dataset_id": args.global_dir.name,
            "split": args.split,
            "n_cases": rows[0]["n_cases"] if rows else 0,
            "n_evaluable": rows[0]["n_evaluable"] if rows else 0,
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print(f"\n[caps_mask] wrote JSON -> {args.output}")


if __name__ == "__main__":
    main()
