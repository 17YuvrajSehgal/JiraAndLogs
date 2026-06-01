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


from .pipelines_retrieval import (
    BM25RetrievalPipeline,
    NomicLMRerankPipeline,
    NomicRetrievalPipeline,
)
from .pipelines_neural import (
    BiEncoderHybridPipeline,
    XgboostGPUPipeline,
)

# memorygraph lives in its own top-level package under src/.
# Soft-import so the comparison harness still works on installs that
# haven't pulled the optional package — the pipeline simply won't appear
# in KNOWN_PIPELINES if the import fails.
try:
    from memorygraph.pipeline import MemoryGraphPipeline
    _HAS_MEMORYGRAPH = True
except ImportError:
    _HAS_MEMORYGRAPH = False


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
    # Phase 4 retrieval-track pipelines (2026-05-26). BM25 is the cheap
    # baseline; Nomic is the production-recommended retriever; LM rerank
    # is gated on LM Studio reachability.
    "bm25_retrieval": BM25RetrievalPipeline,
    "nomic_retrieval": NomicRetrievalPipeline,
    "nomic_lm_rerank": NomicLMRerankPipeline,
    # GPU-aware neural pipelines (2026-05-26). Auto-detect CUDA via
    # util.device; fall back to CPU when no GPU is usable. Run
    # `python -m util.device_check` (or see src/util/device.py) to verify
    # the GPU stack before including these in a leaderboard run.
    "bi_encoder_hybrid": BiEncoderHybridPipeline,
    "xgb_gpu": XgboostGPUPipeline,
}

if _HAS_MEMORYGRAPH:
    # memorygraph: agentic cross-context retrieval. Builds a typed graph
    # of entities extracted from both observability windows and Jira
    # memory entries, then uses a skill-chain agent (rule-based by
    # default, LLM-planned optionally) to score + explain matches.
    KNOWN_PIPELINES["memorygraph"] = MemoryGraphPipeline

    # memorygraph_hybrid: same agent + graph, plus a NumericBlendSkill
    # that fits a HistGradientBoosting head on the train-split numeric
    # features and blends the per-window probability into the per-
    # candidate graph+similarity score inside triage_decide. Targets the
    # observation that on v5-quick the numeric pipelines (hgb, rf) carry
    # most of the triage PR-AUC while memorygraph carries the
    # *explanation*.
    class _MemoryGraphHybrid(MemoryGraphPipeline):
        name = "memorygraph_hybrid"

        def __init__(self) -> None:
            super().__init__(with_numeric=True)

    KNOWN_PIPELINES["memorygraph_hybrid"] = _MemoryGraphHybrid

    # memorygraph_full: hybrid + Nomic dense similarity (via LM Studio).
    # Falls back gracefully to BM25-only if LM Studio is unreachable, so
    # this pipeline is always safe to include in a leaderboard run.
    class _MemoryGraphFull(MemoryGraphPipeline):
        name = "memorygraph_full"

        def __init__(self) -> None:
            super().__init__(with_numeric=True, with_embeddings=True)

    KNOWN_PIPELINES["memorygraph_full"] = _MemoryGraphFull

    # Phase 5.3 cross-train pair: identical to memorygraph_hybrid and
    # memorygraph_full but with the Jira memory corpus swapped from the
    # known-leaky legacy jira-memory-corpus.jsonl (100% contamination
    # per the text-leakage canary, commit b704cb8) to the sanitizer-
    # verified humanized corpus at jira-shadow-humanized-v1/bulk-20260529/.
    # Running a comparison harness with both legacy and humanized
    # variants side-by-side quantifies the leakage premium the legacy
    # corpus was paying.
    class _MemoryGraphHybridHumanized(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True, humanized_subdir="bulk-20260529",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized"] = _MemoryGraphHybridHumanized

    class _MemoryGraphFullHumanized(MemoryGraphPipeline):
        name = "memorygraph_full_humanized"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True, with_embeddings=True,
                humanized_subdir="bulk-20260529",
            )

    KNOWN_PIPELINES["memorygraph_full_humanized"] = _MemoryGraphFullHumanized

    # Move A from ML-NEW-IDEAS.MD: swap the trace-aggregate
    # evidence_text query for a characteristic-log-lines query
    # extracted from raw/loki/<window>.json. E5+E6 showed both BM25
    # and Nomic dense embeddings cap at Recall@5 ≈ 0.07 on the clean
    # humanized corpus when the source-side is evidence_text. This
    # variant tests whether engineer-vocabulary on the source side
    # unlocks meaningful retrieval. BM25-only (no Nomic) so the
    # comparison stays fast and isolates the log-signature effect.
    class _MemoryGraphHybridHumanizedLogs(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_logs"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                with_log_signatures=True,
                humanized_subdir="bulk-20260529",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_logs"] = _MemoryGraphHybridHumanizedLogs

    # V2 pipeline variants (2026-06-01). Identical structure to the V1
    # humanized variants but read the multi-channel V2 corpus at
    # jira-shadow-humanized-v2/bulk-20260531/. memory_text in V2 leads
    # with description_code (engineer-vocabulary log lines per §13.12)
    # so BM25 / embedding retrieval has rich engineer-vocab to match
    # against. The hypothesis tested by these variants: V2 lifts
    # retrieval past the V1 ceiling (R@5 ~0.07 per E5/E6/E7) because
    # the destination side now speaks the same vocabulary as the
    # query side. See LLM-Jira-enhancement.md §14 for V2 details.
    class _MemoryGraphHybridHumanizedV2(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_v2"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_v2"] = _MemoryGraphHybridHumanizedV2

    class _MemoryGraphFullHumanizedV2(MemoryGraphPipeline):
        name = "memorygraph_full_humanized_v2"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                with_embeddings=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
            )

    KNOWN_PIPELINES["memorygraph_full_humanized_v2"] = _MemoryGraphFullHumanizedV2

    # V2 + log-signature query (Move A) on the V2 corpus. With V2's
    # description_code on the destination side AND log-signature on the
    # query side, BOTH sides share engineer vocabulary — this is the
    # configuration E7's analysis predicted would unlock retrieval.
    class _MemoryGraphHybridHumanizedV2Logs(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_v2_logs"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                with_log_signatures=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_v2_logs"] = _MemoryGraphHybridHumanizedV2Logs

    # V2 with distractors mixed in — for measuring top-1 precision
    # against the distractor set per §13.6. Distractors are loaded from
    # jira-shadow-humanized-v2-distractors/mint-20260601/timeline.jsonl
    # alongside the real V2 corpus. Distractor tickets carry
    # scenario_family="__DISTRACTOR__" so the ground-truth evaluator
    # can never count a distractor as a TP — but the retriever can
    # surface one as a top-K match, which is exactly what we want to
    # measure.
    from pathlib import Path as _Path

    class _MemoryGraphHybridHumanizedV2Distractors(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_v2_distractors"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
                distractor_path=_Path(
                    "data/derived/global/2026-05-25-dataset-v5-large-global/"
                    "jira-shadow-humanized-v2-distractors/mint-20260601/timeline.jsonl"
                ),
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_v2_distractors"] = (
        _MemoryGraphHybridHumanizedV2Distractors
    )

    # Cross-encoder reranker on V2 (2026-06-01). Layers MS-MARCO
    # MiniLM-L-6-v2 cross-encoder over the BM25 top-K to rerank.
    # Cross-encoder joint scoring is +5-10 nDCG over bi-encoder on
    # retrieval benchmarks — this variant tests whether that lift
    # closes the V2-comparative-analysis R@5 ceiling (0.0745 ->
    # hopefully 0.10+).
    class _MemoryGraphHybridHumanizedV2CrossEnc(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_v2_crossenc"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                with_cross_encoder=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_v2_crossenc"] = (
        _MemoryGraphHybridHumanizedV2CrossEnc
    )

    # V2 + Move A logs + Cross-encoder rerank — the maximally-stacked
    # retrieval pipeline. Tests the ceiling: engineer-vocab on both
    # source (log signatures) AND destination (V2 description_code)
    # AND cross-encoder joint scoring on the top-K.
    class _MemoryGraphHybridHumanizedV2LogsCrossEnc(MemoryGraphPipeline):
        name = "memorygraph_hybrid_humanized_v2_logs_crossenc"

        def __init__(self) -> None:
            super().__init__(
                with_numeric=True,
                with_log_signatures=True,
                with_cross_encoder=True,
                humanized_subdir="bulk-20260531",
                humanized_root="jira-shadow-humanized-v2",
            )

    KNOWN_PIPELINES["memorygraph_hybrid_humanized_v2_logs_crossenc"] = (
        _MemoryGraphHybridHumanizedV2LogsCrossEnc
    )


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


def _render_jira_helps_section(report: ComparisonReport) -> list[str]:
    """Direct pairwise comparison of the with-Jira vs without-Jira variants.

    Answers the central corporate research thesis: 'does adding historical
    Jira data to triage actually help vs telemetry-only triage?'.

    Compares (when both are present):
      loganalyzer_hybrid_bm25            vs  loganalyzer_hybrid_with_jira
      <any numeric/telemetry baseline>   vs  jira_only

    Verdict in plain English based on the strict-PR-AUC delta + bootstrap
    significance from `report.pairwise_per_metric['pr_auc']`."""
    lines: list[str] = []
    by_name = {r.pipeline_name: r for r in report.results}
    pairs = []
    if "loganalyzer_hybrid_bm25" in by_name and "loganalyzer_hybrid_with_jira" in by_name:
        pairs.append(("loganalyzer_hybrid_bm25", "loganalyzer_hybrid_with_jira",
                      "Same loganalyzer model, with vs without Jira-derived features"))
    if "jira_only" in by_name:
        # Compare jira_only to whatever numeric baseline is present
        for baseline in ("hist_gradient_boosting_numeric", "calibrated_random_forest_numeric",
                         "loganalyzer_hybrid_bm25"):
            if baseline in by_name:
                pairs.append((baseline, "jira_only",
                              "Telemetry-only baseline vs Jira-memory-only"))
                break
    if not pairs:
        return lines

    lines.append("## Research thesis: does Jira memory help log triage?")
    lines.append("")
    lines.append(
        "Direct head-to-head between pipelines that DO and DO NOT use the "
        "Jira memory corpus, on the strict triage task. This is the central "
        "claim the dataset was built to test — whether historical Jira "
        "tickets carry signal beyond what telemetry features alone can "
        "extract."
    )
    lines.append("")
    headline = report.headline or {}
    pair_ci = report.pairwise_per_metric.get("pr_auc", [])
    lines.append("| Comparison | Without Jira PR-AUC | With Jira PR-AUC | Δ (with − without) | 95% CI | p-value | Significant? | Verdict |")
    lines.append("| --- | ---: | ---: | ---: | --- | ---: | :---: | --- |")
    for a, b, description in pairs:
        pa = headline.get(a, {}).get("triage.pr_auc", 0.0)
        pb = headline.get(b, {}).get("triage.pr_auc", 0.0)
        delta = pb - pa
        # Pull the matching CI from paired bootstrap, if present (the
        # significance.py rows store both directions sorted by name)
        ci_row = next((d for d in pair_ci
                       if (d.pipeline_a == a and d.pipeline_b == b)
                       or (d.pipeline_a == b and d.pipeline_b == a)), None)
        if ci_row is None:
            ci_str, p_str, sig = "n/a", "n/a", "n/a"
        else:
            # If the CI row is in the opposite direction, flip
            if ci_row.pipeline_a == b:
                lo, hi, d = -ci_row.ci.hi, -ci_row.ci.lo, -ci_row.delta
            else:
                lo, hi, d = ci_row.ci.lo, ci_row.ci.hi, ci_row.delta
            ci_str = f"[{lo:+.4f}, {hi:+.4f}]"
            p_str = f"{ci_row.p_value:.3f}"
            sig = "yes" if ci_row.p_value < 0.05 else "no"
            delta = d
        # Verdict in plain English
        if abs(delta) < 0.01:
            verdict = "Jira makes no measurable difference"
        elif delta > 0 and sig == "yes":
            verdict = "**Jira HELPS** (significant)"
        elif delta > 0:
            verdict = "Jira helps slightly (not significant)"
        elif delta < 0 and sig == "yes":
            verdict = "**Jira HURTS** (significant)"
        else:
            verdict = "Jira hurts slightly (not significant)"
        lines.append(
            f"| `{a}` vs `{b}` | {pa:.4f} | {pb:.4f} | "
            f"{delta:+.4f} | {ci_str} | {p_str} | {sig} | {verdict} |"
        )
    lines.append("")
    lines.append(
        "_Interpretation guide:_ A positive Δ with `Significant=yes` means "
        "the Jira-aware pipeline beats the non-Jira pipeline beyond what "
        "bootstrap-resampling could explain by chance. A negative Δ means "
        "Jira features confused the model more than they helped — usually "
        "a sign that the Jira memory corpus is too small, too template-y, "
        "or that the test windows fall in scenario families absent from "
        "the memory."
    )
    return lines


def render_report_md(report: ComparisonReport) -> str:
    lines: list[str] = ["# Comparison Report", ""]
    lines.append("Pipelines:")
    for r in report.results:
        lines.append(
            f"- `{r.pipeline_name}` (threshold={r.triage_threshold:.4f}, "
            f"fit={r.fit_seconds:.1f}s, predict={r.predict_seconds:.1f}s)"
        )

    # Corporate thesis section — placed near the top so it answers the
    # "is the Jira-as-memory idea actually working?" question first.
    lines.append("")
    lines.extend(_render_jira_helps_section(report))

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

    # --- Corporate-report stratification axes (2026-05-26) ----------------
    # is_hard_case, triage_reason_class, is_novel — added per the corporate
    # ask. is_hard_case in particular surfaces "are we serving the hard
    # cases?" which is the most product-relevant stratification.
    for axis_label, axis_prefix, metric, group, description in (
        (
            "is_hard_case (True = engineered to confuse simple models)",
            "is_hard_case=",
            "f1_at_fpr_5pct",
            "triage",
            "F1 here directly answers 'does the pipeline handle hard cases?'. "
            "The gap between true and false is the practical hard-case headroom.",
        ),
        (
            "triage_reason_class",
            "triage_reason_class=",
            "pr_auc",
            "triage",
            "Per fault category — `outage`, `latency_regression`, `restart_with_"
            "impact`, etc. Rows where PR-AUC is low identify the fault types "
            "your model doesn't detect well.",
        ),
        (
            "is_novel (true = no matching past Jira; false = match exists; unscored = not ticket_worthy)",
            "is_novel=",
            "pr_auc",
            "triage",
            "Novel incidents are the product axis where Jira pattern matching "
            "fundamentally cannot help — the model must detect from telemetry "
            "alone. If pipelines drop substantially on `novel` vs `known`, "
            "they're leaning on memory pattern matching.",
        ),
    ):
        rows = [s for s in report.strata if s.strata_key.startswith(axis_prefix)]
        if not rows:
            continue
        lines.append("")
        lines.append(f"## Stratified by {axis_label}")
        lines.append("")
        lines.append(description)
        lines.append("")
        lines.append(
            render_strata_table(
                rows, metric=metric, metric_group=group,
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
