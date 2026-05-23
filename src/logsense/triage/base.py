"""LogTriageModel contract.

A log triage model takes a stream of LabeledWindowLogs (or a single
WindowFingerprint at inference time) and emits a calibrated score in
[0, 1] - the probability that the window is ticket-worthy purely on the
strength of its log signal.

Borderline windows are folded into the negative class at training time -
the contract in docs/triage-task-contract.md handles them through STRICT
vs INCLUSIVE metrics on the same score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..data.schema import LabeledWindowLogs, WindowLogs


@dataclass
class LogTriagePrediction:
    window_id: str
    score: float
    label: str  # ticket_worthy | noise


class LogTriageModel(ABC):
    name: str = "abstract_log_model"

    @abstractmethod
    def fit(self, training: list[LabeledWindowLogs]) -> None: ...

    @abstractmethod
    def predict_score(self, window: WindowLogs) -> float: ...

    def predict_batch(self, windows: list[WindowLogs]) -> list[float]:
        return [self.predict_score(w) for w in windows]


def label_to_target(label: str, borderline_as: int = 0) -> int:
    if label == "ticket_worthy":
        return 1
    if label == "borderline":
        return borderline_as
    return 0
