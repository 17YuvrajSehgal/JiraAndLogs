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
    CalibratedRandomForestPipeline,
    GradientBoostingPipeline,
    JiraOnlyPipeline,
    LoganalyzerPipeline,
    LoganalyzerWithJiraPipeline,
    LogisticNumericPipeline,
    LogsensePipeline,
    PipelineRunner,
    _NumericClassifierPipeline,
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
    # Phase 2 classical-ML baselines (2026-05-26). Numeric-only — no
    # retrieval — but use the same feature-list contract so v5's richer
    # columns flow in without code changes.
    "hgb": GradientBoostingPipeline,
    "rf": CalibratedRandomForestPipeline,
    "logistic_sklearn": LogisticNumericPipeline,
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
    # Phase 2 (2026-05-26): inclusive-borderline strata pass + LOFO macros.
    # inclusive_strata mirrors `strata` but counts borderline as positive.
    # lofo_macros: dict {pipeline_name -> {family: {pr_auc, roc_auc, ...},
    #                                      "macro": {pr_auc, roc_auc},
    #                                      "micro_pooled": {pr_auc, roc_auc}}}
    inclusive_strata: list[StrataRow] = field(default_factory=list)
    lofo_macros: dict[str, dict[str, Any]] = field(default_factory=dict)

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
            "inclusive_strata": [
                {
                    "pipeline": s.pipeline_name,
                    "strata_key": s.strata_key,
                    "n": s.n,
                    "triage": s.triage,
                    "retrieval": s.retrieval,
                }
                for s in self.inclusive_strata
            ],
            "lofo_macros": self.lofo_macros,
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


def _compute_lofo_macros(
    pipelines: list[tuple[str, PipelineRunner]],
    global_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Run leave-one-family-out for every numeric classifier pipeline.

    Only pipelines that inherit _NumericClassifierPipeline are LOFO'd —
    they're fast (HGB/RF/logistic on a 3000-row v4 corpus = a few seconds
    per fold) and they don't need raw run data. Retrieval-based pipelines
    (loganalyzer, logsense) get per-family stratified metrics from the
    fixed split instead; full LOFO for those is a future-phase add."""
    out: dict[str, dict[str, Any]] = {}
    for name, runner in pipelines:
        if not isinstance(runner, _NumericClassifierPipeline):
            continue
        print(f"[comparison] LOFO for {runner.name} ...")
        folds = runner.lofo_evaluate(global_dir, binarize_inclusive=False)
        scored = [f for f in folds if f.get("pr_auc") is not None]
        macro_pr = (
            sum(f["pr_auc"] for f in scored) / len(scored) if scored else 0.0
        )
        macro_roc = (
            sum(f["roc_auc"] for f in scored) / len(scored) if scored else 0.0
        )
        out[runner.name] = {
            "fold_count": len(scored),
            "skipped_families": [
                f["family"] for f in folds if f.get("pr_auc") is None
            ],
            "macro_pr_auc": macro_pr,
            "macro_roc_auc": macro_roc,
            "folds": folds,
        }
    return out


def run_comparison(
    global_dir: Path,
    runs_root: Path,
    *,
    pipelines: list[str] | None = None,
    include_ensemble: bool = True,
    n_bootstrap: int = 1000,
    target_fpr: float = 0.05,
    include_lofo: bool = True,
) -> ComparisonReport:
    pipelines = pipelines or ["loganalyzer", "logsense"]
    instantiated: list[tuple[str, PipelineRunner]] = []
    results: list[PipelineResult] = []
    for name in pipelines:
        if name not in KNOWN_PIPELINES:
            raise ValueError(f"Unknown pipeline: {name}. Options: {sorted(KNOWN_PIPELINES)}")
        runner = KNOWN_PIPELINES[name]()
        instantiated.append((name, runner))
        print(f"[comparison] running pipeline: {name}")
        results.append(runner.train_and_predict(global_dir, runs_root, target_fpr=target_fpr))

    if include_ensemble and len(results) >= 2:
        print("[comparison] building mean ensemble")
        ensemble = EnsemblePipeline("ensemble_mean", blend_fn=blend_mean, normalize=True)
        results.append(ensemble.from_results(results, threshold=0.5))

    print("[comparison] computing stratified metrics (strict)")
    strata = stratified_metrics(results, borderline_inclusive=False)
    print("[comparison] computing stratified metrics (inclusive)")
    inclusive_strata = stratified_metrics(results, borderline_inclusive=True)

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

    lofo_macros: dict[str, dict[str, Any]] = {}
    if include_lofo:
        lofo_macros = _compute_lofo_macros(instantiated, global_dir)

    return ComparisonReport(
        results=results,
        strata=strata,
        headline=headline,
        ci_per_metric=ci_per_metric,
        pairwise_per_metric=pairwise_per_metric,
        orphan_recall_gap=orphan_gap,
        inclusive_strata=inclusive_strata,
        lofo_macros=lofo_macros,
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

    # --- Phase 2: inclusive borderline + LOFO macros (2026-05-26) ---------
    if report.inclusive_strata:
        lines.append("")
        lines.append("## Inclusive borderline handling (borderline counted as positive)")
        lines.append("")
        lines.append(
            "The strict variant above is the headline. This inclusive variant "
            "rewards pipelines that surface human-interesting (borderline) "
            "windows. Pipelines whose inclusive PR-AUC is meaningfully higher "
            "than their strict PR-AUC are picking up signal on the borderline "
            "class even if they don't quite call it `ticket_worthy`."
        )
        lines.append("")
        lines.append("### Overall PR-AUC (inclusive)")
        lines.append("")
        lines.append("| Pipeline | PR-AUC | ROC-AUC | ECE | Precision@FPR=5% |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for r in report.results:
            row = next(
                (
                    s
                    for s in report.inclusive_strata
                    if s.pipeline_name == r.pipeline_name and s.strata_key == "overall"
                ),
                None,
            )
            if row is None:
                continue
            t = row.triage
            lines.append(
                f"| `{r.pipeline_name}` | "
                f"{t['pr_auc']:.4f} | "
                f"{t['roc_auc']:.4f} | "
                f"{t['ece']:.4f} | "
                f"{t['precision_at_fpr_5pct']:.4f} |"
            )

    if report.lofo_macros:
        lines.append("")
        lines.append("## Leave-one-family-out macros (numeric pipelines)")
        lines.append("")
        lines.append(
            "Each family is held out as the test set; train uses all other "
            "families pooled across train+val+test. The macro average "
            "weights every family equally regardless of size. Single-class "
            "folds (no positives in the held-out family) are skipped."
        )
        lines.append("")
        lines.append(
            "**The macro is the primary generalization signal.** A pipeline "
            "that wins the fixed-split leaderboard but loses LOFO has "
            "overfit to the families that happen to be in the train split."
        )
        lines.append("")
        lines.append("### Headline LOFO macros (strict)")
        lines.append("")
        lines.append("| Pipeline | Folds scored | Macro PR-AUC | Macro ROC-AUC |")
        lines.append("| --- | ---: | ---: | ---: |")
        for name, m in report.lofo_macros.items():
            lines.append(
                f"| `{name}` | {m['fold_count']} | "
                f"{m['macro_pr_auc']:.4f} | {m['macro_roc_auc']:.4f} |"
            )
        lines.append("")
        lines.append("### Per-family LOFO PR-AUC")
        lines.append("")
        all_families: list[str] = []
        seen: set[str] = set()
        for m in report.lofo_macros.values():
            for f in m["folds"]:
                if f["family"] not in seen:
                    seen.add(f["family"])
                    all_families.append(f["family"])
        header = "| Family | n_windows | n_pos | " + " | ".join(
            f"`{name}`" for name in report.lofo_macros.keys()
        ) + " |"
        sep = "| --- | ---: | ---: | " + " | ".join(["---:"] * len(report.lofo_macros)) + " |"
        lines.append(header)
        lines.append(sep)
        for family in all_families:
            cells = []
            n_win = n_pos = 0
            for name, m in report.lofo_macros.items():
                fold = next((f for f in m["folds"] if f["family"] == family), None)
                if fold is None:
                    cells.append("n/a")
                elif fold.get("pr_auc") is None:
                    n_win = fold["n_windows"]
                    n_pos = fold["n_positives"]
                    cells.append("skip")
                else:
                    n_win = fold["n_windows"]
                    n_pos = fold["n_positives"]
                    cells.append(f"{fold['pr_auc']:.4f}")
            lines.append(f"| {family} | {n_win} | {n_pos} | " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"
