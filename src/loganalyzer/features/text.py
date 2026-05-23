"""Text feature builders for lexical / embedding retrieval.

Tokenization is deliberately stupid: lowercase, alphanumeric-only, drop tokens
shorter than two characters. Telemetry text is already structured (key=value
patterns and span/log names), and a real tokenizer (BERT-style) lives behind
the optional embedding retriever.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..data.schema import JiraMemoryIssue, TriageWindow


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [tok.lower() for tok in _TOKEN_RE.findall(text) if len(tok) >= 2]


def build_window_query_text(window: TriageWindow) -> str:
    """Text used as the retrieval query for a window.

    Combines the structured evidence text from the dataset builder with the
    window's identity (service + window_type) so that lexical retrieval has
    a fighting chance of matching service-specific issue text.
    """
    parts: list[str] = []
    parts.append(f"service={window.service_name} window_type={window.window_type}")
    if window.evidence_text:
        parts.append(window.evidence_text)
    return "\n".join(parts)


def build_memory_doc_text(issue: JiraMemoryIssue) -> str:
    """Text used as the indexed document for a memory issue.

    memory_text already includes summary, description, labels, components,
    comments, and a brief telemetry summary - we just prepend a one-line
    identity header so service / family terms hit the index.
    """
    header = (
        f"jira_issue_key={issue.jira_issue_key} "
        f"affected_service={issue.affected_service} "
        f"scenario_family={issue.scenario_family} "
        f"fault_type={issue.fault_type} "
        f"severity={issue.severity}"
    )
    body = issue.memory_text or ""
    return f"{header}\n{body}"


def tokenize_iter(texts: Iterable[str]) -> list[list[str]]:
    return [tokenize(t) for t in texts]
