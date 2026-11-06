"""The incident pool as a LangGraph Store, with the temporal firewall.

LangGraph's store namespaces memory by *who* ("user_id", "memories").
Incident memory has to namespace by *when*: at triage time the only
admissible incidents are the ones already resolved, and nothing resolved
later may influence the answer. A store that cannot express that is not
usable here, so the firewall lives inside `search` rather than in the
caller, where it can be forgotten.

Two things this buys over the hand-rolled version:

  * memory becomes an INTERFACE. BM25 is one implementation; a dense one
    can be dropped in and compared without touching the agent. That
    comparison is currently untested and is the weakest part of the
    memory story.
  * the firewall is enforced at the only door, so a future caller cannot
    bypass it by querying the pool directly.

What it deliberately keeps: the per-instance index build. Ranking the
whole pool and filtering afterwards computes idf, df and average
document length over tickets that did not exist yet, and leaves
inadmissible incidents occupying slots in the ranked list. Measured on
500 instances: half the ranked pool inadmissible, and the returned top-5
differed on 27.6%.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from localize import BM25Index, tokenize  # noqa: E402

MEM_HALFLIFE_DAYS = 365.0


@dataclass(frozen=True)
class Incident:
    """One resolved ticket, and the files its fix touched."""
    key: str
    resolved: float
    fix_shas: frozenset
    gold_files: tuple
    toks: Any          # Counter, pre-tokenised at load


@dataclass(frozen=True)
class Recall:
    """A scored match, with the reasoning visible to the model."""
    incident: str
    fixed_files: tuple
    n_files_in_that_fix: int
    weight: float
    resolved_days_before: int

    def as_dict(self) -> dict:
        return {"incident": self.incident,
                "fixed_files": list(self.fixed_files),
                "n_files_in_that_fix": self.n_files_in_that_fix,
                "weight": round(self.weight, 4),
                "resolved_days_before_this_report": self.resolved_days_before}


class IncidentStore:
    """Read-only, time-filtered incident memory for one project.

    Mirrors LangGraph's store shape -- namespaced `search` returning
    scored items -- while adding the admissibility rules the domain
    needs. Not a BaseStore subclass: BaseStore's put/delete would imply
    a write path, and a triage run must never mutate history.
    """

    def __init__(self, project: str, incidents: dict[str, Incident]):
        self.project = project
        self._incidents = incidents

    # ---- the firewall, in one place ---------------------------------------
    def admissible(self, inc: Incident, *, cutoff: float, this_key: str,
                   this_fix_shas: frozenset, dup_cluster: Any,
                   dup_of: dict) -> bool:
        """Four rules. Each one has cost us a measurable amount of leakage
        at some point, so each is stated rather than bundled."""
        if inc.key == this_key:
            return False                                   # itself
        if dup_cluster is not None and dup_of.get(inc.key) == dup_cluster:
            return False                                   # a duplicate of it
        if inc.fix_shas & this_fix_shas:
            return False                                   # shares a fix
        if inc.resolved is not None and inc.resolved > cutoff:
            return False                                   # from the future
        return True

    def namespace(self, cutoff: float) -> tuple:
        """LangGraph namespaces by user; we namespace by time. Two queries
        with different cutoffs are genuinely different memories."""
        return (self.project, "incidents", f"before:{int(cutoff)}")

    def search(self, query: str, *, cutoff: float, this_key: str,
               this_fix_shas: Iterable = (), dup_cluster: Any = None,
               dup_of: dict | None = None, in_snapshot=None,
               limit: int = 5) -> list[Recall]:
        """Rank admissible incidents against a query.

        The index is built from the admissible set, NOT filtered after
        ranking -- see the module docstring for why that distinction is
        worth 27.6% of returned results.
        """
        dup_of = dup_of or {}
        shas = frozenset(this_fix_shas)
        adm = {k: inc for k, inc in self._incidents.items()
               if self.admissible(inc, cutoff=cutoff, this_key=this_key,
                                  this_fix_shas=shas, dup_cluster=dup_cluster,
                                  dup_of=dup_of)}
        if not adm:
            return []
        index = BM25Index({k: inc.toks for k, inc in adm.items()})
        qtoks = tokenize(query or "")
        if not qtoks:
            return []
        out: list[Recall] = []
        for rank, key in enumerate(index.rank(qtoks, limit * 10), start=1):
            inc = adm[key]
            files = tuple(f for f in inc.gold_files
                          if in_snapshot is None or f in in_snapshot)
            if not files:
                continue
            n_fix = max(1, len(inc.gold_files))
            age_days = max(0.0, cutoff - (inc.resolved or cutoff)) / 86400.0
            recency = math.exp(-age_days / MEM_HALFLIFE_DAYS)
            out.append(Recall(
                incident=key, fixed_files=files[:6], n_files_in_that_fix=n_fix,
                # similarity x recency / fix size: a 40-file refactor must
                # not outvote a one-file fix
                weight=(1.0 / rank) * recency / n_fix,
                resolved_days_before=int(age_days)))
            if len(out) >= limit:
                break
        out.sort(key=lambda r: -r.weight)
        return out

    @classmethod
    def from_pool(cls, project: str, pool: dict) -> "IncidentStore":
        """Build from the dict load_support already produces, so the two
        implementations read exactly the same data and can be compared."""
        return cls(project, {
            k: Incident(key=k, resolved=r["resolved"],
                        fix_shas=frozenset(r["fix_shas"]),
                        gold_files=tuple(r["gold_files"]), toks=r["toks"])
            for k, r in pool.items()})
