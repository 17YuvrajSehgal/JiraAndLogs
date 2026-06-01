"""Per-family × per-depth cross-stratification of retrieval metrics.

Reads per-window-predictions.jsonl and produces a markdown table where
each row is a (family × depth bucket) cell and columns are pipelines.

This is the "fine-grained breakdown" reviewers will ask for: does the
depth-scaling story hold across all retrievable scenario families?
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


BUCKETS = [
    ("0", lambda n: n == 0),
    ("1-2", lambda n: 1 <= n <= 2),
    ("3-5", lambda n: 3 <= n <= 5),
    ("6-20", lambda n: 6 <= n <= 20),
    ("21+", lambda n: n >= 21),
]


def hit_at_k(retrieved, gold, k):
    return 1.0 if any(r in set(gold) for r in retrieved[:k]) else 0.0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--out-md", type=Path, required=True)
    args = p.parse_args()

    rows = []
    with args.predictions.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    pipelines = sorted({r["pipeline_name"] for r in rows})

    def is_retr(r):
        return (
            r.get("gold_label") == "ticket_worthy"
            and bool(r.get("gold_matched_issue_ids"))
        )

    # Group by (pipeline, family, bucket)
    cells = defaultdict(list)  # (pipeline, family, bucket) -> [hit@5 values]
    counts = defaultdict(int)  # (family, bucket) -> n
    for r in rows:
        if not is_retr(r): continue
        n = r.get("n_prior_family_tickets") or 0
        bucket = next((b for b, pred in BUCKETS if pred(n)), None)
        family = r.get("scenario_family") or "?"
        hit = hit_at_k(r["matched_issue_ids"] or [], r["gold_matched_issue_ids"] or [], 5)
        cells[(r["pipeline_name"], family, bucket)].append(hit)
        counts[(family, bucket)] = max(counts[(family, bucket)], len(cells[(r["pipeline_name"], family, bucket)]))

    # Build markdown
    md = ["# Per-family × per-depth Hit@5 cross-stratification", ""]
    md.append("Cells = mean Hit@5. Empty cells = zero retrievable windows in that (family, bucket).")
    md.append("")
    families = sorted({f for (_, f, _) in cells})
    buckets = ["1-2", "3-5", "6-20", "21+"]  # skip 0 (always empty for retrievable)
    md.append("## Per pipeline tables")
    md.append("")
    for pname in pipelines:
        md.append(f"### {pname}")
        md.append("")
        header = "| family | " + " | ".join(buckets) + " |"
        sep = "|---|" + " ---: |" * len(buckets)
        md.append(header)
        md.append(sep)
        for fam in families:
            vals = []
            for b in buckets:
                hits = cells.get((pname, fam, b))
                if not hits:
                    vals.append("—")
                else:
                    vals.append(f"{sum(hits)/len(hits):.3f} (n={len(hits)})")
            md.append(f"| `{fam}` | " + " | ".join(vals) + " |")
        md.append("")

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"[per_family_depth] wrote {args.out_md}")


if __name__ == "__main__":
    main()
