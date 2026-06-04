"""LLM-based extractor for the knowledge graph (Phase D).

For each Jira ticket (or live telemetry window), call the local LM
Studio LLM with a focused JSON-extraction prompt and parse the result
into an `IncidentExtraction` (for tickets) or `WindowExtraction` (for
windows).

Robustness:
  - LM Studio failures retry up to 3 times.
  - Malformed JSON triggers a single re-ask with a stricter prompt.
  - Per-ticket extractions are cached on disk so re-runs are cheap.

Caching: extractions persist to
  data/derived/global/<id>/v2_kg_extractions/<source>__<sha8>.json

where source is "ticket" or "window" and the sha8 is over the input
text. Re-running this module on the same data is a no-op (instant).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from v2_advanced.shared import LMStudioClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig, LMStudioError
from v2_advanced.shared.json_schemas import (
    TICKET_EXTRACTION_RF,
    WINDOW_EXTRACTION_RF,
)

from .schema import IncidentExtraction, WindowExtraction

log = get_logger("phase_d.extractor")


_TICKET_SYSTEM_PROMPT = """You are an SRE knowledge engineer extracting structured incident facts from a Jira ticket.

Read the ticket carefully and emit a JSON object with EXACTLY these keys:
  - affected_services:   list of microservice short-names (e.g. ["cartservice", "redis-cart"])
  - components:          list of sub-service components or shared infra (e.g. ["envoy", "kubelet"])
  - error_classes:       list of canonical error names mentioned (e.g. ["DeadlineExceeded", "OOMKilled"])
  - root_cause:          one short sentence — the underlying cause
  - fix:                 one short sentence — what the engineer did to resolve
  - fix_kind:            ONE of: config_change | restart | scale_up | code_fix | rollback | other
  - symptoms:            list of 2-5 short observable symptom phrases (e.g. "p99 latency > 5s", "cartservice 500 rate spike")

Rules:
  - Use the EXACT short names that appear in the ticket text. If the ticket calls it "cartservice" not "cart-service", use "cartservice".
  - Do NOT invent services or errors the ticket does not mention.
  - If a field is genuinely unknown, return an empty list or empty string.
  - Output VALID JSON only — no markdown, no commentary, no triple-backticks.
"""


_WINDOW_SYSTEM_PROMPT = """You are an SRE engineer extracting structured facts from a live telemetry window.

Read the log lines, metric summary, and entity hints below. Emit a JSON object with EXACTLY these keys:
  - affected_services:   list of microservice short-names observed in errors
  - components:          list of sub-service components mentioned
  - error_classes:       list of canonical error names observed
  - symptoms:            list of 2-5 short observable symptom phrases

Rules:
  - Use EXACT names from the telemetry. Don't paraphrase service names.
  - Don't invent things; if uncertain, omit.
  - Output VALID JSON only.
"""


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _cache_path(global_dir: Path, source: str, ident: str, text: str) -> Path:
    return global_dir / "v2_kg_extractions" / source / f"{ident}__{_content_hash(text)}.json"


def extract_from_ticket(
    client: LMStudioClient,
    *,
    ticket_id: str,
    ticket_text: str,
    severity: str = "",
    family: str = "",
    timestamp: str = "",
    cache_dir: Path | None = None,
    max_tokens: int = 800,
) -> IncidentExtraction:
    """Extract structured facts from one Jira ticket. Cached on disk
    when cache_dir is provided."""
    cache_file = None
    if cache_dir is not None:
        cache_file = cache_dir / "ticket" / f"{ticket_id}__{_content_hash(ticket_text)}.json"
        if cache_file.exists():
            try:
                d = json.loads(cache_file.read_text(encoding="utf-8"))
                return IncidentExtraction.from_dict(d)
            except (json.JSONDecodeError, OSError):
                pass  # corrupted cache; fall through to re-extract

    try:
        obj = client.chat_json(
            system=_TICKET_SYSTEM_PROMPT,
            user=f"TICKET ID: {ticket_id}\n\n{ticket_text}",
            temperature=0.0,
            max_tokens=max_tokens,
            response_format=TICKET_EXTRACTION_RF,
            enable_thinking=False,   # extraction: fast, no chain-of-thought
        )
    except LMStudioError as e:
        log.error("ticket extraction failed", ticket_id=ticket_id, err=str(e)[:120])
        # Return an empty extraction so the pipeline doesn't crash; the
        # graph builder will silently skip this ticket.
        return IncidentExtraction(
            ticket_id=ticket_id, severity=severity, family=family, timestamp=timestamp,
        )

    ext = IncidentExtraction(
        ticket_id=ticket_id,
        severity=severity,
        family=family,
        timestamp=timestamp,
        affected_services=[s for s in (obj.get("affected_services") or []) if isinstance(s, str)],
        components=[s for s in (obj.get("components") or []) if isinstance(s, str)],
        error_classes=[s for s in (obj.get("error_classes") or []) if isinstance(s, str)],
        root_cause=(obj.get("root_cause") or "").strip(),
        fix=(obj.get("fix") or "").strip(),
        fix_kind=(obj.get("fix_kind") or "other").strip() or "other",
        symptoms=[s for s in (obj.get("symptoms") or []) if isinstance(s, str)],
    )

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(ext.as_dict(), indent=2), encoding="utf-8")

    return ext


def extract_from_window(
    client: LMStudioClient,
    *,
    window_id: str,
    evidence_text: str,
    severity: str = "",
    family: str = "",
    cache_dir: Path | None = None,
    max_tokens: int = 500,
) -> WindowExtraction:
    """Extract structured facts from a live telemetry window."""
    cache_file = None
    if cache_dir is not None:
        cache_file = cache_dir / "window" / f"{window_id}__{_content_hash(evidence_text)}.json"
        if cache_file.exists():
            try:
                d = json.loads(cache_file.read_text(encoding="utf-8"))
                return WindowExtraction.from_dict(d)
            except (json.JSONDecodeError, OSError):
                pass

    try:
        obj = client.chat_json(
            system=_WINDOW_SYSTEM_PROMPT,
            user=f"WINDOW ID: {window_id}\n\n{evidence_text}",
            temperature=0.0,
            max_tokens=max_tokens,
            response_format=WINDOW_EXTRACTION_RF,
            enable_thinking=False,   # extraction: fast, no chain-of-thought
        )
    except LMStudioError as e:
        log.error("window extraction failed", window_id=window_id, err=str(e)[:120])
        return WindowExtraction(window_id=window_id, severity=severity, family=family)

    ext = WindowExtraction(
        window_id=window_id,
        severity=severity,
        family=family,
        affected_services=[s for s in (obj.get("affected_services") or []) if isinstance(s, str)],
        components=[s for s in (obj.get("components") or []) if isinstance(s, str)],
        error_classes=[s for s in (obj.get("error_classes") or []) if isinstance(s, str)],
        symptoms=[s for s in (obj.get("symptoms") or []) if isinstance(s, str)],
    )

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(ext.as_dict(), indent=2), encoding="utf-8")
    return ext


def batch_extract_tickets(
    client: LMStudioClient,
    tickets: list[dict[str, Any]],
    *,
    cache_dir: Path,
    text_field: str = "memory_text",
    id_field: str = "ticket_id",
    severity_field: str = "severity_seen",
    timestamp_field: str = "source_episode_id",
    family_extractor=None,
    progress_every: int = 10,
) -> list[IncidentExtraction]:
    """Batch-extract from a list of tickets. Caches per-ticket. Logs
    progress every `progress_every` extractions.

    Args:
        client: LMStudioClient
        tickets: list of dicts (rows from a humanized timeline.jsonl)
        cache_dir: where to persist per-ticket extractions
        text_field: which key in each dict holds the ticket text
        id_field: which key in each dict holds the ticket id
        severity_field / timestamp_field: optional metadata fields
        family_extractor: optional function (ticket_dict) -> family str
    """
    if not client.is_available():
        raise RuntimeError(
            "LM Studio is not reachable at the configured URL. "
            "Start the LM Studio server and load a model first."
        )

    out: list[IncidentExtraction] = []
    n_cached = 0
    n_extracted = 0
    n_failed = 0

    with log_step(log, "batch_extract_tickets", n=len(tickets)):
        for i, t in enumerate(tickets, start=1):
            tid = t.get(id_field, f"unknown-{i}")
            text = t.get(text_field, "") or ""
            sev = t.get(severity_field, "") or ""
            ts = t.get(timestamp_field, "") or ""
            fam = family_extractor(t) if family_extractor else ""

            cf = cache_dir / "ticket" / f"{tid}__{_content_hash(text)}.json"
            was_cached = cf.exists()

            ext = extract_from_ticket(
                client,
                ticket_id=tid,
                ticket_text=text,
                severity=sev,
                family=fam,
                timestamp=ts,
                cache_dir=cache_dir,
            )

            if was_cached:
                n_cached += 1
            elif not ext.affected_services and not ext.error_classes and not ext.root_cause:
                n_failed += 1
            else:
                n_extracted += 1
            out.append(ext)

            if i % progress_every == 0:
                log.info(
                    "extraction progress",
                    done=i, total=len(tickets),
                    cached=n_cached, extracted=n_extracted, failed=n_failed,
                )

        log.info(
            "extraction complete",
            total=len(out), cached=n_cached, extracted=n_extracted, failed=n_failed,
        )
    return out
