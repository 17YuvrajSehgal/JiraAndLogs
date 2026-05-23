"""Stratified metric breakdowns: per scenario_family / service / window_type.

Reuses loganalyzer.eval.metrics so the numbers match the existing single-
pipeline benchmark exactly - this is critical for "we improved X by Y" to
mean the same thing across reports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from loganalyzer.eval.metrics import (
    expected_calibration_error,
    f_beta,
    pr_auc,
    precision_at_fpr,
    roc_auc,
)
from loganalyzer.eval.retrieval_metrics import (
    mean_reciprocal_rank,
    novelty_f1,
    recall_at_k,
)

from .schema import PipelineResult


def _binarize(label: str, *, inclusive: bool) -> int:
    if label == "ticket_worthy":
        return 1
    if label == "borderline":
        return 1 if inclusive else 0
    return 0


def _triage_metrics(scores: list[float], labels: list[int]) -> dict[str, float]:
    if not scores or sum(labels) == 0 or sum(labels) == len(labels):
        return {
            "pr_auc": 0.0,
            "roc_auc": 0.0,
            "ece": 0.0,
            "precision_at_fpr_5pct": 0.0,
            "recall_at_fpr_5pct": 0.0,
            "f_beta_2_at_fpr_5pct": 0.0,
            "n_pos": int(sum(labels)),
            "n_neg": int(len(labels) - sum(labels)),
        }
    p5, r5, _t5 = precision_at_fpr(scores, labels, 0.05)
    return {
        "pr_auc": pr_auc(scores, labels),
        "roc_auc": roc_auc(scores, labels),
        "ece": expected_calibration_error(scores, labels),
        "precision_at_fpr_5pct": p5,
        "recall_at_fpr_5pct": r5,
        "f_beta_2_at_fpr_5pct": f_beta(p5, r5, beta=2.0),
        "n_pos": int(sum(labels)),
        "n_neg": int(len(labels) - sum(labels)),
    }


def _retrieval_metrics(predictions: list) -> dict[str, float]:
    recalls: dict[int, list[float]] = {1: [], 3: [], 5: []}
    mrr_vals: list[float] = []
    novel_pred: list[bool] = []
    novel_gold: list[bool] = []
    for p in predictions:
        if p.gold_label == "ticket_worthy" and p.gold_matched_issue_ids:
            for k in (1, 3, 5):
                recalls[k].append(recall_at_k(p.matched_issue_ids, p.gold_matched_issue_ids, k))
            mrr_vals.append(mean_reciprocal_rank(p.matched_issue_ids, p.gold_matched_issue_ids))
        if p.triage_decision == "ticket_worthy" and p.gold_label == "ticket_worthy":
            if p.is_novel is not None and p.gold_is_novel is not None:
                novel_pred.append(p.is_novel)
                novel_gold.append(p.gold_is_novel)
    out = {f"recall_at_{k}": (sum(v) / len(v) if v else 0.0) for k, v in recalls.items()}
    out["mrr"] = sum(mrr_vals) / len(mrr_vals) if mrr_vals else 0.0
    out["n_retrievable"] = len(mrr_vals)
    if novel_pred:
        nf = novelty_f1(novel_pred, novel_gold)
        out["novelty_f1"] = nf["f1"]
        out["novelty_precision"] = nf["precision"]
        out["novelty_recall"] = nf["recall"]
        out["n_novelty"] = nf["n"]
    else:
        out["novelty_f1"] = 0.0
        out["novelty_precision"] = 0.0
        out["novelty_recall"] = 0.0
        out["n_novelty"] = 0
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class StrataRow:
    pipeline_name: str
    strata_key: str  # "overall" / "family=cart-redis" / "service=cartservice" / "window_type=active_fault"
    n: int
    triage: dict[str, float]
    retrieval: dict[str, float]


def _key_extractors() -> dict[str, Callable[[Any], str]]:
    return {
        "overall": lambda p: "overall",
        "family": lambda p: f"family={p.scenario_family}",
        "service": lambda p: f"service={p.service_name}",
        "window_type": lambda p: f"window_type={p.window_type}",
    }


def stratified_metrics(
    results: list[PipelineResult],
    *,
    include: tuple[str, ...] = ("overall", "family", "service", "window_type"),
    borderline_inclusive: bool = False,
) -> list[StrataRow]:
    """Compute metrics per (pipeline, strata key) cell.

    Returns a flat list of StrataRow records; callers can pivot to whatever
    table shape they prefer.
    """
    extractors = {k: v for k, v in _key_extractors().items() if k in include}
    rows: list[StrataRow] = []
    for result in results:
        buckets: dict[str, list] = defaultdict(list)
        for prediction in result.predictions:
            for axis_name, extractor in extractors.items():
                buckets[extractor(prediction)].append(prediction)
        for strata_key, predictions in sorted(buckets.items()):
            scores = [p.triage_score for p in predictions]
            labels = [_binarize(p.gold_label, inclusive=borderline_inclusive) for p in predictions]
            rows.append(
                StrataRow(
                    pipeline_name=result.pipeline_name,
                    strata_key=strata_key,
                    n=len(predictions),
                    triage=_triage_metrics(scores, labels),
                    retrieval=_retrieval_metrics(predictions),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_strata_table(
    rows: list[StrataRow],
    *,
    metric: str,
    metric_group: str = "triage",
    pipelines: list[str] | None = None,
) -> str:
    """Pivot rows into a markdown table with one column per pipeline.

    Example: render_strata_table(rows, metric="pr_auc", metric_group="triage")
    """
    by_strata: dict[str, dict[str, float]] = defaultdict(dict)
    by_strata_n: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        group = row.triage if metric_group == "triage" else row.retrieval
        by_strata[row.strata_key][row.pipeline_name] = group.get(metric, 0.0)
        by_strata_n[row.strata_key][row.pipeline_name] = row.n

    if pipelines is None:
        pipelines = sorted({row.pipeline_name for row in rows})

    out: list[str] = []
    header_cells = ["strata", "n"] + pipelines
    out.append("| " + " | ".join(header_cells) + " |")
    out.append("| " + " | ".join(["---"] * len(header_cells)) + " |")
    for strata_key in sorted(by_strata.keys()):
        n_vals = list(by_strata_n[strata_key].values())
        n = max(n_vals) if n_vals else 0
        cells = [strata_key, str(n)]
        for pipeline in pipelines:
            v = by_strata[strata_key].get(pipeline)
            cells.append(f"{v:.3f}" if isinstance(v, float) else "-")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)
