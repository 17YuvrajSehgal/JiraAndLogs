"""Phase C figure: per-channel ablation bar chart.

Reads phase-c-channels per-window-predictions.jsonl and renders a bar
chart of Hit@5 / Hit@1 / MRR for the full SOTA vs each masked variant.
The marginal drop = channel's contribution.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


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
    print(f"[channel_ablation] pipelines: {pipelines}")

    label_map = {
        "memorygraph_v2_sota_nw080": "SOTA (all channels)",
        "memorygraph_v2_sota_nw080_no_logs": "− logs",
        "memorygraph_v2_sota_nw080_no_traces": "− traces",
        "memorygraph_v2_sota_nw080_no_k8s": "− k8s events",
    }
    # Order: SOTA first, then ablations
    order = [
        "memorygraph_v2_sota_nw080",
        "memorygraph_v2_sota_nw080_no_logs",
        "memorygraph_v2_sota_nw080_no_traces",
        "memorygraph_v2_sota_nw080_no_k8s",
    ]
    order = [p for p in order if p in pipelines]

    h1, h5, m = [], [], []
    for pname in order:
        retr = [r for r in rows if r["pipeline_name"] == pname and is_retr(r)]
        h1.append(bootstrap([hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 1) for r in retr]))
        h5.append(bootstrap([hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5) for r in retr]))
        m.append(bootstrap([mrr(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or []) for r in retr]))

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)
    x = np.arange(len(order))
    width = 0.25
    metrics = [("Hit@1", h1, "#d62728"), ("Hit@5", h5, "#1f77b4"), ("MRR", m, "#2ca02c")]
    for i, (label, vals, color) in enumerate(metrics):
        pts = np.array([v[0] for v in vals])
        los = np.array([v[1] for v in vals])
        his = np.array([v[2] for v in vals])
        yerr = np.array([pts - los, his - pts])
        ax.bar(x + (i - 1) * width, pts, width, color=color, yerr=yerr,
               capsize=3, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels([label_map.get(p, p) for p in order], rotation=0)
    ax.set_ylabel("Retrieval metric (95% bootstrap CI)")
    ax.set_title("Per-channel ablation — which telemetry channel carries retrieval signal?")
    ax.legend(loc="upper right", frameon=True)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    fig.savefig(args.out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[channel_ablation] wrote {args.out} (+pdf)")


if __name__ == "__main__":
    main()
