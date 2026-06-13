"""Agent skills layer (Phase 1.6+).

    skills.base     — Skill ABC, AgentContext, MemoryView, FailureMode
    skills.cache    — SkillCache (content-addressed; ablation accelerator)
    skills.registry — SkillRegistry + register_skill helper

Concrete skill classes live in this package (one per file, registered
at import time) starting in Phase 1.7:

    skills.triage_numeric           — HGB wrapper
    skills.retrieve_dense           — BiEncoder wrapper
    skills.retrieve_log_sequence    — LogSeq2Vec wrapper
    skills.retrieve_hybrid_fusion   — Hybrid-RRF wrapper
    skills.retrieve_knowledge_graph — KG-Retrieval wrapper
    skills.verify_with_llm          — DiagnosisAgent wrapper
    skills.extract_entities_llm     — KG-extractor wrapper
    skills.reformulate_query        — new in v1
    skills.compose_l2 / compose_triage / compose_novelty
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
