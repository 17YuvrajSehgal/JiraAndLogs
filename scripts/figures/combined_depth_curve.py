"""High-quality anchor figure with three subplots (Hit@1, Hit@5, MRR).

Designed for the ICSE paper. Single matplotlib figure with 1 row × 3 cols,
shared x-axis (depth bucket), each subplot showing one metric.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


BUCKETS = [
    ("0", lambda n: n == 0),
    ("1-2", lambda n: 1 <= n <= 2),
    ("3-5", lambda n: 3 <= n <= 5),
    ("6-20", lambda n: 6 <= n <= 20),
    ("21+", lambda n: n >= 21),
]
BUCKET_LABELS = ["0", "1-2", "3-5", "6-20", "21+"]


def hit_at_k(retrieved, gold, k):
    return 1.0 if any(r in set(gold) for r in retrieved[:k]) else 0.0


def mrr(retrieved, gold):
    gold_set = set(gold)
    for i, r in enumerate(retrieved, start=1):
        if r in gold_set:
            return 1.0 / i
    return 0.0


def bootstrap(values, *, n_resamples=1000, seed=42):
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    pt = sum(values) / n
    means = []
    for _ in range(n_resamples):
        s = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(s) / n)
    means.sort()
    return pt, means[int(0.025 * (n_resamples - 1))], means[int(0.975 * (n_resamples - 1))]


def is_retr(r):
    return r.get("gold_label") == "ticket_worthy" and bool(r.get("gold_matched_issue_ids"))


def per_pipeline_curve(rows, pname, metric_fn):
    """Returns list of (point, lo, hi) per bucket."""
    out = []
    for _, pred in BUCKETS:
        bucket_rows = [
            r for r in rows
            if r["pipeline_name"] == pname
            and is_retr(r)
            and pred(r.get("n_prior_family_tickets") or 0)
        ]
        vals = [
            metric_fn(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [])
            for r in bucket_rows
        ]
        out.append(bootstrap(vals))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    rows = []
    with args.predictions.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    pipelines = sorted({r["pipeline_name"] for r in rows})
    print(f"[combined_depth_curve] pipelines: {pipelines}")

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
        "hist_gradient_boosting_numeric": "HGB (telemetry only)",
        "memorygraph_v2_sota_nw080": "SOTA + off-the-shelf reranker",
        "memorygraph_v2_sota_nw080_ft": "SOTA + fine-tuned reranker",
    }

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=120, sharex=True)
    x = np.arange(len(BUCKETS))

    panels = [
        ("Hit@1", lambda r, g: hit_at_k(r, g, 1), axes[0]),
        ("Hit@5", lambda r, g: hit_at_k(r, g, 5), axes[1]),
        ("MRR",   mrr,                                axes[2]),
    ]
    for title, fn, ax in panels:
        for p in pipelines:
            curve = per_pipeline_curve(rows, p, fn)
            pts = np.array([c[0] for c in curve])
            los = np.array([c[1] for c in curve])
            his = np.array([c[2] for c in curve])
            yerr = np.array([pts - los, his - pts])
            ax.errorbar(x, pts, yerr=yerr,
                        color=colors.get(p), marker=markers.get(p, "x"),
                        linewidth=2, markersize=8, capsize=4, elinewidth=1.5,
                        label=labels.get(p, p))
        ax.set_xticks(x)
        ax.set_xticklabels(BUCKET_LABELS)
        ax.set_xlabel("Compatible prior tickets in memory")
        ax.set_ylabel(title)
        ax.set_ylim(bottom=-0.02)
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_title(title, fontsize=12)

    # Single legend at the top
    handles, lbls = axes[0].get_legend_handles_labels()
    fig.legend(handles, lbls, loc="upper center",
               bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=True)
    fig.suptitle("Retrieval quality scales with deployment history (95% bootstrap CIs)",
                 fontsize=13, y=1.05)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    fig.savefig(args.out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[combined_depth_curve] wrote {args.out} (+pdf)")


if __name__ == "__main__":
    main()
