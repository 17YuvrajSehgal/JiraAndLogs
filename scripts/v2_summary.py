"""Cross-pipeline summary — pull headline metrics from all v1+v2 runs.

Walks every comparison/<run-id>/report.json, extracts the headline
metrics for every pipeline, and emits a single table you can paste
into the paper or compare side-by-side.

Usage:
    python scripts/v2_summary.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --out docs3/v2-headline-summary.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_run(report_path: Path) -> dict:
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    comp_root = args.global_dir / "comparison"
    runs = sorted(d for d in comp_root.iterdir() if d.is_dir())

    rows = []   # (run_id, pipeline_name, pr_auc, r1, r5, mrr)
    for rd in runs:
        report = load_run(rd / "report.json")
        if not report:
            continue
        for pname, m in report.get("headline", {}).items():
            rows.append({
                "run_id": rd.name,
                "pipeline": pname,
                "pr_auc":  m.get("triage.pr_auc"),
                "roc_auc": m.get("triage.roc_auc"),
                "r1":      m.get("retrieval.recall_at_1"),
                "r5":      m.get("retrieval.recall_at_5"),
                "mrr":     m.get("retrieval.mrr"),
                "n_retrievable": m.get("retrieval.n_retrievable"),
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# v1 + v2 headline metrics — all runs",
        "",
        "Aggregated from every `comparison/<run-id>/report.json`. Triage on full test split; retrieval on retrievable subset only.",
        "",
        "| Run | Pipeline | PR-AUC | ROC-AUC | R@1 | R@5 | MRR | n_retr |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        def fmt(x):
            return f"{x:.4f}" if isinstance(x, (int, float)) else (x or "—")
        lines.append(
            f"| `{r['run_id']}` | `{r['pipeline']}` | "
            f"{fmt(r['pr_auc'])} | {fmt(r['roc_auc'])} | "
            f"{fmt(r['r1'])} | {fmt(r['r5'])} | {fmt(r['mrr'])} | "
            f"{r.get('n_retrievable') or '—'} |"
        )
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
