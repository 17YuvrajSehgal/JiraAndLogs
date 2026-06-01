"""Phase D figure: distractor robustness curve.

Reads multiple comparison `per-window-predictions.jsonl` files (one per
distractor ratio) and plots how Hit@K and MRR degrade as memory becomes
noisier with irrelevant tickets.
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
    p.add_argument("--predictions", type=Path, required=True,
                   help="Single combined per-window-predictions.jsonl across ratios")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    rows = []
    with args.predictions.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    # The pipeline names embed the ratio: memorygraph_v2_sota_d000pct, ..._d050pct
    pipelines = sorted({r["pipeline_name"] for r in rows
                        if "memorygraph_v2_sota_d" in r["pipeline_name"]})
    # Extract ratios
    def ratio_of(p):
        # e.g. "memorygraph_v2_sota_d025pct" -> 25
        return int(p.replace("memorygraph_v2_sota_d", "").replace("pct", ""))
    pipelines = sorted(pipelines, key=ratio_of)

    h1_curve, h5_curve, mrr_curve = [], [], []
    ratios = []
    for pname in pipelines:
        retr = [r for r in rows
                if r["pipeline_name"] == pname and is_retr(r)]
        if not retr:
            continue
        ratios.append(ratio_of(pname))
        h1 = [hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 1) for r in retr]
        h5 = [hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5) for r in retr]
        m  = [mrr(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or []) for r in retr]
        h1_curve.append(bootstrap(h1))
        h5_curve.append(bootstrap(h5))
        mrr_curve.append(bootstrap(m))

    if not ratios:
        print("[distractor_curve] no distractor-ratio pipelines found")
        return

    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    x = np.array(ratios)
    metrics = [
        ("Hit@5", h5_curve, "#1f77b4", "o"),
        ("Hit@1", h1_curve, "#d62728", "s"),
        ("MRR",   mrr_curve, "#2ca02c", "D"),
    ]
    for label, vals, color, marker in metrics:
        pts = np.array([v[0] for v in vals])
        los = np.array([v[1] for v in vals])
        his = np.array([v[2] for v in vals])
        yerr = np.array([pts - los, his - pts])
        ax.errorbar(x, pts, yerr=yerr, color=color, marker=marker,
                    linewidth=2, markersize=9, capsize=4, label=label)
    ax.set_xlabel("Fraction of memory occupied by distractor tickets (%)")
    ax.set_ylabel("Retrieval metric (95% bootstrap CI)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r}%" for r in x])
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper right", frameon=True)
    ax.set_title(
        "Retrieval robustness under distractor noise\n"
        f"(SOTA pipeline, V2 memory {347} real + N distractor tickets)"
    )
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    fig.savefig(args.out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[distractor_curve] wrote {args.out} (+pdf)")


if __name__ == "__main__":
    main()
