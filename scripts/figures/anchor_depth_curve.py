"""Phase A4.1 anchor figure: R@5 vs deployment-history depth.

Loads a comparison `report.json` produced by `python -m comparison.cli`
and draws the headline curve of the paper:

    x-axis: n_prior_family_tickets bucket
    y-axis: Recall@5
    one line per pipeline; HGB (no retrieval head) sits flat at zero,
    memorygraph_v2_sota_nw080 (and any other retrieval pipeline) rises
    with deployment history.

CI error bars come from `report.depth_ci_per_metric['recall_at_5']`
(charter §10 / Phase A3 — 1000 bootstrap resamples, paired).

Usage:
    python scripts/figures/anchor_depth_curve.py \\
        --report data/derived/global/<id>/comparison/phase-a-anchor/report.json \\
        --out-dir results/figures
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


BUCKET_ORDER = [
    "n_prior_family=0",
    "n_prior_family=1-2",
    "n_prior_family=3-5",
    "n_prior_family=6-20",
    "n_prior_family=21+",
]
BUCKET_LABELS = ["0", "1-2", "3-5", "6-20", "21+"]


def load_depth_table(report_path: Path, metric: str = "recall_at_5"):
    data = json.loads(report_path.read_text(encoding="utf-8"))
    depth = data.get("depth_ci_per_metric", {}).get(metric, {})
    pipelines = sorted({
        pname
        for stratum_data in depth.values()
        for pname in stratum_data
    })
    table: dict[str, list[tuple[float, float, float]]] = {p: [] for p in pipelines}
    for bucket in BUCKET_ORDER:
        per_pipe = depth.get(bucket, {})
        for p in pipelines:
            ci = per_pipe.get(p)
            if ci is None:
                table[p].append((np.nan, np.nan, np.nan))
            else:
                table[p].append((ci["point"], ci["lo"], ci["hi"]))
    return pipelines, table


def render_figure(pipelines, table, *, out_path: Path, metric_label: str):
    fig, ax = plt.subplots(figsize=(7.5, 4.5), dpi=120)
    x = np.arange(len(BUCKET_ORDER))
    colors = {
        "hist_gradient_boosting_numeric": "#888888",
        "memorygraph_v2_sota_nw080": "#1f77b4",
        "memorygraph_v2_sota_nw080_ft": "#d62728",
    }
    markers = {
        "hist_gradient_boosting_numeric": "s",
        "memorygraph_v2_sota_nw080": "o",
        "memorygraph_v2_sota_nw080_ft": "D",
    }
    labels = {
        "hist_gradient_boosting_numeric": "HGB (telemetry-only, no retrieval)",
        "memorygraph_v2_sota_nw080": "memorygraph SOTA (Jira memory)",
        "memorygraph_v2_sota_nw080_ft": "memorygraph SOTA + fine-tuned reranker",
    }
    for p in pipelines:
        points = np.array([t[0] for t in table[p]])
        los = np.array([t[1] for t in table[p]])
        his = np.array([t[2] for t in table[p]])
        yerr = np.array([points - los, his - points])
        ax.errorbar(
            x, points, yerr=yerr,
            marker=markers.get(p, "x"), color=colors.get(p, None),
            linewidth=2, markersize=9,
            capsize=4, elinewidth=1.5,
            label=labels.get(p, p),
        )
    ax.set_xticks(x)
    ax.set_xticklabels(BUCKET_LABELS)
    ax.set_xlabel("Number of compatible prior tickets in Jira memory")
    ax.set_ylabel(metric_label)
    ax.set_ylim(bottom=-0.02)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", frameon=True)
    ax.set_title(
        "Retrieval quality scales with deployment history\n"
        f"({metric_label}, 95% paired bootstrap CIs, 1000 resamples)"
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[anchor_depth_curve] wrote: {out_path} (+pdf)")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--out-dir", type=Path,
                   default=Path("results/figures"))
    p.add_argument("--metric", default="recall_at_5",
                   choices=["recall_at_5", "mrr", "pr_auc"])
    args = p.parse_args()

    pipelines, table = load_depth_table(args.report, args.metric)
    print(f"[anchor_depth_curve] pipelines: {pipelines}")
    label_map = {
        "recall_at_5": "Recall@5",
        "mrr": "MRR",
        "pr_auc": "PR-AUC",
    }
    out_path = args.out_dir / f"anchor_depth_{args.metric}.png"
    render_figure(pipelines, table, out_path=out_path,
                  metric_label=label_map[args.metric])

    # Also write a small CSV of the underlying numbers
    csv_path = args.out_dir / f"anchor_depth_{args.metric}.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("bucket,pipeline,point,lo,hi\n")
        for pipeline in pipelines:
            for bucket, (pt, lo, hi) in zip(BUCKET_LABELS, table[pipeline]):
                f.write(f"{bucket},{pipeline},{pt:.6f},{lo:.6f},{hi:.6f}\n")
    print(f"[anchor_depth_curve] wrote: {csv_path}")


if __name__ == "__main__":
    main()
