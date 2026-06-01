"""Paired-bootstrap CIs and significance tests for metric deltas.

Why paired: every pipeline scores the SAME test windows; resampling the
window indices and re-computing both pipelines' metrics on the resampled
set is the correct way to get a CI on the *difference*.

Why bootstrap: PR-AUC / recall@5 / novelty F1 don't have closed-form CIs.
1000 resamples is plenty for headline numbers; 10000 for paper-final.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from loganalyzer.eval.metrics import pr_auc, roc_auc, precision_at_fpr
from loganalyzer.eval.retrieval_metrics import recall_at_k, mean_reciprocal_rank

from .schema import PipelinePrediction, PipelineResult


@dataclass
class BootstrapCI:
    point_estimate: float
    lo: float
    hi: float
    confidence: float = 0.95


@dataclass
class PairwiseDelta:
    metric: str
    pipeline_a: str
    pipeline_b: str
    delta: float  # b - a
    ci: BootstrapCI
    p_value: float  # two-sided p-value of "delta != 0"


# ---------------------------------------------------------------------------
# Metric callables: each takes a list of PipelinePrediction, returns a float
# ---------------------------------------------------------------------------


def _pr_auc(preds: list[PipelinePrediction]) -> float:
    scores = [p.triage_score for p in preds]
    labels = [1 if p.gold_label == "ticket_worthy" else 0 for p in preds]
    if sum(labels) == 0 or sum(labels) == len(labels):
        return 0.0
    return pr_auc(scores, labels)


def _roc_auc(preds: list[PipelinePrediction]) -> float:
    scores = [p.triage_score for p in preds]
    labels = [1 if p.gold_label == "ticket_worthy" else 0 for p in preds]
    if sum(labels) == 0 or sum(labels) == len(labels):
        return 0.0
    return roc_auc(scores, labels)


def _precision_at_fpr5(preds: list[PipelinePrediction]) -> float:
    scores = [p.triage_score for p in preds]
    labels = [1 if p.gold_label == "ticket_worthy" else 0 for p in preds]
    if sum(labels) == 0 or sum(labels) == len(labels):
        return 0.0
    p, _r, _t = precision_at_fpr(scores, labels, 0.05)
    return p


def _recall_at_5(preds: list[PipelinePrediction]) -> float:
    vals = [
        recall_at_k(p.matched_issue_ids, p.gold_matched_issue_ids, 5)
        for p in preds
        if p.gold_label == "ticket_worthy" and p.gold_matched_issue_ids
    ]
    return sum(vals) / len(vals) if vals else 0.0


def _mrr(preds: list[PipelinePrediction]) -> float:
    vals = [
        mean_reciprocal_rank(p.matched_issue_ids, p.gold_matched_issue_ids)
        for p in preds
        if p.gold_label == "ticket_worthy" and p.gold_matched_issue_ids
    ]
    return sum(vals) / len(vals) if vals else 0.0


METRICS: dict[str, Callable[[list[PipelinePrediction]], float]] = {
    "pr_auc": _pr_auc,
    "roc_auc": _roc_auc,
    "precision_at_fpr_5pct": _precision_at_fpr5,
    "recall_at_5": _recall_at_5,
    "mrr": _mrr,
}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def paired_bootstrap_ci(
    results: list[PipelineResult],
    *,
    metric: str,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 17,
) -> tuple[dict[str, BootstrapCI], list[PairwiseDelta]]:
    """Returns (per-pipeline CIs, pairwise deltas with CI + p-values).

    The resampling indexes are shared across pipelines so CIs on deltas are
    paired - that's the entire point of pairing.
    """
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}. Options: {sorted(METRICS)}")
    fn = METRICS[metric]

    by_window: dict[str, dict[str, PipelinePrediction]] = {}
    for r in results:
        for p in r.predictions:
            by_window.setdefault(p.window_id, {})[r.pipeline_name] = p
    # only keep window_ids predicted by ALL pipelines (otherwise pairing breaks)
    pipeline_names = sorted({r.pipeline_name for r in results})
    common_window_ids = [
        wid for wid, by_name in by_window.items()
        if all(name in by_name for name in pipeline_names)
    ]
    if not common_window_ids:
        return {}, []

    # Point estimates on the full common set
    point_estimates: dict[str, float] = {}
    for name in pipeline_names:
        preds = [by_window[wid][name] for wid in common_window_ids]
        point_estimates[name] = fn(preds)

    # Resamples
    rng = random.Random(seed)
    n = len(common_window_ids)
    resample_estimates: dict[str, list[float]] = {name: [] for name in pipeline_names}
    resample_deltas: dict[tuple[str, str], list[float]] = {
        (a, b): [] for a in pipeline_names for b in pipeline_names if a < b
    }
    for _ in range(n_resamples):
        idx = [rng.randrange(0, n) for _ in range(n)]
        sampled_ids = [common_window_ids[i] for i in idx]
        per_pipe_metric: dict[str, float] = {}
        for name in pipeline_names:
            preds = [by_window[wid][name] for wid in sampled_ids]
            per_pipe_metric[name] = fn(preds)
            resample_estimates[name].append(per_pipe_metric[name])
        for (a, b) in resample_deltas:
            resample_deltas[(a, b)].append(per_pipe_metric[b] - per_pipe_metric[a])

    alpha = (1 - confidence) / 2
    ci_per_pipeline: dict[str, BootstrapCI] = {}
    for name in pipeline_names:
        s = sorted(resample_estimates[name])
        ci_per_pipeline[name] = BootstrapCI(
            point_estimate=point_estimates[name],
            lo=_percentile(s, alpha),
            hi=_percentile(s, 1 - alpha),
            confidence=confidence,
        )

    pairwise: list[PairwiseDelta] = []
    for (a, b), deltas in resample_deltas.items():
        s = sorted(deltas)
        observed = point_estimates[b] - point_estimates[a]
        # two-sided p-value: fraction of resampled deltas with the opposite
        # sign of the observed delta (or zero), doubled.
        if observed >= 0:
            tail = sum(1 for d in deltas if d <= 0) / len(deltas)
        else:
            tail = sum(1 for d in deltas if d >= 0) / len(deltas)
        p_value = min(1.0, 2.0 * tail)
        pairwise.append(
            PairwiseDelta(
                metric=metric,
                pipeline_a=a,
                pipeline_b=b,
                delta=observed,
                ci=BootstrapCI(
                    point_estimate=observed,
                    lo=_percentile(s, alpha),
                    hi=_percentile(s, 1 - alpha),
                    confidence=confidence,
                ),
                p_value=p_value,
            )
        )
    return ci_per_pipeline, pairwise


def stratified_bootstrap_ci(
    results: list[PipelineResult],
    *,
    metric: str,
    key_fn: Callable[[PipelinePrediction], str],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
    min_stratum_n: int = 10,
) -> dict[str, tuple[dict[str, BootstrapCI], list[PairwiseDelta]]]:
    """Per-stratum paired bootstrap CIs.

    Charter §10 / Phase A3. For each stratum bucket (produced by
    `key_fn(prediction) -> str`), filter the predictions, then run the
    same paired bootstrap that `paired_bootstrap_ci()` does. Returns a
    dict keyed by stratum, with the same value shape as the unstratified
    function — `(per-pipeline CIs, pairwise deltas)`.

    Strata with fewer than `min_stratum_n` shared windows are skipped
    (the CIs would be too wide to interpret). seed=42 per charter §10.
    """
    # Group window_ids by stratum (using any pipeline's predictions —
    # the stratum is a property of the window/gold, not the pipeline).
    if not results:
        return {}
    by_window_first: dict[str, PipelinePrediction] = {}
    for p in results[0].predictions:
        by_window_first[p.window_id] = p
    strata_wids: dict[str, set[str]] = {}
    for wid, p in by_window_first.items():
        strata_wids.setdefault(key_fn(p), set()).add(wid)

    out: dict[str, tuple[dict[str, BootstrapCI], list[PairwiseDelta]]] = {}
    for stratum, wid_set in strata_wids.items():
        if len(wid_set) < min_stratum_n:
            continue
        filtered = [
            PipelineResult(
                pipeline_name=r.pipeline_name,
                predictions=[p for p in r.predictions if p.window_id in wid_set],
                triage_threshold=r.triage_threshold,
                fit_seconds=r.fit_seconds,
                predict_seconds=r.predict_seconds,
                metadata=r.metadata,
            )
            for r in results
        ]
        try:
            ci, pairwise = paired_bootstrap_ci(
                filtered,
                metric=metric,
                n_resamples=n_resamples,
                confidence=confidence,
                seed=seed,
            )
            out[stratum] = (ci, pairwise)
        except Exception:  # defensive — keep the pipeline running
            continue
    return out


def render_ci_table(ci_per_pipeline: dict[str, BootstrapCI], metric: str) -> str:
    if not ci_per_pipeline:
        return f"_no data for {metric}_"
    lines = [
        f"| pipeline | {metric} | 95% CI |",
        "| --- | ---: | --- |",
    ]
    for name in sorted(ci_per_pipeline):
        ci = ci_per_pipeline[name]
        lines.append(f"| {name} | {ci.point_estimate:.4f} | [{ci.lo:.4f}, {ci.hi:.4f}] |")
    return "\n".join(lines)


def render_pairwise_table(pairwise: list[PairwiseDelta]) -> str:
    if not pairwise:
        return "_no pairwise data_"
    lines = [
        "| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |",
        "| --- | --- | --- | ---: | --- | ---: | :---: |",
    ]
    for d in pairwise:
        sig = "yes" if d.p_value < 0.05 else "no"
        lines.append(
            f"| {d.metric} | {d.pipeline_a} | {d.pipeline_b} | {d.delta:+.4f} | "
            f"[{d.ci.lo:+.4f}, {d.ci.hi:+.4f}] | {d.p_value:.3f} | {sig} |"
        )
    return "\n".join(lines)
