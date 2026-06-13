"""Pure metric functions used by the eval harness.

Apples-to-apples rule #4 says the same metric formula must be used for
every comparison. These functions define those formulas, with explicit
behaviour on edge cases (empty gold, ties, K > len). Callers reference
them rather than re-implementing.

Conventions:
  - `matched` is the agent's ranked list, position 0 = top-1.
  - `gold` is the set of acceptable answers.
  - `k` is 1-indexed in tradition; len-comparisons are 1-indexed too.
  - Cases with empty `gold` are excluded from `mean_hit_at_k` / `mean_reciprocal_rank`.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def hit_at_k(matched: Sequence[str], gold: Sequence[str], k: int) -> bool:
    """True iff any of `matched[:k]` is in `gold`.

    Empty `gold` always returns False — the mean wrapper filters those
    out before averaging."""
    if not gold:
        return False
    if k <= 0:
        return False
    gold_set = set(gold)
    return any(c in gold_set for c in matched[:k])


def reciprocal_rank(matched: Sequence[str], gold: Sequence[str]) -> float:
    """1/rank of the first gold hit (1-indexed); 0 if no hit or empty gold."""
    if not gold:
        return 0.0
    gold_set = set(gold)
    for i, c in enumerate(matched, start=1):
        if c in gold_set:
            return 1.0 / i
    return 0.0


def mean_hit_at_k(
    matched_per_case: Iterable[Sequence[str]],
    gold_per_case: Iterable[Sequence[str]],
    k: int,
) -> float:
    """Mean Hit@K, applying the apples-to-apples rule #4 filter:
    cases with empty `gold` are excluded from the denominator."""
    n = 0
    hits = 0
    for matched, gold in zip(matched_per_case, gold_per_case):
        if not gold:
            continue
        n += 1
        if hit_at_k(matched, gold, k):
            hits += 1
    if n == 0:
        return 0.0
    return hits / n


def mean_reciprocal_rank(
    matched_per_case: Iterable[Sequence[str]],
    gold_per_case: Iterable[Sequence[str]],
) -> float:
    """MRR with the same empty-gold filter as `mean_hit_at_k`."""
    n = 0
    rr_sum = 0.0
    for matched, gold in zip(matched_per_case, gold_per_case):
        if not gold:
            continue
        n += 1
        rr_sum += reciprocal_rank(matched, gold)
    if n == 0:
        return 0.0
    return rr_sum / n


# ---------------------------------------------------------------------------
# Pages-per-incident — the §7.4 ops metric
# ---------------------------------------------------------------------------


def pages_per_incident(
    triage_decisions: Iterable[str],
    incident_ids: Iterable[str | None],
) -> tuple[int, int, float]:
    """Return (n_pages, n_incidents, ratio).

    A "page" is a ticket_worthy decision. Borderline (post-suppression)
    decisions don't count as pages — they're attached to an existing
    incident. needs_review counts as a page (conservative — we'd want
    a human to look).

    An "incident" is each unique incident_id observed (None is excluded
    — windows without an attached incident haven't been assigned one).

    Ratio is `n_pages / n_incidents`. Target ≤ 1.5 vs cascade's ~6
    (§7.4). When there are no incidents, ratio is 0.0.
    """
    page_states = {"ticket_worthy", "needs_review"}
    n_pages = sum(1 for d in triage_decisions if d in page_states)
    unique = {i for i in incident_ids if i}
    n_incidents = len(unique)
    if n_incidents == 0:
        return n_pages, 0, 0.0
    return n_pages, n_incidents, n_pages / n_incidents
