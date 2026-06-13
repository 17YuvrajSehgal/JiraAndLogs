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

from .ablation import (
    AblationConfig,
    AblationGridResult,
    AblationHarness,
    AblationSpec,
)
from .distractor_sweep import (
    DistractorSweepReport,
    compute_max_similarity_per_window,
    compute_window_weights,
    inject_similarity_weighted,
    inject_uniform,
    load_distractor_texts,
    load_window_texts_for_cascade,
    run_similarity_weighted_sweep,
    run_uniform_sweep,
)
from .exceptions import ApplesToApplesViolation, EvaluationModeMismatch
from .harness import EvalHarness
from .metrics import (
    hit_at_k,
    mean_hit_at_k,
    mean_reciprocal_rank,
    pages_per_incident,
    reciprocal_rank,
)
from .novelty import (
    DEFAULT_FREE_THRESHOLD,
    DEFAULT_LEARNED_THRESHOLD,
    NoveltyQuery,
    NoveltyReport,
    evaluate_l3_novelty,
    load_agent_signal,
    load_free_signal,
    load_learned_signal,
    load_wol_ood_queries,
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
    # ablation
    "AblationSpec",
    "AblationConfig",
    "AblationGridResult",
    "AblationHarness",
    # metrics
    "hit_at_k",
    "mean_hit_at_k",
    "reciprocal_rank",
    "mean_reciprocal_rank",
    "pages_per_incident",
    # distractor sweep (Phase 3.4 — RQ-A4)
    "DistractorSweepReport",
    "run_uniform_sweep",
    "run_similarity_weighted_sweep",
    "inject_uniform",
    "inject_similarity_weighted",
    "compute_window_weights",
    "compute_max_similarity_per_window",
    "load_window_texts_for_cascade",
    "load_distractor_texts",
    # novelty (Phase 3.3 — RQ-A5)
    "NoveltyQuery",
    "NoveltyReport",
    "evaluate_l3_novelty",
    "load_wol_ood_queries",
    "load_free_signal",
    "load_agent_signal",
    "load_learned_signal",
    "DEFAULT_FREE_THRESHOLD",
    "DEFAULT_LEARNED_THRESHOLD",
    # exceptions
    "EvaluationModeMismatch",
    "ApplesToApplesViolation",
]
