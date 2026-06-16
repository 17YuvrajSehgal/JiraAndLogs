"""Phase 3 — bootstrap CIs on a flat predictions JSONL (RQ-A6 + RQ-C1).

Where `bootstrap_headlines.py` consumes EvaluationReport JSONs from the
agent's smokes, this script handles **flat predictions JSONLs** — the
shape the cascade emits at `comparison/<pipeline>/per-window-predictions.jsonl`
and the WoL Mode 3 refit at `tch-lite-refit/<retriever>-predictions.jsonl`.

Use cases:
  - **WoL Mode 3 (RQ-A6)** — bootstrap each retriever's per-project +
    overall Hit@K. Adds statistical envelope to the published numbers
    (BiEncoder coarse Hit@5 = 0.959, Hybrid-RRF strong Hit@5 = 0.787).
  - **OB cascade Final** — bootstrap the locked baseline.
  - **Paired Δ-CIs** between two pipelines (e.g., BiEncoder vs
    Hybrid-RRF, or pre/post symmetric extraction).

Usage:
    PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \\
        --predictions \\
            data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/biencoder-predictions.jsonl \\
            data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/hybrid-rrf-predictions.jsonl \\
            data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/logseq2vec-predictions.jsonl \\
            data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/kg-retrieval-predictions.jsonl \\
        --paired bi_encoder_retrieval hybrid_rrf_retrieval \\
        --output data/agent_runs/wol-mode3-bootstrap.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    DEFAULT_CONFIDENCE,
    DEFAULT_N_RESAMPLES,
    DEFAULT_SEED,
    bootstrap_metric,
    metric_hit_at_1,
    metric_hit_at_5,
    metric_hit_at_10,
    metric_mrr,
    paired_bootstrap_delta,
    rows_from_dicts,
)


def _load_predictions(
    paths: list[Path],
) -> dict[str, list[dict[str, Any]]]:
    """Read every JSONL and bucket rows by `pipeline_name`."""
    by_pipeline: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        if not path.exists():
            logging.warning("skipping missing %s", path)
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pname = row.get("pipeline_name") or path.stem
                by_pipeline[pname].append(row)
    return by_pipeline


def _stratify_by_project(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """For Mode 3 WoL data, the row's `wol_project` (or `scenario_family`)
    identifies which Apache project the window came from. Return a
    project → rows mapping. Returns {"_all": rows} when no project is set."""
    by_proj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    n_with_proj = 0
    for r in rows:
        proj = r.get("wol_project") or r.get("scenario_family")
        if proj:
            n_with_proj += 1
        by_proj[proj or "_all"].append(r)
    if n_with_proj == 0:
        return {"_all": rows}
    return by_proj


def _bootstrap_pipeline(
    pipeline_name: str,
    rows: list[dict[str, Any]],
    *,
    n_resamples: int,
    seed: int,
    confidence: float,
) -> dict:
    bs_rows = rows_from_dicts(rows)
    out: dict[str, Any] = {
        "pipeline_name": pipeline_name,
        "n_rows": len(rows),
        "overall": {},
        "per_project": {},
    }
    for m_name, m_fn in (
        ("hit_at_1", metric_hit_at_1),
        ("hit_at_5", metric_hit_at_5),
        ("hit_at_10", metric_hit_at_10),
        ("mrr", metric_mrr),
    ):
        bs = bootstrap_metric(
            bs_rows, m_fn, metric_name=m_name,
            n_resamples=n_resamples, seed=seed, confidence=confidence,
        )
        out["overall"][m_name] = bs.to_dict()

    by_proj = _stratify_by_project(rows)
    if list(by_proj) != ["_all"]:
        for proj, sub in sorted(by_proj.items()):
            sub_rows = rows_from_dicts(sub)
            proj_metrics: dict[str, Any] = {"n_rows": len(sub)}
            for m_name, m_fn in (
                ("hit_at_1", metric_hit_at_1),
                ("hit_at_5", metric_hit_at_5),
                ("mrr", metric_mrr),
            ):
                bs = bootstrap_metric(
                    sub_rows, m_fn, metric_name=m_name,
                    n_resamples=n_resamples, seed=seed, confidence=confidence,
                )
                proj_metrics[m_name] = bs.to_dict()
            out["per_project"][proj] = proj_metrics
    return out


def _paired_delta(
    a_name: str, a_rows: list[dict[str, Any]],
    b_name: str, b_rows: list[dict[str, Any]],
    *,
    n_resamples: int, seed: int, confidence: float,
) -> dict | None:
    """Align by window_id and run paired Δ-CIs on Hit@K + MRR."""
    a_by_wid = {r["window_id"]: r for r in a_rows if "window_id" in r}
    b_by_wid = {r["window_id"]: r for r in b_rows if "window_id" in r}
    common = sorted(set(a_by_wid) & set(b_by_wid))
    if not common:
        logging.warning(
            "no common window_ids between %s and %s; skipping paired",
            a_name, b_name,
        )
        return None
    a_aligned = rows_from_dicts(a_by_wid[w] for w in common)
    b_aligned = rows_from_dicts(b_by_wid[w] for w in common)

    out: dict[str, Any] = {
        "a_label": a_name, "b_label": b_name,
        "n_common_windows": len(common),
        "deltas": {},
    }
    for m_name, m_fn in (
        ("hit_at_1", metric_hit_at_1),
        ("hit_at_5", metric_hit_at_5),
        ("hit_at_10", metric_hit_at_10),
        ("mrr", metric_mrr),
    ):
        pbr = paired_bootstrap_delta(
            a_aligned, b_aligned, m_fn,
            metric_name=m_name,
            a_label=a_name, b_label=b_name,
            n_resamples=n_resamples, seed=seed, confidence=confidence,
        )
        out["deltas"][m_name] = pbr.to_dict()
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, nargs="+", required=True,
                   help="one or more predictions JSONL paths")
    p.add_argument("--paired", nargs=2, action="append", default=[],
                   metavar=("A", "B"),
                   help="pipeline_name pair for paired Δ-CI (repeatable)")
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

    print(f"[bootstrap_preds] loading {len(args.predictions)} predictions file(s)")
    by_pipeline = _load_predictions(args.predictions)
    print(f"[bootstrap_preds] found pipelines: {sorted(by_pipeline)}")

    report: dict[str, Any] = {
        "n_resamples": args.n_resamples,
        "seed": args.seed,
        "confidence": args.confidence,
        "pipelines": {},
        "paired": [],
    }

    for pname, rows in sorted(by_pipeline.items()):
        print(f"\n[bootstrap_preds] bootstrapping {pname} ({len(rows)} rows)...")
        report["pipelines"][pname] = _bootstrap_pipeline(
            pname, rows,
            n_resamples=args.n_resamples,
            seed=args.seed, confidence=args.confidence,
        )

    # ---------- print headline table
    print()
    print("=" * 88)
    print(f"  Headline bootstrap (n_resamples={args.n_resamples}, seed={args.seed})")
    print("=" * 88)
    print(f"  {'pipeline':<32} {'metric':<10} {'point':>8}  {'95% CI':>20}")
    print("  " + "-" * 75)
    for pname in sorted(report["pipelines"]):
        block = report["pipelines"][pname]
        for m_name, mbs in block["overall"].items():
            print(f"  {pname:<32} {m_name:<10} "
                  f"{mbs['point_estimate']:>8.4f}  "
                  f"[{mbs['ci_low']:>7.4f}, {mbs['ci_high']:>7.4f}]")
        print()

    # ---------- paired deltas
    for a_name, b_name in args.paired:
        if a_name not in by_pipeline or b_name not in by_pipeline:
            logging.warning("paired %s vs %s: pipeline missing; skipping",
                            a_name, b_name)
            continue
        d = _paired_delta(
            a_name, by_pipeline[a_name],
            b_name, by_pipeline[b_name],
            n_resamples=args.n_resamples,
            seed=args.seed, confidence=args.confidence,
        )
        if d:
            report["paired"].append(d)
            print(f"  Paired: {b_name} vs {a_name}  (n_common={d['n_common_windows']})")
            print(f"    {'metric':<10} {'delta':>9}  {'95% delta-CI':>22} {'fraction_better':>16}")
            print("    " + "-" * 60)
            for m_name, mbs in d["deltas"].items():
                sig = "*" if (mbs["delta_ci_low"] > 0 or mbs["delta_ci_high"] < 0) else " "
                print(f"    {m_name:<10} "
                      f"{mbs['delta_point']:>+9.4f}  "
                      f"[{mbs['delta_ci_low']:>+7.4f}, {mbs['delta_ci_high']:>+7.4f}] "
                      f"{sig}  {mbs['fraction_b_better']:>14.3f}")
            print()
    if args.paired:
        print("    (* = 95% CI excludes zero)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str),
                                encoding="utf-8")
        print(f"\n[bootstrap_preds] wrote -> {args.output}")


if __name__ == "__main__":
    main()
