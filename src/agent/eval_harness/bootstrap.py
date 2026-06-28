"""Phase 3.5 — paired bootstrap CIs (RQ-C1 closure).

The §12 apples-to-apples contract calls for "1,000-resample paired
bootstrap, seed=42" as the statistical envelope for every headline.
This module is that utility.

Two flavors:

  - `bootstrap_metric` — single-system CI. Resamples case indices with
    replacement, recomputes the metric each time, reports the
    percentile CI.

  - `paired_bootstrap_delta` — two-system Δ-CI. Resamples the SAME
    indices for both systems each iteration so the delta is paired
    (the right test when systems are evaluated on the SAME windows,
    e.g., baseline vs ablation, uniform vs similarity-weighted).

The metric function takes a list of `CaseRow`s (a thin protocol — has
`matched_issue_ids` + `gold_matched_issue_ids`) and returns a float.
Three pre-built metric functions cover the headline set: Hit@1,
Hit@5, MRR. Custom metrics plug in via the `metric_fn` argument.

By convention: empty-gold rows are excluded inside the metric_fn (same
filter as `eval_harness.metrics`), so resamples that happen to draw
many empty-gold rows still produce a defined metric.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §12 rule 5.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol, Sequence


log = logging.getLogger(__name__)


#: Canonical configuration from the apples-to-apples contract.
DEFAULT_N_RESAMPLES = 1000
DEFAULT_SEED = 42
DEFAULT_CONFIDENCE = 0.95


# ---------------------------------------------------------------------------
# CaseRow protocol — anything with matched + gold lists works
# ---------------------------------------------------------------------------


class CaseRow(Protocol):
    """Minimal interface a bootstrap row needs.

    `eval_harness.CaseResult` satisfies it (it has both fields).
    Plain dicts that have these keys can be wrapped with `_DictRow`.
    """
    matched_issue_ids: Sequence[str]
    gold_matched_issue_ids: Sequence[str]


@dataclass(frozen=True)
class _DictRow:
    """Adapter for dict-shaped rows (e.g. cascade predictions JSONL)."""
    matched_issue_ids: Sequence[str]
    gold_matched_issue_ids: Sequence[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "_DictRow":
        return cls(
            matched_issue_ids=tuple(d.get("matched_issue_ids") or ()),
            gold_matched_issue_ids=tuple(d.get("gold_matched_issue_ids") or ()),
        )


def rows_from_dicts(rows: Iterable[dict[str, Any]]) -> list[_DictRow]:
    """Convenience: turn raw prediction dicts into _DictRow."""
    return [_DictRow.from_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pre-built metric functions
# ---------------------------------------------------------------------------


def _matched_ids(row: Any) -> Sequence[str]:
    """Extract matched_issue_ids from either a flat row or a
    CaseResult (which carries them under .decision)."""
    matched = getattr(row, "matched_issue_ids", None)
    if matched is None:
        decision = getattr(row, "decision", None)
        if decision is not None:
            matched = getattr(decision, "matched_issue_ids", None)
    if matched is None and isinstance(row, dict):
        matched = row.get("matched_issue_ids")
    return matched or ()


def _gold_ids(row: Any) -> Sequence[str]:
    """Extract gold_matched_issue_ids; same dual-shape support."""
    gold = getattr(row, "gold_matched_issue_ids", None)
    if gold is None and isinstance(row, dict):
        gold = row.get("gold_matched_issue_ids")
    return gold or ()


def metric_hit_at_k(rows: Sequence[CaseRow], *, k: int) -> float:
    """Hit@K with the standard `len(gold) >= 1` filter."""
    n = hits = 0
    for r in rows:
        gold = set(_gold_ids(r))
        if not gold:
            continue
        n += 1
        for i, m in enumerate(_matched_ids(r)):
            if i >= k:
                break
            if m in gold:
                hits += 1
                break
    return hits / n if n else 0.0


def metric_hit_at_1(rows: Sequence[CaseRow]) -> float:
    return metric_hit_at_k(rows, k=1)


def metric_hit_at_5(rows: Sequence[CaseRow]) -> float:
    return metric_hit_at_k(rows, k=5)


def metric_hit_at_10(rows: Sequence[CaseRow]) -> float:
    return metric_hit_at_k(rows, k=10)


def metric_mrr(rows: Sequence[CaseRow]) -> float:
    """Mean reciprocal rank with `len(gold) >= 1` filter."""
    n = 0
    total = 0.0
    for r in rows:
        gold = set(_gold_ids(r))
        if not gold:
            continue
        n += 1
        for i, m in enumerate(_matched_ids(r), start=1):
            if m in gold:
                total += 1.0 / i
                break
    return total / n if n else 0.0


def metric_triage_accuracy(rows: Sequence[Any]) -> float:
    """For CaseResult-shaped rows with `decision.triage_decision` and
    `gold_triage`. Returns 0.0 if no rows."""
    if not rows:
        return 0.0
    n_correct = 0
    for r in rows:
        # CaseResult shape: r.decision.triage_decision vs r.gold_triage
        decision = getattr(r, "decision", None)
        pred = getattr(decision, "triage_decision", None) if decision else None
        gold = getattr(r, "gold_triage", None)
        if pred is not None and gold is not None and pred == gold:
            n_correct += 1
    return n_correct / len(rows)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapResult:
    """Per-metric CI on a single system."""
    metric_name: str
    point_estimate: float
    mean: float
    ci_low: float
    ci_high: float
    n_resamples: int
    confidence: float
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "point_estimate": self.point_estimate,
            "mean": self.mean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n_resamples": self.n_resamples,
            "confidence": self.confidence,
            "seed": self.seed,
        }

    @property
    def ci_width(self) -> float:
        return self.ci_high - self.ci_low


@dataclass(frozen=True)
class PairedBootstrapResult:
    """Δ-CI for two systems evaluated on the same windows."""
    metric_name: str
    a_label: str
    b_label: str
    a_point: float
    b_point: float
    delta_point: float
    delta_mean: float
    delta_ci_low: float
    delta_ci_high: float
    fraction_b_better: float        # 0.0–1.0; "p-value-ish" for b vs a
    n_resamples: int
    confidence: float
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "a_label": self.a_label,
            "b_label": self.b_label,
            "a_point": self.a_point,
            "b_point": self.b_point,
            "delta_point": self.delta_point,
            "delta_mean": self.delta_mean,
            "delta_ci_low": self.delta_ci_low,
            "delta_ci_high": self.delta_ci_high,
            "fraction_b_better": self.fraction_b_better,
            "n_resamples": self.n_resamples,
            "confidence": self.confidence,
            "seed": self.seed,
        }

    def is_significant(self) -> bool:
        """True iff the Δ-CI excludes zero (95% by default)."""
        return self.delta_ci_low > 0 or self.delta_ci_high < 0


# ---------------------------------------------------------------------------
# Bootstrap drivers
# ---------------------------------------------------------------------------


def bootstrap_metric(
    rows: Sequence[CaseRow],
    metric_fn: Callable[[Sequence[CaseRow]], float],
    *,
    metric_name: str = "metric",
    n_resamples: int = DEFAULT_N_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> BootstrapResult:
    """Resample `rows` with replacement n_resamples times; recompute
    `metric_fn` on each resample; report a percentile CI.

    Edge cases:
      - len(rows) == 0 → all-zero result.
      - confidence must be in (0, 1).
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0,1), got {confidence}")
    n = len(rows)
    point = metric_fn(rows)
    if n == 0 or n_resamples <= 0:
        return BootstrapResult(
            metric_name=metric_name, point_estimate=point,
            mean=point, ci_low=point, ci_high=point,
            n_resamples=n_resamples, confidence=confidence, seed=seed,
        )

    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        resample = [rows[i] for i in idx]
        samples.append(metric_fn(resample))

    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    low = samples[int(alpha * n_resamples)]
    high = samples[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]
    mean = sum(samples) / n_resamples
    return BootstrapResult(
        metric_name=metric_name, point_estimate=point,
        mean=mean, ci_low=low, ci_high=high,
        n_resamples=n_resamples, confidence=confidence, seed=seed,
    )


def paired_bootstrap_delta(
    rows_a: Sequence[CaseRow],
    rows_b: Sequence[CaseRow],
    metric_fn: Callable[[Sequence[CaseRow]], float],
    *,
    metric_name: str = "metric",
    a_label: str = "A",
    b_label: str = "B",
    n_resamples: int = DEFAULT_N_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> PairedBootstrapResult:
    """Paired bootstrap: same resample indices applied to both systems.

    Requires `len(rows_a) == len(rows_b)`. Caller must ensure rows are
    aligned by window_id."""
    if len(rows_a) != len(rows_b):
        raise ValueError(
            f"paired_bootstrap_delta: a + b must have same length, "
            f"got {len(rows_a)} vs {len(rows_b)}",
        )
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0,1), got {confidence}")
    n = len(rows_a)
    a_point = metric_fn(rows_a)
    b_point = metric_fn(rows_b)
    delta_point = b_point - a_point

    if n == 0 or n_resamples <= 0:
        return PairedBootstrapResult(
            metric_name=metric_name,
            a_label=a_label, b_label=b_label,
            a_point=a_point, b_point=b_point, delta_point=delta_point,
            delta_mean=delta_point,
            delta_ci_low=delta_point, delta_ci_high=delta_point,
            fraction_b_better=0.5,
            n_resamples=n_resamples, confidence=confidence, seed=seed,
        )

    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        sub_a = [rows_a[i] for i in idx]
        sub_b = [rows_b[i] for i in idx]
        deltas.append(metric_fn(sub_b) - metric_fn(sub_a))

    deltas.sort()
    alpha = (1.0 - confidence) / 2.0
    low = deltas[int(alpha * n_resamples)]
    high = deltas[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]
    mean = sum(deltas) / n_resamples
    n_b_better = sum(1 for d in deltas if d > 0)
    n_ties = sum(1 for d in deltas if d == 0)
    # Split ties evenly when counting "fraction b better"
    fraction = (n_b_better + 0.5 * n_ties) / n_resamples

    return PairedBootstrapResult(
        metric_name=metric_name,
        a_label=a_label, b_label=b_label,
        a_point=a_point, b_point=b_point, delta_point=delta_point,
        delta_mean=mean, delta_ci_low=low, delta_ci_high=high,
        fraction_b_better=fraction,
        n_resamples=n_resamples, confidence=confidence, seed=seed,
    )


# ---------------------------------------------------------------------------
# Convenience: bootstrap a whole EvaluationReport's headlines
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadlineBootstrapReport:
    """All headline metrics bootstrapped for one EvaluationReport."""
    name: str
    n_cases: int
    n_resamples: int
    seed: int
    confidence: float
    metrics: dict[str, BootstrapResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "n_cases": self.n_cases,
            "n_resamples": self.n_resamples,
            "seed": self.seed,
            "confidence": self.confidence,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }


def bootstrap_eval_report(
    rows: Sequence[Any],
    *,
    name: str = "report",
    n_resamples: int = DEFAULT_N_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
    include_triage: bool = True,
) -> HeadlineBootstrapReport:
    """Bootstrap Hit@1, Hit@5, Hit@10, MRR for `rows`.

    `rows` must have `.matched_issue_ids` + `.gold_matched_issue_ids`.
    When `include_triage=True` and rows have CaseResult shape (with
    `.decision.triage_decision` + `.gold_triage`), also bootstrap
    triage_accuracy."""
    metrics: dict[str, BootstrapResult] = {}
    for name_, fn in (
        ("hit_at_1", metric_hit_at_1),
        ("hit_at_5", metric_hit_at_5),
        ("hit_at_10", metric_hit_at_10),
        ("mrr", metric_mrr),
    ):
        metrics[name_] = bootstrap_metric(
            rows, fn, metric_name=name_,
            n_resamples=n_resamples, seed=seed,
            confidence=confidence,
        )
    if include_triage and rows and hasattr(rows[0], "decision"):
        metrics["triage_accuracy"] = bootstrap_metric(
            rows, metric_triage_accuracy,
            metric_name="triage_accuracy",
            n_resamples=n_resamples, seed=seed,
            confidence=confidence,
        )
    return HeadlineBootstrapReport(
        name=name, n_cases=len(rows),
        n_resamples=n_resamples, seed=seed, confidence=confidence,
        metrics=metrics,
    )


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR correction over a family of p-values.

    Returns {"rejected": [bool,...], "qvalues": [float,...], "alpha": alpha,
    "n": len(pvalues)} in the ORIGINAL order. Use when reporting many RQ
    bootstrap tests together so the paper controls the false-discovery rate
    rather than reporting uncorrected per-test significance.
    """
    n = len(pvalues)
    if n == 0:
        return {"rejected": [], "qvalues": [], "alpha": alpha, "n": 0}
    order = sorted(range(n), key=lambda i: pvalues[i])
    q = [0.0] * n
    prev = 1.0
    # step-up: iterate from largest p to smallest, enforce monotonic q
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        val = pvalues[i] * n / rank
        prev = min(prev, val)
        q[i] = min(prev, 1.0)
    rejected = [q[i] <= alpha for i in range(n)]
    return {"rejected": rejected, "qvalues": q, "alpha": alpha, "n": n}
