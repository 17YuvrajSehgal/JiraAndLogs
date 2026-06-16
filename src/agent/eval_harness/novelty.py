"""Phase 3.3 — Full-L3 novelty evaluator.

Closes RQ-A5. Mode 2 published the **lower bound** (free signal alone:
800/800 = 100% precision on the OOD set). Phase 3.3 runs the full L3
disjunction the cascade defines:

    is_novel = agent_novel ∨ free_signal ∨ learned_novel

and reports:
  - which signal(s) fired per query
  - novel_precision + novel_recall (against the queries' gold_is_novel)
  - per-project stratification
  - signal-incremental contribution (free → free+agent → free+agent+learned)

Pure data module — no skill execution. Three signal sources can be
plugged in independently:
  - free: a JSONL with `window_id, max_sim, is_novel_at_T` per row
  - agent: a JSONL with `window_id, is_novel` per row (from a
    verifier run; absent for WoL by RQ-A8 design)
  - learned: a JSONL with `window_id, learned_novelty_prob` per row
    (from a fitted classifier; absent in v1)

Returns a `NoveltyReport` with the per-signal counts + final metrics,
serializable to JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


log = logging.getLogger(__name__)


#: L3 free-signal threshold (matches `compose_novelty.L3_FREE_NOVELTY_THRESHOLD`).
DEFAULT_FREE_THRESHOLD = 0.5

#: L3 learned-classifier threshold.
DEFAULT_LEARNED_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Input rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoveltyQuery:
    """One labelled query in a novelty set."""
    window_id: str
    gold_is_novel: bool
    project: str = ""          # WoL: source project; other datasets: dataset name
    family: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "NoveltyQuery":
        return cls(
            window_id=str(row["window_id"]),
            gold_is_novel=bool(row.get("is_novel", False)),
            project=str(row.get("wol_project") or row.get("project") or ""),
            family=str(row.get("scenario_family") or ""),
        )


@dataclass(frozen=True)
class _SignalSet:
    """Aggregated per-window signal flags from the three sources."""
    free_novel: bool = False
    agent_novel: bool = False
    learned_novel: bool = False

    def any(self) -> bool:
        return self.free_novel or self.agent_novel or self.learned_novel

    def n_signals(self) -> int:
        return int(self.free_novel) + int(self.agent_novel) + int(self.learned_novel)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SignalTally:
    n_flagged: int = 0
    n_true_positive: int = 0
    n_false_positive: int = 0

    def precision(self, n_flagged_override: int | None = None) -> float:
        n = n_flagged_override if n_flagged_override is not None else self.n_flagged
        if n == 0:
            return 0.0
        return self.n_true_positive / n


@dataclass(frozen=True)
class NoveltyReport:
    """Full L3 disjunction report — RQ-A5 paper-ready."""

    n_queries: int
    n_gold_novel: int

    # Per-signal counts (independent — each is "flagged by THIS signal")
    free_flagged: int = 0
    agent_flagged: int = 0
    learned_flagged: int = 0

    # Cumulative disjunction (free → free|agent → free|agent|learned)
    flagged_free_only: int = 0
    flagged_free_or_agent: int = 0
    flagged_full_l3: int = 0

    # Final disjunction (full L3) metrics
    novel_precision: float = 0.0
    novel_recall: float = 0.0
    n_true_positive_l3: int = 0
    n_false_positive_l3: int = 0

    # Per-project breakdown
    per_project: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Provenance
    free_threshold: float = DEFAULT_FREE_THRESHOLD
    learned_threshold: float = DEFAULT_LEARNED_THRESHOLD
    agent_signal_present: bool = False
    learned_signal_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_queries": self.n_queries,
            "n_gold_novel": self.n_gold_novel,
            "free_flagged": self.free_flagged,
            "agent_flagged": self.agent_flagged,
            "learned_flagged": self.learned_flagged,
            "flagged_free_only": self.flagged_free_only,
            "flagged_free_or_agent": self.flagged_free_or_agent,
            "flagged_full_l3": self.flagged_full_l3,
            "novel_precision": self.novel_precision,
            "novel_recall": self.novel_recall,
            "n_true_positive_l3": self.n_true_positive_l3,
            "n_false_positive_l3": self.n_false_positive_l3,
            "per_project": dict(self.per_project),
            "free_threshold": self.free_threshold,
            "learned_threshold": self.learned_threshold,
            "agent_signal_present": self.agent_signal_present,
            "learned_signal_present": self.learned_signal_present,
        }


# ---------------------------------------------------------------------------
# Signal loaders
# ---------------------------------------------------------------------------


def load_free_signal(
    path: Path | str,
    *,
    threshold: float = DEFAULT_FREE_THRESHOLD,
) -> dict[str, bool]:
    """Load free-signal flags from `mode2_per_query.jsonl`-style rows.

    A row's `is_novel_at_T` flag wins when present; otherwise we
    re-evaluate against `max_sim < threshold`. Returns
    window_id → free_novel."""
    out: dict[str, bool] = {}
    for row in _iter_jsonl(Path(path)):
        wid = row.get("window_id")
        if not wid:
            continue
        # Prefer the precomputed flag if its threshold matches.
        if f"is_novel_at_{threshold}" in row:
            out[wid] = bool(row[f"is_novel_at_{threshold}"])
        else:
            sim = row.get("max_sim")
            if sim is None:
                # No similarity → can't decide → assume novel (conservative)
                out[wid] = True
            else:
                out[wid] = float(sim) < threshold
    return out


def load_agent_signal(path: Path | str) -> dict[str, bool]:
    """Load agent-novelty flags from a verifier predictions JSONL.

    Reads `is_novel` per row. Returns window_id → bool. Missing file →
    empty dict (caller surfaces `agent_signal_present=False`)."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, bool] = {}
    for row in _iter_jsonl(p):
        wid = row.get("window_id")
        if not wid:
            continue
        flag = row.get("is_novel")
        if flag is None:
            continue
        out[wid] = bool(flag)
    return out


def load_learned_signal(
    path: Path | str,
    *,
    threshold: float = DEFAULT_LEARNED_THRESHOLD,
) -> dict[str, bool]:
    """Load learned-classifier flags (prob → flag at threshold).

    Reads `learned_novelty_prob` per row. Missing file → empty dict."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, bool] = {}
    for row in _iter_jsonl(p):
        wid = row.get("window_id")
        if not wid:
            continue
        prob = row.get("learned_novelty_prob")
        if prob is None:
            continue
        out[wid] = float(prob) >= threshold
    return out


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate_l3_novelty(
    *,
    queries: Iterable[NoveltyQuery],
    free_signal: dict[str, bool],
    agent_signal: dict[str, bool] | None = None,
    learned_signal: dict[str, bool] | None = None,
    free_threshold: float = DEFAULT_FREE_THRESHOLD,
    learned_threshold: float = DEFAULT_LEARNED_THRESHOLD,
) -> NoveltyReport:
    """Run the L3 disjunction over `queries`, return a NoveltyReport.

    Each query is novel iff ANY of (free, agent, learned) signals flag
    it. Missing signal maps default to all-False (the cumulative
    disjunction columns then track what *would* fire if a signal were
    present).
    """
    agent_signal = agent_signal or {}
    learned_signal = learned_signal or {}

    queries = list(queries)
    n_queries = len(queries)
    n_gold_novel = sum(1 for q in queries if q.gold_is_novel)

    # Per-signal independent counts
    free_flagged = 0
    agent_flagged = 0
    learned_flagged = 0

    # Cumulative disjunction
    flagged_free_only = 0
    flagged_free_or_agent = 0
    flagged_full_l3 = 0

    # L3 TP/FP for precision + recall
    n_tp = 0
    n_fp = 0

    # Per-project tallies
    per_proj: dict[str, dict[str, int]] = {}

    for q in queries:
        f = bool(free_signal.get(q.window_id, False))
        a = bool(agent_signal.get(q.window_id, False))
        l = bool(learned_signal.get(q.window_id, False))

        if f:
            free_flagged += 1
            flagged_free_only += 1
        if a:
            agent_flagged += 1
        if l:
            learned_flagged += 1
        if f or a:
            flagged_free_or_agent += 1

        l3_novel = f or a or l
        if l3_novel:
            flagged_full_l3 += 1
            if q.gold_is_novel:
                n_tp += 1
            else:
                n_fp += 1

        # Per-project bucket
        proj = q.project or "_unknown"
        bucket = per_proj.setdefault(proj, {
            "n_queries": 0, "n_gold_novel": 0,
            "free_flagged": 0, "agent_flagged": 0, "learned_flagged": 0,
            "flagged_full_l3": 0, "n_tp": 0,
        })
        bucket["n_queries"] += 1
        bucket["n_gold_novel"] += int(q.gold_is_novel)
        bucket["free_flagged"] += int(f)
        bucket["agent_flagged"] += int(a)
        bucket["learned_flagged"] += int(l)
        bucket["flagged_full_l3"] += int(l3_novel)
        if l3_novel and q.gold_is_novel:
            bucket["n_tp"] += 1

    # Headline metrics on the full L3 disjunction
    precision = n_tp / flagged_full_l3 if flagged_full_l3 else 0.0
    recall = n_tp / n_gold_novel if n_gold_novel else 0.0

    # Add per-project precision/recall
    per_project_out: dict[str, dict[str, Any]] = {}
    for proj, b in per_proj.items():
        n_flag = b["flagged_full_l3"]
        n_gold = b["n_gold_novel"]
        p = b["n_tp"] / n_flag if n_flag else 0.0
        r = b["n_tp"] / n_gold if n_gold else 0.0
        per_project_out[proj] = {
            **b,
            "precision": p,
            "recall": r,
        }

    return NoveltyReport(
        n_queries=n_queries,
        n_gold_novel=n_gold_novel,
        free_flagged=free_flagged,
        agent_flagged=agent_flagged,
        learned_flagged=learned_flagged,
        flagged_free_only=flagged_free_only,
        flagged_free_or_agent=flagged_free_or_agent,
        flagged_full_l3=flagged_full_l3,
        novel_precision=precision,
        novel_recall=recall,
        n_true_positive_l3=n_tp,
        n_false_positive_l3=n_fp,
        per_project=per_project_out,
        free_threshold=free_threshold,
        learned_threshold=learned_threshold,
        agent_signal_present=bool(agent_signal),
        learned_signal_present=bool(learned_signal),
    )


# ---------------------------------------------------------------------------
# Query loaders
# ---------------------------------------------------------------------------


def load_wol_ood_queries(
    queries_jsonl: Path | str,
) -> list[NoveltyQuery]:
    """Load the 800 WoL OOD novelty queries from
    `novelty-queries/windows.jsonl`."""
    out: list[NoveltyQuery] = []
    for row in _iter_jsonl(Path(queries_jsonl)):
        try:
            out.append(NoveltyQuery.from_row(row))
        except KeyError:
            continue
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
