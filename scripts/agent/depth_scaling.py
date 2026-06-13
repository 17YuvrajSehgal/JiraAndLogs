"""RQ-B2 — depth-scaling analysis on cached predictions.

Stratifies a predictions JSONL by `n_prior_family_tickets` and bootstraps
Hit@K + MRR per bucket. Closes the depth-scaling story: "does retrieval
performance grow with deployment history?"

Default buckets follow the catalogue (`docs7/RESEARCH-QUESTIONS.md` §B2):
  0, 1–10, 11–50, 51–200, 201+

Suitable for:
  - **OB cascade Final** (1008 windows; depth field populated by the
    cascade build). Use this for the paper's depth-scaling figure.
  - Any other dataset whose predictions JSONL carries
    `n_prior_family_tickets` per row.

WoL caveat: the published WoL Mode 3 predictions all have
`n_prior_family_tickets=0` (the test set wasn't stratified by depth at
build time). The script reports zero-only buckets honestly so the reader
sees the gap; closing it on WoL would require a depth annotation pass.

Usage:
    PYTHONPATH=src python scripts/agent/depth_scaling.py \\
        --predictions \\
            data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \\
        --output data/agent_runs/ob-depth-scaling.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    DEFAULT_CONFIDENCE,
    DEFAULT_N_RESAMPLES,
    DEFAULT_SEED,
    bootstrap_metric,
    metric_hit_at_1,
    metric_hit_at_5,
    metric_mrr,
    rows_from_dicts,
)


#: Catalogue buckets. (lo, hi_inclusive, label).
DEFAULT_BUCKETS: list[tuple[int, int, str]] = [
    (0, 0, "0"),
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 10_000_000, "201+"),
]


def _bucket_for(n: int, buckets) -> str:
    for lo, hi, label in buckets:
        if lo <= n <= hi:
            return label
    return "?"


def _read_predictions(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logging.warning("skipping malformed line in %s", path)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True,
                   help="predictions JSONL with `n_prior_family_tickets` per row")
    p.add_argument("--pipeline-name", default=None,
                   help="optional filter (when the JSONL has multiple pipelines)")
    p.add_argument("--n-resamples", type=int, default=DEFAULT_N_RESAMPLES)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    rows = _read_predictions(args.predictions)
    if args.pipeline_name:
        rows = [r for r in rows if r.get("pipeline_name") == args.pipeline_name]
    print(f"[depth_scaling] loaded {len(rows)} prediction rows from {args.predictions}")

    by_bucket: dict[str, list[dict]] = {label: [] for _, _, label in DEFAULT_BUCKETS}
    for r in rows:
        n = r.get("n_prior_family_tickets") or 0
        b = _bucket_for(n, DEFAULT_BUCKETS)
        by_bucket[b].append(r)

    print()
    print("=" * 88)
    print(f"  Depth-scaling analysis — {args.predictions.parent.name}")
    print(f"  n_resamples={args.n_resamples}  seed={args.seed}")
    print("=" * 88)
    print(f"  {'bucket':<8} {'n':>5} {'n_eval':>7} "
          f"{'Hit@1':>22} {'Hit@5':>22} {'MRR':>22}")
    print("  " + "-" * 86)

    report: dict = {"buckets": {}, "n_total": len(rows)}

    for label in (b for _, _, b in DEFAULT_BUCKETS):
        sub_rows = by_bucket[label]
        if not sub_rows:
            print(f"  {label:<8} {0:>5} {'-':>7} {'(empty bucket)':<22}")
            report["buckets"][label] = {"n": 0, "n_evaluable": 0,
                                        "metrics": {}}
            continue
        bs_rows = rows_from_dicts(sub_rows)
        n_eval = sum(1 for r in sub_rows if r.get("gold_matched_issue_ids"))

        bucket_metrics: dict = {}
        h1 = bootstrap_metric(bs_rows, metric_hit_at_1,
                              metric_name="hit_at_1",
                              n_resamples=args.n_resamples,
                              seed=args.seed, confidence=args.confidence)
        h5 = bootstrap_metric(bs_rows, metric_hit_at_5,
                              metric_name="hit_at_5",
                              n_resamples=args.n_resamples,
                              seed=args.seed, confidence=args.confidence)
        mrr = bootstrap_metric(bs_rows, metric_mrr,
                               metric_name="mrr",
                               n_resamples=args.n_resamples,
                               seed=args.seed, confidence=args.confidence)
        bucket_metrics = {
            "hit_at_1": h1.to_dict(),
            "hit_at_5": h5.to_dict(),
            "mrr": mrr.to_dict(),
        }
        report["buckets"][label] = {
            "n": len(sub_rows),
            "n_evaluable": n_eval,
            "metrics": bucket_metrics,
        }
        print(
            f"  {label:<8} {len(sub_rows):>5} {n_eval:>7} "
            f"{h1.point_estimate:>6.4f} [{h1.ci_low:>5.3f},{h1.ci_high:>5.3f}] "
            f"{h5.point_estimate:>6.4f} [{h5.ci_low:>5.3f},{h5.ci_high:>5.3f}] "
            f"{mrr.point_estimate:>6.4f} [{mrr.ci_low:>5.3f},{mrr.ci_high:>5.3f}]"
        )
    print("=" * 88)

    # Lightweight monotonicity check — is the trend in the right
    # direction? "Yes" means each populated bucket is >= the previous one.
    populated = [
        (label, report["buckets"][label]["metrics"].get("hit_at_5", {}).get("point_estimate"))
        for _, _, label in DEFAULT_BUCKETS
        if report["buckets"][label]["n"] > 0 and report["buckets"][label]["n_evaluable"] > 0
    ]
    if len(populated) >= 2:
        h5s = [v for _, v in populated]
        monotonic = all(h5s[i] <= h5s[i + 1] for i in range(len(h5s) - 1))
        print(f"\n  Hit@5 monotonicity across populated buckets: "
              f"{'YES' if monotonic else 'NO'}  "
              f"({[round(v, 3) for v in h5s]})")
        report["monotonic_hit_at_5"] = bool(monotonic)
        report["hit_at_5_sequence"] = h5s

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str),
                                encoding="utf-8")
        print(f"\n[depth_scaling] wrote -> {args.output}")


if __name__ == "__main__":
    main()
