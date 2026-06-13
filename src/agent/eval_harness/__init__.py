"""eval_harness — apples-to-apples agent evaluation.

The harness composes Controller + Runner + (optional) StateLayer over a
stream of `EvaluationCase`s, then aggregates per-case results into a
single `EvaluationReport`. The §12 apples-to-apples contract is
declared upfront and enforced at runtime:

  - Same dataset + split (contract.dataset_id, contract.split)
  - Same gold relation (contract.gold_relation)
  - Same memory pool (contract.memory_pool_size)
  - Same metric formula (contract.metric_formula)
  - Same statistical envelope (contract.statistical_envelope)
  - Mode-pure: every decision's `evaluation_mode` must match
    `contract.evaluation_mode` — mixed modes raise
    `EvaluationModeMismatch`.

Public API:
  - `EvaluationCase` — one bundle + memory + gold labels.
  - `CaseResult` — per-case computed metrics + agent's decision.
  - `ApplesToApplesContract` — frozen evaluation declaration.
  - `EvaluationReport` — aggregated metrics + provenance.
  - `EvalHarness` — orchestrator.
  - `EvaluationModeMismatch`, `ApplesToApplesViolation` — refusal exceptions.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §12, §14.
"""

from .exceptions import ApplesToApplesViolation, EvaluationModeMismatch
from .harness import EvalHarness
from .metrics import (
    hit_at_k,
    mean_hit_at_k,
    mean_reciprocal_rank,
    pages_per_incident,
    reciprocal_rank,
)
from .types import (
    ApplesToApplesContract,
    CaseResult,
    EvaluationCase,
    EvaluationReport,
)

__all__ = [
    # types
    "EvaluationCase",
    "CaseResult",
    "ApplesToApplesContract",
    "EvaluationReport",
    # harness
    "EvalHarness",
    # metrics
    "hit_at_k",
    "mean_hit_at_k",
    "reciprocal_rank",
    "mean_reciprocal_rank",
    "pages_per_incident",
    # exceptions
    "EvaluationModeMismatch",
    "ApplesToApplesViolation",
]
