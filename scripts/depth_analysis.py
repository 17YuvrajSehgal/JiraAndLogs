"""Phase A4.1 — depth-stratified analysis with corrected retrieval metrics.

The existing `recall_at_k` is implemented as |top_K ∩ gold| / |gold| —
which mechanically drops as |gold| grows beyond K. This script
computes the canonical IR metrics directly from per-window-predictions:

  Hit@K  = 1 if any gold in top-K else 0    (the right "did the engineer find one" metric)
  R@K_norm = |top_K ∩ gold| / min(K, |gold|)  (capacity-normalized recall)
  P@K    = |top_K ∩ gold| / K                (precision)
  MRR    = 1 / rank_of_first_gold

The depth-stratification axis is `n_prior_family_tickets` (= len(gold_matched_issue_ids))
bucketed into {0, 1-2, 3-5, 6-20, 21+}.

Output:
  results/phase-a-anchor/depth_analysis.json   raw numbers + bootstrap CIs
  results/phase-a-anchor/depth_analysis.md     human-readable table
  results/figures/anchor_depth_hit5.{png,pdf}  the headline figure
  results/figures/anchor_depth_mrr.{png,pdf}   secondary figure
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


BUCKETS = [
    ("n_prior_family=0", lambda n: n == 0),
    ("n_prior_family=1-2", lambda n: 1 <= n <= 2),
    ("n_prior_family=3-5", lambda n: 3 <= n <= 5),
    ("n_prior_family=6-20", lambda n: 6 <= n <= 20),
    ("n_prior_family=21+", lambda n: n >= 21),
]
BUCKET_LABELS = ["0", "1-2", "3-5", "6-20", "21+"]


def hit_at_k(retrieved, gold, k):
    gold_set = set(gold)
    return 1.0 if any(r in gold_set for r in retrieved[:k]) else 0.0


def recall_at_k_norm(retrieved, gold, k):
    if not gold:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in set(gold))
    return hits / min(k, len(gold))


def precision_at_k(retrieved, gold, k):
    if not retrieved:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in set(gold))
    return hits / k


def mrr(retrieved, gold):
    gold_set = set(gold)
    for i, r in enumerate(retrieved, start=1):
        if r in gold_set:
            return 1.0 / i
    return 0.0


def bootstrap_ci(values, n_resamples=1000, confidence=0.95, seed=42):
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    pt = sum(values) / n
    resampled_means = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        s = [values[i] for i in idx]
        resampled_means.append(sum(s) / n)
    resampled_means.sort()
    alpha = (1 - confidence) / 2
    lo = resampled_means[max(0, int(round(alpha * (len(resampled_means) - 1))))]
    hi = resampled_means[min(len(resampled_means) - 1, int(round((1 - alpha) * (len(resampled_means) - 1))))]
    return pt, lo, hi


def load_predictions(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--fig-dir", type=Path,
                        default=Path("results/figures"))
    parser.add_argument("--n-resamples", type=int, default=1000)
    args = parser.parse_args()

    rows = load_predictions(args.predictions)
    print(f"[depth_analysis] loaded {len(rows)} prediction rows")

    # Group rows by (pipeline, bucket)
    pipelines = sorted({r["pipeline_name"] for r in rows})
    print(f"[depth_analysis] pipelines: {pipelines}")

    # We only score retrievable rows (gold_matched_issue_ids non-empty AND
    # gold_label == ticket_worthy — the standard retrieval-set filter).
    def is_retrievable(r):
        return (
            r.get("gold_label") == "ticket_worthy"
            and bool(r.get("gold_matched_issue_ids"))
        )

    # For each pipeline x bucket, compute four metrics with CIs
    out: dict = {
        "buckets": BUCKET_LABELS,
        "pipelines": pipelines,
        "metrics": {},
        "n_per_bucket": {},
    }
    metric_fns = {
        "hit_at_5": lambda r: hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5),
        "hit_at_1": lambda r: hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 1),
        "hit_at_3": lambda r: hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 3),
        "mrr": lambda r: mrr(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or []),
        "precision_at_5": lambda r: precision_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5),
        "recall_at_5_norm": lambda r: recall_at_k_norm(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5),
    }
    for metric_name, fn in metric_fns.items():
        out["metrics"][metric_name] = {}
        for bucket_name, bucket_pred in BUCKETS:
            out["metrics"][metric_name][bucket_name] = {}
            for p in pipelines:
                rows_in = [
                    r for r in rows
                    if r["pipeline_name"] == p
                    and is_retrievable(r)
                    and bucket_pred(r.get("n_prior_family_tickets") or 0)
                ]
                values = [fn(r) for r in rows_in]
                point, lo, hi = bootstrap_ci(values, n_resamples=args.n_resamples)
                out["metrics"][metric_name][bucket_name][p] = {
                    "point": point, "lo": lo, "hi": hi, "n": len(values),
                }
                if metric_name == "hit_at_5":  # record n once
                    out["n_per_bucket"].setdefault(bucket_name, {})[p] = len(values)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[depth_analysis] wrote JSON: {args.out_json}")

    # Build the markdown table
    md_lines = ["# Depth-Stratified Retrieval Analysis", "",
                "Computed from `per-window-predictions.jsonl` with bootstrap CIs (n_resamples=1000, seed=42).",
                "",
                "Stratification axis: `n_prior_family_tickets` = number of memory tickets the gold-truth matcher considers compatible with each window (i.e., |gold_matched_issue_ids|).",
                "",
                "## Why Hit@5 is the primary metric",
                "",
                "The standard `recall@K = |top_K ∩ gold| / |gold|` definition mechanically *drops* as |gold| grows beyond K (e.g., with |gold|=21, max possible recall@5 = 5/21 = 0.238). This makes deep-history buckets look worse than they are. **Hit@K** = `1 if any gold in top-K else 0` is the right metric for 'did the engineer find a relevant ticket'.",
                "",
                ""]
    for metric_name in ["hit_at_5", "hit_at_3", "hit_at_1", "mrr", "precision_at_5", "recall_at_5_norm"]:
        md_lines.append(f"## {metric_name}")
        md_lines.append("")
        header = "| Bucket | n |"
        sep = "|---|---:|"
        for p in pipelines:
            header += f" {p} |"
            sep += " ---: |"
        md_lines.append(header)
        md_lines.append(sep)
        for bucket_name in [b for b, _ in BUCKETS]:
            ns = [out["metrics"][metric_name][bucket_name][p]["n"] for p in pipelines]
            n_disp = ns[0] if all(n == ns[0] for n in ns) else "/".join(map(str, ns))
            row = f"| {bucket_name.replace('n_prior_family=', '')} | {n_disp} |"
            for p in pipelines:
                v = out["metrics"][metric_name][bucket_name][p]
                row += f" {v['point']:.4f} [{v['lo']:.4f}, {v['hi']:.4f}] |"
            md_lines.append(row)
        md_lines.append("")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[depth_analysis] wrote MD: {args.out_md}")

    # Plot Hit@5 and MRR figures
    args.fig_dir.mkdir(parents=True, exist_ok=True)
    plot_figure(out, "hit_at_5", "Hit@5", "Probability gold appears in top-5",
                args.fig_dir / "anchor_depth_hit5.png")
    plot_figure(out, "mrr", "MRR", "Mean Reciprocal Rank",
                args.fig_dir / "anchor_depth_mrr.png")
    plot_figure(out, "hit_at_1", "Hit@1", "Probability gold is top-1",
                args.fig_dir / "anchor_depth_hit1.png")
    plot_figure(out, "precision_at_5", "Precision@5", "Precision in top-5",
                args.fig_dir / "anchor_depth_precision5.png")


def plot_figure(data, metric, title, ylabel, out_path):
    pipelines = data["pipelines"]
    buckets = [b for b, _ in BUCKETS]
    x = np.arange(len(buckets))
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=120)
    colors = {
        "hist_gradient_boosting_numeric": "#888888",
        "tab_transformer": "#9467bd",
        "memorygraph_v2_sota_nw080": "#1f77b4",
        "memorygraph_v2_sota_nw080_ft": "#d62728",
        "bi_encoder_retrieval": "#2ca02c",
    }
    markers = {
        "hist_gradient_boosting_numeric": "s",
        "tab_transformer": "v",
        "memorygraph_v2_sota_nw080": "o",
        "memorygraph_v2_sota_nw080_ft": "D",
        "bi_encoder_retrieval": "^",
    }
    labels = {
        "hist_gradient_boosting_numeric": "HGB on telemetry (no retrieval head)",
        "tab_transformer": "TabTransformer on telemetry",
        "memorygraph_v2_sota_nw080": "memorygraph SOTA + Jira memory",
        "memorygraph_v2_sota_nw080_ft": "memorygraph SOTA + fine-tuned reranker",
        "bi_encoder_retrieval": "Fine-tuned BiEncoder (this paper)",
    }
    for p in pipelines:
        points = np.array([data["metrics"][metric][b][p]["point"] for b in buckets])
        los = np.array([data["metrics"][metric][b][p]["lo"] for b in buckets])
        his = np.array([data["metrics"][metric][b][p]["hi"] for b in buckets])
        yerr = np.array([points - los, his - points])
        ax.errorbar(
            x, points, yerr=yerr,
            marker=markers.get(p, "x"), color=colors.get(p, None),
            linewidth=2.0, markersize=9, capsize=4, elinewidth=1.4,
            label=labels.get(p, p),
        )
    ax.set_xticks(x)
    ax.set_xticklabels(BUCKET_LABELS)
    ax.set_xlabel("Number of compatible prior tickets in Jira memory  (depth)")
    ax.set_ylabel(ylabel)
    ax.set_ylim(bottom=-0.02)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", frameon=True, fontsize=9)
    ax.set_title(f"Retrieval quality vs deployment history\n({title}, 95% bootstrap CI)")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[depth_analysis] wrote: {out_path} (+pdf)")


if __name__ == "__main__":
    main()
