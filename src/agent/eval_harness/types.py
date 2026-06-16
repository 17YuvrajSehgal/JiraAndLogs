"""eval_harness types — EvaluationCase, ApplesToApplesContract,
CaseResult, EvaluationReport.

Frozen dataclasses with explicit `to_dict()` / `from_dict()` so the
harness's outputs serialize cleanly to JSON. The report is the
artifact a paper-table row is read from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..skills.base import MemoryView
from ..types import AgentDecision, EvaluationMode, InputBundle, SkillCallCost, TriageDecision


GoldRelation = Literal["coarse", "strong"]


# ---------------------------------------------------------------------------
# EvaluationCase — one input to the harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationCase:
    """One bundle + memory + gold labels.

    Dataset loaders produce these; the harness consumes them. Gold
    fields use sane defaults so a partial labelled case (e.g. only
    retrieval gold, no triage gold) still works."""

    bundle: InputBundle
    memory: MemoryView
    gold_matched_issue_ids: tuple[str, ...] = ()
    gold_triage: TriageDecision = "ticket_worthy"
    gold_is_novel: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def bundle_id(self) -> str:
        return self.bundle.window_id


# ---------------------------------------------------------------------------
# CaseResult — per-case outputs (input to aggregation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    """The agent's decision + per-case computed metrics.

    Persisted in `EvaluationReport.case_results` so post-hoc analysis
    can re-aggregate without re-running the agent."""

    bundle_id: str
    decision: AgentDecision

    # Retrieval metrics (None when len(gold) == 0 — excluded from means)
    hit_at_1: bool | None = None
    hit_at_5: bool | None = None
    hit_at_10: bool | None = None
    rank_of_first_hit: int | None = None
    reciprocal_rank: float | None = None

    # Triage metrics
    triage_correct: bool = False
    is_novel_correct: bool = False

    gold_matched_issue_ids: tuple[str, ...] = ()
    gold_triage: TriageDecision = "ticket_worthy"
    gold_is_novel: bool = False

    # Suppression provenance
    suppression_fired: bool = False
    suppression_incident_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "decision": self.decision.to_dict(),
            "hit_at_1": self.hit_at_1,
            "hit_at_5": self.hit_at_5,
            "hit_at_10": self.hit_at_10,
            "rank_of_first_hit": self.rank_of_first_hit,
            "reciprocal_rank": self.reciprocal_rank,
            "triage_correct": self.triage_correct,
            "is_novel_correct": self.is_novel_correct,
            "gold_matched_issue_ids": list(self.gold_matched_issue_ids),
            "gold_triage": self.gold_triage,
            "gold_is_novel": self.gold_is_novel,
            "suppression_fired": self.suppression_fired,
            "suppression_incident_id": self.suppression_incident_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CaseResult":
        return cls(
            bundle_id=str(d["bundle_id"]),
            decision=AgentDecision.from_dict(d["decision"]),
            hit_at_1=d.get("hit_at_1"),
            hit_at_5=d.get("hit_at_5"),
            hit_at_10=d.get("hit_at_10"),
            rank_of_first_hit=d.get("rank_of_first_hit"),
            reciprocal_rank=d.get("reciprocal_rank"),
            triage_correct=bool(d.get("triage_correct", False)),
            is_novel_correct=bool(d.get("is_novel_correct", False)),
            gold_matched_issue_ids=tuple(d.get("gold_matched_issue_ids") or ()),
            gold_triage=d.get("gold_triage", "ticket_worthy"),
            gold_is_novel=bool(d.get("gold_is_novel", False)),
            suppression_fired=bool(d.get("suppression_fired", False)),
            suppression_incident_id=d.get("suppression_incident_id"),
        )


# ---------------------------------------------------------------------------
# ApplesToApplesContract — the §12 declaration enforced by the harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplesToApplesContract:
    """The six apples-to-apples rules, declared as data.

    The harness embeds this in the report; rendering layers refuse to
    draw a row whose contract disagrees with another row's contract
    (e.g. cross-dataset rows need explicit annotation).
    """

    dataset_id: str
    split: str = "test"
    gold_relation: GoldRelation = "coarse"
    memory_pool_size: int = 0
    metric_formula: str = "Hit@K with len(gold)>=1 filter"
    statistical_envelope: str = "1000 paired bootstrap, seed=42"
    evaluation_mode: EvaluationMode = "telemetry_diagnosis"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "split": self.split,
            "gold_relation": self.gold_relation,
            "memory_pool_size": self.memory_pool_size,
            "metric_formula": self.metric_formula,
            "statistical_envelope": self.statistical_envelope,
            "evaluation_mode": self.evaluation_mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ApplesToApplesContract":
        return cls(
            dataset_id=str(d.get("dataset_id", "")),
            split=str(d.get("split", "test")),
            gold_relation=d.get("gold_relation", "coarse"),
            memory_pool_size=int(d.get("memory_pool_size", 0)),
            metric_formula=str(d.get("metric_formula", "Hit@K with len(gold)>=1 filter")),
            statistical_envelope=str(
                d.get("statistical_envelope", "1000 paired bootstrap, seed=42")
            ),
            evaluation_mode=d.get("evaluation_mode", "telemetry_diagnosis"),
        )


# ---------------------------------------------------------------------------
# EvaluationReport — the harness's final output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregated metrics + provenance.

    Headline scalars are exactly what a paper table row consumes.
    Per-case detail in `case_results` enables drill-down analysis."""

    name: str
    n_cases: int
    n_evaluable_retrieval_cases: int                # cases with len(gold) >= 1
    contract: ApplesToApplesContract

    # Headline retrieval
    hit_at_1: float
    hit_at_5: float
    hit_at_10: float
    mrr: float

    # Triage + novelty
    triage_accuracy: float = 0.0
    novel_recall: float = 0.0
    novel_precision: float = 0.0

    # Operations / state
    n_pages_emitted: int = 0
    n_incidents: int = 0
    pages_per_incident: float = 0.0
    n_suppressions_fired: int = 0

    # Cost
    total_cost: SkillCallCost = field(default_factory=SkillCallCost.zero)
    cache_hit_rate: float = 0.0

    # Provenance
    experiment_name: str = ""
    ablation: str = ""
    plan_ids_seen: tuple[str, ...] = ()

    # Per-case detail — optional; large reports may drop this when
    # writing to disk.
    case_results: tuple[CaseResult, ...] = ()

    # ------------------------------------------------------------------ serialize

    def to_dict(self, *, include_case_results: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "n_cases": self.n_cases,
            "n_evaluable_retrieval_cases": self.n_evaluable_retrieval_cases,
            "contract": self.contract.to_dict(),
            "hit_at_1": self.hit_at_1,
            "hit_at_5": self.hit_at_5,
            "hit_at_10": self.hit_at_10,
            "mrr": self.mrr,
            "triage_accuracy": self.triage_accuracy,
            "novel_recall": self.novel_recall,
            "novel_precision": self.novel_precision,
            "n_pages_emitted": self.n_pages_emitted,
            "n_incidents": self.n_incidents,
            "pages_per_incident": self.pages_per_incident,
            "n_suppressions_fired": self.n_suppressions_fired,
            "total_cost": self.total_cost.to_dict(),
            "cache_hit_rate": self.cache_hit_rate,
            "experiment_name": self.experiment_name,
            "ablation": self.ablation,
            "plan_ids_seen": list(self.plan_ids_seen),
        }
        if include_case_results:
            d["case_results"] = [c.to_dict() for c in self.case_results]
        return d

    def write_to(
        self,
        path: Path | str,
        *,
        include_case_results: bool = True,
        indent: int | None = 2,
    ) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                self.to_dict(include_case_results=include_case_results),
                indent=indent,
                default=str,
            ),
            encoding="utf-8",
        )
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvaluationReport":
        return cls(
            name=str(d["name"]),
            n_cases=int(d.get("n_cases", 0)),
            n_evaluable_retrieval_cases=int(d.get("n_evaluable_retrieval_cases", 0)),
            contract=ApplesToApplesContract.from_dict(d.get("contract") or {}),
            hit_at_1=float(d.get("hit_at_1", 0.0)),
            hit_at_5=float(d.get("hit_at_5", 0.0)),
            hit_at_10=float(d.get("hit_at_10", 0.0)),
            mrr=float(d.get("mrr", 0.0)),
            triage_accuracy=float(d.get("triage_accuracy", 0.0)),
            novel_recall=float(d.get("novel_recall", 0.0)),
            novel_precision=float(d.get("novel_precision", 0.0)),
            n_pages_emitted=int(d.get("n_pages_emitted", 0)),
            n_incidents=int(d.get("n_incidents", 0)),
            pages_per_incident=float(d.get("pages_per_incident", 0.0)),
            n_suppressions_fired=int(d.get("n_suppressions_fired", 0)),
            total_cost=SkillCallCost.from_dict(d.get("total_cost") or {}),
            cache_hit_rate=float(d.get("cache_hit_rate", 0.0)),
            experiment_name=str(d.get("experiment_name", "")),
            ablation=str(d.get("ablation", "")),
            plan_ids_seen=tuple(d.get("plan_ids_seen") or ()),
            case_results=tuple(
                CaseResult.from_dict(c) for c in (d.get("case_results") or ())
            ),
        )

    def __repr__(self) -> str:
        return (
            f"EvaluationReport({self.name!r}, n={self.n_cases}, "
            f"Hit@1={self.hit_at_1:.3f}, Hit@5={self.hit_at_5:.3f}, "
            f"MRR={self.mrr:.3f}, P/I={self.pages_per_incident:.2f})"
        )
