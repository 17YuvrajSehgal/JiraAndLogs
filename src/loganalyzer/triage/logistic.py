"""Pure-Python logistic regression on the numeric feature vector.

Matches the math in scripts/research-lab/run_triage_benchmark.py but exposed
as a reusable model class. L2-regularized, batch gradient descent on
standardized features. Tiny dataset (hundreds of rows), so stdlib is fine.
"""

from __future__ import annotations

import math

from .base import TriageModel, label_to_target
from ..data.schema import TriageWindow
from ..features.numeric import (
    NumericFeaturizer,
    StandardScaler,
    standardize_apply,
    standardize_fit,
)


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class LogisticTriageModel(TriageModel):
    name = "logistic_numeric"

    def __init__(
        self,
        feature_columns: list[str],
        *,
        l2: float = 1.0,
        learning_rate: float = 0.1,
        n_iters: int = 800,
        borderline_as: int = 0,
    ) -> None:
        self.featurizer = NumericFeaturizer(feature_columns)
        self.features_used = list(feature_columns)
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
        x = self.featurizer.transform(windows)
        self.scaler = standardize_fit(x)
        x = standardize_apply(x, self.scaler)
        y = [label_to_target(w.triage_label, borderline_as=self.borderline_as) for w in windows]

        n_features = len(x[0])
        w = [0.0] * n_features
        b = 0.0
        n = len(x)
        lr = self.learning_rate
        l2 = self.l2

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
                w[j] -= lr * (grad_w[j] / n + l2 * w[j] / n)
            b -= lr * (grad_b / n)

        self.weights = w
        self.bias = b

    def predict_score(self, window: TriageWindow) -> float:
        if self.scaler is None:
            raise RuntimeError("Model has not been fit yet")
        xi = self.featurizer.transform_one(window)
        xi_std = standardize_apply([xi], self.scaler)[0]
        z = self.bias + sum(self.weights[j] * xi_std[j] for j in range(len(self.weights)))
        return _sigmoid(z)
