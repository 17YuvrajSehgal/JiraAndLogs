"""Combine multiple comparison runs into a single headline table for the paper.

Each row is a pipeline; each column is a metric. Shows point estimates
+ 95% bootstrap CIs (when available). Designed to fit cleanly into a
two-column ICSE paper layout.

Reads multiple report.json files and per-window-predictions.jsonl to
re-compute Hit@K from scratch (since the canonical recall@K is capped).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


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


def load_preds(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def is_retr(r):
    return r.get("gold_label") == "ticket_worthy" and bool(r.get("gold_matched_issue_ids"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", nargs="+", type=Path, required=True)
    p.add_argument("--reports", nargs="+", type=Path, default=[],
                   help="Optional: report.json paths for PR-AUC / ROC-AUC")
    p.add_argument("--out-md", type=Path, required=True)
    args = p.parse_args()

    # Aggregate all prediction rows (across all comparison runs)
    all_preds = []
    seen = set()
    for path in args.predictions:
        for r in load_preds(path):
            key = (r["pipeline_name"], r["window_id"])
            if key in seen:
                continue
            seen.add(key)
            all_preds.append(r)
    pipelines = sorted({r["pipeline_name"] for r in all_preds})
    print(f"[headline_table] {len(pipelines)} pipelines, {len(all_preds)} prediction rows")

    # Aggregate report.json headlines
    headline_by_pipe = {}
    for rp in args.reports:
        d = json.loads(rp.read_text(encoding="utf-8"))
        for pname, m in d.get("headline", {}).items():
            headline_by_pipe[pname] = m

    md = [
        "# Headline results table",
        "",
        "Each row is a pipeline configuration. Columns are metric "
        "(point estimate, 95% bootstrap CI on Hit@K and MRR over 1000 "
        "resamples, seed=42).",
        "",
        "| Pipeline | n | PR-AUC | ROC-AUC | Hit@1 | Hit@5 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for pname in pipelines:
        retr = [r for r in all_preds
                if r["pipeline_name"] == pname and is_retr(r)]
        if not retr:
            continue
        h1_vals = [hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 1) for r in retr]
        h5_vals = [hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5) for r in retr]
        mrr_vals = [mrr(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or []) for r in retr]
        h1_pt, h1_lo, h1_hi = bootstrap(h1_vals)
        h5_pt, h5_lo, h5_hi = bootstrap(h5_vals)
        mrr_pt, mrr_lo, mrr_hi = bootstrap(mrr_vals)

        pra = headline_by_pipe.get(pname, {}).get("triage.pr_auc", float("nan"))
        roc = headline_by_pipe.get(pname, {}).get("triage.roc_auc", float("nan"))

        md.append(
            f"| `{pname}` | {len(retr)} | {pra:.4f} | {roc:.4f} | "
            f"{h1_pt:.3f} [{h1_lo:.3f}, {h1_hi:.3f}] | "
            f"{h5_pt:.3f} [{h5_lo:.3f}, {h5_hi:.3f}] | "
            f"{mrr_pt:.3f} [{mrr_lo:.3f}, {mrr_hi:.3f}] |"
        )
    md.append("")
    md.append("Notes:")
    md.append("- `n` = number of retrievable test windows (gold_label=ticket_worthy and non-empty gold_matched_issue_ids).")
    md.append("- HGB has zero matched_issue_ids by construction (no retrieval head); Hit@K and MRR are exactly 0.")
    md.append("- PR-AUC / ROC-AUC are computed over the full test set (n=2940), not just the retrievable subset.")

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"[headline_table] wrote {args.out_md}")


if __name__ == "__main__":
    main()
