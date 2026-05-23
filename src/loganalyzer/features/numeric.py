"""Numeric feature extraction from triage_feature_* columns.

The columns are the ones declared in triage-feature-columns.json - we trust
that file as the production-safe feature contract instead of hardcoding
column names, so adding a feature in the dataset builder picks up here
automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from ..data.schema import TriageWindow


class NumericFeaturizer:
    """Pulls the production-safe numeric vector out of each window.

    Stateless apart from the column list; the column list is supplied at
    construction time so callers can ablate features by passing a subset.
    """

    def __init__(self, feature_columns: list[str]) -> None:
        if not feature_columns:
            raise ValueError("feature_columns must be non-empty")
        self.feature_columns = list(feature_columns)

    def transform_one(self, window: TriageWindow) -> list[float]:
        row = window.raw
        return [float(row.get(col, 0.0) or 0.0) for col in self.feature_columns]

    def transform(self, windows: Iterable[TriageWindow]) -> list[list[float]]:
        return [self.transform_one(w) for w in windows]


@dataclass
class StandardScaler:
    means: list[float]
    stds: list[float]


def standardize_fit(matrix: list[list[float]]) -> StandardScaler:
    if not matrix:
        return StandardScaler(means=[], stds=[])
    n_features = len(matrix[0])
    means: list[float] = []
    stds: list[float] = []
    for j in range(n_features):
        col = [row[j] for row in matrix]
        mean = sum(col) / len(col)
        var = sum((v - mean) ** 2 for v in col) / max(1, len(col) - 1)
        means.append(mean)
        stds.append(max(math.sqrt(var), 1e-9))
    return StandardScaler(means=means, stds=stds)


def standardize_apply(matrix: list[list[float]], scaler: StandardScaler) -> list[list[float]]:
    out: list[list[float]] = []
    for row in matrix:
        out.append([(row[j] - scaler.means[j]) / scaler.stds[j] for j in range(len(row))])
    return out
