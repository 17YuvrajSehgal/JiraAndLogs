"""CLI: log-only end-to-end analysis.

Usage:
    python -m logsense.cli.analyze \
        --global-dir data/derived/global/2026-05-21-dataset-v4-pilot-global \
        --runs-root  data/runs \
        --triage-model hybrid \
        --output-dir data/derived/global/2026-05-21-dataset-v4-pilot-global/logsense/v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loganalyzer.memory.corpus import MemoryCorpus

from ..data.dataset import load_logs_dataset
from ..eval.runner import run_log_evaluation
from ..memory.retrieval import LogTemplateBM25Retriever
from ..product.analyzer import LogSenseAnalyzer
from ..triage.anomaly import AnomalyScoreModel
from ..triage.hybrid import HybridLogModel
from ..triage.logistic import TemplateLogisticModel
from ..triage.rule import ErrorBurstRuleModel


TRIAGE_MODELS = ["rule", "logistic", "anomaly", "hybrid"]


def _build_triage(name: str):
    if name == "rule":
        return ErrorBurstRuleModel()
    if name == "logistic":
        return TemplateLogisticModel()
    if name == "anomaly":
        return AnomalyScoreModel()
    if name == "hybrid":
        return HybridLogModel()
    raise ValueError(f"Unknown triage model: {name}")


def _render_report_md(d: dict) -> str:
    lines = [f"# logsense benchmark report", "", f"Pipeline: `{d['pipeline_name']}`", "",
             f"Operating threshold (validation @ FPR<=5%): {d['triage_threshold']:.4f}", "",
             "## Split sizes"]
    for k, v in d["split_sizes"].items():
        lines.append(f"- {k}: {v}")
    for mode in ("strict", "inclusive"):
        lines.append("")
        lines.append(f"## Triage metrics ({mode})")
        for key in ("pr_auc", "roc_auc", "expected_calibration_error",
                    "precision_at_fpr_1pct", "recall_at_fpr_1pct",
                    "precision_at_fpr_5pct", "recall_at_fpr_5pct",
                    "f_beta_2_at_fpr_5pct"):
            v = d[mode].get(key)
            lines.append(f"- {key}: {v:.4f}" if isinstance(v, float) else f"- {key}: {v}")
    lines.append("")
    lines.append("## Retrieval metrics")
    for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "n_eval_windows"):
        v = d["retrieval"].get(key)
        lines.append(f"- {key}: {v:.4f}" if isinstance(v, float) else f"- {key}: {v}")
    lines.append("")
    lines.append("## Novelty")
    for key in ("precision", "recall", "f1", "n"):
        v = d["novelty"].get(key)
        lines.append(f"- {key}: {v:.4f}" if isinstance(v, float) else f"- {key}: {v}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-dir", required=True, type=Path)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--triage-model", choices=TRIAGE_MODELS, default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--skip-namespace-context", action="store_true", default=True)
    args = parser.parse_args(argv)

    print(f"Loading log dataset from {args.global_dir} (runs under {args.runs_root})...")
    ds = load_logs_dataset(
        args.global_dir,
        args.runs_root,
        skip_namespace_context=args.skip_namespace_context,
        progress_every=100,
    )
    print(
        f"  windows loaded={len(ds.labeled_windows)} "
        f"missing={len(ds.missing_window_ids)} "
        f"memory_issues={len(ds.memory_corpus)}"
    )

    analyzer = LogSenseAnalyzer(
        triage_model=_build_triage(args.triage_model),
        retriever=LogTemplateBM25Retriever(),
        memory_corpus=MemoryCorpus(issues=ds.memory_corpus),
        retrieval_top_k=args.top_k,
    )
    report, per_window = run_log_evaluation(analyzer, ds, target_fpr=args.target_fpr)
    report_dict = report.as_dict()

    output_dir = args.output_dir or (
        args.global_dir / "logsense" / f"{args.triage_model}-bm25"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(_render_report_md(report_dict), encoding="utf-8")
    (output_dir / "per-window-predictions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in per_window) + "\n", encoding="utf-8"
    )
    print(f"Wrote logsense report to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
