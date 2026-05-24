"""Orchestrator: run every pipeline, ensemble them, stratify, and write a
single comparison report.

Public entrypoint: run_comparison(global_dir, runs_root, pipelines, ...)
returns a ComparisonReport you can serialize to disk however you like.
The CLI in cli.py wraps it with arg parsing + markdown rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ensemble import EnsemblePipeline, blend_mean
from .pipelines import (
    JiraOnlyPipeline,
    LoganalyzerPipeline,
    LoganalyzerWithJiraPipeline,
    LogsensePipeline,
    PipelineRunner,
)
from .schema import PipelineResult
from .significance import paired_bootstrap_ci, render_ci_table, render_pairwise_table
from .stratified import (
    OrphanRecallGap,
    StrataRow,
    compute_orphan_recall_gap,
    render_orphan_recall_gap_table,
    render_strata_table,
    stratified_metrics,
)


KNOWN_PIPELINES: dict[str, type[PipelineRunner]] = {
    "loganalyzer": LoganalyzerPipeline,
    "loganalyzer_with_jira": LoganalyzerWithJiraPipeline,
    "jira_only": JiraOnlyPipeline,
    "logsense": LogsensePipeline,
}


@dataclass
class ComparisonReport:
    results: list[PipelineResult]
    strata: list[StrataRow]
    headline: dict[str, dict[str, float]] = field(default_factory=dict)
    ci_per_metric: dict[str, dict] = field(default_factory=dict)
    pairwise_per_metric: dict[str, list] = field(default_factory=dict)
    # D12.6 (2026-05-24): orphan-detection recall gap per pipeline.
    # Empty list if no pipeline's gold has expected_in_memory annotations
    # (pre-D12.3 datasets).
    orphan_recall_gap: list[OrphanRecallGap] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipelines": [
                {
                    "name": r.pipeline_name,
                    "threshold": r.triage_threshold,
                    "fit_seconds": r.fit_seconds,
                    "predict_seconds": r.predict_seconds,
                    "metadata": r.metadata,
                }
                for r in self.results
            ],
            "headline": self.headline,
            "ci_per_metric": {
                metric: {
                    name: {"point": ci.point_estimate, "lo": ci.lo, "hi": ci.hi}
                    for name, ci in by_pipe.items()
                }
                for metric, by_pipe in self.ci_per_metric.items()
            },
            "pairwise_per_metric": {
                metric: [
                    {
                        "metric": d.metric,
                        "a": d.pipeline_a,
                        "b": d.pipeline_b,
                        "delta": d.delta,
                        "ci_lo": d.ci.lo,
                        "ci_hi": d.ci.hi,
                        "p_value": d.p_value,
                    }
                    for d in pairwise
                ]
                for metric, pairwise in self.pairwise_per_metric.items()
            },
            "strata": [
                {
                    "pipeline": s.pipeline_name,
                    "strata_key": s.strata_key,
                    "n": s.n,
                    "triage": s.triage,
                    "retrieval": s.retrieval,
                }
                for s in self.strata
            ],
            "orphan_recall_gap": [g.as_dict() for g in self.orphan_recall_gap],
        }


def _headline_metrics(strata: list[StrataRow]) -> dict[str, dict[str, float]]:
    """Pull the 'overall' strata row for every pipeline into a flat table."""
    out: dict[str, dict[str, float]] = {}
    for s in strata:
        if s.strata_key != "overall":
            continue
        flat = {f"triage.{k}": v for k, v in s.triage.items()}
        flat.update({f"retrieval.{k}": v for k, v in s.retrieval.items()})
        out[s.pipeline_name] = flat
    return out


def run_comparison(
    global_dir: Path,
    runs_root: Path,
    *,
    pipelines: list[str] | None = None,
    include_ensemble: bool = True,
    n_bootstrap: int = 1000,
    target_fpr: float = 0.05,
) -> ComparisonReport:
    pipelines = pipelines or ["loganalyzer", "logsense"]
    results: list[PipelineResult] = []
    for name in pipelines:
        if name not in KNOWN_PIPELINES:
            raise ValueError(f"Unknown pipeline: {name}. Options: {sorted(KNOWN_PIPELINES)}")
        runner = KNOWN_PIPELINES[name]()
        print(f"[comparison] running pipeline: {name}")
        results.append(runner.train_and_predict(global_dir, runs_root, target_fpr=target_fpr))

    if include_ensemble and len(results) >= 2:
        print("[comparison] building mean ensemble")
        ensemble = EnsemblePipeline("ensemble_mean", blend_fn=blend_mean, normalize=True)
        results.append(ensemble.from_results(results, threshold=0.5))

    print("[comparison] computing stratified metrics")
    strata = stratified_metrics(results)
    # D12.6 — only meaningful when the dataset has expected_in_memory
    # annotations (D12.3+). On pre-D12.3 datasets every row reports
    # verdict=no_orphan_data, which is the correct "N/A" signal.
    orphan_gap = compute_orphan_recall_gap(results)

    headline = _headline_metrics(strata)

    print(f"[comparison] paired bootstrap ({n_bootstrap} resamples) per metric")
    ci_per_metric: dict[str, dict] = {}
    pairwise_per_metric: dict[str, list] = {}
    for metric in ("pr_auc", "roc_auc", "precision_at_fpr_5pct", "recall_at_5", "mrr"):
        ci, pairwise = paired_bootstrap_ci(results, metric=metric, n_resamples=n_bootstrap)
        ci_per_metric[metric] = ci
        pairwise_per_metric[metric] = pairwise

    return ComparisonReport(
        results=results,
        strata=strata,
        headline=headline,
        ci_per_metric=ci_per_metric,
        pairwise_per_metric=pairwise_per_metric,
        orphan_recall_gap=orphan_gap,
    )


def render_report_md(report: ComparisonReport) -> str:
    lines: list[str] = ["# Comparison Report", ""]
    lines.append("Pipelines:")
    for r in report.results:
        lines.append(
            f"- `{r.pipeline_name}` (threshold={r.triage_threshold:.4f}, "
            f"fit={r.fit_seconds:.1f}s, predict={r.predict_seconds:.1f}s)"
        )

    # D12.6 headline section — placed near the top so the
     # memorization-vs-detection signal is the first thing a reader sees.
    # On pre-D12.3 datasets all rows show verdict=no_orphan_data; we
    # still render the table so the section is consistently present.
    lines.append("")
    lines.append("## Orphan-detection recall gap (D12.6)")
    lines.append("")
    lines.append(
        "`gap_pts = 100 × (recall on reported ticket_worthy - recall on "
        "orphan ticket_worthy)`. Verdict: < 10pts = signal_learning, "
        "10-20 = borderline, > 20 = pattern_matching, "
        "n_orphan=0 = no_orphan_data."
    )
    lines.append("")
    lines.append(render_orphan_recall_gap_table(report.orphan_recall_gap))

    lines.append("")
    lines.append("## Headline (overall, with 95% bootstrap CIs)")
    for metric in ("pr_auc", "roc_auc", "precision_at_fpr_5pct", "recall_at_5", "mrr"):
        lines.append("")
        lines.append(f"### {metric}")
        lines.append(render_ci_table(report.ci_per_metric.get(metric, {}), metric))

    lines.append("")
    lines.append("## Pairwise deltas (paired bootstrap)")
    for metric in ("pr_auc", "precision_at_fpr_5pct", "recall_at_5"):
        lines.append("")
        lines.append(f"### {metric}")
        lines.append(render_pairwise_table(report.pairwise_per_metric.get(metric, [])))

    lines.append("")
    lines.append("## Per-family PR-AUC")
    family_rows = [s for s in report.strata if s.strata_key.startswith("family=")]
    lines.append(
        render_strata_table(
            family_rows,
            metric="pr_auc",
            metric_group="triage",
            pipelines=[r.pipeline_name for r in report.results],
        )
    )

    lines.append("")
    lines.append("## Per-family recall@5")
    lines.append(
        render_strata_table(
            family_rows,
            metric="recall_at_5",
            metric_group="retrieval",
            pipelines=[r.pipeline_name for r in report.results],
        )
    )

    lines.append("")
    lines.append("## Per-window-type PR-AUC")
    wt_rows = [s for s in report.strata if s.strata_key.startswith("window_type=")]
    lines.append(
        render_strata_table(
            wt_rows,
            metric="pr_auc",
            metric_group="triage",
            pipelines=[r.pipeline_name for r in report.results],
        )
    )

    return "\n".join(lines) + "\n"
