"""Rule-based fallback extractor for the knowledge graph (Phase D).

When LM Studio isn't available (no model loaded, no GPU memory), we
can still populate the graph using regex + keyword matching over the
ticket text. The extractions are coarser but the schema is identical,
so the rest of the Phase D pipeline (loader, retriever) works the same.

The rule-based extractor exists for three reasons:
  1. So Phase D can run end-to-end on machines without LM Studio.
  2. As a baseline to compare against — does the LLM extraction
     actually help vs simple keyword matching?
  3. To pre-populate the graph quickly during development before
     waiting for an LLM run.
"""
from __future__ import annotations

import re
from typing import Any

from v2_advanced.shared import get_logger
from .schema import IncidentExtraction, WindowExtraction

log = get_logger("phase_d.rule_extractor")


# Known canonical entities for the microservices-demo dataset
_KNOWN_SERVICES = [
    "cartservice", "checkoutservice", "productcatalogservice",
    "currencyservice", "paymentservice", "shippingservice",
    "emailservice", "recommendationservice", "adservice",
    "frontend", "loadgenerator", "redis-cart",
]

_KNOWN_COMPONENTS = [
    "redis", "envoy", "kubelet", "mysql", "kafka", "postgres",
    "istio", "prometheus", "grafana", "loki", "tempo",
    "ingress", "configmap", "secret", "pvc", "pod", "deployment",
]

_KNOWN_ERRORS = [
    "DeadlineExceeded", "OOMKilled", "ConnectionRefused", "CrashLoopBackOff",
    "ImagePullBackOff", "Unavailable", "Internal", "ResourceExhausted",
    "NotFound", "Unauthenticated", "PermissionDenied", "Aborted",
    "FailedPrecondition", "AlreadyExists", "OutOfRange",
    "Cancelled", "DataLoss", "Unknown", "Unimplemented",
    "Bad Gateway", "504", "503", "502", "500",
]

_FIX_KIND_PATTERNS = [
    ("config_change", ["change configmap", "update config", "set maxmemory", "raise limit",
                       "increase timeout", "tune", "config change", "kubectl edit configmap"]),
    ("restart",       ["kubectl rollout restart", "restart pod", "restart deployment",
                       "delete pod", "kubectl delete pod", "force restart"]),
    ("scale_up",      ["kubectl scale", "increase replicas", "scale up", "horizontal pod autoscaler",
                       "vertical pod autoscaler", "add more replicas"]),
    ("code_fix",      ["fix in code", "patched", "committed fix", "merged pr", "code change",
                       "git revert", "hot patch"]),
    ("rollback",      ["rollback", "revert deployment", "kubectl rollout undo", "previous version",
                       "revert to v"]),
]


_ERROR_SYMPTOMS_PATTERNS = [
    (r"p99 latency .* (?:>|reached) ?\d", "high p99 latency"),
    (r"5\d\d.*(?:rate|spike|surge|jump)", "5xx error spike"),
    (r"\boom\b", "out-of-memory"),
    (r"crash\s*loop", "crashloop"),
    (r"\brestart(?:ing|ed)?\b", "pod restart"),
    (r"\bconnection.*(?:timeout|refused|reset)\b", "connection failure"),
    (r"\btimeout\b", "request timeout"),
    (r"\b(?:db|database|redis|mysql|postgres).*(?:down|unavailable|degraded)\b", "datastore unavailable"),
]


def _find_first_matching_set(text: str, candidates: list[str]) -> list[str]:
    """Return the subset of `candidates` whose lowercased form appears in
    text. Stable order matches `candidates`'s ordering."""
    t = text.lower()
    return [c for c in candidates if c.lower() in t]


def _extract_fix_kind(text: str) -> str:
    t = text.lower()
    for kind, patterns in _FIX_KIND_PATTERNS:
        for p in patterns:
            if p.lower() in t:
                return kind
    return "other"


def _extract_root_cause_sentence(text: str) -> str:
    """Pick the sentence that most likely contains the root cause.

    Heuristic: prefer sentences containing 'cause', 'because', 'due to',
    'root', 'reason'. If none, use the first sentence that contains an
    error class or service name.
    """
    lines = re.split(r"[.\n]+", text)
    cause_keywords = ["root cause", "because", "due to", "caused by", "reason was"]
    for ln in lines:
        s = ln.strip()
        if 5 < len(s) < 200 and any(k in s.lower() for k in cause_keywords):
            return s
    # Fallback: shortest line that mentions an error class
    for ln in lines:
        s = ln.strip()
        if 5 < len(s) < 200 and any(e.lower() in s.lower() for e in _KNOWN_ERRORS):
            return s
    return ""


def _extract_fix_sentence(text: str) -> str:
    """Pick the sentence that most likely contains the fix description."""
    lines = re.split(r"[.\n]+", text)
    fix_keywords = ["fix", "resolved", "applied", "patched", "kubectl",
                    "restarted", "rolled back", "increased", "raised"]
    for ln in lines:
        s = ln.strip()
        if 5 < len(s) < 200 and any(k in s.lower() for k in fix_keywords):
            return s
    return ""


def _extract_symptoms(text: str) -> list[str]:
    found = []
    for pat, label in _ERROR_SYMPTOMS_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            if label not in found:
                found.append(label)
    return found


def extract_from_ticket_rules(
    *,
    ticket_id: str,
    ticket_text: str,
    severity: str = "",
    family: str = "",
    timestamp: str = "",
) -> IncidentExtraction:
    """Rule-based extraction. No LLM. Deterministic."""
    services = _find_first_matching_set(ticket_text, _KNOWN_SERVICES)
    components = _find_first_matching_set(ticket_text, _KNOWN_COMPONENTS)
    errors = _find_first_matching_set(ticket_text, _KNOWN_ERRORS)
    root_cause = _extract_root_cause_sentence(ticket_text)
    fix = _extract_fix_sentence(ticket_text)
    fix_kind = _extract_fix_kind(ticket_text)
    symptoms = _extract_symptoms(ticket_text)
    return IncidentExtraction(
        ticket_id=ticket_id,
        severity=severity,
        family=family,
        timestamp=timestamp,
        affected_services=services,
        components=components,
        error_classes=errors,
        root_cause=root_cause,
        fix=fix,
        fix_kind=fix_kind,
        symptoms=symptoms,
    )


def extract_from_window_rules(
    *,
    window_id: str,
    evidence_text: str,
    severity: str = "",
    family: str = "",
) -> WindowExtraction:
    """Rule-based window extraction."""
    services = _find_first_matching_set(evidence_text, _KNOWN_SERVICES)
    components = _find_first_matching_set(evidence_text, _KNOWN_COMPONENTS)
    errors = _find_first_matching_set(evidence_text, _KNOWN_ERRORS)
    symptoms = _extract_symptoms(evidence_text)
    return WindowExtraction(
        window_id=window_id,
        severity=severity,
        family=family,
        affected_services=services,
        components=components,
        error_classes=errors,
        symptoms=symptoms,
    )
