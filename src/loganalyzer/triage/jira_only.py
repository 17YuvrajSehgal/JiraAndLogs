"""JiraOnlyTriageModel: triage purely from Jira-memory features.

This is the cleanest test of "does the Jira-as-memory signal carry
standalone triage value?" - if it beats the rule baseline, the central
research claim has empirical support.

It is NOT meant as a production model. It deliberately ignores trace,
log, metric, and k8s features so any lift it shows comes purely from the
similarity-to-prior-tickets structure of the input.
"""

from __future__ import annotations

import math

from .base import TriageModel, label_to_target
from ..data.schema import TriageWindow
from ..features.numeric import (
    StandardScaler,
    standardize_apply,
    standardize_fit,
)

from jira_features import JIRA_FEATURE_COLUMNS, JiraMemoryFeaturizer


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class JiraOnlyTriageModel(TriageModel):
    """L2 logistic regression on JIRA_FEATURE_COLUMNS only."""

    name = "jira_only_logistic"

    def __init__(
        self,
        jira_featurizer: "JiraMemoryFeaturizer",
        *,
        l2: float = 1.0,
        learning_rate: float = 0.1,
        n_iters: int = 800,
        borderline_as: int = 0,
    ) -> None:
        if jira_featurizer is None:
            raise ValueError("JiraOnlyTriageModel requires a JiraMemoryFeaturizer")
        self.jira_featurizer = jira_featurizer
        self.features_used = list(JIRA_FEATURE_COLUMNS)
        self.l2 = l2
        self.learning_rate = learning_rate
        self.n_iters = n_iters
        self.borderline_as = borderline_as
        self.scaler: StandardScaler | None = None
        self.weights: list[float] = []
        self.bias: float = 0.0

    def fit(self, windows: list[TriageWindow]) -> None:
        if not windows:
            raise ValueError("Cannot fit on empty training data")
        if not self.jira_featurizer._fit_done:
            self.jira_featurizer.fit()

        x = [self.jira_featurizer.features_vector(w) for w in windows]
        self.scaler = standardize_fit(x)
        x = standardize_apply(x, self.scaler)
        y = [label_to_target(w.triage_label, borderline_as=self.borderline_as) for w in windows]

        n_features = len(x[0])
        w = [0.0] * n_features
        b = 0.0
        n = len(x)

        for _ in range(self.n_iters):
            grad_w = [0.0] * n_features
            grad_b = 0.0
            for xi, yi in zip(x, y):
                z = b + sum(w[j] * xi[j] for j in range(n_features))
                p = _sigmoid(z)
                err = p - yi
                grad_b += err
                for j in range(n_features):
                    grad_w[j] += err * xi[j]
            for j in range(n_features):
                w[j] -= self.learning_rate * (grad_w[j] / n + self.l2 * w[j] / n)
            b -= self.learning_rate * (grad_b / n)

        self.weights = w
        self.bias = b

    def predict_score(self, window: TriageWindow) -> float:
        if self.scaler is None:
            raise RuntimeError("Model has not been fit yet")
        xi = self.jira_featurizer.features_vector(window)
        xi_std = standardize_apply([xi], self.scaler)[0]
        z = self.bias + sum(self.weights[j] * xi_std[j] for j in range(len(self.weights)))
        return _sigmoid(z)

    def feature_importance(self) -> list[tuple[str, float]]:
        """Returns (feature_name, |standardized_weight|) sorted descending."""
        if not self.weights:
            return []
        return sorted(
            zip(JIRA_FEATURE_COLUMNS, [abs(w) for w in self.weights]),
            key=lambda kv: kv[1],
            reverse=True,
        )
