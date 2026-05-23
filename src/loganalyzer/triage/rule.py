"""Rule baseline.

Mirrors the rule logic in scripts/research-lab/run_triage_benchmark.py: a
window scores high if (trace_error_rate or pod_unavailable or
log_error_count) cross simple thresholds. The score is a soft combination
so it can be calibrated and PR-AUC'd alongside the learned models.
"""

from __future__ import annotations

from .base import TriageModel
from ..data.schema import TriageWindow


class RuleTriageModel(TriageModel):
    name = "rule_baseline"
    features_used = [
        "triage_feature_trace_error_rate",
        "triage_feature_trace_error_count",
        "triage_feature_k8s_pod_unavailable_count",
        "triage_feature_log_error_count",
        "triage_feature_delta_trace_error_count",
    ]

    def fit(self, windows: list[TriageWindow]) -> None:
        # Stateless. The thresholds below are the contract defaults.
        return

    def predict_score(self, window: TriageWindow) -> float:
        r = window.raw
        trace_err_rate = float(r.get("triage_feature_trace_error_rate") or 0.0)
        trace_err_count = float(r.get("triage_feature_trace_error_count") or 0.0)
        pod_unavail = float(r.get("triage_feature_k8s_pod_unavailable_count") or 0.0)
        log_err = float(r.get("triage_feature_log_error_count") or 0.0)
        delta_trace_err = float(r.get("triage_feature_delta_trace_error_count") or 0.0)

        score = 0.0
        score += min(trace_err_rate, 1.0) * 0.50
        score += min(trace_err_count / 50.0, 1.0) * 0.20
        score += min(pod_unavail, 1.0) * 0.20
        score += min(log_err / 20.0, 1.0) * 0.05
        score += min(max(delta_trace_err, 0.0) / 20.0, 1.0) * 0.05
        return min(max(score, 0.0), 1.0)
