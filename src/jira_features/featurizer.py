"""JiraMemoryFeaturizer: window -> dict[str, float] of Jira-derived features.

We deliberately emit a SMALL, FIXED set of scalar features. Categorical
one-hot expansion (per-family, per-service) is tempting on paper but on
the 576-window pilot blows variance without benefit. Once v4-large lands
(~3700 windows) we can revisit per-family one-hots.

Every feature here is observable at inference time - it depends only on
window attributes already exposed in production (start_time, service_name,
dataset_run_id) and the visible-at-the-time memory corpus. Nothing reads
the window's own triage label or its gold matched_memory_issue_ids.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from loganalyzer.data.schema import TriageWindow
from loganalyzer.memory.corpus import MemoryCorpus, _parse_iso
from loganalyzer.memory.retrieval import BM25Retriever, RetrievalHit


# Ordered list of features the featurizer produces. Downstream triage models
# treat this as their input vocabulary.
JIRA_FEATURE_COLUMNS: list[str] = [
    "jira_max_score",
    "jira_top3_mean_score",
    "jira_top5_mean_score",
    "jira_score_spread_top1_top5",
    "jira_novelty_distance",
    "jira_n_visible_memory",
    "jira_n_above_half_top",
    "jira_top_service_matches_window",
    "jira_top_fault_compatible",
    "jira_recurring_same_service_24h",
    "jira_recurring_same_service_7d",
]


JIRA_FEATURE_DESCRIPTIONS: dict[str, str] = {
    "jira_max_score": "Highest retrieval score across the visible memory corpus.",
    "jira_top3_mean_score": "Mean score across the top-3 memory hits.",
    "jira_top5_mean_score": "Mean score across the top-5 memory hits.",
    "jira_score_spread_top1_top5": "top1 minus top5 score; high values = confident rank-1, low = diffuse cluster of hits.",
    "jira_novelty_distance": "1 / (1 + jira_max_score); high values = nothing in memory looks like this window.",
    "jira_n_visible_memory": "Count of memory entries visible to this window after time-ordering + own-run exclusion.",
    "jira_n_above_half_top": "Count of memory hits scoring at least half the top score.",
    "jira_top_service_matches_window": "1.0 if the top-1 hit's affected_service equals window.service_name.",
    "jira_top_fault_compatible": "1.0 if the top-1 hit's fault_compatibility_class is not 'none'.",
    "jira_recurring_same_service_24h": "Count of visible memory entries within 24h of window.start_time with same service.",
    "jira_recurring_same_service_7d": "Count of visible memory entries within 7d of window.start_time with same service.",
}


class _RetrieverLike(Protocol):
    """Anything with .fit(corpus) and .retrieve(window, corpus, top_k) works."""

    def fit(self, corpus: MemoryCorpus) -> None: ...
    def retrieve(self, window: TriageWindow, corpus: MemoryCorpus, *, top_k: int = 5) -> list[RetrievalHit]: ...


class JiraMemoryFeaturizer:
    """Compute Jira-memory features for any TriageWindow.

    Construction is deferred-fit: you build the object with a retriever and
    a corpus, then call .fit() once to index the corpus, then call
    .features_for(window) for each window.

    The retriever defaults to BM25 because:
      - it's already in the codebase
      - no extra dependencies
      - its scores are unbounded but consistently ordered, which is all the
        Jira-feature consumers need.
    """

    def __init__(
        self,
        memory_corpus: MemoryCorpus,
        *,
        retriever: _RetrieverLike | None = None,
        top_k: int = 5,
        recurring_window_24h: timedelta = timedelta(hours=24),
        recurring_window_7d: timedelta = timedelta(days=7),
    ) -> None:
        self.memory_corpus = memory_corpus
        self.retriever = retriever or BM25Retriever()
        self.top_k = top_k
        self.recurring_window_24h = recurring_window_24h
        self.recurring_window_7d = recurring_window_7d
        self._fit_done = False

    def fit(self) -> None:
        self.retriever.fit(self.memory_corpus)
        self._fit_done = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def features_for(self, window: TriageWindow) -> dict[str, float]:
        if not self._fit_done:
            raise RuntimeError("JiraMemoryFeaturizer.fit() must be called first")

        visible = self.memory_corpus.visible_to(window)
        n_visible = len(visible)
        hits = self.retriever.retrieve(window, self.memory_corpus, top_k=self.top_k)

        feats: dict[str, float] = {col: 0.0 for col in JIRA_FEATURE_COLUMNS}
        feats["jira_n_visible_memory"] = float(n_visible)

        if not hits:
            # Nothing visible OR empty retrieval. Leave score-derived features
            # at zero; recurring counts can still be computed from visible.
            self._fill_recurring_features(feats, visible, window)
            # Novelty is maximal when nothing matches
            feats["jira_novelty_distance"] = 1.0
            return feats

        scores = [h.score for h in hits]
        top1 = scores[0]
        top3_mean = sum(scores[:3]) / min(3, len(scores))
        top5_mean = sum(scores[: self.top_k]) / min(self.top_k, len(scores))
        top5_val = scores[min(self.top_k, len(scores)) - 1]
        n_above_half_top = sum(1 for s in scores if top1 > 0 and s >= 0.5 * top1)

        feats["jira_max_score"] = float(top1)
        feats["jira_top3_mean_score"] = float(top3_mean)
        feats["jira_top5_mean_score"] = float(top5_mean)
        feats["jira_score_spread_top1_top5"] = float(top1 - top5_val)
        feats["jira_novelty_distance"] = 1.0 / (1.0 + max(top1, 0.0))
        feats["jira_n_above_half_top"] = float(n_above_half_top)

        # Categorical-as-binary on the TOP hit
        top_issue = hits[0].issue
        feats["jira_top_service_matches_window"] = (
            1.0 if top_issue.affected_service == window.service_name else 0.0
        )
        feats["jira_top_fault_compatible"] = (
            1.0
            if top_issue.fault_compatibility_class
            and top_issue.fault_compatibility_class != "none"
            else 0.0
        )

        self._fill_recurring_features(feats, visible, window)
        return feats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_recurring_features(
        self,
        feats: dict[str, float],
        visible: list,
        window: TriageWindow,
    ) -> None:
        if not visible:
            return
        try:
            window_start = _parse_iso(window.start_time)
        except (ValueError, TypeError):
            return
        cutoff_24h = window_start - self.recurring_window_24h
        cutoff_7d = window_start - self.recurring_window_7d
        n_24 = 0
        n_7 = 0
        for issue in visible:
            if issue.affected_service != window.service_name:
                continue
            try:
                t = _parse_iso(issue.available_as_memory_from)
            except (ValueError, TypeError):
                continue
            if t >= cutoff_24h:
                n_24 += 1
            if t >= cutoff_7d:
                n_7 += 1
        feats["jira_recurring_same_service_24h"] = float(n_24)
        feats["jira_recurring_same_service_7d"] = float(n_7)

    def features_vector(self, window: TriageWindow) -> list[float]:
        feats = self.features_for(window)
        return [feats[col] for col in JIRA_FEATURE_COLUMNS]
