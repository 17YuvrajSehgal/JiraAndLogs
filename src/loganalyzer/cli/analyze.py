"""CLI: end-to-end analysis on a global derived directory.

Usage:
    python -m loganalyzer.cli.analyze \
        --global-dir data/derived/global/2026-05-21-dataset-v4-pilot-global \
        --triage-model hybrid \
        --retriever bm25 \
        --output-dir data/derived/global/2026-05-21-dataset-v4-pilot-global/loganalyzer/v1

Picks a triage model + retriever, runs the full eval, writes report.json
and a small report.md alongside per-window predictions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..data.loaders import load_dataset
from ..eval.runner import run_full_evaluation
from ..memory.corpus import MemoryCorpus
from ..memory.retrieval import (
    BM25Retriever,
    EmbeddingHashingRetriever,
    HybridRetriever,
)
from ..product.analyzer import SmartLogAnalyzer
from ..triage.hybrid import HybridTriageModel
from ..triage.lexical import LexicalTriageModel
from ..triage.logistic import LogisticTriageModel
from ..triage.rule import RuleTriageModel


TRIAGE_MODELS = {
    "rule": "RuleTriageModel",
    "logistic": "LogisticTriageModel",
    "lexical": "LexicalTriageModel",
    "hybrid": "HybridTriageModel",
}
RETRIEVERS = {
    "bm25": "BM25Retriever",
    "embedding": "EmbeddingHashingRetriever",
    "hybrid": "HybridRetriever",
}


def _build_triage(name: str, feature_columns: list[str]):
    if name == "rule":
        return RuleTriageModel()
    if name == "logistic":
        return LogisticTriageModel(feature_columns)
    if name == "lexical":
        return LexicalTriageModel()
    if name == "hybrid":
        return HybridTriageModel(feature_columns)
    raise ValueError(f"Unknown triage model: {name}")


def _build_retriever(name: str):
    if name == "bm25":
        return BM25Retriever()
    if name == "embedding":
        return EmbeddingHashingRetriever()
    if name == "hybrid":
        return HybridRetriever()
    raise ValueError(f"Unknown retriever: {name}")


def _render_report_md(report_dict: dict) -> str:
    lines: list[str] = []
    lines.append(f"# loganalyzer benchmark report")
    lines.append("")
    lines.append(f"Pipeline: `{report_dict['pipeline_name']}`")
    lines.append("")
    lines.append(f"Operating threshold (picked on validation @ FPR<=5%): {report_dict['triage_threshold']:.4f}")
    lines.append("")
    lines.append("## Split sizes")
    for k, v in report_dict["split_sizes"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    for mode in ("strict", "inclusive"):
        lines.append(f"## Triage metrics ({mode}, borderline={'positive' if mode=='inclusive' else 'negative'})")
        for key in (
            "pr_auc",
            "roc_auc",
            "expected_calibration_error",
            "precision_at_fpr_1pct",
            "recall_at_fpr_1pct",
            "precision_at_fpr_5pct",
            "recall_at_fpr_5pct",
            "f_beta_2_at_fpr_5pct",
        ):
            val = report_dict[mode].get(key)
            if isinstance(val, float):
                lines.append(f"- {key}: {val:.4f}")
            else:
                lines.append(f"- {key}: {val}")
        lines.append("")
    lines.append("## Retrieval metrics (on ticket-worthy test windows)")
    for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "n_eval_windows"):
        val = report_dict["retrieval"].get(key)
        if isinstance(val, float):
            lines.append(f"- {key}: {val:.4f}")
        else:
            lines.append(f"- {key}: {val}")
    lines.append("")
    lines.append("## Novelty (predicted ticket-worthy & gold ticket-worthy)")
    for key in ("precision", "recall", "f1", "n"):
        val = report_dict["novelty"].get(key)
        if isinstance(val, float):
            lines.append(f"- {key}: {val:.4f}")
        else:
            lines.append(f"- {key}: {val}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-dir", required=True, type=Path)
    parser.add_argument("--triage-model", choices=sorted(TRIAGE_MODELS), default="hybrid")
    parser.add_argument("--retriever", choices=sorted(RETRIEVERS), default="bm25")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    dataset = load_dataset(args.global_dir)
    triage = _build_triage(args.triage_model, dataset.feature_columns)
    retriever = _build_retriever(args.retriever)
    corpus = MemoryCorpus(issues=dataset.memory_corpus, mode="time_ordered")

    analyzer = SmartLogAnalyzer(
        triage_model=triage,
        retriever=retriever,
        memory_corpus=corpus,
        retrieval_top_k=args.top_k,
    )
    report, per_window = run_full_evaluation(analyzer, dataset, target_fpr=args.target_fpr)
    report_dict = report.as_dict()

    output_dir = args.output_dir or (
        args.global_dir / "loganalyzer" / f"{args.triage_model}-{args.retriever}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(_render_report_md(report_dict), encoding="utf-8")
    (output_dir / "per-window-predictions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in per_window) + "\n", encoding="utf-8"
    )
    print(f"Wrote report to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
