"""Hybrid log triage: blend of rule + logistic + anomaly score."""

from __future__ import annotations

from .anomaly import AnomalyScoreModel
from .base import LogTriageModel
from .logistic import TemplateLogisticModel
from .rule import ErrorBurstRuleModel
from ..data.schema import LabeledWindowLogs, WindowLogs


class HybridLogModel(LogTriageModel):
    name = "hybrid_log"

    def __init__(
        self,
        *,
        rule_weight: float = 0.25,
        logistic_weight: float = 0.55,
        anomaly_weight: float = 0.20,
        vocab_size: int = 1000,
        borderline_as: int = 0,
    ) -> None:
        self.rule = ErrorBurstRuleModel()
        self.logistic = TemplateLogisticModel(
            vocab_size=vocab_size, borderline_as=borderline_as
        )
        self.anomaly = AnomalyScoreModel()
        self.rule_weight = rule_weight
        self.logistic_weight = logistic_weight
        self.anomaly_weight = anomaly_weight

    def fit(self, training: list[LabeledWindowLogs]) -> None:
        self.rule.fit(training)
        self.logistic.fit(training)
        self.anomaly.fit(training)

    def predict_score(self, window: WindowLogs) -> float:
        return (
            self.rule_weight * self.rule.predict_score(window)
            + self.logistic_weight * self.logistic.predict_score(window)
            + self.anomaly_weight * self.anomaly.predict_score(window)
        )
