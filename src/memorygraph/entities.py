"""Typed entities + cross-context extractors.

An Entity is a (kind, value) pair like `("component", "paymentservice")`
that exists in both the observability side and the Jira side. The point of
the extractor pair below is that *the same Entity kinds come out of both
sides* — that is what makes the graph join meaningful.

Production-realism rule (enforced here, not in callers):
  - Observability extractor reads only `evidence_text`, `service_name`,
    `window_type`, and the numeric `triage_feature_*` columns from the
    window's `raw` dict. It NEVER reads `triage_label`, `triage_severity`,
    `triage_components`, `triage_reason_class`, `is_hard_case`,
    `scenario_id`, or `scenario_family`.
  - Jira extractor strips lab-leakage labels (`scenario-*`, `dataset-*`,
    `synthetic-incident`, `telemetry-linked`, `severity-*`, `root-*`)
    before they reach the graph. The Jira `severity` and
    `fault_compatibility_class` fields ARE used — they are the
    structured fields a real Jira instance also exposes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from loganalyzer.data.schema import JiraMemoryIssue, TriageWindow


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class EntityKind:
    """Closed enumeration of entity kinds the graph understands.

    Kept as a class of string constants rather than `enum.Enum` so the
    values are JSON-serializable for the explanations.jsonl artifact
    without a custom encoder."""

    SERVICE = "service"
    COMPONENT = "component"
    ERROR_CLASS = "error_class"
    LATENCY_BAND = "latency_band"
    K8S_SIGNAL = "k8s_signal"
    SATURATION = "saturation"
    SEVERITY = "severity"
    FAULT_CLASS = "fault_class"
    REASON_CLASS = "reason_class"


# All entity kinds that exist on both sides of the bridge — used by the
# graph builder to know which kinds to create cross-domain edges for.
BRIDGEABLE_KINDS: tuple[str, ...] = (
    EntityKind.SERVICE,
    EntityKind.COMPONENT,
    EntityKind.ERROR_CLASS,
    EntityKind.SEVERITY,
    EntityKind.FAULT_CLASS,
    EntityKind.REASON_CLASS,
    EntityKind.LATENCY_BAND,
    EntityKind.SATURATION,
    EntityKind.K8S_SIGNAL,
)


@dataclass(frozen=True)
class EntityId:
    """Stable identifier for an entity node in the graph.

    The (kind, value) tuple is the join key across observability and Jira
    domains. `domain` is metadata for explanation rendering — the same
    EntityId can be discovered by both extractors, which is the point.
    """

    kind: str
    value: str

    def key(self) -> str:
        return f"{self.kind}:{self.value}"

    @classmethod
    def make(cls, kind: str, value: str | None) -> "EntityId | None":
        if value is None:
            return None
        v = value.strip().lower()
        return cls(kind, v) if v else None


@dataclass
class Entity:
    """A node in the memory graph.

    `domain` is "obs" when produced by the observability extractor and
    "jira" when produced by the Jira extractor. Cross-domain matching
    happens by joining on the `EntityId`, not on `domain`.
    """

    id: EntityId
    domain: str  # "obs" | "jira"
    source_id: str  # window_id or jira_shadow_issue_id
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """A typed, directed edge in the memory graph.

    The graph builder creates two edge categories:
      - "membership" edges: window/jira parent node -> entity node
      - "relation" edges: entity node -> entity node (the cross-domain
        bridges that drive retrieval)
    """

    src: str  # node id (entity key, window_id, or jira_shadow_issue_id)
    dst: str
    relation: str
    weight: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observability extractor
# ---------------------------------------------------------------------------


_LATENCY_BANDS = (
    (0, 50, "p95_under_50ms"),
    (50, 250, "p95_50_to_250ms"),
    (250, 1000, "p95_250ms_to_1s"),
    (1000, 5000, "p95_1s_to_5s"),
    (5000, 10**9, "p95_over_5s"),
)

# A small, deliberately-coarse mapping from substring-in-evidence to an
# error_class entity. Real production telemetry has thousands of err_class
# strings; the graph only needs a few coarse buckets to be useful.
_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\btimeout\b|\bdeadline\b|\bdeadlineexceeded\b", re.I), "timeout"),
    (re.compile(r"\bunavailable\b|\bconnectionrefused\b|\bENOTFOUND\b", re.I), "unavailable"),
    (re.compile(r"\bredis\b.*\b(error|failed|refused|timeout)\b", re.I), "redis_failure"),
    (re.compile(r"\bOOM\b|\boutofmemory\b|memory.*saturat", re.I), "oom"),
    (re.compile(r"\bDNS\b|\bnoSuchHost\b|name.*resolution", re.I), "dns_failure"),
    (re.compile(r"\b5\d\d\b|\binternal.*error\b|\bservererror\b", re.I), "server_error"),
    (re.compile(r"\b4\d\d\b|\binvalid\b|\bvalidation\b", re.I), "client_error"),
    (re.compile(r"\bpanic\b|\bunhandled\b|\bsegfault\b", re.I), "crash"),
    (re.compile(r"\bcanceled\b|\bcanceled\b", re.I), "canceled"),
    (re.compile(r"\bnotfound\b|\bnot_found\b", re.I), "not_found"),
)

# Known service names in the lab; we still parse arbitrary peer-service
# tokens from evidence so this stays useful when the corpus rotates.
_KNOWN_SERVICES = (
    "adservice", "cartservice", "checkoutservice", "currencyservice",
    "emailservice", "frontend", "loadgenerator", "paymentservice",
    "productcatalogservice", "recommendationservice", "shippingservice",
    "redis", "redis-cart", "redis-rec",
)

_SERVICE_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _KNOWN_SERVICES) + r")\b",
    re.IGNORECASE,
)


def _latency_band(p95_ms: float | None) -> str | None:
    if p95_ms is None or p95_ms <= 0:
        return None
    for lo, hi, name in _LATENCY_BANDS:
        if lo <= p95_ms < hi:
            return name
    return None


def _k8s_signals(raw: dict[str, Any]) -> list[tuple[str, float]]:
    """Surface k8s-side entity signals from production-safe numeric features.

    Returns (signal_name, magnitude) pairs. Empty when nothing fired.
    Reads only `triage_feature_*` columns — never label-side fields.
    """
    out: list[tuple[str, float]] = []
    pod_unavail = float(raw.get("triage_feature_k8s_pod_unavailable_count", 0) or 0)
    restarts = float(raw.get("triage_feature_k8s_restart_count", 0) or 0)
    warnings = float(raw.get("triage_feature_k8s_warning_event_count", 0) or 0)
    if pod_unavail >= 1:
        out.append(("pods_unavailable", pod_unavail))
    if restarts >= 1:
        out.append(("pod_restart", restarts))
    if warnings >= 3:
        out.append(("warning_events", warnings))
    return out


def _saturation_signals(raw: dict[str, Any]) -> list[tuple[str, float]]:
    """Surface saturation entities (cpu/mem high) from numeric features."""
    out: list[tuple[str, float]] = []
    cpu = float(raw.get("triage_feature_metric_cpu_pct", 0) or 0)
    mem = float(raw.get("triage_feature_metric_memory_pct", 0) or 0)
    if cpu >= 80:
        out.append(("cpu_saturated", cpu))
    if mem >= 80:
        out.append(("memory_saturated", mem))
    return out


def _error_classes_from_text(text: str) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for pattern, label in _ERROR_PATTERNS:
        if pattern.search(text):
            if label not in seen:
                seen.append(label)
    return seen


def _services_from_text(text: str) -> list[str]:
    if not text:
        return []
    found = [m.group(1).lower() for m in _SERVICE_RE.finditer(text)]
    # dedupe while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for s in found:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def extract_obs_entities(window: TriageWindow) -> tuple[list[Entity], dict[str, Any]]:
    """Pull entities out of an observability window.

    Returns (entities, summary). The summary dict carries scalar magnitudes
    the graph builder uses to weight edges (e.g. p95 latency, error rate).
    """
    raw = window.raw or {}
    text = window.evidence_text or ""
    entities: list[Entity] = []

    # 1) The window's own service is the primary anchor.
    svc_id = EntityId.make(EntityKind.SERVICE, window.service_name)
    if svc_id:
        entities.append(
            Entity(svc_id, "obs", window.window_id, {"role": "primary"})
        )
        # service doubles as a component candidate — Jira components are
        # named after services in this corpus.
        cmp_id = EntityId(EntityKind.COMPONENT, window.service_name.lower())
        entities.append(
            Entity(cmp_id, "obs", window.window_id, {"role": "primary"})
        )

    # 2) Co-mentioned services in the evidence text become peer-service
    #    entities (cart's evidence mentions redis-cart, etc.).
    for peer in _services_from_text(text):
        if peer == (window.service_name or "").lower():
            continue
        eid = EntityId(EntityKind.SERVICE, peer)
        entities.append(Entity(eid, "obs", window.window_id, {"role": "peer"}))
        cid = EntityId(EntityKind.COMPONENT, peer)
        entities.append(Entity(cid, "obs", window.window_id, {"role": "peer"}))

    # 3) Error classes from evidence text.
    for ec in _error_classes_from_text(text):
        eid = EntityId(EntityKind.ERROR_CLASS, ec)
        entities.append(Entity(eid, "obs", window.window_id, {}))

    # 4) Latency band from p95 feature.
    p95 = raw.get("triage_feature_trace_latency_p95_ms")
    band = _latency_band(float(p95) if p95 is not None else None)
    if band:
        eid = EntityId(EntityKind.LATENCY_BAND, band)
        entities.append(
            Entity(eid, "obs", window.window_id, {"p95_ms": float(p95)})
        )

    # 5) K8s signals.
    for sig, mag in _k8s_signals(raw):
        eid = EntityId(EntityKind.K8S_SIGNAL, sig)
        entities.append(
            Entity(eid, "obs", window.window_id, {"magnitude": mag})
        )

    # 6) Saturation signals.
    for sig, mag in _saturation_signals(raw):
        eid = EntityId(EntityKind.SATURATION, sig)
        entities.append(
            Entity(eid, "obs", window.window_id, {"pct": mag})
        )

    summary = {
        "window_id": window.window_id,
        "service": window.service_name,
        "p95_ms": float(p95) if p95 is not None else None,
        "trace_error_rate": float(
            raw.get("triage_feature_trace_error_rate", 0) or 0
        ),
        "log_error_count": float(
            raw.get("triage_feature_log_error_count", 0) or 0
        ),
        "n_entities": len(entities),
    }
    return entities, summary


# ---------------------------------------------------------------------------
# Jira extractor
# ---------------------------------------------------------------------------


# Lab-leakage labels that must not reach the graph — they encode the
# scenario identity in plain text and would let retrieval cheat.
_LAB_LEAK_PREFIXES = (
    "scenario-",
    "dataset-",
    "severity-",
    "root-",
)
_LAB_LEAK_EXACT = frozenset({"synthetic-incident", "telemetry-linked"})

# Labels we keep — these look like real-Jira semantic labels.
_KEEP_LABELS = frozenset({
    "bug", "incident", "production", "customer-impact", "regression",
    "rollback", "investigation", "needs-followup", "monitoring",
    "performance", "stability", "data-loss",
})

# Severity vocabulary the Jira corpus uses, mapped to a coarse ordinal so
# severity_aligned edges can compare across contexts.
SEVERITY_ORDINAL: dict[str, int] = {
    "minor": 1,
    "low": 1,
    "major": 2,
    "medium": 2,
    "critical": 3,
    "high": 3,
}


_COMPONENTS_RE = re.compile(r"^Components:\s*(.+)$", re.MULTILINE)
_LABELS_RE = re.compile(r"^Labels:\s*(.+)$", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^Summary:\s*(.+)$", re.MULTILINE)
_AFFECTED_RE = re.compile(r"^Affected services:\s*(.+)$", re.MULTILINE)


def _clean_labels(raw_labels: Iterable[str]) -> list[str]:
    """Strip lab-leakage labels; keep the semantic remainder.

    Drop reasoning: leaving `scenario-cart-redis-degradation-critical` in
    the graph would give the retrieval a free oracle for the exact lab
    label, defeating the whole production-realism setup.
    """
    out: list[str] = []
    for label in raw_labels:
        L = (label or "").strip().lower()
        if not L:
            continue
        if any(L.startswith(p) for p in _LAB_LEAK_PREFIXES):
            continue
        if L in _LAB_LEAK_EXACT:
            continue
        out.append(L)
    return out


def _parse_csv_line(line: str) -> list[str]:
    return [t.strip().lower() for t in (line or "").split(",") if t.strip()]


def extract_jira_entities(issue: JiraMemoryIssue) -> tuple[list[Entity], dict[str, Any]]:
    """Pull entities out of one Jira memory entry.

    Reads the structured fields (`affected_service`, `severity`,
    `fault_compatibility_class`, `fault_type`) and parses the memory_text
    for Components / Labels / Affected-services lines that the generator
    emits. Lab-leakage labels are dropped here, before they reach the
    graph.
    """
    entities: list[Entity] = []
    text = issue.memory_text or ""
    sid = issue.jira_shadow_issue_id

    # 1) Affected service from the structured field is the primary anchor.
    svc_id = EntityId.make(EntityKind.SERVICE, issue.affected_service)
    if svc_id:
        entities.append(
            Entity(svc_id, "jira", sid, {"role": "primary"})
        )
        cid = EntityId(EntityKind.COMPONENT, issue.affected_service.lower())
        entities.append(
            Entity(cid, "jira", sid, {"role": "primary"})
        )

    # 2) Components line (e.g. "Components: checkoutservice, frontend").
    m = _COMPONENTS_RE.search(text)
    if m:
        for c in _parse_csv_line(m.group(1)):
            eid = EntityId(EntityKind.COMPONENT, c)
            entities.append(Entity(eid, "jira", sid, {"role": "component"}))

    # 3) Affected services line (often overlaps with Components).
    m = _AFFECTED_RE.search(text)
    if m:
        for s in _parse_csv_line(m.group(1)):
            eid = EntityId(EntityKind.SERVICE, s)
            entities.append(Entity(eid, "jira", sid, {"role": "affected"}))

    # 4) Severity entity, from the structured field (eval-only on
    #    windows; OK on Jira since the memory corpus is the system input).
    sev_id = EntityId.make(EntityKind.SEVERITY, issue.severity)
    if sev_id:
        entities.append(
            Entity(
                sev_id,
                "jira",
                sid,
                {"ordinal": SEVERITY_ORDINAL.get(sev_id.value, 0)},
            )
        )

    # 5) Fault class (compatibility class is a coarser version of fault
    #    type — both are useful as separate entities).
    fc_id = EntityId.make(EntityKind.FAULT_CLASS, issue.fault_compatibility_class)
    if fc_id and fc_id.value != "none":
        entities.append(Entity(fc_id, "jira", sid, {}))
    ft_id = EntityId.make(EntityKind.FAULT_CLASS, issue.fault_type)
    if ft_id and ft_id.value != fc_id.value if fc_id else True:
        if ft_id and ft_id.value:
            entities.append(Entity(ft_id, "jira", sid, {}))

    # 6) Error classes the resolution_notes or memory_text hint at.
    haystack = f"{text}\n{issue.resolution_notes or ''}"
    for ec in _error_classes_from_text(haystack):
        eid = EntityId(EntityKind.ERROR_CLASS, ec)
        entities.append(Entity(eid, "jira", sid, {}))

    # 7) Reason class — coarsely inferred from fault_type / fault_class.
    rc = _infer_reason_class(issue.fault_type, issue.fault_compatibility_class)
    if rc:
        eid = EntityId(EntityKind.REASON_CLASS, rc)
        entities.append(Entity(eid, "jira", sid, {}))

    # 8) Labels: keep the semantic remainder after stripping lab leakage.
    m = _LABELS_RE.search(text)
    raw_labels = _parse_csv_line(m.group(1)) if m else []
    clean = _clean_labels(raw_labels)

    summary = {
        "jira_shadow_issue_id": sid,
        "affected_service": issue.affected_service,
        "severity": issue.severity,
        "fault_class": issue.fault_compatibility_class,
        "fault_type": issue.fault_type,
        "kept_labels": clean,
        "dropped_labels": [lab for lab in raw_labels if lab not in clean],
        "n_entities": len(entities),
    }
    return entities, summary


def _infer_reason_class(fault_type: str | None, fault_class: str | None) -> str | None:
    """Coarse reason-class taxonomy aligned with `docs/triage-task-contract.md`.

    We never use the window's own `triage_reason_class` (eval-only). We
    re-derive a reason class from the Jira-side structured fields, which
    is allowed because the Jira memory corpus is part of the system's
    input.
    """
    ft = (fault_type or "").lower()
    fc = (fault_class or "").lower()
    if any(k in ft for k in ("outage", "unavailable", "down")):
        return "outage"
    if any(k in ft for k in ("latency", "slow", "p95")):
        return "latency_regression"
    if any(k in ft for k in ("restart", "flap", "crash")):
        return "restart_with_impact"
    if "config" in ft:
        return "bad_config"
    if any(k in ft for k in ("capacity", "leak", "saturation")):
        return "capacity"
    if any(k in fc for k in ("dependency", "redis", "downstream")):
        return "dependency_failure"
    if any(k in ft for k in ("consistency", "data")):
        return "data_consistency"
    return None
