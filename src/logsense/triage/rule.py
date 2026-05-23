"""Hand-rolled rule baseline on log error burst.

Mirrors the philosophy of loganalyzer.triage.rule.RuleTriageModel but on the
log axis: error count, warning count, max burst-per-second, ratio of error
templates. Stateless - the rule is "if logs have a lot of errors and they
arrive in a tight burst, it's probably worth a ticket."
"""

from __future__ import annotations

from .base import LogTriageModel
from ..data.schema import LabeledWindowLogs, WindowLogs
from ..templates.fingerprint import fingerprint_window


class ErrorBurstRuleModel(LogTriageModel):
    name = "rule_error_burst"

    def fit(self, training: list[LabeledWindowLogs]) -> None:
        return  # stateless

    def predict_score(self, window: WindowLogs) -> float:
        fp = fingerprint_window(window)
        agg = fp.aggregate
        score = 0.0
        score += min(agg["error_count"] / 20.0, 1.0) * 0.40
        score += min(agg["warning_count"] / 20.0, 1.0) * 0.10
        score += min(agg["max_burst_per_sec"] / 30.0, 1.0) * 0.25
        score += min(agg["error_template_share"], 1.0) * 0.15
        score += min(agg["unique_templates"] / 40.0, 1.0) * 0.10
        return min(max(score, 0.0), 1.0)
