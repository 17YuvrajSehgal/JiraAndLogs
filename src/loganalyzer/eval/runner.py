"""End-to-end evaluation runner for SmartLogAnalyzer.

The runner trains on the train split, picks an operating threshold on the
validation split, then reports STRICT (borderline=negative) and INCLUSIVE
(borderline=positive) metrics on the test split. It also runs retrieval on
every analyzed window so retrieval recall@k can be reported together.

Output shape mirrors scripts/research-lab/run_triage_benchmark.py so the
loganalyzer numbers slot into the same triage report comparison tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..data.loaders import LoadedDataset
from ..data.schema import TriageWindow
from ..data.splits import iter_split
from ..product.analyzer import SmartLogAnalyzer
from ..triage.base import label_to_target
from .metrics import (
    expected_calibration_error,
    f_beta,
    pr_auc,
    precision_at_fpr,
    roc_auc,
)
from .retrieval_metrics import mean_reciprocal_rank, novelty_f1, recall_at_k


@dataclass
class EvaluationReport:
    pipeline_name: str
    triage_threshold: float
    strict: dict[str, Any] = field(default_factory=dict)
    inclusive: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    novelty: dict[str, Any] = field(default_factory=dict)
    n_train: int = 0
    n_validation: int = 0
    n_test: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "triage_threshold": self.triage_threshold,
            "strict": self.strict,
            "inclusive": self.inclusive,
            "retrieval": self.retrieval,
            "novelty": self.novelty,
            "split_sizes": {
                "train": self.n_train,
                "validation": self.n_validation,
                "test": self.n_test,
            },
        }


def _binarize(label: str, *, inclusive: bool) -> int:
    return label_to_target(label, borderline_as=1 if inclusive else 0)


def _triage_metrics(scores: list[float], labels: list[int]) -> dict[str, Any]:
    p1, r1, t1 = precision_at_fpr(scores, labels, 0.01)
    p5, r5, t5 = precision_at_fpr(scores, labels, 0.05)
    return {
        "pr_auc": pr_auc(scores, labels),
        "roc_auc": roc_auc(scores, labels),
        "expected_calibration_error": expected_calibration_error(scores, labels),
        "precision_at_fpr_1pct": p1,
        "recall_at_fpr_1pct": r1,
        "threshold_at_fpr_1pct": t1,
        "precision_at_fpr_5pct": p5,
        "recall_at_fpr_5pct": r5,
        "threshold_at_fpr_5pct": t5,
        "f_beta_2_at_fpr_5pct": f_beta(p5, r5, beta=2.0),
        "n_pos": sum(labels),
        "n_neg": len(labels) - sum(labels),
    }


def _pick_threshold(
    analyzer: SmartLogAnalyzer,
    val_windows: list[TriageWindow],
    *,
    target_fpr: float = 0.05,
) -> float:
    scores = analyzer.triage_model.predict_batch(val_windows)
    labels = [_binarize(w.triage_label, inclusive=False) for w in val_windows]
    _p, _r, threshold = precision_at_fpr(scores, labels, target_fpr)
    return threshold


def _retrieval_metrics(
    analyzer: SmartLogAnalyzer,
    test_windows: list[TriageWindow],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    recall_buckets = {k: [] for k in k_values}
    mrr_values: list[float] = []
    pred_novel: list[bool] = []
    gold_novel: list[bool] = []
    per_window: list[dict[str, Any]] = []

    for w in test_windows:
        result = analyzer.analyze(w)
        retrieved_ids = [hit.issue_id for hit in result.matched_issues]
        gold_ids = w.matched_memory_issue_ids or []

        if w.triage_label == "ticket_worthy":
            for k in k_values:
                recall_buckets[k].append(recall_at_k(retrieved_ids, gold_ids, k))
            mrr_values.append(mean_reciprocal_rank(retrieved_ids, gold_ids))

        if result.triage_decision == "ticket_worthy" and w.triage_label == "ticket_worthy":
            pred_novel.append(result.is_novel)
            gold_novel.append(bool(w.is_novel))

        per_window.append(
            {
                "window_id": w.window_id,
                "triage_label": w.triage_label,
                "triage_score": result.triage_score,
                "triage_decision": result.triage_decision,
                "is_novel_predicted": result.is_novel,
                "is_novel_gold": w.is_novel,
                "matched_issue_ids": retrieved_ids,
                "gold_issue_ids": gold_ids,
            }
        )

    retrieval = {f"recall_at_{k}": (sum(v) / len(v) if v else 0.0) for k, v in recall_buckets.items()}
    retrieval["mrr"] = sum(mrr_values) / len(mrr_values) if mrr_values else 0.0
    retrieval["n_eval_windows"] = len(mrr_values)
    novelty = novelty_f1(pred_novel, gold_novel)
    return retrieval, novelty, per_window


def run_full_evaluation(
    analyzer: SmartLogAnalyzer,
    dataset: LoadedDataset,
    *,
    target_fpr: float = 0.05,
) -> tuple[EvaluationReport, list[dict[str, Any]]]:
    """Train the analyzer, pick a threshold, score the test split.

    Returns the EvaluationReport plus a per-window prediction trail useful
    for stratified analysis.
    """
    train = list(iter_split(dataset.windows, dataset.split_manifest, "train"))
    val = list(iter_split(dataset.windows, dataset.split_manifest, "validation"))
    test = list(iter_split(dataset.windows, dataset.split_manifest, "test"))
    if not train:
        raise RuntimeError("Empty train split - check split manifest.")
    if not test:
        raise RuntimeError("Empty test split - check split manifest.")

    analyzer.fit(train)

    if val:
        threshold = _pick_threshold(analyzer, val, target_fpr=target_fpr)
    else:
        threshold = 0.5
    analyzer.triage_threshold = threshold

    test_scores = analyzer.triage_model.predict_batch(test)
    strict_labels = [_binarize(w.triage_label, inclusive=False) for w in test]
    inclusive_labels = [_binarize(w.triage_label, inclusive=True) for w in test]

    retrieval, novelty, per_window = _retrieval_metrics(analyzer, test)

    report = EvaluationReport(
        pipeline_name=f"{analyzer.triage_model.name}+{getattr(analyzer.retriever, 'name', 'retriever')}",
        triage_threshold=threshold,
        strict=_triage_metrics(test_scores, strict_labels),
        inclusive=_triage_metrics(test_scores, inclusive_labels),
        retrieval=retrieval,
        novelty=novelty,
        n_train=len(train),
        n_validation=len(val),
        n_test=len(test),
    )
    return report, per_window
