"""Agentic Incident Triage System.

Top-level package for the agent system specified in
`DOCS/docs7/AGENTIC-SYSTEM.md`. The package is organised by layer:

    agent.llm           — LLM provider abstraction (Phase 1.2)
    agent.capabilities  — Capabilities + flag constants (Phase 1.4)
    agent.types         — InputBundle, SkillOutput, AgentDecision, ... (Phase 1.4)
    agent.budget        — Budget + BudgetSnapshot (Phase 1.4)
    agent.plan          — Plan + SkillInvocation (Phase 1.4)
    agent.trace         — Trace + TraceEvent (Phase 1.4)
    agent.skills        — Skill registry (Phase 1.7) [pending]
    agent.controller    — pluggable controller (Phase 1.9) [pending]
    agent.runner        — plan executor (Phase 1.11) [pending]
    agent.state         — cross-window state (Phase 1.12) [pending]
    agent.eval          — evaluation harness (Phase 1.13) [pending]
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
