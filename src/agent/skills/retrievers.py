"""Concrete retrieval skill wrappers (predictions-backed).

Each class wraps one cascade pipeline. The required_flags + cost_class
match the AGENTIC-SYSTEM.md §5.1 table. Versions are pinned to the
cascade phase that produced the underlying predictions; bumping a
version invalidates the SkillCache (Phase 1.6) for that skill only.

These skills don't drive their underlying models — they consume the
pre-computed `per-window-predictions.jsonl` files. To re-run a model
(new dataset, new prompt), invoke the existing v2_advanced driver
scripts; their output is what these skills load.
"""

from __future__ import annotations

from ..capabilities import (
    KG_GRAPH_MEMORY,
    KG_GRAPH_WINDOW,
    MEMORY_TEXT,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    TEXT_EVIDENCE,
    VERIFIER_KNOWN_HELPFUL,
)
from .base import FailureMode
from .predictions_backed import PredictionsBackedSkill


# ---------------------------------------------------------------------------
# triage_numeric — HGB on the 94 numeric features.
# ---------------------------------------------------------------------------


class TriageNumericSkill(PredictionsBackedSkill):
    """Wraps HGB (`hist_gradient_boosting_numeric`).

    Strict triage PR-AUC = 0.9998 on the OB locked dataset — the
    cascade's dominant triage signal. Not invokable on WoL because
    WoL bundles have no numeric_features.
    """

    name = "triage_numeric"
    version = "1.0.0"
    required_flags = frozenset({NUMERIC_FEATURES})
    cost_class = "cheap"

    predictions_pipeline_name = "hist_gradient_boosting_numeric"
    predictions_subdir = "v2a-resplit"          # cascade convention


# ---------------------------------------------------------------------------
# retrieve_dense — BiEncoder.
# ---------------------------------------------------------------------------


class RetrieveDenseSkill(PredictionsBackedSkill):
    """Wraps the G1 BiEncoder (`bi_encoder_retrieval`).

    Strongest single-retriever Hit@5 on real Apache Jira (0.959 coarse
    on WoL Mode 3); the position-1 anchor for L2 overlap rerank. Always
    available — requires only TEXT_EVIDENCE + MEMORY_TEXT.
    """

    name = "retrieve_dense"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE, MEMORY_TEXT})
    cost_class = "cheap"

    predictions_pipeline_name = "bi_encoder_retrieval"
    predictions_subdir = "v2a-resplit"


# ---------------------------------------------------------------------------
# retrieve_log_sequence — LogSeq2Vec.
# ---------------------------------------------------------------------------


class RetrieveLogSequenceSkill(PredictionsBackedSkill):
    """Wraps LogSeq2Vec (`logseq2vec_retrieval_pretrained`).

    Designed for time-ordered Loki-style log streams. **Drops sharply
    on WoL** (Mode 3 §3.5: Hit@5 coarse 0.310 vs BiEncoder 0.959) — WoL
    `log_quotes` are unordered fragments, removing the sequence signal
    LogSeq2Vec relies on. The controller may down-weight or skip when
    ORDERED_LOGS richness shows few lines (configurable via
    agent-config.yaml > skills.retrieve_log_sequence.min_lines_to_invoke).
    """

    name = "retrieve_log_sequence"
    version = "1.0.0"
    required_flags = frozenset({ORDERED_LOGS})
    cost_class = "medium"

    predictions_pipeline_name = "logseq2vec_retrieval_pretrained"
    predictions_subdir = "v2b-logseq2vec"

    failure_modes = (
        FailureMode(
            kind="ood_modality_loss",
            description=(
                "LogSeq2Vec relies on temporal order of log lines. "
                "When log_lines_ordered=False (WoL log_quotes), the "
                "sequence aggregator's positional signal disappears "
                "and Hit@5 drops by ~0.6 absolute."
            ),
            citation="DOCS/docs7/MODE3-TCH-LITE-WoL-RESULTS.md §3.5",
            triggered_when=frozenset({"UNORDERED_LOGS"}),
            severity="warning",
        ),
    )


# ---------------------------------------------------------------------------
# retrieve_hybrid_fusion — Hybrid-RRF (rule + LLM graph variants).
# ---------------------------------------------------------------------------


class RetrieveHybridFusionSkill(PredictionsBackedSkill):
    """Wraps Hybrid-RRF rule (`hybrid_rrf_retrieval_rule`).

    Strongest retriever on the WoL strong-match relation (Hit@5 = 0.787
    vs BiEncoder 0.663) — the lexical (SPLADE) + graph signals lift the
    BiEncoder on strong matches where dense similarity is too coarse to
    distinguish symptom-rich neighbours. KG-graph-memory presence is
    not strictly required — graceful fallback to BiEncoder+SPLADE.
    """

    name = "retrieve_hybrid_fusion"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE, MEMORY_TEXT})
    cost_class = "medium"

    predictions_pipeline_name = "hybrid_rrf_retrieval_rule"
    predictions_subdir = "v2c-hybrid"


class RetrieveHybridFusionLLMSkill(PredictionsBackedSkill):
    """Hybrid-RRF with LLM-extracted graph (`hybrid_rrf_retrieval_llm`).

    Same fusion, LLM-extracted entities on the graph component instead
    of rule-extracted. Not in TCH's L2 RRF set (dropped per the
    cascade's drop-one sweep), but kept as a registered skill for the
    L4 stacker and ablation comparisons.
    """

    name = "retrieve_hybrid_fusion_llm"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE, MEMORY_TEXT, KG_GRAPH_MEMORY})
    cost_class = "medium"

    predictions_pipeline_name = "hybrid_rrf_retrieval_llm"
    predictions_subdir = "v2c-hybrid-llm"


# ---------------------------------------------------------------------------
# retrieve_knowledge_graph — KG-Retrieval (Neo4j-only).
# ---------------------------------------------------------------------------


class RetrieveKnowledgeGraphSkill(PredictionsBackedSkill):
    """Wraps KG-Retrieval rule (`kg_retrieval_rulebased`).

    Pure graph-overlap retriever; rule-based window-side extraction in
    v1. On WoL the rule-based windows are sparse (Apache vocabulary
    doesn't match the OB-trained rule extractor), so KG-Retrieval alone
    underperforms — but in fusion it still contributes (the cascade's
    drop-one sweep showed dropping it costs −0.015 Hit@5).

    Closing RQ-A6 requires LLM-extracted windows (KG_GRAPH_WINDOW flag);
    a future v1.1 skill version will be optimised for that case.
    """

    name = "retrieve_knowledge_graph"
    version = "1.0.0"
    required_flags = frozenset({KG_GRAPH_MEMORY})
    cost_class = "medium"

    predictions_pipeline_name = "kg_retrieval_rulebased"
    predictions_subdir = "v2d-kg-rulebased"

    failure_modes = (
        FailureMode(
            kind="ood_extraction_asymmetry",
            description=(
                "Memory-side entities come from LLM extraction (rich); "
                "window-side comes from a rule extractor calibrated on "
                "the OB service catalog. WoL test windows produce nearly "
                "empty entity sets through that rule extractor, so "
                "graph overlap underperforms. Closing requires the "
                "RQ-A6 fix: LLM-extracted windows."
            ),
            citation="DOCS/docs7/MODE3-TCH-LITE-WoL-RESULTS.md §3.7",
            triggered_when=frozenset(),  # always relevant on WoL/non-OB
            severity="warning",
        ),
    )


# ---------------------------------------------------------------------------
# verify_with_llm — DiagnosisAgent.
# ---------------------------------------------------------------------------


class VerifyWithLLMSkill(PredictionsBackedSkill):
    """Wraps DiagnosisAgent (`diagnosis_agent`).

    Strictly gated by `VERIFIER_KNOWN_HELPFUL` (set by the
    VerifierCalibration from agent-config.yaml). On WoL it's known to
    degrade Hit@5 by −0.272 (Mode 3 §3.9) so the calibration table puts
    WoL in `known_harmful_distributions` → the flag is absent → this
    skill's `can_invoke` returns False → the runner never invokes it.

    This is the structural closure of RQ-A8.
    """

    name = "verify_with_llm"
    version = "1.0.0"
    required_flags = frozenset({VERIFIER_KNOWN_HELPFUL, TEXT_EVIDENCE})
    cost_class = "expensive_llm"

    predictions_pipeline_name = "diagnosis_agent"
    predictions_subdir = "v2e-agent-llm"

    failure_modes = (
        FailureMode(
            kind="ood_verifier_degradation",
            description=(
                "OB-tuned verifier prompt degrades performance on Apache "
                "Jira (WoL): Hit@5 coarse −0.272 / Hit@5 strong −0.225 vs "
                "the Hybrid-RRF input pool. Three causes: false novelty "
                "calls (15.6%), out-of-domain verify-prompt distribution, "
                "top-10→top-5 compression dropping rank-6-10 golds."
            ),
            citation="DOCS/docs7/MODE3-TCH-LITE-WoL-RESULTS.md §3.9",
            triggered_when=frozenset(),
            severity="error",
        ),
    )
