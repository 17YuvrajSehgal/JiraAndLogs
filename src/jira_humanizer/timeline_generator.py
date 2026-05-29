"""Phase 2 generator — one LLM call produces one TimelineStep.

Currently implements the `report` step only. Phases 3+ add the rest of
the timeline by re-using the same prompt-building scaffolding with
different personas, evidence slices, and prior-conversation context.

Pipeline:
  1. Read the Loki dump for the (episode, service) at fault start.
  2. Pick K characteristic log lines (Phase-2 stub: take L1/L2 error
     lines first, then a sample of non-error lines).
  3. Build an evidence-summary the LLM will see, sanitized via the
     vocabulary firewall.
  4. Compose persona + symptom + evidence into a prompt.
  5. Call Qwen via LM Studio. Capture prompt hash for reproducibility.
  6. Return a TimelineStep.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make src/ importable so we can use the LM-Studio client from comparison/
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from comparison.retrievers import chat_via_lm_studio  # noqa: E402

from .personas import DEFAULT_PERSONA_FOR_STEP, avatar_for, persona_for
from .sanitizer import (
    SANITIZER_VERSION,
    assert_clean,
    find_lab_tokens,
)
from .symptom_map import SYMPTOM_MAP_VERSION, symptom_for
from .timeline_schema import EvidenceSlice, StepKind, TimelineStep


GENERATOR_VERSION = "v0.2.0-phase2-report-only"


# ---------------------------------------------------------------------------
# Characteristic-log-line extraction (Phase 2 stub)
# ---------------------------------------------------------------------------


# Loki dumps share schema with raw/loki/*.json — we read service_window
# only (per-service window slice) and ignore namespace_context (overlap).
def _load_loki_lines(loki_path: Path) -> list[str]:
    if not loki_path.exists():
        return []
    try:
        data = json.loads(loki_path.read_text(encoding="utf-8", errors="ignore"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    sub = data.get("service_window")
    if not isinstance(sub, dict):
        return []
    resp = sub.get("response") or {}
    result = (resp.get("data") or {}).get("result") or []
    lines: list[str] = []
    for stream in result:
        for value in stream.get("values") or []:
            # Each entry is [ts_nanos, raw_line_json_string].
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                lines.append(str(value[1]))
    return lines


# Lines that contain these markers are L2 dep_error / L1 RPC error logs
# — the high-signal ones for the reporter's first glance.
_ERROR_HINTS = re.compile(
    r"\b(error|failed|timeout|refused|unavailable|exception|panic|5\d\d)\b",
    re.IGNORECASE,
)


def _pick_characteristic_lines(
    lines: list[str],
    *,
    max_lines: int = 3,
    max_chars_per_line: int = 240,
) -> list[str]:
    """Phase 2 placeholder for ML-NEW-IDEAS.MD Move A.

    Naive policy: take the first K lines matching _ERROR_HINTS, then
    fall back to a sample of non-error lines if we don't have enough.
    Phase 3 will replace this with the proper TF-IDF-vs-baseline
    extractor.
    """
    error_lines: list[str] = []
    other_lines: list[str] = []
    for raw_line in lines:
        # Loki streams often store JSON-encoded log records. If we can
        # parse it, prefer the `message` field; else just truncate.
        text: str
        try:
            obj = json.loads(raw_line)
            if isinstance(obj, dict):
                text = (
                    obj.get("message")
                    or obj.get("msg")
                    or obj.get("body")
                    or json.dumps({k: v for k, v in obj.items() if k != "timestamp"})
                )
            else:
                text = raw_line
        except (json.JSONDecodeError, ValueError):
            text = raw_line
        text = text.strip()
        if not text:
            continue
        text = text[:max_chars_per_line]
        if _ERROR_HINTS.search(text):
            error_lines.append(text)
        else:
            other_lines.append(text)
    chosen = error_lines[:max_lines]
    while len(chosen) < max_lines and other_lines:
        chosen.append(other_lines.pop(0))
    return chosen


# ---------------------------------------------------------------------------
# Loki path helper
# ---------------------------------------------------------------------------


@dataclass
class WindowEvidenceInputs:
    """Where to find the raw telemetry for the window we're describing."""

    run_dir: Path                  # data/runs/<dataset_run_id>/
    window_id: str                 # e.g. "...active_fault-cartservice"
    service_name: str
    window_start_iso: str
    window_end_iso: str


def _loki_path_for(inputs: WindowEvidenceInputs) -> Path:
    return inputs.run_dir / "raw" / "loki" / f"{inputs.window_id}.json"


# ---------------------------------------------------------------------------
# Evidence slice builder (sanitized before reaching the LLM)
# ---------------------------------------------------------------------------


def build_report_evidence(inputs: WindowEvidenceInputs) -> EvidenceSlice:
    """Pull the top-K characteristic log lines for the reporter's view.

    At REPORT time the reporter has only seen the first ~30s of the
    fault, so we'd ideally clip to that. For Phase 2 we take the whole
    active_fault window — Phase 3 will introduce true time-clipping
    against the L1/L2 timestamps.
    """
    lines = _load_loki_lines(_loki_path_for(inputs))
    quotes = _pick_characteristic_lines(lines, max_lines=3, max_chars_per_line=220)
    return EvidenceSlice(
        log_quotes=quotes,
        metric_observations=[],   # filled in Phase 3 when we plumb metric snapshots
        k8s_observations=[],
        time_window_start=inputs.window_start_iso,
        time_window_end=inputs.window_end_iso,
    )


# ---------------------------------------------------------------------------
# Prompt construction (every byte goes through the sanitizer)
# ---------------------------------------------------------------------------


@dataclass
class ReportContext:
    """The information that flows into the `report` step prompt.

    NOTE: the `scenario_family` is used only to look up the symptom
    paraphrase. It is **never** put into the LLM prompt directly. The
    LLM sees the symptom, not the family name.
    """

    episode_id: str
    affected_service: str
    scenario_family: str     # lookup key only
    severity_seen: str       # the SYMPTOM severity, not eval-only label
    evidence: EvidenceSlice


def _format_log_quotes(quotes: list[str]) -> str:
    if not quotes:
        return "(none captured)"
    return "\n".join(f"  - {q}" for q in quotes)


def _build_report_prompt(ctx: ReportContext) -> tuple[str, str]:
    """Return (system, user) message strings, both sanitizer-checked."""
    persona = persona_for(DEFAULT_PERSONA_FOR_STEP[StepKind.REPORT])
    symptom = symptom_for(ctx.scenario_family, affected_service=ctx.affected_service)

    # NB: the system message must itself pass the sanitizer, so we
    # avoid naming the banned vocabulary here. Constraints are framed
    # positively ("write about symptoms") rather than negatively
    # ("don't say X"), which keeps the prompt clean *and* tends to
    # produce better LLM output anyway.
    system = (
        "You are writing a Jira ticket at a large e-commerce company. "
        f"Write as a {persona.role}: {persona.style_descriptor}\n\n"
        "Style rules:\n"
        f"- Target length: {persona.terseness}\n"
        "- You only know what end-users experience. You don't know the "
        "  internal cause yet.\n"
        "- Describe what users see and what you observed on dashboards.\n"
        "- Quote at most one specific log line that caught your eye, "
        "  in your own voice.\n"
        "- Write in the persona's natural register; do not include "
        "  Jira field labels."
    )
    # Sanitize the symptom phrases before composing — defence-in-depth.
    assert_clean(symptom.headline, context="symptom.headline")
    for hint in symptom.evidence_hints:
        assert_clean(hint, context="symptom.evidence_hint")
    assert_clean(symptom.severity_phrasing, context="symptom.severity_phrasing")
    assert_clean(symptom.reporter_framing, context="symptom.reporter_framing")

    # Evidence quotes: any lab vocabulary leaking from raw logs would be
    # bad. find_lab_tokens flags them; we keep the quote if clean,
    # otherwise we drop it silently. (Dropping is OK here — we have
    # other clean lines to fall back on.)
    safe_quotes = [q for q in ctx.evidence.log_quotes if not find_lab_tokens(q)]
    quotes_block = _format_log_quotes(safe_quotes)

    user = (
        f"What you observed:\n  {symptom.headline}\n\n"
        f"How urgent it feels: {symptom.severity_phrasing}\n"
        f"Your framing: {symptom.reporter_framing}\n\n"
        f"Log lines you (or the customer) sampled when filing:\n{quotes_block}\n\n"
        "Write the opening Jira ticket as this persona. Start with a one-line "
        "summary, then a short description paragraph. Do not include any field "
        "labels — write it as a person would type it into a ticket form."
    )

    assert_clean(system, context="report.system")
    assert_clean(user, context="report.user")
    return system, user


def _hash_prompt(system: str, user: str) -> str:
    h = hashlib.sha256()
    h.update(system.encode("utf-8"))
    h.update(b"\n---USER---\n")
    h.update(user.encode("utf-8"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Generator entrypoint
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:1234"
    model: str = "qwen/qwen2.5-coder-14b"
    temperature: float = 0.7
    max_tokens: int = 350
    timeout_s: float = 60.0


def generate_report_step(
    ctx: ReportContext,
    *,
    llm: LLMConfig | None = None,
) -> TimelineStep:
    """Run one LLM call to produce the `report` step. Raises on failure."""
    llm = llm or LLMConfig()
    system, user = _build_report_prompt(ctx)
    prompt_hash = _hash_prompt(system, user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    text = chat_via_lm_studio(
        llm.base_url, llm.model, messages,
        temperature=llm.temperature, max_tokens=llm.max_tokens,
        timeout=llm.timeout_s,
    )
    if not text or text.startswith("__ERROR__"):
        raise RuntimeError(
            f"LM Studio call failed for episode={ctx.episode_id}: "
            f"{text[:200] if text else 'empty response'}"
        )

    # Defence-in-depth: even if the LLM ignored our instructions, fail
    # loud rather than letting a leak into the corpus.
    leaks = find_lab_tokens(text)
    if leaks:
        raise RuntimeError(
            f"LLM output contained lab-leakage tokens {leaks[:4]} for "
            f"episode={ctx.episode_id}. Refusing to ship; tighten the prompt."
        )

    persona_role = DEFAULT_PERSONA_FOR_STEP[StepKind.REPORT]
    avatar = avatar_for(persona_role, ctx.episode_id, salt="report")
    return TimelineStep(
        step_kind=StepKind.REPORT,
        persona_role=persona_role,
        persona_avatar=avatar,
        t_offset_s=0,
        context_window_s=30,
        evidence=ctx.evidence,
        text=text.strip(),
        prompt_hash=prompt_hash,
    )


# ---------------------------------------------------------------------------
# Versioning surface used by the driver to stamp manifests
# ---------------------------------------------------------------------------


def stamp_versions() -> dict[str, Any]:
    return {
        "generator_version": GENERATOR_VERSION,
        "sanitizer_version": SANITIZER_VERSION,
        "symptom_map_version": SYMPTOM_MAP_VERSION,
    }
