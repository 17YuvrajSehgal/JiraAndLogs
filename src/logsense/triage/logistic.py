"""Logistic regression over sparse template-count features.

Builds a vocabulary at .fit() time (top-K most frequent templates across
the training corpus), turns each window into a (vocab_size + aggregates)
vector, and learns an L2 logistic. Pure stdlib so we don't fight numpy on
sparse matrices; vocabulary size is capped at 2000 which keeps training
fast on a v4-large run.
"""

from __future__ import annotations

import math

from .base import LogTriageModel, label_to_target
from ..data.schema import LabeledWindowLogs, WindowLogs
from ..templates.fingerprint import AGGREGATE_FEATURES, fingerprint_window
from ..templates.miner import TemplateMiner


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class TemplateLogisticModel(LogTriageModel):
    name = "logistic_template_counts"

    def __init__(
        self,
        *,
        vocab_size: int = 1000,
        l2: float = 1.0,
        learning_rate: float = 0.05,
        n_iters: int = 600,
        borderline_as: int = 0,
    ) -> None:
        self.vocab_size = vocab_size
        self.l2 = l2
        self.learning_rate = learning_rate
        self.n_iters = n_iters
        self.borderline_as = borderline_as
        self.vocabulary: list[str] = []
        self.weights: list[float] = []
        self.bias: float = 0.0
        self.feature_means: list[float] = []
        self.feature_stds: list[float] = []
        self.miner = TemplateMiner()

    def _feature_vector(self, window: WindowLogs) -> list[float]:
        fp = fingerprint_window(window)
        template_vec = fp.template_vector(self.vocabulary)
        agg_vec = fp.aggregate_vector()
        return template_vec + agg_vec

    def fit(self, training: list[LabeledWindowLogs]) -> None:
        # 1. mine the vocabulary across all training windows
        for lw in training:
            self.miner.fit_lines(lw.logs.lines)
        self.vocabulary = self.miner.vocabulary(self.vocab_size)

        # 2. featurize and standardize
        x = [self._feature_vector(lw.logs) for lw in training]
        if not x:
            raise ValueError("No training windows")
        n_features = len(x[0])
        means = [sum(row[j] for row in x) / len(x) for j in range(n_features)]
        stds: list[float] = []
        for j in range(n_features):
            var = sum((row[j] - means[j]) ** 2 for row in x) / max(1, len(x) - 1)
            stds.append(max(math.sqrt(var), 1e-9))
        self.feature_means = means
        self.feature_stds = stds
        x = [
            [(row[j] - means[j]) / stds[j] for j in range(n_features)]
            for row in x
        ]
        y = [label_to_target(lw.triage_label, borderline_as=self.borderline_as) for lw in training]

        # 3. batch gradient descent
        w = [0.0] * n_features
        b = 0.0
        lr = self.learning_rate
        l2 = self.l2
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
                w[j] -= lr * (grad_w[j] / n + l2 * w[j] / n)
            b -= lr * (grad_b / n)
        self.weights = w
        self.bias = b

    def predict_score(self, window: WindowLogs) -> float:
        if not self.weights:
            raise RuntimeError("Model has not been fit yet")
        raw = self._feature_vector(window)
        x = [
            (raw[j] - self.feature_means[j]) / self.feature_stds[j]
            for j in range(len(raw))
        ]
        z = self.bias + sum(self.weights[j] * x[j] for j in range(len(self.weights)))
        return _sigmoid(z)
