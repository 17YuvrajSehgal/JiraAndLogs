"""Standalone CLI: run the memorygraph pipeline and write rich artifacts.

The comparison harness gives us back a PipelineResult; this CLI writes:

  output_dir/
    predictions.jsonl       # one PipelinePrediction per test window
    explanations.jsonl      # one AgentDecision.as_dict() per test window
                            #   — includes skill chain, trace, top matches,
                            #     human-readable explanation
    graph-stats.json        # node/edge counts, bridges per kind, dropped
                            #   lab labels (the leakage-audit artifact)
    summary.md              # human-readable headline metrics + samples

Usage:
    python -m memorygraph.cli \\
        --global-dir data/derived/global/<id> \\
        --output-dir data/derived/global/<id>/memorygraph/baseline

Optional: --planner llm to use the LLMPlanner (LM Studio required).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure `src/` is on sys.path when invoked as `python -m memorygraph.cli`
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from loganalyzer.eval.metrics import pr_auc, roc_auc

from .pipeline import MemoryGraphPipeline


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="memorygraph.cli")
    p.add_argument("--global-dir", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument(
        "--planner", default="rule", choices=("rule", "llm"),
        help="Skill chain planner. 'llm' requires LM Studio at --llm-base-url.",
    )
    p.add_argument("--llm-base-url", default="http://localhost:1234")
    p.add_argument("--top-k-matches", type=int, default=5)
    p.add_argument("--target-fpr", type=float, default=0.05)
    p.add_argument(
        "--with-numeric", action="store_true",
        help="Hybrid mode: fit a HistGradientBoosting head on the train "
             "split and blend its per-window probability into the final "
             "triage_score. This is the 'memorygraph_hybrid' pipeline.",
    )
    p.add_argument(
        "--with-embeddings", action="store_true",
        help="Add Nomic dense embedding cosine similarity (via LM Studio) "
             "blended 50/50 with the BM25 similarity. Fails soft if LM "
             "Studio is unreachable.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = MemoryGraphPipeline(
        planner=args.planner,
        llm_base_url=args.llm_base_url,
        top_k_matches=args.top_k_matches,
        with_numeric=args.with_numeric,
        with_embeddings=args.with_embeddings,
    )
    result = pipeline.train_and_predict(
        args.global_dir, runs_root=Path("."), target_fpr=args.target_fpr,
    )

    # 1) predictions.jsonl
    predictions_path = args.output_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as fh:
        for pred in result.predictions:
            fh.write(json.dumps(pred.as_dict()) + "\n")

    # 2) explanations.jsonl — the artifact only this pipeline produces
    explanations_path = args.output_dir / "explanations.jsonl"
    with explanations_path.open("w", encoding="utf-8") as fh:
        for decision in pipeline.last_decisions:
            fh.write(json.dumps(decision.as_dict()) + "\n")

    # 3) graph-stats.json
    stats_path = args.output_dir / "graph-stats.json"
    stats_path.write_text(
        json.dumps(pipeline.last_graph_stats or {}, indent=2), encoding="utf-8"
    )

    # 4) summary.md
    scores = [p.triage_score for p in result.predictions]
    labels = [1 if p.gold_label == "ticket_worthy" else 0 for p in result.predictions]
    summary_path = args.output_dir / "summary.md"
    pr = pr_auc(scores, labels) if scores else 0.0
    roc = roc_auc(scores, labels) if scores else 0.0
    n_pos_pred = sum(1 for p in result.predictions if p.triage_decision == "ticket_worthy")
    n_novel = sum(
        1 for p in result.predictions
        if p.is_novel is True and p.triage_decision == "ticket_worthy"
    )
    samples = pipeline.last_decisions[:3]
    md_lines = [
        f"# memorygraph pipeline summary",
        "",
        f"- global_dir: `{args.global_dir}`",
        f"- planner:    `{args.planner}`",
        f"- threshold:  {result.triage_threshold:.4f}",
        f"- fit:        {result.fit_seconds:.1f}s",
        f"- predict:    {result.predict_seconds:.1f}s",
        "",
        "## Headline (test split)",
        "",
        f"- PR-AUC:  {pr:.4f}",
        f"- ROC-AUC: {roc:.4f}",
        f"- ticket_worthy predictions: {n_pos_pred} / {len(result.predictions)}",
        f"- novel-incident predictions: {n_novel}",
        "",
        "## Graph stats",
        "",
        "```json",
        json.dumps(pipeline.last_graph_stats or {}, indent=2),
        "```",
        "",
        "## Sample explanations",
        "",
    ]
    for s in samples:
        md_lines.extend([
            f"### {s.window_id}",
            f"- decision: `{s.decision}`  score: {s.triage_score:.3f}  novel: {s.is_novel}",
            f"- candidates after filter: {s.n_candidates_after_filter}",
            f"- skill chain: {' → '.join(s.skill_chain)}",
            f"- explanation: {s.explanation}",
            "",
        ])
    summary_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(
        f"[memorygraph] wrote predictions={predictions_path} "
        f"explanations={explanations_path} graph_stats={stats_path} summary={summary_path}",
        file=sys.stderr,
    )
    print(
        f"[memorygraph] test PR-AUC={pr:.4f} ROC-AUC={roc:.4f} "
        f"threshold={result.triage_threshold:.4f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
