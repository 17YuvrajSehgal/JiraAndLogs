"""Agent skills layer.

Infrastructure:
    skills.base                — Skill ABC, AgentContext, MemoryView, FailureMode
    skills.cache               — SkillCache (content-addressed; ablation accelerator)
    skills.registry            — SkillRegistry + register_skill helper
    skills.predictions_backed  — PredictionsBackedSkill base for cascade-derived retrievers

Concrete skill modules (each file registers one or more skills):
    skills.retrievers           — triage_numeric, retrieve_dense,
                                  retrieve_log_sequence, retrieve_hybrid_fusion,
                                  retrieve_hybrid_fusion_llm,
                                  retrieve_knowledge_graph, verify_with_llm
    skills.composition          — compose_l2, compose_triage, compose_novelty
    skills.extract_entities_llm — KG entity extractor (indexing-time only)
    skills.reformulate_query    — bounded-action query reformulator
    skills.evidence_request     — EvidenceRequestSkill base + 4 ReAct tools
                                  (request_pod_events,
                                   request_extended_trace_window,
                                   request_pod_metrics,
                                   request_similar_incident_window)
    skills.rerank_with_evidence — consumes ReAct tool results to re-rank L2
"""

from .base import (
    AgentContext,
    CostClass,
    FailureMode,
    MemoryView,
    Skill,
    make_cost,
)
from .cache import DEFAULT_CACHE_ROOT, NullSkillCache, SkillCache
from .composition import (
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
)
from .predictions_backed import (
    PredictionsBackedSkill,
    PredictionsNotFoundError,
)
from .extract_entities_llm import ExtractEntitiesLLMSkill
from .reformulate_query import (
    REFORMULATION_ACTIONS,
    ReformulateQuerySkill,
)
from .registry import (
    SkillRegistry,
    get_default_registry,
    register_skill,
    reset_default_registry,
)
from .retrievers import (
    RetrieveDenseSkill,
    RetrieveHybridFusionLLMSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    TriageNumericSkill,
    VerifyWithLLMSkill,
)

__all__ = [
    # base
    "Skill",
    "AgentContext",
    "MemoryView",
    "FailureMode",
    "CostClass",
    "make_cost",
    # cache
    "SkillCache",
    "NullSkillCache",
    "DEFAULT_CACHE_ROOT",
    # registry
    "SkillRegistry",
    "register_skill",
    "get_default_registry",
    "reset_default_registry",
    # predictions-backed base
    "PredictionsBackedSkill",
    "PredictionsNotFoundError",
    # reformulation
    "ReformulateQuerySkill",
    "REFORMULATION_ACTIONS",
    # indexing-time entity extractor
    "ExtractEntitiesLLMSkill",
    # concrete retrieval / triage / verifier skills
    "TriageNumericSkill",
    "RetrieveDenseSkill",
    "RetrieveLogSequenceSkill",
    "RetrieveHybridFusionSkill",
    "RetrieveHybridFusionLLMSkill",
    "RetrieveKnowledgeGraphSkill",
    "VerifyWithLLMSkill",
    # composition
    "ComposeL2Skill",
    "ComposeTriageSkill",
    "ComposeNoveltySkill",
]
