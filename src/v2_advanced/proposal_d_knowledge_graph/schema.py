"""Knowledge-graph schema for the v2_advanced Phase D pipeline.

We extract a small, focused set of nodes and edges from each Jira ticket
(and from each live window at query time). Keeping the schema small
keeps the LLM extraction prompt manageable and the Cypher queries
readable.

NODES
    Incident       The Jira ticket itself (one per ticket).
        id           ticket_id, unique
        severity     minor | major | critical
        family       coarse scenario family
        ts           when the incident was filed (ISO timestamp)

    Service        A microservice involved.
        name         "cartservice", "checkoutservice", ...

    Component      A sub-service component (often shared infra).
        name         "cart-redis", "kubelet", "envoy", ...

    ErrorClass     A canonical error class name observed.
        name         "DeadlineExceeded", "OOMKilled", "ConnectionRefused"

    RootCause      One-sentence root cause description.
        description  free text

    Fix            One-sentence fix description + type.
        description  free text
        kind         config_change | restart | scale_up | code_fix | rollback | other

    Symptom        Short observable symptom phrase.
        description  e.g. "p99 latency > 5s", "cart_500_rate_spike"

EDGES
    (Incident) -[:AFFECTS]->          (Service)
    (Incident) -[:INVOLVES]->         (Component)
    (Incident) -[:RAISED]->           (ErrorClass)
    (Incident) -[:CAUSED_BY]->        (RootCause)
    (Incident) -[:FIXED_BY]->         (Fix)
    (Incident) -[:EXHIBITED]->        (Symptom)

Retrieval scoring (the Cypher LIMIT-K query):

    Given a live window's extracted entities, score each Incident by:
        service_overlap   × 2.0
      + error_overlap     × 3.0
      + symptom_overlap   × 1.0
      + component_overlap × 1.5

    The error_class match weight is highest because an exact error
    class is the strongest signal in SRE work; symptoms are common
    across many incidents so each one contributes less.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


FixKind = Literal[
    "config_change", "restart", "scale_up", "code_fix", "rollback", "other",
]


@dataclass
class IncidentExtraction:
    """The structured fact set we extract from one Jira ticket."""

    ticket_id: str
    severity: str = ""                              # minor / major / critical
    family: str = ""                                # scenario family
    timestamp: str = ""                             # ISO format
    affected_services: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    error_classes: list[str] = field(default_factory=list)
    root_cause: str = ""
    fix: str = ""
    fix_kind: FixKind = "other"
    symptoms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "severity": self.severity,
            "family": self.family,
            "timestamp": self.timestamp,
            "affected_services": self.affected_services,
            "components": self.components,
            "error_classes": self.error_classes,
            "root_cause": self.root_cause,
            "fix": self.fix,
            "fix_kind": self.fix_kind,
            "symptoms": self.symptoms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IncidentExtraction":
        return cls(
            ticket_id=d.get("ticket_id", ""),
            severity=d.get("severity", "") or "",
            family=d.get("family", "") or "",
            timestamp=d.get("timestamp", "") or "",
            affected_services=list(d.get("affected_services") or []),
            components=list(d.get("components") or []),
            error_classes=list(d.get("error_classes") or []),
            root_cause=d.get("root_cause", "") or "",
            fix=d.get("fix", "") or "",
            fix_kind=d.get("fix_kind", "other") or "other",
            symptoms=list(d.get("symptoms") or []),
        )


@dataclass
class WindowExtraction:
    """Same shape minus the resolution / fix; for live windows where
    we haven't fixed it yet — we just need to find similar past
    incidents."""

    window_id: str
    severity: str = ""
    family: str = ""
    affected_services: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    error_classes: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "window_id": self.window_id,
            "severity": self.severity,
            "family": self.family,
            "affected_services": self.affected_services,
            "components": self.components,
            "error_classes": self.error_classes,
            "symptoms": self.symptoms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WindowExtraction":
        return cls(
            window_id=d.get("window_id", ""),
            severity=d.get("severity", "") or "",
            family=d.get("family", "") or "",
            affected_services=list(d.get("affected_services") or []),
            components=list(d.get("components") or []),
            error_classes=list(d.get("error_classes") or []),
            symptoms=list(d.get("symptoms") or []),
        )
