"""Agentic Incident Triage System.

Top-level package for the agent system specified in
`DOCS/docs7/AGENTIC-SYSTEM.md`. The package is organised by layer:

    agent.llm           — LLM provider abstraction (Phase 1.2)
    agent.dataclasses   — core data types (Phase 1.4) [pending]
    agent.capabilities  — modality observer (Phase 1.5) [pending]
    agent.skills        — skill registry (Phase 1.7) [pending]
    agent.controller    — pluggable controller (Phase 1.9) [pending]
    agent.runner        — plan executor (Phase 1.11) [pending]
    agent.state         — cross-window state (Phase 1.12) [pending]
    agent.eval          — evaluation harness (Phase 1.13) [pending]
"""

__version__ = "0.1.0-dev"
