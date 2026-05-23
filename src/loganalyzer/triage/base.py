"""Triage model contract.

Every triage model emits a single calibrated score in [0, 1] - the probability
the window is ticket-worthy. The label decision is delegated to
docs/triage-task-contract.md and lives in apply_threshold below: borderline
windows are NOT a third class output - the contract says we choose a single
operating threshold and report STRICT / INCLUSIVE metrics on the same scores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from ..data.schema import TriageWindow


@dataclass
class TriagePrediction:
    window_id: str
    score: float  # P(ticket-worthy) in [0, 1]
    label: str  # ticket_worthy | noise (borderline collapses per threshold)
    features_used: list[str]


class TriageModel(ABC):
    """Common fit/predict interface so the runner can swap models."""

    name: str = "abstract"

    @abstractmethod
    def fit(self, windows: list[TriageWindow]) -> None: ...

    @abstractmethod
    def predict_score(self, window: TriageWindow) -> float: ...

    def predict_batch(self, windows: Iterable[TriageWindow]) -> list[float]:
        return [self.predict_score(w) for w in windows]

    def predict(self, window: TriageWindow, threshold: float = 0.5) -> TriagePrediction:
        score = self.predict_score(window)
        return TriagePrediction(
            window_id=window.window_id,
            score=score,
            label="ticket_worthy" if score >= threshold else "noise",
            features_used=getattr(self, "features_used", []),
        )


def label_to_target(label: str, borderline_as: int = 0) -> int:
    """Binary target for training. STRICT trains with borderline as negative."""
    if label == "ticket_worthy":
        return 1
    if label == "borderline":
        return borderline_as
    return 0
