"""PipelineRunner protocol + adapters for the existing analyzers.

Each runner is responsible for:
  - loading whatever data it needs from disk
  - fitting on the train split
  - picking a threshold on validation (matching the rest of the codebase)
  - emitting PipelinePrediction for every test-split window

The orchestrator (runner.py) only calls .train_and_predict() and gets a
PipelineResult back. Adding a new pipeline = subclass + register.

Pipelines that do NOT do retrieval (e.g. the classical-ML numeric
pipelines added 2026-05-26 for Phase 2 of the ML dev plan) emit
is_novel=None and matched_issue_ids=[]. The retrieval metrics for those
pipelines surface as 0 in the report — that is the correct "n/a" signal
for a pure classifier, not a bug.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

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
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
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
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
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
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
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
                    gold_expected_in_memory=getattr(lw.label, "expected_in_memory", None),
                    scenario_family=lw.scenario_family,
                    service_name=lw.logs.service_name,
                    window_type=lw.logs.window_type,
                    is_hard_case=getattr(lw.label, "is_hard_case", False),
                    triage_reason_class=getattr(lw.label, "triage_reason_class", None),
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
# Classical-ML numeric pipelines (Phase 2 of ML dev plan, 2026-05-26)
#
# These pipelines share data loading + threshold tuning with the loganalyzer
# adapters above but skip retrieval entirely — they exist to give the
# bootstrap-CI / pairwise-significance harness a head-to-head between the
# hand-crafted hybrid pipelines and off-the-shelf sklearn classifiers
# trained on the same production-safe numeric feature set.
#
# Both are feature-list-agnostic: the feature catalog is taken from
# ds.feature_columns (which itself is read from triage-feature-columns.json).
# When v5 emits new RED / business / runtime columns, they flow into these
# pipelines without any code change.
# ---------------------------------------------------------------------------


def _build_feature_matrix(
    windows: list[Any], feature_columns: list[str]
) -> list[list[float]]:
    """Pull the numeric feature vector out of each TriageWindow.raw dict.
    Missing columns zero-fill; that matches NumericFeaturizer behaviour and
    is what the contract documents."""
    return [
        [float(w.raw.get(col, 0.0) or 0.0) for col in feature_columns]
        for w in windows
    ]


class _NumericClassifierPipeline(PipelineRunner):
    """Shared scaffolding for any sklearn classifier that consumes the
    production-safe numeric features and emits probability scores.

    Subclasses define `name` and `_fit(X_train, y_train)` returning a
    fitted estimator that exposes `.predict_proba(X)[:, 1]`."""

    needs_scaling: bool = False

    def _fit(self, X_train: list[list[float]], y_train: list[int]) -> Any:
        raise NotImplementedError

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root  # numeric classifier doesn't need raw runs
        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        X_train = _build_feature_matrix(train, ds.feature_columns)
        X_val = _build_feature_matrix(val, ds.feature_columns)
        X_test = _build_feature_matrix(test, ds.feature_columns)
        y_train = [1 if w.triage_label == "ticket_worthy" else 0 for w in train]

        if self.needs_scaling:
            from sklearn.preprocessing import StandardScaler

            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train).tolist()
            X_val = scaler.transform(X_val).tolist()
            X_test = scaler.transform(X_test).tolist()

        t0 = time.time()
        model = self._fit(X_train, y_train)
        fit_seconds = time.time() - t0

        # threshold tuning on validation, same contract as loganalyzer
        if val:
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            val_scores = [float(p[1]) for p in model.predict_proba(X_val)]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5

        t0 = time.time()
        test_scores = [float(p[1]) for p in model.predict_proba(X_test)]
        predict_seconds = time.time() - t0

        predictions: list[PipelinePrediction] = []
        for w, score in zip(test, test_scores):
            decision = "ticket_worthy" if score >= threshold else "noise"
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision=decision,
                    # Pure classifier — no retrieval. None signals "n/a"
                    # so the retrieval metrics for this pipeline read 0.
                    is_novel=None,
                    matched_issue_ids=[],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
                )
            )

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
                "n_features": len(ds.feature_columns),
                "retrieval": "none",
            },
        )

    def lofo_evaluate(
        self,
        global_dir: Path,
        *,
        binarize_inclusive: bool = False,
    ) -> list[dict[str, Any]]:
        """Leave-one-family-out evaluation. Returns one record per fold with
        the held-out family's PR-AUC + ROC-AUC.

        For each family in the dataset's `leave_one_family_out_folds`:
          - train on all windows whose family is NOT this one,
          - score on windows whose family IS this one,
          - record metrics.

        Macro-averages are computed by the caller. Single-class folds (no
        positives) return pr_auc/roc_auc = None and are skipped from the
        macro by the caller, matching the run_triage_benchmark.py convention.
        """
        ds = load_loganalyzer_dataset(global_dir)
        all_windows = ds.windows
        folds = ds.split_manifest.leave_one_family_out_folds or sorted(
            {w.scenario_family for w in all_windows}
        )

        binarize = (
            (lambda w: 1 if w.triage_label in {"ticket_worthy", "borderline"} else 0)
            if binarize_inclusive
            else (lambda w: 1 if w.triage_label == "ticket_worthy" else 0)
        )

        records: list[dict[str, Any]] = []
        for family in folds:
            holdout = [w for w in all_windows if w.scenario_family == family]
            train_w = [w for w in all_windows if w.scenario_family != family]
            if not holdout or not train_w:
                continue
            y_holdout = [binarize(w) for w in holdout]
            n_pos = sum(y_holdout)
            n_neg = len(y_holdout) - n_pos
            if n_pos == 0 or n_neg == 0:
                records.append(
                    {
                        "family": family,
                        "n_windows": len(holdout),
                        "n_positives": n_pos,
                        "pr_auc": None,
                        "roc_auc": None,
                        "skipped": "single-class fold",
                    }
                )
                continue

            X_train = _build_feature_matrix(train_w, ds.feature_columns)
            X_holdout = _build_feature_matrix(holdout, ds.feature_columns)
            y_train = [binarize(w) for w in train_w]

            if self.needs_scaling:
                from sklearn.preprocessing import StandardScaler

                scaler = StandardScaler().fit(X_train)
                X_train = scaler.transform(X_train).tolist()
                X_holdout = scaler.transform(X_holdout).tolist()

            model = self._fit(X_train, y_train)
            scores = [float(p[1]) for p in model.predict_proba(X_holdout)]

            from loganalyzer.eval.metrics import pr_auc as _pr_auc
            from loganalyzer.eval.metrics import roc_auc as _roc_auc

            records.append(
                {
                    "family": family,
                    "n_windows": len(holdout),
                    "n_positives": n_pos,
                    "pr_auc": float(_pr_auc(scores, y_holdout)),
                    "roc_auc": float(_roc_auc(scores, y_holdout)),
                    "skipped": None,
                }
            )
        return records


class GradientBoostingPipeline(_NumericClassifierPipeline):
    """HistGradientBoosting over the production-safe numeric features.

    Strongest fast-to-train classical baseline for tabular telemetry data.
    Tree models are scale-invariant, so no standardization. `class_weight`
    handles the ~22% positive rate."""

    name = "hist_gradient_boosting_numeric"
    needs_scaling = False

    def __init__(
        self,
        *,
        max_iter: int = 300,
        learning_rate: float = 0.05,
        max_depth: int = 8,
        l2_regularization: float = 0.1,
        random_state: int = 42,
    ) -> None:
        self.max_iter = max_iter
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.l2_regularization = l2_regularization
        self.random_state = random_state

    def _fit(self, X_train: list[list[float]], y_train: list[int]) -> Any:
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=self.max_iter,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            l2_regularization=self.l2_regularization,
            class_weight="balanced",
            random_state=self.random_state,
        ).fit(X_train, y_train)


class CalibratedRandomForestPipeline(_NumericClassifierPipeline):
    """RandomForest wrapped in isotonic calibration on a CV split.

    Calibration matters: the Precision@FPR=1% headline is meaningless if
    the underlying probabilities aren't calibrated. RF probabilities are
    notoriously over-confident at the extremes; isotonic on a 3-fold inner
    split fixes that without leaking the val split."""

    name = "calibrated_random_forest_numeric"
    needs_scaling = False

    def __init__(
        self,
        *,
        n_estimators: int = 300,
        max_depth: int | None = None,
        min_samples_leaf: int = 5,
        cv: int = 3,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.cv = cv
        self.random_state = random_state

    def _fit(self, X_train: list[list[float]], y_train: list[int]) -> Any:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier

        base = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            class_weight="balanced",
            random_state=self.random_state,
            n_jobs=-1,
        )
        return CalibratedClassifierCV(base, method="isotonic", cv=self.cv).fit(
            X_train, y_train
        )


class LogisticNumericPipeline(_NumericClassifierPipeline):
    """sklearn L2-regularized logistic regression over the numeric features.

    Apples-to-apples comparison vs the stdlib logistic in
    scripts/research-lab/run_triage_benchmark.py — useful as a sanity check
    that the comparison harness is reading the same data."""

    name = "logistic_numeric_sklearn"
    needs_scaling = True

    def __init__(self, *, C: float = 1.0, max_iter: int = 2000) -> None:
        self.C = C
        self.max_iter = max_iter

    def _fit(self, X_train: list[list[float]], y_train: list[int]) -> Any:
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(
            C=self.C,
            class_weight="balanced",
            max_iter=self.max_iter,
            solver="lbfgs",
        ).fit(X_train, y_train)
