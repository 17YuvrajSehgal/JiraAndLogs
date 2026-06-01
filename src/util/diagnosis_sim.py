"""Phase E — time-to-diagnose simulation.

Converts retrieval metrics into the engineer-time-saved framing reviewers
care about: how many minutes does the on-call engineer spend before they
identify the right past ticket?

Model:
  - The engineer scans ranked candidates serially, ~T_per_candidate seconds
    each (reading title + skimming description + rejecting irrelevant
    candidates). Default 30s per docs review.
  - If a gold-matching ticket appears at rank r in the ranked list (1-indexed),
    diagnosis_time = T_per_candidate * r seconds.
  - If no gold-matching ticket appears at any rank, the engineer falls
    back to manual investigation (diagnosis_time = T_fallback, default
    30 minutes).
  - For pipelines with no retrieval head (HGB, telemetry-only),
    every resolvable incident takes T_fallback (no candidates to
    show the engineer).

The simulator runs per-window over the test split's retrievable
incidents (gold_label=ticket_worthy AND gold_matched_issue_ids non-empty)
and reports mean / median time-to-diagnose per pipeline.

Reads predictions from per-window-predictions.jsonl (cheap, stdlib only).
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def diagnosis_seconds(retrieved_ids, gold_ids, *, t_per_candidate=30.0, t_fallback=1800.0):
    if not gold_ids:
        return None  # not a resolvable incident
    gold_set = set(gold_ids)
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in gold_set:
            return t_per_candidate * i
    return t_fallback


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--out-md", type=Path, default=None)
    p.add_argument("--t-per-candidate", type=float, default=30.0,
                   help="Seconds per candidate the engineer reviews")
    p.add_argument("--t-fallback", type=float, default=1800.0,
                   help="Seconds the engineer spends when no candidate is helpful")
    p.add_argument("--top-k", type=int, default=10,
                   help="Engineer scans at most top-K candidates")
    args = p.parse_args()

    rows = []
    with args.predictions.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    pipelines = sorted({r["pipeline_name"] for r in rows})

    summary = {
        "params": {
            "t_per_candidate_s": args.t_per_candidate,
            "t_fallback_s": args.t_fallback,
            "top_k": args.top_k,
        },
        "per_pipeline": {},
    }

    for pname in pipelines:
        pipe_rows = [
            r for r in rows
            if r["pipeline_name"] == pname
            and r.get("gold_label") == "ticket_worthy"
            and r.get("gold_matched_issue_ids")
        ]
        seconds = []
        n_found = 0
        for r in pipe_rows:
            retrieved = (r.get("matched_issue_ids") or [])[: args.top_k]
            t = diagnosis_seconds(
                retrieved,
                r["gold_matched_issue_ids"],
                t_per_candidate=args.t_per_candidate,
                t_fallback=args.t_fallback,
            )
            if t is None:
                continue
            seconds.append(t)
            if t < args.t_fallback:
                n_found += 1
        if not seconds:
            continue
        summary["per_pipeline"][pname] = {
            "n_resolvable": len(seconds),
            "n_found_in_top_k": n_found,
            "find_rate": n_found / len(seconds),
            "mean_minutes": sum(seconds) / len(seconds) / 60,
            "median_minutes": statistics.median(seconds) / 60,
            "p25_minutes": statistics.quantiles(seconds, n=4)[0] / 60 if len(seconds) >= 4 else None,
            "p75_minutes": statistics.quantiles(seconds, n=4)[2] / 60 if len(seconds) >= 4 else None,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[diagnosis_sim] wrote {args.out}")

    # Markdown
    md = [
        "# Time-to-diagnose simulation (Phase E)",
        "",
        f"Parameters: `t_per_candidate={args.t_per_candidate:.0f}s`, "
        f"`t_fallback={args.t_fallback/60:.0f}min`, "
        f"`top_k={args.top_k}` (engineer scans at most this many candidates).",
        "",
        "| Pipeline | n resolvable | Found in top-K | Find rate | Mean min | Median min |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pname in sorted(summary["per_pipeline"]):
        s = summary["per_pipeline"][pname]
        md.append(
            f"| `{pname}` | {s['n_resolvable']} | {s['n_found_in_top_k']} | "
            f"{s['find_rate']:.3f} | {s['mean_minutes']:.2f} | {s['median_minutes']:.2f} |"
        )
    md.append("")
    md.append("Interpretation:")
    md.append("- Lower mean / median minutes = faster diagnosis.")
    md.append(f"- Find rate < 1.0 means a fraction of incidents fall back to {args.t_fallback/60:.0f}min manual investigation.")

    out_md = args.out_md or args.out.with_suffix(".md")
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"[diagnosis_sim] wrote {out_md}")


if __name__ == "__main__":
    main()
