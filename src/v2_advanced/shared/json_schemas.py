"""JSON schemas for our LLM calls.

Centralized so each pipeline can request a specific schema instead of
relying on a server-side default. We use OpenAI-compatible
`response_format: {"type": "json_schema", "json_schema": {...}}`
which LM Studio supports as of 2024-Q4.

Strict mode (`strict: true`) makes the model's generation grammar-
constrained to a valid instance of the schema, eliminating prose
wrapping and free-text leakage that "JSON mode" alone allows.

Naming convention: every schema name ends in `_schema` and the
top-level `json_schema.name` is short snake_case (LM Studio displays
it in logs / chat templates).
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Phase D — ticket extraction
# ---------------------------------------------------------------------------

TICKET_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "affected_services": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Microservice short-names mentioned (e.g. cartservice, "
                "redis-cart). Use EXACT names from the ticket; empty list "
                "if uncertain."
            ),
        },
        "components": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Sub-service components or shared infra (e.g. envoy, "
                "kubelet, redis). Empty list if uncertain."
            ),
        },
        "error_classes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Canonical error names observed (e.g. DeadlineExceeded, "
                "OOMKilled, ConnectionRefused). Empty list if none."
            ),
        },
        "root_cause": {
            "type": "string",
            "description": (
                "One short sentence describing the underlying cause. "
                "Empty string if unknown."
            ),
        },
        "fix": {
            "type": "string",
            "description": (
                "One short sentence describing what the engineer did to "
                "resolve. Empty string if unknown."
            ),
        },
        "fix_kind": {
            "type": "string",
            "enum": [
                "config_change", "restart", "scale_up",
                "code_fix", "rollback", "other",
            ],
            "description": "Category of fix applied. Use 'other' if uncertain.",
        },
        "symptoms": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "2-5 short observable symptom phrases (e.g. 'p99 latency > 5s', "
                "'cartservice 500 rate spike')."
            ),
        },
    },
    "required": [
        "affected_services", "components", "error_classes",
        "root_cause", "fix", "fix_kind", "symptoms",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Phase D — window extraction (no fix / fix_kind)
# ---------------------------------------------------------------------------

WINDOW_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "affected_services": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Microservice short-names observed in errors.",
        },
        "components": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Sub-service components mentioned in the logs.",
        },
        "error_classes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Canonical error names observed.",
        },
        "symptoms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-5 short observable symptom phrases.",
        },
    },
    "required": [
        "affected_services", "components", "error_classes", "symptoms",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Phase E — DiagnosisAgent Stage 1 (hypothesize)
# ---------------------------------------------------------------------------

HYPOTHESIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_cause_hypothesis": {
            "type": "string",
            "description": "ONE short sentence — your best guess for the underlying cause.",
        },
        "key_symptoms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-5 short phrases observed.",
        },
        "suspected_services": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Service short-names most likely affected.",
        },
    },
    "required": ["root_cause_hypothesis", "key_symptoms", "suspected_services"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Phase E — DiagnosisAgent Stage 3 (verify / rank)
# ---------------------------------------------------------------------------

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "consistent": {"type": "boolean"},
                    "reason": {
                        "type": "string",
                        "description": "One short sentence explaining the rating.",
                    },
                },
                "required": ["ticket_id", "confidence", "consistent", "reason"],
                "additionalProperties": False,
            },
        },
        "novel": {
            "type": "boolean",
            "description": "True if no candidate is consistent with the hypothesis.",
        },
    },
    # Both top-level properties must be `required` under OpenAI's strict
    # structured-outputs mode (LM Studio is lenient about this).
    "required": ["ranked", "novel"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def response_format(schema: dict[str, Any], *, name: str) -> dict[str, Any]:
    """Wrap a schema in the OpenAI / LM Studio response_format envelope.

    Use this in the `response_format` parameter of a chat-completions call:

        client.chat(
            messages=[...],
            response_format=response_format(TICKET_EXTRACTION_SCHEMA,
                                           name="ticket_extraction"),
        )

    LM Studio honors the `strict: true` flag and grammar-constrains
    generation to match the schema.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


# Convenience pre-built envelopes for the four call sites.
TICKET_EXTRACTION_RF = response_format(TICKET_EXTRACTION_SCHEMA, name="ticket_extraction")
WINDOW_EXTRACTION_RF = response_format(WINDOW_EXTRACTION_SCHEMA, name="window_extraction")
HYPOTHESIZE_RF       = response_format(HYPOTHESIZE_SCHEMA,       name="diagnosis_hypothesize")
VERIFY_RF            = response_format(VERIFY_SCHEMA,            name="diagnosis_verify")


__all__ = [
    "TICKET_EXTRACTION_SCHEMA",
    "WINDOW_EXTRACTION_SCHEMA",
    "HYPOTHESIZE_SCHEMA",
    "VERIFY_SCHEMA",
    "response_format",
    "TICKET_EXTRACTION_RF",
    "WINDOW_EXTRACTION_RF",
    "HYPOTHESIZE_RF",
    "VERIFY_RF",
]
