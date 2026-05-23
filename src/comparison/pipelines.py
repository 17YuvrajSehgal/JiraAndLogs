"""PipelineRunner protocol + adapters for the existing analyzers.

Each runner is responsible for:
  - loading whatever data it needs from disk
  - fitting on the train split
  - picking a threshold on validation (matching the rest of the codebase)
  - emitting PipelinePrediction for every test-split window

The orchestrator (runner.py) only calls .train_and_predict() and gets a
PipelineResult back. Adding a new pipeline = subclass + register.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

from jira_features import JiraMemoryFeaturizer

from loganalyzer.data.loaders import load_dataset as load_loganalyzer_dataset
from loganalyzer.data.splits import iter_split
from loganalyzer.eval.metrics import precision_at_fpr
from loganalyzer.memory.corpus import MemoryCorpus as LoganalyzerCorpus
from loganalyzer.memory.retrieval import BM25Retriever as LoganalyzerBM25
from loganalyzer.product.analyzer import SmartLogAnalyzer
from loganalyzer.triage.hybrid import HybridTriageModel
from loganalyzer.triage.jira_only import JiraOnlyTriageModel

from logsense.data.dataset import load_logs_dataset
from logsense.memory.retrieval import LogTemplateBM25Retriever
from logsense.product.analyzer import LogSenseAnalyzer
from logsense.triage.hybrid import HybridLogModel

from .schema import PipelinePrediction, PipelineResult


class PipelineRunner(ABC):
    name: str = "abstract"

    @abstractmethod
    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult: ...


# ---------------------------------------------------------------------------
# loganalyzer adapter
# ---------------------------------------------------------------------------


class LoganalyzerPipeline(PipelineRunner):
    name = "loganalyzer_hybrid_bm25"

    def __init__(self, *, retrieval_top_k: int = 5) -> None:
        self.retrieval_top_k = retrieval_top_k

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root  # loganalyzer doesn't need raw runs
        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        analyzer = SmartLogAnalyzer(
            triage_model=HybridTriageModel(ds.feature_columns),
            retriever=LoganalyzerBM25(),
            memory_corpus=LoganalyzerCorpus(issues=ds.memory_corpus),
            retrieval_top_k=self.retrieval_top_k,
        )

        t0 = time.time()
        analyzer.fit(train)
        fit_seconds = time.time() - t0

        # threshold tuning on validation
        if val:
            val_scores = analyzer.triage_model.predict_batch(val)
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5
        analyzer.triage_threshold = threshold

        t0 = time.time()
        predictions: list[PipelinePrediction] = []
        for w in test:
            result = analyzer.analyze(w)
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=result.triage_score,
                    triage_decision=result.triage_decision,
                    is_novel=result.is_novel,
                    matched_issue_ids=[h.issue_id for h in result.matched_issues],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                )
            )
        predict_seconds = time.time() - t0

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={"train_n": len(train), "val_n": len(val), "test_n": len(test)},
        )


# ---------------------------------------------------------------------------
# loganalyzer adapter, JIRA-AWARE variant (Phase 0.5)
# ---------------------------------------------------------------------------


class LoganalyzerWithJiraPipeline(PipelineRunner):
    """Same loganalyzer hybrid model, but its logistic head also consumes
    the Phase 0.5 JIRA_FEATURE_COLUMNS computed from time-ordered memory."""

    name = "loganalyzer_hybrid_with_jira"

    def __init__(self, *, retrieval_top_k: int = 5) -> None:
        self.retrieval_top_k = retrieval_top_k

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        corpus = LoganalyzerCorpus(issues=ds.memory_corpus)
        jira_featurizer = JiraMemoryFeaturizer(memory_corpus=corpus, top_k=self.retrieval_top_k)
        jira_featurizer.fit()

        analyzer = SmartLogAnalyzer(
            triage_model=HybridTriageModel(
                ds.feature_columns, jira_featurizer=jira_featurizer
            ),
            retriever=LoganalyzerBM25(),
            memory_corpus=corpus,
            retrieval_top_k=self.retrieval_top_k,
        )

        t0 = time.time()
        analyzer.fit(train)
        fit_seconds = time.time() - t0

        if val:
            val_scores = analyzer.triage_model.predict_batch(val)
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5
        analyzer.triage_threshold = threshold

        t0 = time.time()
        predictions: list[PipelinePrediction] = []
        for w in test:
            result = analyzer.analyze(w)
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=result.triage_score,
                    triage_decision=result.triage_decision,
                    is_novel=result.is_novel,
                    matched_issue_ids=[h.issue_id for h in result.matched_issues],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                )
            )
        predict_seconds = time.time() - t0

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train),
                "val_n": len(val),
                "test_n": len(test),
                "uses_jira_features": True,
            },
        )


# ---------------------------------------------------------------------------
# JIRA-ONLY adapter (Phase 0.5)
# ---------------------------------------------------------------------------


class JiraOnlyPipeline(PipelineRunner):
    """Triage purely from Phase 0.5 Jira-memory features. Tests whether the
    Jira-as-memory signal carries standalone value (must beat rule baseline
    for the central research principle to hold)."""

    name = "jira_only"

    def __init__(self, *, retrieval_top_k: int = 5) -> None:
        self.retrieval_top_k = retrieval_top_k

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        corpus = LoganalyzerCorpus(issues=ds.memory_corpus)
        jira_featurizer = JiraMemoryFeaturizer(memory_corpus=corpus, top_k=self.retrieval_top_k)
        jira_featurizer.fit()

        analyzer = SmartLogAnalyzer(
            triage_model=JiraOnlyTriageModel(jira_featurizer=jira_featurizer),
            retriever=LoganalyzerBM25(),
            memory_corpus=corpus,
            retrieval_top_k=self.retrieval_top_k,
        )

        t0 = time.time()
        analyzer.fit(train)
        fit_seconds = time.time() - t0

        if val:
            val_scores = analyzer.triage_model.predict_batch(val)
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5
        analyzer.triage_threshold = threshold

        t0 = time.time()
        predictions: list[PipelinePrediction] = []
        for w in test:
            result = analyzer.analyze(w)
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=result.triage_score,
                    triage_decision=result.triage_decision,
                    is_novel=result.is_novel,
                    matched_issue_ids=[h.issue_id for h in result.matched_issues],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                )
            )
        predict_seconds = time.time() - t0

        if hasattr(analyzer.triage_model, "feature_importance"):
            importance = list(analyzer.triage_model.feature_importance())
        else:
            importance = []

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train),
                "val_n": len(val),
                "test_n": len(test),
                "uses_jira_features": True,
                "jira_only": True,
                "feature_importance": importance,
            },
        )


# ---------------------------------------------------------------------------
# logsense adapter
# ---------------------------------------------------------------------------


class LogsensePipeline(PipelineRunner):
    name = "logsense_hybrid_bm25"

    def __init__(self, *, retrieval_top_k: int = 5, top_anomalies: int = 5) -> None:
        self.retrieval_top_k = retrieval_top_k
        self.top_anomalies = top_anomalies

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        ds = load_logs_dataset(global_dir, runs_root, progress_every=0)
        train = ds.by_split("train")
        val = ds.by_split("validation")
        test = ds.by_split("test")

        analyzer = LogSenseAnalyzer(
            triage_model=HybridLogModel(),
            retriever=LogTemplateBM25Retriever(),
            memory_corpus=LoganalyzerCorpus(issues=ds.memory_corpus),
            retrieval_top_k=self.retrieval_top_k,
            top_anomalies=self.top_anomalies,
        )

        t0 = time.time()
        analyzer.fit(train)
        fit_seconds = time.time() - t0

        if val:
            val_scores = analyzer.triage_model.predict_batch([lw.logs for lw in val])
            val_labels = [1 if lw.triage_label == "ticket_worthy" else 0 for lw in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5
        analyzer.triage_threshold = threshold

        t0 = time.time()
        predictions: list[PipelinePrediction] = []
        for lw in test:
            result = analyzer.analyze_labeled(lw)
            predictions.append(
                PipelinePrediction(
                    window_id=lw.window_id,
                    pipeline_name=self.name,
                    triage_score=result.triage_score,
                    triage_decision=result.triage_decision,
                    is_novel=result.is_novel,
                    matched_issue_ids=[h.issue_id for h in result.matched_issues],
                    gold_label=lw.triage_label,
                    gold_is_novel=lw.label.is_novel,
                    gold_matched_issue_ids=list(lw.label.matched_memory_issue_ids or []),
                    scenario_family=lw.scenario_family,
                    service_name=lw.logs.service_name,
                    window_type=lw.logs.window_type,
                )
            )
        predict_seconds = time.time() - t0

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={"train_n": len(train), "val_n": len(val), "test_n": len(test)},
        )
