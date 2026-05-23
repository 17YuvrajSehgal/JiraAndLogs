"""Anomaly-score model: how many of this window's templates were rare in
training?

Learns a per-template "ticket-worthy frequency" at .fit() time: for each
template, what fraction of training windows containing that template were
ticket-worthy. At inference time, score = weighted average of template
ticket-worthy frequency, weighted by how often the template appears in
this window.

This is unsupervised-ish (no gradient descent), purely template-statistic
based - useful as a sanity-check model and as a feature input for hybrids.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .base import LogTriageModel, label_to_target
from ..data.schema import LabeledWindowLogs, WindowLogs
from ..templates.miner import mask_line


class AnomalyScoreModel(LogTriageModel):
    name = "template_ticket_frequency"

    def __init__(self, *, min_template_support: int = 3, default_score: float = 0.4) -> None:
        self.min_template_support = min_template_support
        self.default_score = default_score
        self.template_pos_rate: dict[str, float] = {}
        self.template_support: dict[str, int] = {}
        self.global_pos_rate: float = default_score

    def fit(self, training: list[LabeledWindowLogs]) -> None:
        pos_total = 0
        for lw in training:
            if label_to_target(lw.triage_label) == 1:
                pos_total += 1
        self.global_pos_rate = pos_total / max(len(training), 1)

        pos_counts: dict[str, int] = defaultdict(int)
        support: Counter[str] = Counter()
        for lw in training:
            seen = set()
            for ln in lw.logs.lines:
                tmpl = mask_line(ln.body)
                if not tmpl or tmpl in seen:
                    continue
                seen.add(tmpl)
                support[tmpl] += 1
                if label_to_target(lw.triage_label) == 1:
                    pos_counts[tmpl] += 1

        self.template_support = dict(support)
        self.template_pos_rate = {
            tmpl: pos_counts[tmpl] / support[tmpl]
            for tmpl in support
            if support[tmpl] >= self.min_template_support
        }

    def predict_score(self, window: WindowLogs) -> float:
        if not window.lines:
            return self.global_pos_rate
        counts: Counter[str] = Counter()
        for ln in window.lines:
            tmpl = mask_line(ln.body)
            if tmpl:
                counts[tmpl] += 1
        if not counts:
            return self.global_pos_rate
        num = 0.0
        denom = 0.0
        for tmpl, c in counts.items():
            rate = self.template_pos_rate.get(tmpl, self.global_pos_rate)
            num += rate * c
            denom += c
        return num / max(denom, 1.0)
