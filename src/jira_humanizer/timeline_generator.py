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


GENERATOR_VERSION = "v0.3.0-phase3-full-timeline"


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
# Phase 3 — ack / hypothesis / redirect / resolve step prompts +
#          misattribution sampler + full-timeline orchestrator
# ---------------------------------------------------------------------------


# Per LLM-Jira-enhancement.md §3 Rule 3, 10–15% of tickets carry a
# misattributed components_seen — early steps frame the issue as the
# wrong service's problem and the redirect step explicitly corrects it.
MISATTRIBUTION_RATE = 0.15


@dataclass
class MisattributionPlan:
    """Decision + content for Rule 3 misattribution on one ticket.

    `wrong_service` is the service the reporter blames first. It is
    chosen from the symptom-side services (downstream of the actual
    root cause) so the misframing is plausible.

    `correct_service` is the actual root-cause service (= window.service_name).
    `enabled=False` → no misattribution; redirect step is skipped.
    """

    enabled: bool
    wrong_service: str = ""
    correct_service: str = ""


def _is_misattributed(episode_id: str) -> bool:
    """Deterministic per-episode sampler — same episode_id, same decision
    across re-runs. Uses a different seed namespace from avatar_for so
    persona avatars and misattribution decisions are independent."""
    h = int(hashlib.sha256(f"misattr::{episode_id}".encode("utf-8")).hexdigest()[:8], 16)
    return (h / 0xFFFFFFFF) < MISATTRIBUTION_RATE


def plan_misattribution(
    episode_id: str,
    correct_service: str,
    candidate_downstream_services: list[str],
) -> MisattributionPlan:
    """Decide whether this ticket is misattributed and, if so, which
    service the reporter incorrectly blames.

    `candidate_downstream_services` is the legacy shadow's
    affected_services list (or any superset of the symptom-side
    services). We pick deterministically from those, excluding the
    correct service. If no plausible downstream is available the plan
    is forced disabled (no point misattributing without an alternative).
    """
    if not _is_misattributed(episode_id):
        return MisattributionPlan(enabled=False)
    pool = [s for s in candidate_downstream_services
            if s and s != correct_service]
    if not pool:
        return MisattributionPlan(enabled=False)
    # Pick deterministically from the pool using a separate salt so
    # multiple downstream services get fair coverage across the corpus.
    h = int(hashlib.sha256(f"misattr-pick::{episode_id}".encode("utf-8")).hexdigest()[:8], 16)
    wrong = pool[h % len(pool)]
    return MisattributionPlan(
        enabled=True,
        wrong_service=wrong,
        correct_service=correct_service,
    )


def _format_prior_thread(prior: list[TimelineStep], max_chars_per_step: int = 600) -> str:
    """Render the prior steps as a thread the LLM can see. We keep this
    short (~600 chars per step) so longer timelines don't blow past the
    model's context window."""
    if not prior:
        return "(this is the first message on the ticket)"
    lines: list[str] = []
    for step in prior:
        text = (step.text or "").strip()
        if len(text) > max_chars_per_step:
            text = text[:max_chars_per_step] + "..."
        lines.append(f"[{step.persona_avatar} ({step.persona_role})]:\n{text}\n")
    return "\n".join(lines)


def _build_followup_prompt(
    *,
    step_kind: str,
    persona_role: str,
    ctx: ReportContext,
    prior: list[TimelineStep],
    misattr: MisattributionPlan,
) -> tuple[str, str]:
    """Shared prompt scaffold for ack / hypothesis / redirect / resolve.

    Differences between steps are encoded in the system message
    (persona + step-specific guidance) and in the user message
    (step-specific framing of "what you're contributing"). Same
    sanitizer guardrails apply.
    """
    persona = persona_for(persona_role)
    symptom = symptom_for(ctx.scenario_family, affected_service=ctx.affected_service)

    step_guidance = _STEP_GUIDANCE[step_kind]
    system = (
        f"You are continuing a Jira ticket at a large e-commerce company. "
        f"Write as a {persona.role}: {persona.style_descriptor}\n\n"
        "Style rules:\n"
        f"- Target length: {persona.terseness}\n"
        "- Stay in your persona's natural register — no Jira field labels.\n"
        "- Refer to the previous messages as if you've just read them.\n"
        f"- {step_guidance}\n"
        "- Describe symptoms and observations; do not state a definitive "
        "  internal cause unless you are the resolver and you have enough "
        "  evidence in the thread to justify it."
    )
    assert_clean(system, context=f"{step_kind}.system")

    # Misattribution framing — only the reporter and early commenters
    # carry the wrong-service language; the redirect step corrects it.
    misattr_block = ""
    if misattr.enabled:
        if step_kind in (StepKind.ACK, StepKind.HYPOTHESIS):
            misattr_block = (
                f"\nNote: when you reference the affected service, you "
                f"believe it's {misattr.wrong_service} based on where the "
                f"errors are visible. Don't say you've ruled anything else "
                f"out — you haven't looked upstream yet.\n"
            )
        elif step_kind == StepKind.REDIRECT:
            misattr_block = (
                f"\nNote: earlier comments suspect {misattr.wrong_service}, "
                f"but looking at the call chain, the upstream "
                f"{misattr.correct_service} is showing the actual error "
                f"signature. Politely redirect attention there with a "
                f"specific reason (the metrics or logs that point to it).\n"
            )
        else:
            misattr_block = ""

    prior_thread = _format_prior_thread(prior)
    safe_quotes = [q for q in ctx.evidence.log_quotes if not find_lab_tokens(q)]
    quotes_block = _format_log_quotes(safe_quotes)

    user = (
        f"Symptom the reporter logged: {symptom.headline}\n"
        f"Urgency framing: {symptom.severity_phrasing}\n\n"
        f"Log lines available to anyone investigating:\n{quotes_block}\n"
        f"{misattr_block}\n"
        f"Prior thread:\n{prior_thread}\n\n"
        f"Now write your contribution as {persona_role}. Just the comment "
        f"body, in your voice."
    )
    assert_clean(user, context=f"{step_kind}.user")
    return system, user


# Per-step instructions that ride along in the system prompt. Phrased
# positively so the sanitizer accepts them.
_STEP_GUIDANCE: dict[str, str] = {
    StepKind.ACK: (
        "Acknowledge the page in pager-speak: two or three short lines. "
        "State what dashboard or metric you're checking next."
    ),
    StepKind.HYPOTHESIS: (
        "Offer a hypothesis grounded in the log lines or metrics you've "
        "seen. Hedge appropriately. If you suspect a specific component, "
        "say so and explain what you'd check to confirm."
    ),
    StepKind.REDIRECT: (
        "You've looked at the metrics for the previously-suspected "
        "service and they look healthier than expected. Suggest "
        "checking the upstream dependency, naming exactly which one "
        "and the signal that pointed you there."
    ),
    StepKind.RESOLVE: (
        "Close the ticket. State what was done (deploy rolled back, "
        "config changed, restart, etc.) or note 'self-resolved, "
        "monitoring' if there's no clear root cause. One or two "
        "sentences max."
    ),
}


def _generate_followup_step(
    *,
    step_kind: str,
    persona_role: str,
    avatar_salt: str,
    t_offset_s: int,
    context_window_s: int,
    ctx: ReportContext,
    prior: list[TimelineStep],
    misattr: MisattributionPlan,
    llm: LLMConfig,
) -> TimelineStep:
    """Single-step LLM call for any of the follow-up step kinds."""
    system, user = _build_followup_prompt(
        step_kind=step_kind,
        persona_role=persona_role,
        ctx=ctx,
        prior=prior,
        misattr=misattr,
    )
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
            f"LM Studio call failed at step={step_kind} for "
            f"episode={ctx.episode_id}: "
            f"{text[:200] if text else 'empty response'}"
        )
    leaks = find_lab_tokens(text)
    if leaks:
        raise RuntimeError(
            f"LLM output at step={step_kind} contained lab-leakage tokens "
            f"{leaks[:4]} for episode={ctx.episode_id}. Refusing to ship."
        )
    avatar = avatar_for(persona_role, ctx.episode_id, salt=avatar_salt)
    return TimelineStep(
        step_kind=step_kind,
        persona_role=persona_role,
        persona_avatar=avatar,
        t_offset_s=t_offset_s,
        context_window_s=context_window_s,
        # Follow-up steps see the same baseline evidence in Phase 3;
        # Phase 4 will introduce time-clipped per-step evidence slices.
        evidence=ctx.evidence,
        text=text.strip(),
        prompt_hash=prompt_hash,
    )


# Step-kind -> (persona_role, avatar_salt, t_offset_s, context_window_s).
# `hypothesis` rotates among backend / frontend / junior to vary voices
# across tickets; we pick deterministically on the episode_id below.
_HYPOTHESIS_PERSONAS: tuple[str, ...] = (
    "backend-eng",
    "frontend-eng",
    "junior-eng",
)


def _pick_hypothesis_persona(episode_id: str) -> str:
    h = int(hashlib.sha256(f"hypo-role::{episode_id}".encode("utf-8")).hexdigest()[:8], 16)
    return _HYPOTHESIS_PERSONAS[h % len(_HYPOTHESIS_PERSONAS)]


@dataclass
class FullTimelineInputs:
    """Bundles everything generate_full_timeline needs.

    Kept separate from ReportContext so a caller assembling a ticket
    doesn't need to know about misattribution mechanics — the
    generator decides per episode.
    """

    window_row: dict[str, Any]
    inputs: WindowEvidenceInputs
    severity_seen: str
    candidate_downstream_services: list[str]


def generate_full_timeline(
    bundle: FullTimelineInputs,
    *,
    llm: LLMConfig | None = None,
) -> "TicketTimeline":
    """Generate report -> ack -> hypothesis -> [redirect] -> resolve.

    `redirect` is emitted only when misattribution was sampled — that's
    the whole point of the step: correct the wrong attribution. When
    misattribution is disabled the ticket goes report -> ack ->
    hypothesis -> resolve.

    Returns a complete TicketTimeline ready to write to timeline.jsonl.
    """
    from .timeline_schema import TicketTimeline  # local import to avoid cycle

    llm = llm or LLMConfig()
    row = bundle.window_row
    episode_id = row["incident_episode_id"]
    correct_service = row["service_name"]

    misattr = plan_misattribution(
        episode_id=episode_id,
        correct_service=correct_service,
        candidate_downstream_services=bundle.candidate_downstream_services,
    )

    # The reporter "sees" the misattributed service if misattribution
    # was sampled — that's the whole point of Rule 3. Otherwise they
    # see the actual affected service.
    reporter_service = misattr.wrong_service if misattr.enabled else correct_service
    components_seen = (
        [misattr.wrong_service] if misattr.enabled else [correct_service]
    )

    evidence = build_report_evidence(bundle.inputs)
    ctx = ReportContext(
        episode_id=episode_id,
        affected_service=reporter_service,
        scenario_family=row["scenario_family"],
        severity_seen=bundle.severity_seen,
        evidence=evidence,
    )

    # 1. REPORT — reuses the existing Phase 2 generator. The Phase 2
    #    prompt is symptom-driven so the misattribution flows through
    #    via reporter_service in ctx.
    report_step = generate_report_step(ctx, llm=llm)
    steps: list[TimelineStep] = [report_step]

    # 2. ACK
    ack_step = _generate_followup_step(
        step_kind=StepKind.ACK,
        persona_role="oncall-sre",
        avatar_salt="ack",
        t_offset_s=180,
        context_window_s=180,
        ctx=ctx,
        prior=steps,
        misattr=misattr,
        llm=llm,
    )
    steps.append(ack_step)

    # 3. HYPOTHESIS — pick a persona that varies per episode.
    hypothesis_role = _pick_hypothesis_persona(episode_id)
    hypothesis_step = _generate_followup_step(
        step_kind=StepKind.HYPOTHESIS,
        persona_role=hypothesis_role,
        avatar_salt="hyp",
        t_offset_s=420,
        context_window_s=300,
        ctx=ctx,
        prior=steps,
        misattr=misattr,
        llm=llm,
    )
    steps.append(hypothesis_step)

    # 4. REDIRECT — only when misattribution was sampled. When
    #    misattribution=False, an explicit redirect step would feel
    #    forced (nothing to redirect from). Skip it cleanly.
    if misattr.enabled:
        redirect_step = _generate_followup_step(
            step_kind=StepKind.REDIRECT,
            persona_role="senior-sre",
            avatar_salt="redir",
            t_offset_s=900,
            context_window_s=900,
            ctx=ctx,
            prior=steps,
            misattr=misattr,
            llm=llm,
        )
        steps.append(redirect_step)

    # 5. RESOLVE
    resolve_step = _generate_followup_step(
        step_kind=StepKind.RESOLVE,
        persona_role="fix-author",
        avatar_salt="resolve",
        t_offset_s=1800,
        context_window_s=1800,
        ctx=ctx,
        prior=steps,
        misattr=misattr,
        llm=llm,
    )
    steps.append(resolve_step)

    versions = stamp_versions()
    return TicketTimeline(
        ticket_id=f"HMN-{episode_id}",
        source_episode_id=episode_id,
        source_dataset_run_id=row["dataset_run_id"],
        affected_services_seen=[reporter_service],
        severity_seen=bundle.severity_seen,
        components_seen=components_seen,
        is_misattributed=misattr.enabled,
        closed_as_noise=False,   # Phase 4 introduces Rule 5
        steps=steps,
        **versions,
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
