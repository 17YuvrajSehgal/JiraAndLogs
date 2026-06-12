"""Stratified metric breakdowns: per scenario_family / service / window_type.

Reuses core.eval.metrics so the numbers match the existing single-
pipeline benchmark exactly - this is critical for "we improved X by Y" to
mean the same thing across reports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from core.eval.metrics import (
    expected_calibration_error,
    f_beta,
    pr_auc,
    precision_at_fpr,
    roc_auc,
)
from core.eval.retrieval_metrics import (
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
            "f1_at_fpr_5pct": 0.0,
            "f_beta_2_at_fpr_5pct": 0.0,
            "n_pos": int(sum(labels)),
            "n_neg": int(len(labels) - sum(labels)),
        }
    p5, r5, _t5 = precision_at_fpr(scores, labels, 0.05)
    # F1 = harmonic mean of precision and recall (beta=1 special case of f_beta).
    # Added 2026-05-26 as a corporate-report headline metric — the standard
    # binary-classification single-number summary that non-ML stakeholders
    # expect alongside PR-AUC.
    f1 = (2 * p5 * r5 / (p5 + r5)) if (p5 + r5) > 0 else 0.0
    return {
        "pr_auc": pr_auc(scores, labels),
        "roc_auc": roc_auc(scores, labels),
        "ece": expected_calibration_error(scores, labels),
        "precision_at_fpr_5pct": p5,
        "recall_at_fpr_5pct": r5,
        "f1_at_fpr_5pct": f1,
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


def _bucket_n_prior(n: int | None) -> str:
    """Charter §10 / Phase A2: deployment-history depth buckets.

    The 'depth' axis groups windows by how many memory tickets the
    gold-truth matcher considers compatible with them. n=0 means no
    prior tickets in memory are relevant — true cold-start. Higher n
    means a richer history of similar incidents exists, which is
    where retrieval-augmented diagnosis is supposed to win.
    """
    if n is None:
        return "n_prior_family=unknown"
    if n == 0:
        return "n_prior_family=0"
    if n <= 2:
        return "n_prior_family=1-2"
    if n <= 5:
        return "n_prior_family=3-5"
    if n <= 20:
        return "n_prior_family=6-20"
    return "n_prior_family=21+"


def _key_extractors() -> dict[str, Callable[[Any], str]]:
    return {
        "overall": lambda p: "overall",
        "family": lambda p: f"family={p.scenario_family}",
        "service": lambda p: f"service={p.service_name}",
        "window_type": lambda p: f"window_type={p.window_type}",
        # Added 2026-05-26: corporate-report product axes.
        "is_hard_case": lambda p: f"is_hard_case={'true' if p.is_hard_case else 'false'}",
        "triage_reason_class": lambda p: f"triage_reason_class={p.triage_reason_class or 'unknown'}",
        # is_novel — only meaningful on ticket_worthy windows (the rest
        # have no retrieval gold). Bucketed into novel / known / unscored.
        "is_novel": lambda p: (
            f"is_novel={'novel' if p.gold_is_novel else ('known' if p.gold_is_novel is False else 'unscored')}"
        ),
        # Charter §10 / Phase A2: deployment-history depth axis. Anchor
        # of the headline figure — R@5 vs how many prior tickets in
        # memory are compatible with the window.
        "n_prior_family_tickets": lambda p: _bucket_n_prior(
            getattr(p, "n_prior_family_tickets", None)
        ),
    }


def stratified_metrics(
    results: list[PipelineResult],
    *,
    include: tuple[str, ...] = (
        "overall", "family", "service", "window_type",
        "is_hard_case", "triage_reason_class", "is_novel",
        "n_prior_family_tickets",
    ),
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


# ---------------------------------------------------------------------------
# D12.6 — Orphan-detection recall gap (the headline orphan-fault metric)
# ---------------------------------------------------------------------------


@dataclass
class OrphanRecallGap:
    pipeline_name: str
    n_reported: int  # ticket_worthy AND expected_in_memory=True
    n_orphan: int    # ticket_worthy AND expected_in_memory=False
    recall_reported: float
    recall_orphan: float
    gap_pts: float   # 100 * (recall_reported - recall_orphan)
    verdict: str     # interpretive bucket per dataset-todo.md D12.6

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "n_reported": self.n_reported,
            "n_orphan": self.n_orphan,
            "recall_reported": self.recall_reported,
            "recall_orphan": self.recall_orphan,
            "gap_pts": self.gap_pts,
            "verdict": self.verdict,
        }


def _gap_verdict(gap_pts: float, n_orphan: int) -> str:
    """Per dataset-todo.md D12.6:
    > A gap > 20pts means the pipeline relies on Jira pattern matching;
    > a gap < 10pts means the pipeline learned the underlying anomaly signal.
    """
    if n_orphan == 0:
        return "no_orphan_data"
    if gap_pts > 20.0:
        return "pattern_matching"  # over-reliant on Jira memory
    if gap_pts < 10.0:
        return "signal_learning"  # generalizes from telemetry
    return "borderline"  # 10-20pt gap: ambiguous


def compute_orphan_recall_gap(
    results: list[PipelineResult],
    *,
    decision: str | None = None,
) -> list[OrphanRecallGap]:
    """For each pipeline, compute recall on (reported ticket_worthy) vs
    (orphan ticket_worthy), where orphan = expected_in_memory is False.

    The "decision" used for recall is the predicted `triage_decision`
    string ("ticket_worthy" counts as a positive prediction). If
    `decision` is set, only predictions where triage_decision == decision
    are counted as flagged; default is "ticket_worthy".

    Returns one OrphanRecallGap per pipeline. Pipelines with no
    expected_in_memory annotations on their gold (e.g. pre-D12.3 datasets)
    return n_reported = n_orphan = 0 and gap_pts = 0.0.
    """
    flagged_label = decision or "ticket_worthy"
    rows: list[OrphanRecallGap] = []
    for result in results:
        n_reported_pos = n_reported_hit = 0
        n_orphan_pos = n_orphan_hit = 0
        for p in result.predictions:
            if p.gold_label != "ticket_worthy":
                continue
            em = p.gold_expected_in_memory
            if em is None:
                continue  # window has no orphan annotation — skip
            flagged = p.triage_decision == flagged_label
            if em is True:
                n_reported_pos += 1
                if flagged:
                    n_reported_hit += 1
            else:  # em is False → orphan
                n_orphan_pos += 1
                if flagged:
                    n_orphan_hit += 1
        rr = (n_reported_hit / n_reported_pos) if n_reported_pos else 0.0
        ro = (n_orphan_hit / n_orphan_pos) if n_orphan_pos else 0.0
        gap = 100.0 * (rr - ro)
        rows.append(
            OrphanRecallGap(
                pipeline_name=result.pipeline_name,
                n_reported=n_reported_pos,
                n_orphan=n_orphan_pos,
                recall_reported=rr,
                recall_orphan=ro,
                gap_pts=gap,
                verdict=_gap_verdict(gap, n_orphan_pos),
            )
        )
    return rows


def render_orphan_recall_gap_table(rows: list[OrphanRecallGap]) -> str:
    """Markdown table for the headline report."""
    out: list[str] = []
    out.append(
        "| pipeline | n_reported | recall_reported | n_orphan | "
        "recall_orphan | gap_pts | verdict |"
    )
    out.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |"
    )
    for r in sorted(rows, key=lambda x: x.pipeline_name):
        out.append(
            f"| {r.pipeline_name} | {r.n_reported} | "
            f"{r.recall_reported:.3f} | {r.n_orphan} | "
            f"{r.recall_orphan:.3f} | {r.gap_pts:+.1f} | {r.verdict} |"
        )
    return "\n".join(out)


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
