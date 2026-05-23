"""Hybrid triage: simple weighted blend of numeric + lexical scores."""

from __future__ import annotations

from .base import TriageModel
from .logistic import LogisticTriageModel
from .lexical import LexicalTriageModel
from ..data.schema import TriageWindow


class HybridTriageModel(TriageModel):
    name = "hybrid_numeric_lexical"

    def __init__(
        self,
        feature_columns: list[str],
        *,
        numeric_weight: float = 0.7,
        lexical_weight: float = 0.3,
        borderline_as: int = 0,
        jira_featurizer=None,
    ) -> None:
        self.numeric = LogisticTriageModel(
            feature_columns,
            borderline_as=borderline_as,
            jira_featurizer=jira_featurizer,
        )
        self.lexical = LexicalTriageModel(borderline_as=borderline_as)
        self.numeric_weight = numeric_weight
        self.lexical_weight = lexical_weight
        self.features_used = self.numeric.features_used + self.lexical.features_used
        if jira_featurizer is not None:
            self.name = "hybrid_numeric_lexical_with_jira"

    def fit(self, windows: list[TriageWindow]) -> None:
        self.numeric.fit(windows)
        self.lexical.fit(windows)

    def predict_score(self, window: TriageWindow) -> float:
        n_score = self.numeric.predict_score(window)
        l_score = self.lexical.predict_score(window)
        return self.numeric_weight * n_score + self.lexical_weight * l_score
