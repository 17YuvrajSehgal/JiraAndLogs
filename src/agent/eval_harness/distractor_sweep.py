"""Phase 3.4 — Similarity-weighted distractor sweep (RQ-A4 closure).

Mode 1 (`docs7/MODE1-DISTRACTOR-RESULTS.md`) gave the **lower bound**:
each top-K slot is independently replaced with a *placeholder* distractor
at probability `p = n_distractors / (n_distractors + n_memory)`. Pool
size, not vocabulary, drove the deltas (identity-agnostic).

This module gives the **identity-aware** sweep: replacement probability
PER WINDOW scales with how textually similar that window is to the
distractors. Same expected total replacement count as the uniform model,
but redistributed — windows whose top-similar distractor *looks like*
their evidence get hit harder, exactly the mechanism that gold gets
pushed out in real retrieval.

Algorithm:

    1. Build TF-IDF over window + distractor texts (shared vocabulary).
    2. For each window w, compute sim_max[w] = max cos(w, d) over d.
    3. Compute window weight[w] = sim_max[w] / mean(sim_max),
       capped at WEIGHT_CAP (defends against outliers).
    4. Per-window displacement prob:
            p_w = clip( p_baseline * weight[w], 0, 1 )
       — by construction E[p_w] ≈ p_baseline so total expected
       displacements match uniform; only the distribution changes.
    5. For each top-K slot, independently replace with the next
       most-similar distractor for window w at probability p_w.

The replacement IDs are synthetic placeholders (`DISTRACTOR-XYZ`), so
they never coincidentally match gold — the comparison isolates the
identity effect from any vocabulary fluke.

Closes RQ-A4 per `docs7/MODE1-DISTRACTOR-RESULTS.md` §5 Level 1.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


log = logging.getLogger(__name__)


#: Cap on per-window weight (prevents one outlier window from absorbing
#: all displacement budget). 3× the mean = "this window is 3× more
#: similar to its top distractor than the average window".
WEIGHT_CAP = 3.0


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RatioResult:
    ratio_pct: int
    n_distractors: int
    p_per_slot_baseline: float
    hit_at_1: float
    hit_at_5: float
    mrr: float
    n_with_gold: int
    mean_p_per_slot_realized: float = 0.0      # only set in weighted runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratio_pct": self.ratio_pct,
            "n_distractors": self.n_distractors,
            "p_per_slot_baseline": self.p_per_slot_baseline,
            "mean_p_per_slot_realized": self.mean_p_per_slot_realized,
            "hit_at_1": self.hit_at_1,
            "hit_at_5": self.hit_at_5,
            "mrr": self.mrr,
            "n_with_gold": self.n_with_gold,
        }


@dataclass(frozen=True)
class DistractorSweepReport:
    method: str                                # "uniform" | "similarity_weighted"
    n_windows: int
    n_distractors_pool: int
    n_memory: int
    seed: int
    ratios: tuple[_RatioResult, ...] = field(default_factory=tuple)
    sim_summary: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "n_windows": self.n_windows,
            "n_distractors_pool": self.n_distractors_pool,
            "n_memory": self.n_memory,
            "seed": self.seed,
            "ratios": [r.to_dict() for r in self.ratios],
            "sim_summary": dict(self.sim_summary),
        }


# ---------------------------------------------------------------------------
# Hit@K / MRR — identical to the cascade's v2_advanced/tch helper
# ---------------------------------------------------------------------------


def _compute_metrics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit@1 + Hit@5 + MRR with the standard len(gold)>=1 filter."""
    h1 = h5 = n = 0
    mrr_sum = 0.0
    for p in predictions:
        gold = set(p.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        n += 1
        top = p.get("matched_issue_ids") or []
        for i, t in enumerate(top, 1):
            if t in gold:
                if i == 1:
                    h1 += 1
                if i <= 5:
                    h5 += 1
                mrr_sum += 1.0 / i
                break
    return {
        "n_with_gold": n,
        "hit_at_1": h1 / n if n else 0.0,
        "hit_at_5": h5 / n if n else 0.0,
        "mrr": mrr_sum / n if n else 0.0,
    }


# ---------------------------------------------------------------------------
# Uniform injection (parity with v2_advanced/tch/distractor_sweep.py)
# ---------------------------------------------------------------------------


def inject_uniform(
    cascade: Sequence[dict[str, Any]],
    n_distractors: int,
    n_memory: int,
    *,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Identity-agnostic distractor injection (Mode 1 baseline).

    Each top-K slot is replaced with a placeholder distractor at
    probability `p = n_distractors / (n_distractors + n_memory)`,
    independently and uniformly across windows."""
    if n_distractors == 0:
        return [dict(p) for p in cascade]
    rng = random.Random(seed)
    p = n_distractors / (n_distractors + n_memory)
    distractor_ids = [f"DISTRACTOR-{i:04d}" for i in range(n_distractors)]
    out = []
    for window_pred in cascade:
        new_top = list(window_pred.get("matched_issue_ids") or [])
        for i in range(len(new_top)):
            if rng.random() < p:
                new_top[i] = rng.choice(distractor_ids)
        out.append({**window_pred, "matched_issue_ids": new_top})
    return out


# ---------------------------------------------------------------------------
# Similarity-weighted injection
# ---------------------------------------------------------------------------


def compute_window_weights(
    sim_max_per_window: Sequence[float],
    *,
    weight_cap: float = WEIGHT_CAP,
) -> list[float]:
    """Convert per-window top-similarity into displacement-weight multipliers.

    `weight[w] = sim_max[w] / mean(sim_max)` clipped to [0, weight_cap].
    Mean of returned weights is approximately 1.0 (after clipping):
    expected displacement count under uniform p_baseline is preserved."""
    if not sim_max_per_window:
        return []
    mean_sim = sum(sim_max_per_window) / len(sim_max_per_window)
    if mean_sim <= 0.0:
        # Degenerate corpus — fall back to uniform.
        return [1.0] * len(sim_max_per_window)
    weights = [
        min(max(s / mean_sim, 0.0), weight_cap) for s in sim_max_per_window
    ]
    return weights


def inject_similarity_weighted(
    cascade: Sequence[dict[str, Any]],
    n_distractors: int,
    n_memory: int,
    *,
    window_weights: Sequence[float],
    seed: int = 42,
) -> tuple[list[dict[str, Any]], float]:
    """Per-window displacement scaled by `window_weights[i]`.

    Returns the injected cascade + the realized mean p_per_slot (a
    sanity check; it should be close to the uniform baseline)."""
    if n_distractors == 0:
        return [dict(p) for p in cascade], 0.0
    if len(window_weights) != len(cascade):
        raise ValueError(
            f"window_weights len ({len(window_weights)}) != cascade len "
            f"({len(cascade)})",
        )
    rng = random.Random(seed)
    p_baseline = n_distractors / (n_distractors + n_memory)
    distractor_ids = [f"DISTRACTOR-{i:04d}" for i in range(n_distractors)]
    out = []
    total_p = 0.0
    n_slots = 0
    for w_idx, window_pred in enumerate(cascade):
        p_w = min(max(p_baseline * window_weights[w_idx], 0.0), 1.0)
        new_top = list(window_pred.get("matched_issue_ids") or [])
        for i in range(len(new_top)):
            total_p += p_w
            n_slots += 1
            if rng.random() < p_w:
                new_top[i] = rng.choice(distractor_ids)
        out.append({**window_pred, "matched_issue_ids": new_top})
    mean_p = total_p / n_slots if n_slots else 0.0
    return out, mean_p


# ---------------------------------------------------------------------------
# TF-IDF similarity matrix
# ---------------------------------------------------------------------------


def compute_max_similarity_per_window(
    window_texts: Sequence[str],
    distractor_texts: Sequence[str],
    *,
    max_features: int = 8000,
    min_df: int = 2,
) -> tuple[list[float], dict[str, float]]:
    """For each window, return max cos(w, d) over all distractors.

    Uses sklearn's TfidfVectorizer fit on the combined corpus
    (windows + distractors) so vocab is shared.

    Returns (max_sim_per_window, summary_stats).
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError as e:
        raise ImportError(
            "scikit-learn required for similarity-weighted distractor "
            "sweep. pip install scikit-learn",
        ) from e

    if not window_texts:
        return [], {"n_windows": 0, "n_distractors": 0}
    if not distractor_texts:
        return [0.0] * len(window_texts), {
            "n_windows": len(window_texts),
            "n_distractors": 0,
            "warning": "no distractor texts — sim_max = 0 for all windows",
        }

    corpus = list(window_texts) + list(distractor_texts)
    vec = TfidfVectorizer(
        max_features=max_features, min_df=min_df,
        lowercase=True, ngram_range=(1, 1),
    )
    X = vec.fit_transform(corpus)
    n_w = len(window_texts)
    W = X[:n_w]                                  # window vectors
    D = X[n_w:]                                  # distractor vectors

    # Cosine sim: TfidfVectorizer rows are L2-normalized, so dot product
    # is already cosine.
    sim = W @ D.T                                # shape (n_w, n_d)
    sim_dense = sim.toarray() if hasattr(sim, "toarray") else sim

    # Per-window max
    max_per_window = sim_dense.max(axis=1).tolist()
    summary = {
        "n_windows": n_w,
        "n_distractors": len(distractor_texts),
        "sim_max_mean": float(sum(max_per_window) / n_w),
        "sim_max_min": float(min(max_per_window)),
        "sim_max_max": float(max(max_per_window)),
    }
    return max_per_window, summary


# ---------------------------------------------------------------------------
# Sweep drivers
# ---------------------------------------------------------------------------


def run_uniform_sweep(
    cascade: Sequence[dict[str, Any]],
    *,
    distractor_pool_size: int,
    memory_size: int,
    ratios_pct: Iterable[int] = (0, 10, 25, 50),
    seed: int = 42,
) -> DistractorSweepReport:
    results = []
    for r in ratios_pct:
        n_d = int(distractor_pool_size * r / 100)
        injected = inject_uniform(cascade, n_d, memory_size, seed=seed + r)
        m = _compute_metrics(injected)
        p_baseline = (n_d / (n_d + memory_size)) if n_d else 0.0
        results.append(_RatioResult(
            ratio_pct=r, n_distractors=n_d,
            p_per_slot_baseline=p_baseline,
            mean_p_per_slot_realized=p_baseline,
            hit_at_1=m["hit_at_1"], hit_at_5=m["hit_at_5"], mrr=m["mrr"],
            n_with_gold=m["n_with_gold"],
        ))
    return DistractorSweepReport(
        method="uniform",
        n_windows=len(cascade),
        n_distractors_pool=distractor_pool_size,
        n_memory=memory_size,
        seed=seed,
        ratios=tuple(results),
    )


def run_similarity_weighted_sweep(
    cascade: Sequence[dict[str, Any]],
    window_weights: Sequence[float],
    *,
    distractor_pool_size: int,
    memory_size: int,
    ratios_pct: Iterable[int] = (0, 10, 25, 50),
    seed: int = 42,
    sim_summary: dict[str, float] | None = None,
) -> DistractorSweepReport:
    results = []
    for r in ratios_pct:
        n_d = int(distractor_pool_size * r / 100)
        if n_d == 0:
            # Zero-distractor baseline: no displacement, no realized p.
            m = _compute_metrics(list(cascade))
            results.append(_RatioResult(
                ratio_pct=r, n_distractors=0,
                p_per_slot_baseline=0.0, mean_p_per_slot_realized=0.0,
                hit_at_1=m["hit_at_1"], hit_at_5=m["hit_at_5"], mrr=m["mrr"],
                n_with_gold=m["n_with_gold"],
            ))
            continue
        injected, mean_p = inject_similarity_weighted(
            cascade, n_d, memory_size,
            window_weights=window_weights, seed=seed + r,
        )
        m = _compute_metrics(injected)
        p_baseline = n_d / (n_d + memory_size)
        results.append(_RatioResult(
            ratio_pct=r, n_distractors=n_d,
            p_per_slot_baseline=p_baseline,
            mean_p_per_slot_realized=mean_p,
            hit_at_1=m["hit_at_1"], hit_at_5=m["hit_at_5"], mrr=m["mrr"],
            n_with_gold=m["n_with_gold"],
        ))
    return DistractorSweepReport(
        method="similarity_weighted",
        n_windows=len(cascade),
        n_distractors_pool=distractor_pool_size,
        n_memory=memory_size,
        seed=seed,
        ratios=tuple(results),
        sim_summary=sim_summary or {},
    )


# ---------------------------------------------------------------------------
# JSONL loaders (window text + distractor text + cascade predictions)
# ---------------------------------------------------------------------------


def load_window_texts_for_cascade(
    cascade: Sequence[dict[str, Any]],
    triage_examples_path: Path | str,
) -> list[str]:
    """For each cascade prediction (in order), return the matching
    window's `triage_evidence_text`. Falls back to "" when missing."""
    by_id: dict[str, str] = {}
    for row in _iter_jsonl(Path(triage_examples_path)):
        wid = row.get("window_id")
        if wid:
            by_id[wid] = str(row.get("triage_evidence_text") or "")
    out = []
    n_missing = 0
    for p in cascade:
        wid = p.get("window_id")
        text = by_id.get(wid, "")
        if not text:
            n_missing += 1
        out.append(text)
    if n_missing:
        log.warning(
            "load_window_texts_for_cascade: %d/%d windows missing "
            "triage_evidence_text",
            n_missing, len(cascade),
        )
    return out


def load_distractor_texts(
    distractors_jsonl_path: Path | str,
    *,
    limit: int | None = None,
) -> list[str]:
    """Read distractor descriptions from `distractors/timeline.jsonl`.

    Each row's `description_code` field is the primary distractor text;
    the row's `timeline` list may also have `body_code` per step. We
    concatenate description_code + the first timeline step's body_code
    when present, giving the simulation the same lexical surface as a
    real retrieval would see."""
    out = []
    for row in _iter_jsonl(Path(distractors_jsonl_path)):
        desc = str(row.get("description_code") or "")
        tl = row.get("timeline") or []
        if tl and isinstance(tl, list):
            first = tl[0] if isinstance(tl[0], dict) else {}
            body = first.get("body_code") or first.get("body") or ""
            text = f"{desc}\n{body}" if body else desc
        else:
            text = desc
        if text:
            out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping malformed line in %s", path)
                continue
