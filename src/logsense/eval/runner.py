"""End-to-end evaluation: train on train split, threshold-tune on
validation, score on test, surface triage + retrieval + novelty metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

from ..data.dataset import LogsDataset
from ..data.schema import LabeledWindowLogs
from ..product.analyzer import LogSenseAnalyzer
from ..triage.base import label_to_target


@dataclass
class LogEvaluationReport:
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
        "precision_at_fpr_5pct": p5,
        "recall_at_fpr_5pct": r5,
        "f_beta_2_at_fpr_5pct": f_beta(p5, r5, beta=2.0),
        "n_pos": sum(labels),
        "n_neg": len(labels) - sum(labels),
    }


def run_log_evaluation(
    analyzer: LogSenseAnalyzer,
    dataset: LogsDataset,
    *,
    target_fpr: float = 0.05,
) -> tuple[LogEvaluationReport, list[dict[str, Any]]]:
    train = dataset.by_split("train")
    val = dataset.by_split("validation")
    test = dataset.by_split("test")
    if not train:
        raise RuntimeError("Empty train split.")
    if not test:
        raise RuntimeError("Empty test split.")

    analyzer.fit(train)

    if val:
        val_scores = analyzer.triage_model.predict_batch([lw.logs for lw in val])
        val_labels = [_binarize(lw.triage_label, inclusive=False) for lw in val]
        _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
    else:
        threshold = 0.5
    analyzer.triage_threshold = threshold

    test_scores = analyzer.triage_model.predict_batch([lw.logs for lw in test])
    strict_labels = [_binarize(lw.triage_label, inclusive=False) for lw in test]
    inclusive_labels = [_binarize(lw.triage_label, inclusive=True) for lw in test]

    # Retrieval / novelty
    recall_buckets = {k: [] for k in (1, 3, 5)}
    mrr_values: list[float] = []
    pred_novel: list[bool] = []
    gold_novel: list[bool] = []
    per_window: list[dict[str, Any]] = []

    for lw in test:
        result = analyzer.analyze_labeled(lw)
        retrieved_ids = [hit.issue_id for hit in result.matched_issues]
        gold_ids = lw.label.matched_memory_issue_ids or []

        if lw.triage_label == "ticket_worthy":
            for k in (1, 3, 5):
                recall_buckets[k].append(recall_at_k(retrieved_ids, gold_ids, k))
            mrr_values.append(mean_reciprocal_rank(retrieved_ids, gold_ids))

        if result.triage_decision == "ticket_worthy" and lw.triage_label == "ticket_worthy":
            pred_novel.append(result.is_novel)
            gold_novel.append(bool(lw.label.is_novel))

        per_window.append(
            {
                "window_id": lw.window_id,
                "triage_label": lw.triage_label,
                "triage_score": result.triage_score,
                "triage_decision": result.triage_decision,
                "is_novel_predicted": result.is_novel,
                "is_novel_gold": lw.label.is_novel,
                "matched_issue_ids": retrieved_ids,
                "gold_issue_ids": gold_ids,
                "top_anomalies": [
                    {
                        "template": a.template,
                        "count_active": a.count_active,
                        "count_baseline": a.count_baseline,
                        "severity": a.severity,
                        "novelty_score": a.novelty_score,
                    }
                    for a in result.anomalous_templates[:3]
                ],
            }
        )

    retrieval = {f"recall_at_{k}": (sum(v) / len(v) if v else 0.0) for k, v in recall_buckets.items()}
    retrieval["mrr"] = sum(mrr_values) / len(mrr_values) if mrr_values else 0.0
    retrieval["n_eval_windows"] = len(mrr_values)
    novelty = novelty_f1(pred_novel, gold_novel)

    report = LogEvaluationReport(
        pipeline_name=f"{analyzer.triage_model.name}+{analyzer.retriever.name}",
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
