"""Per-window log fingerprint + baseline anomaly comparison.

A fingerprint summarises a window in three ways:
  1. dense aggregate features (n_lines, error_count, burst, ...)
  2. sparse template counts (template -> count) on the vocabulary
  3. severity-weighted top templates (used to surface explanations)

`compare_to_baseline` produces an "anomalous template" list - templates that
fire in the active window but not in a same-service pre_fault_baseline
window. This is the log-only signal that mirrors loganalyzer's
`delta_trace_error_count` feature: novelty vs the recent calm.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..data.schema import WindowLogs
from .miner import mask_line


# Aggregate feature names (dense, fixed-size, deterministic)
AGGREGATE_FEATURES = [
    "n_lines",
    "error_count",
    "warning_count",
    "info_count",
    "unique_templates",
    "max_burst_per_sec",
    "error_template_share",
    "duration_seconds",
]


@dataclass
class AnomalousTemplate:
    template: str
    count_active: int
    count_baseline: int
    severity: str
    example_body: str
    novelty_score: float  # higher = weirder


@dataclass
class WindowFingerprint:
    window_id: str
    aggregate: dict[str, float] = field(default_factory=dict)
    template_counts: Counter[str] = field(default_factory=Counter)
    severity_counts: Counter[str] = field(default_factory=Counter)
    example_by_template: dict[str, str] = field(default_factory=dict)

    def template_vector(self, vocabulary: list[str]) -> list[float]:
        return [float(self.template_counts.get(t, 0)) for t in vocabulary]

    def aggregate_vector(self) -> list[float]:
        return [self.aggregate.get(name, 0.0) for name in AGGREGATE_FEATURES]


def _max_burst_per_sec(timestamps_ns: list[int]) -> float:
    if not timestamps_ns:
        return 0.0
    if len(timestamps_ns) == 1:
        return 1.0
    sorted_s = sorted(t // 1_000_000_000 for t in timestamps_ns)
    counts = Counter(sorted_s)
    return float(max(counts.values()))


def fingerprint_window(window: WindowLogs) -> WindowFingerprint:
    fp = WindowFingerprint(window_id=window.window_id)
    if not window.lines:
        fp.aggregate = {name: 0.0 for name in AGGREGATE_FEATURES}
        return fp

    for ln in window.lines:
        tmpl = mask_line(ln.body)
        if not tmpl:
            continue
        fp.template_counts[tmpl] += 1
        fp.severity_counts[ln.severity] += 1
        fp.example_by_template.setdefault(tmpl, ln.body.strip()[:240])

    n_lines = float(len(window.lines))
    error_count = float(fp.severity_counts.get("error", 0) + fp.severity_counts.get("critical", 0))
    warning_count = float(fp.severity_counts.get("warning", 0))
    info_count = float(fp.severity_counts.get("info", 0))
    unique_templates = float(len(fp.template_counts))
    burst = _max_burst_per_sec([l.timestamp_ns for l in window.lines])
    duration = float(window.duration_seconds)
    error_template_share = 0.0
    if fp.template_counts:
        error_templates = 0
        # crude: templates whose modal severity bucket is error/warning
        # We re-tag from line severities since the miner here is stateless
        # for simplicity. This is an approximation, not exact.
        for tmpl in fp.template_counts:
            if any(
                mask_line(ln.body) == tmpl and ln.is_error
                for ln in window.lines[:200]  # cap scan
            ):
                error_templates += 1
        error_template_share = error_templates / unique_templates if unique_templates else 0.0

    fp.aggregate = {
        "n_lines": n_lines,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "unique_templates": unique_templates,
        "max_burst_per_sec": burst,
        "error_template_share": error_template_share,
        "duration_seconds": duration,
    }
    return fp


def compare_to_baseline(
    active: WindowFingerprint,
    baseline: WindowFingerprint | None,
    *,
    top_n: int = 5,
    severity_lookup: dict[str, str] | None = None,
) -> list[AnomalousTemplate]:
    """Return the top-N templates with the highest novelty vs baseline.

    novelty_score = active_count / (1 + baseline_count); we boost error
    templates by 2x so a single new error outranks 10 new infos.
    """
    severity_lookup = severity_lookup or {}
    items: list[AnomalousTemplate] = []
    for tmpl, active_count in active.template_counts.items():
        baseline_count = baseline.template_counts.get(tmpl, 0) if baseline else 0
        severity = severity_lookup.get(tmpl, "unknown")
        novelty = active_count / (1.0 + baseline_count)
        if severity in {"error", "critical", "warning"}:
            novelty *= 2.0
        items.append(
            AnomalousTemplate(
                template=tmpl,
                count_active=int(active_count),
                count_baseline=int(baseline_count),
                severity=severity,
                example_body=active.example_by_template.get(tmpl, tmpl),
                novelty_score=novelty,
            )
        )
    items.sort(key=lambda x: x.novelty_score, reverse=True)
    return items[:top_n]
