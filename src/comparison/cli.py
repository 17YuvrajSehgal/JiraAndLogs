"""CLI entrypoint: python -m comparison.cli ..."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import render_report_md, run_comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-dir", required=True, type=Path)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument(
        "--pipelines",
        default="loganalyzer,logsense",
        help="Comma-separated pipeline names (default: loganalyzer,logsense)",
    )
    parser.add_argument("--no-ensemble", action="store_true", default=False)
    parser.add_argument("--n-bootstrap", type=int, default=1000)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    report = run_comparison(
        global_dir=args.global_dir,
        runs_root=args.runs_root,
        pipelines=pipelines,
        include_ensemble=not args.no_ensemble,
        n_bootstrap=args.n_bootstrap,
        target_fpr=args.target_fpr,
    )

    output_dir = args.output_dir or (args.global_dir / "comparison" / "phase0")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")
    (output_dir / "report.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    # Per-window-per-pipeline predictions
    with (output_dir / "per-window-predictions.jsonl").open("w", encoding="utf-8") as fh:
        for r in report.results:
            for p in r.predictions:
                fh.write(json.dumps(p.as_dict()) + "\n")
    print(f"Wrote comparison report to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
