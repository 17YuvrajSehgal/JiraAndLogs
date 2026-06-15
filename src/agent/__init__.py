"""Agentic Incident Triage System.

Top-level package. Current architecture reference:
`DOCS/docs8/AGENTIC-SYSTEM-V3.md`. The package is organised by layer:

    agent.types               — InputBundle, SkillOutput, AgentDecision
    agent.budget              — Budget + BudgetSnapshot
    agent.plan                — Plan + SkillInvocation
    agent.trace               — Trace + TraceEvent
    agent.capabilities        — Capabilities + flag constants
    agent.capabilities_observer — observer that maps bundles to Capabilities
    agent.tool_protocol       — ReAct ToolRequest / ToolResult contract
    agent.skills              — Skill ABC + registry + concrete skills
    agent.controller          — Controller ABC + RuleController + CapabilityAwareRuleController
    agent.runner              — AgentRunner (plan executor)
    agent.state               — StateLayer + WindowState + page suppression
    agent.eval_harness        — six-rule apples-to-apples harness + metrics + ablation
    agent.data_loaders        — per-dataset case loaders (OB / OTel Demo / WoL)
    agent.data_lake           — RawRunDataLake (read-only telemetry fetcher for ReAct tools)
    agent.llm                 — LLM provider abstraction (six providers)
    agent.integrity           — GraphMetadata fingerprint / dataset-isolation safeguard
    agent.harness_builder     — single source of truth for building a harness per dataset
"""

from .budget import Budget, BudgetExhausted, BudgetSnapshot
from .capabilities import (
    ALL_FLAGS,
    Capabilities,
    K8S_EVENTS,
    KG_GRAPH_MEMORY,
    KG_GRAPH_WINDOW,
    MEMORY_TEXT,
    METRIC_SNAPSHOTS,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    TEXT_EVIDENCE,
    TRACE_SUMMARY,
    UNORDERED_LOGS,
    VERIFIER_KNOWN_HELPFUL,
)
from .capabilities_observer import (
    CapabilitiesObserver,
    ObservationContext,
    VerifierCalibration,
    observe,
)
from .plan import Plan, SkillInvocation
from .trace import Trace, TraceEvent
from .types import (
    AgentDecision,
    InputBundle,
    K8sEvent,
    LogLine,
    SkillCallCost,
    SkillOutput,
    TraceSummary,
)

__version__ = "0.1.0-dev"

__all__ = [
    # InputBundle + sub-records
    "InputBundle",
    "LogLine",
    "TraceSummary",
    "K8sEvent",
    # Capabilities + flag constants
    "Capabilities",
    "CapabilitiesObserver",
    "ObservationContext",
    "VerifierCalibration",
    "observe",
    "ALL_FLAGS",
    "NUMERIC_FEATURES",
    "TEXT_EVIDENCE",
    "ORDERED_LOGS",
    "UNORDERED_LOGS",
    "TRACE_SUMMARY",
    "K8S_EVENTS",
    "METRIC_SNAPSHOTS",
    "MEMORY_TEXT",
    "KG_GRAPH_MEMORY",
    "KG_GRAPH_WINDOW",
    "VERIFIER_KNOWN_HELPFUL",
    # Budget
    "Budget",
    "BudgetExhausted",
    "BudgetSnapshot",
    # Skill I/O
    "SkillOutput",
    "SkillCallCost",
    # Plan
    "Plan",
    "SkillInvocation",
    # Trace
    "Trace",
    "TraceEvent",
    # Final output
    "AgentDecision",
]
