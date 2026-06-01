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

import time
import urllib.error
import urllib.request

from .evidence_bundle import EvidenceBundle, build_evidence, slice_for_step
from .personas import DEFAULT_PERSONA_FOR_STEP, avatar_for, persona_for
from .sanitizer import (
    SANITIZER_VERSION,
    assert_clean,
    find_lab_tokens,
)
from .symptom_map import SYMPTOM_MAP_VERSION, symptom_for
from .timeline_schema import (
    DESCRIPTION_MAX_CHARS,
    EvidenceSlice,
    StepKind,
    TimelineStep,
)


# V2 step 3 — multi-channel evidence + severity-weighted reporter
# + variable comment count + resolution outcome sampling per §13.1.
GENERATOR_VERSION = "v2.1.0-step3-variable-thread-and-resolution"


# ---------------------------------------------------------------------------
# LM Studio client with usage tracking — local to the humanizer so we can
# capture per-call token counts for the research-findings manifest.
# (comparison.retrievers.chat_via_lm_studio discards `usage`; we don't want
# to change its signature because it has other callers.)
# ---------------------------------------------------------------------------


@dataclass
class UsageStats:
    """Cumulative token / call counters for one generation run."""
    n_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_errors: int = 0
    n_leak_rejections: int = 0
    wall_time_s: float = 0.0

    def add(self, prompt_t: int, completion_t: int, elapsed_s: float) -> None:
        self.n_calls += 1
        self.prompt_tokens += int(prompt_t or 0)
        self.completion_tokens += int(completion_t or 0)
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.wall_time_s += float(elapsed_s or 0.0)

    def as_dict(self) -> dict[str, Any]:
        n = max(1, self.n_calls)
        return {
            "n_calls": self.n_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "n_errors": self.n_errors,
            "n_leak_rejections": self.n_leak_rejections,
            "wall_time_s": round(self.wall_time_s, 2),
            "avg_prompt_tokens_per_call": round(self.prompt_tokens / n, 1),
            "avg_completion_tokens_per_call": round(self.completion_tokens / n, 1),
            "avg_wall_time_per_call_s": round(self.wall_time_s / n, 3),
        }


_USAGE_TRACKER = UsageStats()


def get_usage_stats() -> UsageStats:
    return _USAGE_TRACKER


def reset_usage_stats() -> None:
    """Call at the top of each generation run to start fresh counters."""
    global _USAGE_TRACKER
    _USAGE_TRACKER = UsageStats()


def _chat_with_usage(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    """LM Studio chat call that captures `usage` into _USAGE_TRACKER."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.URLError as e:
        _USAGE_TRACKER.n_errors += 1
        return f"__ERROR__ {e}"
    elapsed = time.time() - t0
    usage = data.get("usage") or {}
    _USAGE_TRACKER.add(
        prompt_t=usage.get("prompt_tokens", 0),
        completion_t=usage.get("completion_tokens", 0),
        elapsed_s=elapsed,
    )
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


# ---------------------------------------------------------------------------
# Per-persona output budget — strict char/token caps to keep V2 tickets
# close to the TAWOS-empirical median (200-500 chars) instead of V1's
# 1500-3000 char paragraphs. Token caps are aggressive on purpose: the
# LLM cuts off mid-thought, which itself looks engineer-realistic.
# ---------------------------------------------------------------------------


# ~4 chars/token for English. Char cap is what we put in the prompt as a
# soft target; max_tokens is the hard server-side ceiling.
_MAX_TOKENS_BY_PERSONA: dict[str, int] = {
    "cs-agent":    150,   # report:    ~600 chars (summary + short paragraph)
    "oncall-sre":   80,   # ack:       ~320 chars (pager-speak)
    "junior-eng":  220,   # hypothesis: ~880 chars (verbose by design, still capped)
    "frontend-eng": 180,  # hypothesis: ~720 chars
    "backend-eng":  180,  # hypothesis: ~720 chars
    "senior-sre":  140,   # redirect:   ~560 chars
    "eng-mgr":      40,   # nudge:      ~160 chars
    "db-team":     100,   # targeted:   ~400 chars
    "fix-author":   90,   # resolve:    ~360 chars (short close note)
}


def _max_tokens_for(persona_role: str, default: int) -> int:
    return _MAX_TOKENS_BY_PERSONA.get(persona_role, default)


def _char_cap_for(persona_role: str) -> int:
    return _max_tokens_for(persona_role, default=180) * 4


# ---------------------------------------------------------------------------
# Severity-weighted reporter persona (LLM-Jira-enhancement.md §11 Q1)
#
# Real ratio: critical incidents are usually paged to on-call BEFORE
# customer-support sees customer complaints; minor degradations usually
# come in via CS forwards. Picking per-episode by severity gives the
# corpus a realistic mix of "engineer-first" and "customer-first" report
# voices instead of every report sounding identical (cs-agent only,
# which is the V1 problem we're fixing).
#
# Deterministic per episode_id so re-runs are stable.
# ---------------------------------------------------------------------------


_REPORTER_PROBS_BY_SEVERITY: dict[str, dict[str, float]] = {
    "high":   {"oncall-sre": 0.70, "cs-agent": 0.30},
    "medium": {"oncall-sre": 0.50, "cs-agent": 0.50},
    "low":    {"oncall-sre": 0.20, "cs-agent": 0.80},
}
_REPORTER_DEFAULT: dict[str, float] = {"oncall-sre": 0.50, "cs-agent": 0.50}


def _pick_report_persona(episode_id: str, severity_seen: str) -> str:
    """Pick the reporter persona for `report` step given severity.

    Returns one of "oncall-sre" or "cs-agent". Deterministic per
    episode_id — the same episode always gets the same reporter across
    re-runs.
    """
    probs = _REPORTER_PROBS_BY_SEVERITY.get(
        (severity_seen or "").lower(), _REPORTER_DEFAULT,
    )
    h = int(hashlib.sha256(
        f"reporter::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    threshold = h / 0xFFFFFFFF
    cumulative = 0.0
    for role, p in probs.items():
        cumulative += p
        if threshold < cumulative:
            return role
    # Fallback — shouldn't happen but covers float-rounding edge cases.
    return next(iter(probs))


# ---------------------------------------------------------------------------
# Output-format rules — kept as a shared snippet so report and followup
# prompts enforce the same hygiene. Negative examples are deliberate:
# Qwen ignores positive-only instructions for sign-offs and field
# labels (observed in step 1 smoke). Explicit "do NOT write X" with
# the exact strings the model defaults to is what actually works.
# ---------------------------------------------------------------------------


_OUTPUT_FORMAT_RULES = (
    "Output format rules (these are strict):\n"
    "- Do NOT prefix with 'Summary:' or 'Description:' field labels. "
    "Just write the body.\n"
    "- Do NOT start with greetings like 'Hi team', 'Hey team', 'Hello', or 'Thanks'.\n"
    "- Do NOT end with sign-offs like 'Thanks,', '[Your Name]', "
    "'Best,', or 'Regards'.\n"
    "- Do NOT use markdown headers (no ###, no **bold**) for section dividers.\n"
    "- Write as if typing directly into a Jira comment box mid-incident — "
    "no preamble, no farewells."
)


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
# V2 multi-channel evidence (§13.12) — slice the bundle per persona-step
# and format it into the user-prompt evidence block.
# ---------------------------------------------------------------------------


# Personas with backend access that naturally paste raw log lines into
# their comments. cs-agent / eng-mgr / junior-eng don't, per §13.3 rule 4.
_LOG_PASTING_PERSONAS: frozenset[str] = frozenset({
    "oncall-sre", "backend-eng", "senior-sre", "fix-author", "db-team",
})


def _slice_bundle_to_evidence(
    bundle: EvidenceBundle,
    step_kind: str,
    *,
    time_window_start: str = "",
    time_window_end: str = "",
) -> EvidenceSlice:
    """Project the bundle through slice_for_step and convert to the
    persisted EvidenceSlice shape (lists of strings)."""
    sliced = slice_for_step(bundle, step_kind)
    trace_obs: list[str] = []
    ts = sliced.get("trace_summary")
    if ts:
        p95 = ts.get("trace_latency_p95_ms")
        if p95 is not None:
            trace_obs.append(f"trace p95 {float(p95):.0f}ms")
        p50 = ts.get("trace_latency_p50_ms")
        if p50 is not None:
            trace_obs.append(f"trace p50 {float(p50):.0f}ms")
        err_rate = ts.get("trace_error_rate")
        if err_rate is not None and float(err_rate) > 0:
            trace_obs.append(f"trace error rate {float(err_rate) * 100:.1f}%")
        cnt = ts.get("trace_count")
        ec = ts.get("trace_error_count")
        if cnt is not None and ec is not None:
            trace_obs.append(f"{int(ec)}/{int(cnt)} traces errored")

    k8s_obs: list[str] = []
    ks = sliced.get("k8s_state")
    if ks:
        for key in ("k8s_restart_count", "k8s_warning_event_count",
                    "k8s_pod_unavailable_count"):
            v = ks.get(key)
            if v:
                short = key.replace("k8s_", "")
                k8s_obs.append(f"{short}={int(v)}")

    return EvidenceSlice(
        log_quotes=list(sliced.get("log_lines", [])),
        metric_observations=list(sliced.get("metric_observations", [])),
        k8s_observations=k8s_obs,
        trace_observations=trace_obs,
        alert_names=list(sliced.get("alert_names", [])),
        trace_id_quoted=sliced.get("trace_id_quoted"),
        symptom_phrase=sliced.get("symptom_phrase", ""),
        time_window_start=time_window_start,
        time_window_end=time_window_end,
    )


def _format_evidence_block(evidence: EvidenceSlice) -> str:
    """Render the multi-channel evidence as it appears in the LLM prompt.

    Each channel becomes a labelled section. Empty channels are
    omitted entirely so a cs-agent's prompt isn't padded with "(none)"
    placeholders that confuse the model.
    """
    parts: list[str] = []
    if evidence.alert_names:
        parts.append("Alerts firing right now:")
        for a in evidence.alert_names:
            parts.append(f"  - {a}")
        parts.append("")
    if evidence.metric_observations:
        parts.append("Metric observations (vs baseline):")
        for m in evidence.metric_observations:
            parts.append(f"  - {m}")
        parts.append("")
    if evidence.trace_observations:
        parts.append("Trace summary:")
        for t in evidence.trace_observations:
            parts.append(f"  - {t}")
        parts.append("")
    if evidence.k8s_observations:
        parts.append("K8s state:")
        for k in evidence.k8s_observations:
            parts.append(f"  - {k}")
        parts.append("")
    if evidence.log_quotes:
        parts.append("Log lines you can see:")
        for q in evidence.log_quotes:
            parts.append(f"  - {q}")
        parts.append("")
    if evidence.trace_id_quoted:
        parts.append(f"Trace ID you can reference: {evidence.trace_id_quoted}")
        parts.append("")
    if not parts:
        return "(no telemetry available to you at this moment)"
    return "\n".join(parts).rstrip()


def _hash_evidence_bundle(bundle: EvidenceBundle) -> str:
    """Stable 16-char hash of the canonical bundle for reproducibility."""
    canonical = json.dumps(
        {
            "log_lines": bundle.log_lines,
            "log_lines_source": bundle.log_lines_source,
            "log_lines_service": bundle.log_lines_service,
            "metric_observations": bundle.metric_observations,
            "trace_summary": bundle.trace_summary,
            "k8s_state": bundle.k8s_state,
            "alert_names": bundle.alert_names,
            "symptom_phrase": bundle.symptom_phrase,
            "trace_id_quoted": bundle.trace_id_quoted,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _lookup_shadow_record(
    run_dir: Path, episode_id: str,
) -> dict[str, Any] | None:
    """Find the per-run shadow record for an episode_id.

    Used to surface a quotable trace_id for engineer-personas. Returns
    None when no matching row exists (e.g. orphan episodes that don't
    produce a shadow ticket).
    """
    p = run_dir / "jira_shadow_issues.jsonl"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("incident_episode_id") == episode_id:
                return rec
    return None


# Soft cleanup applied to LLM output BEFORE the hard sanitizer check.
# Qwen (and probably any LLM trained on real SRE postmortems) reaches
# for specific incident-vocabulary terms even when we explicitly steer
# it away. These are the empirical offenders from the v2 bulk run:
# bulk-20260531 had 11 leak-rejections, all due to `near-miss` (10) or
# standalone `fault` (1). Rejecting the whole ticket loses data — better
# to swap the offending word for a clean synonym and let the rest of
# the LLM's output through. The sanitizer's hard reject still runs
# AFTER this so anything we miss still fails loud.
#
# Word-boundary matching with re.IGNORECASE — `default` / `faulty` etc.
# stay untouched (they're real words, not lab-vocabulary).
_PRE_SANITIZER_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Order: longest match first (so "fault tolerance" wins over "fault").
    ("near-miss", "transient blip"),
    ("nearmiss", "transient blip"),
    ("fault tolerance", "resilience"),
    ("fault injection", "controlled test"),
    ("fault", "issue"),  # standalone word only (boundary regex below)
)


def _redact_lab_tokens(text: str) -> str:
    """Replace LLM-emitted SRE jargon with clean synonyms BEFORE the
    sanitizer's hard reject. Defence-in-depth, not a replacement for
    the firewall — `find_lab_tokens` still runs after this."""
    out = text
    for bad, good in _PRE_SANITIZER_REPLACEMENTS:
        pattern = re.compile(rf"\b{re.escape(bad)}\b", re.IGNORECASE)
        out = pattern.sub(good, out)
    return out


def _body_code_for_step(persona_role: str, evidence: EvidenceSlice) -> str | None:
    """Per §13.3 rule 4: backend-access personas paste raw log lines
    alongside their prose; cs-agent / eng-mgr / junior-eng don't.

    Returns the log lines (newline-joined) the persona would paste,
    or None if this persona doesn't naturally paste or no lines are
    available for this step's slice.
    """
    if persona_role not in _LOG_PASTING_PERSONAS:
        return None
    if not evidence.log_quotes:
        return None
    return "\n".join(evidence.log_quotes)


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
    """Legacy single-channel formatter. Retained for callers that pass a
    bare quote list. V2 generation goes through `_format_evidence_block`."""
    if not quotes:
        return "(none captured)"
    return "\n".join(f"  - {q}" for q in quotes)


def _build_report_prompt(
    ctx: ReportContext,
    *,
    persona_role: str = "cs-agent",
) -> tuple[str, str]:
    """Return (system, user) message strings, both sanitizer-checked.

    V2 + Step 2: persona-aware. `cs-agent` writes customer-forward
    voice (no telemetry, paraphrased customer words). `oncall-sre`
    writes pager-speak (paged by the alert, references alert name +
    one log/metric). Severity-weighted selection happens in
    `generate_full_timeline` via `_pick_report_persona`.
    """
    persona = persona_for(persona_role)
    symptom = symptom_for(ctx.scenario_family, affected_service=ctx.affected_service)
    char_cap = _char_cap_for(persona.role)

    # Persona-specific framing — the cs-agent and oncall-sre voices
    # diverge sharply, so a single shared block dilutes both. Keep them
    # explicit. Constraints are framed positively; negative examples
    # are in the shared _OUTPUT_FORMAT_RULES block.
    if persona_role == "oncall-sre":
        persona_block = (
            "You were paged by an automated alert. Open the ticket from the "
            "on-call seat: lowercase ok, abbreviations ok, terse. State which "
            "alert(s) paged you and what metric/log confirmed it. Don't "
            "speculate on root cause yet — that's for the hypothesis step."
        )
    else:
        persona_block = (
            "You're a customer-support agent forwarding what a customer just "
            "told you. Paste the customer's symptom in their own words. You "
            "don't have telemetry access. Don't try to diagnose anything — "
            "the engineering team will."
        )

    system = (
        "You are writing a Jira ticket at a large e-commerce company. "
        f"Write as a {persona.role}: {persona.style_descriptor}\n\n"
        f"{persona_block}\n\n"
        "Style rules:\n"
        f"- HARD LENGTH LIMIT: keep total output under {char_cap} characters. "
        f"Aim for {persona.terseness}. Going over is worse than stopping early.\n"
        "- TAWOS-realistic engineer ticket median is 200-500 chars. Match that.\n\n"
        f"{_OUTPUT_FORMAT_RULES}"
    )

    # Sanitize the symptom phrases before composing — defence-in-depth.
    assert_clean(symptom.headline, context="symptom.headline")
    for hint in symptom.evidence_hints:
        assert_clean(hint, context="symptom.evidence_hint")
    assert_clean(symptom.severity_phrasing, context="symptom.severity_phrasing")
    assert_clean(symptom.reporter_framing, context="symptom.reporter_framing")

    # V2: multi-channel evidence block. _strip_unsafe on the bundle
    # has already dropped any leaker, so this just formats the
    # surviving channels for the persona-step.
    evidence_block = _format_evidence_block(ctx.evidence)

    user = (
        f"What you observed:\n  {symptom.headline}\n\n"
        f"How urgent it feels: {symptom.severity_phrasing}\n"
        f"Your framing: {symptom.reporter_framing}\n\n"
        f"Evidence available to you:\n{evidence_block}\n\n"
        "Write the opening Jira ticket. Start with a one-line summary on its "
        "own line, then a short body paragraph — that's it."
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
    persona_role: str | None = None,
) -> TimelineStep:
    """Run one LLM call to produce the `report` step. Raises on failure.

    `persona_role` defaults to the catalog's report persona (cs-agent).
    Step 2 callers pass `oncall-sre` for severity-weighted picks where
    the engineer was paged before the customer-support team saw it.
    """
    llm = llm or LLMConfig()
    persona_role_for_report = persona_role or DEFAULT_PERSONA_FOR_STEP[StepKind.REPORT]
    system, user = _build_report_prompt(ctx, persona_role=persona_role_for_report)
    prompt_hash = _hash_prompt(system, user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    text = _chat_with_usage(
        llm.base_url, llm.model, messages,
        temperature=llm.temperature,
        max_tokens=_max_tokens_for(persona_role_for_report, default=llm.max_tokens),
        timeout=llm.timeout_s,
    )
    if not text or text.startswith("__ERROR__"):
        raise RuntimeError(
            f"LM Studio call failed for episode={ctx.episode_id}: "
            f"{text[:200] if text else 'empty response'}"
        )

    # Soft cleanup: swap known SRE-jargon offenders for clean synonyms.
    # Sanitizer's hard reject still runs after — only catches what
    # this layer misses.
    text = _redact_lab_tokens(text)

    # Defence-in-depth: even if the LLM ignored our instructions, fail
    # loud rather than letting a leak into the corpus.
    leaks = find_lab_tokens(text)
    if leaks:
        _USAGE_TRACKER.n_leak_rejections += 1
        raise RuntimeError(
            f"LLM output contained lab-leakage tokens {leaks[:4]} for "
            f"episode={ctx.episode_id}. Refusing to ship; tighten the prompt."
        )

    avatar = avatar_for(persona_role_for_report, ctx.episode_id, salt="report")
    return TimelineStep(
        step_kind=StepKind.REPORT,
        persona_role=persona_role_for_report,
        persona_avatar=avatar,
        t_offset_s=0,
        context_window_s=30,
        evidence=ctx.evidence,
        text=text.strip(),
        body_code=_body_code_for_step(persona_role_for_report, ctx.evidence),
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


# ---------------------------------------------------------------------------
# Phase 4 — wrong-hypothesis injection (independent of misattribution)
# ---------------------------------------------------------------------------


WRONG_HYPOTHESIS_RATE = 0.15

# Family-agnostic pool of plausible-sounding but wrong technical theories.
# Each is a complete sentence the hypothesis persona can claim. The list
# is intentionally diverse so different episodes get different wrong
# theories — a model that learns "any wrong theory = redirect" would
# otherwise collapse to memorizing one phrase.
#
# Sanitizer-audited via the smoke test below; if you add an entry, the
# audit will catch a banned token immediately.
_WRONG_HYPOTHESIS_POOL: tuple[str, ...] = (
    "the load balancer in front of the service",
    "the recent config rollout from yesterday",
    "DNS resolution slowdowns inside the cluster",
    "the rate limiter firing on bursty traffic",
    "a memory-pressure spike on the host node",
    "the service-mesh sidecar dropping connections",
    "the auth token cache being stale",
    "a slow upstream from the metrics exporter",
)


@dataclass
class WrongHypothesisPlan:
    """Decision + content for Rule "wrong-hypothesis" on one ticket.

    Independent of MisattributionPlan: misattribution is about which
    *service* gets blamed (components_seen). WrongHypothesisPlan is
    about a wrong *technical theory* that the thread proposes — even
    on the right service. They can co-occur.

    `enabled=False` → hypothesis step runs normally (data-driven from
    log evidence). When True, the hypothesis step is steered toward
    `wrong_theory`, and the redirect step is emitted to correct it
    (independently of whether misattribution also triggered it).
    """

    enabled: bool
    wrong_theory: str = ""


def _samples_wrong_hypothesis(episode_id: str) -> bool:
    h = int(
        hashlib.sha256(f"wronghyp::{episode_id}".encode("utf-8")).hexdigest()[:8],
        16,
    )
    return (h / 0xFFFFFFFF) < WRONG_HYPOTHESIS_RATE


def plan_wrong_hypothesis(episode_id: str) -> WrongHypothesisPlan:
    """Sample whether this ticket gets a wrong-hypothesis arc and, if so,
    which theory the hypothesizer takes a wrong turn on.

    Deterministic per episode_id; separate seed namespace from
    misattribution so a ticket can have both, neither, or one.
    """
    if not _samples_wrong_hypothesis(episode_id):
        return WrongHypothesisPlan(enabled=False)
    h = int(
        hashlib.sha256(f"wronghyp-pick::{episode_id}".encode("utf-8")).hexdigest()[:8],
        16,
    )
    return WrongHypothesisPlan(
        enabled=True,
        wrong_theory=_WRONG_HYPOTHESIS_POOL[h % len(_WRONG_HYPOTHESIS_POOL)],
    )


# ---------------------------------------------------------------------------
# Step 3 — Resolution outcome + resolution_time + variable comment count
# samplers, all per LLM-Jira-enhancement.md §13.1 TAWOS-empirical
# distributions. Replaces the V1/Phase-4 closure-rate-by-label scheme.
# ---------------------------------------------------------------------------


# §13.1 TAWOS-real resolution outcome distribution.
# Used to sample the Jira `Resolution` field for every V2 ticket.
# When resolution != "Fixed", the resolve step writes a close-note
# (cannot-reproduce / self-resolved / by-design / duplicate style)
# instead of a fix description. The ClosurePlan is derived from the
# resolution rather than sampled independently — single source of truth.
_RESOLUTION_DISTRIBUTION: dict[str, float] = {
    "Fixed":            0.60,
    "Won't Fix":        0.15,
    "Duplicate":        0.12,
    "Cannot Reproduce": 0.04,
    "Not A Bug":        0.03,
    "Timed out":        0.04,
}
# Remaining 0.02 absorbed by Fixed at the boundary.


# §13.1 TAWOS-real resolution_time buckets. Each entry is
# (min_seconds, max_seconds, probability). Probability sums to 1.0.
# Sampled uniformly within the chosen bucket.
_RESOLUTION_TIME_BUCKETS: tuple[tuple[int, int, float], ...] = (
    (60,        3600,      0.04),   # <1h
    (3600,      86400,     0.11),   # 1h-1d
    (86400,     604800,    0.20),   # 1d-1wk
    (604800,    2592000,   0.25),   # 1wk-1mo
    (2592000,   31536000,  0.40),   # 1mo-1yr
)


# §13.1 TAWOS-real comments-per-issue distribution.
# 1 comment: 36%, 2-5: 43%, 6-15: 14%, 15+: 4%.
# Slight rebalance to absorb the 0.03 rounding gap → "1" bucket gets 0.39.
# We cap the long-tail bucket at 15 (instead of 15+) to bound bulk-run
# wall time — the upper 4% would otherwise have 30+ comments and each
# extra step costs an LLM call (~10s).
def _sample_resolution(episode_id: str) -> str:
    """Sample a Jira-realistic resolution outcome for this episode."""
    h = int(hashlib.sha256(
        f"resolution::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    threshold = h / 0xFFFFFFFF
    cum = 0.0
    for resolution, prob in _RESOLUTION_DISTRIBUTION.items():
        cum += prob
        if threshold < cum:
            return resolution
    return "Fixed"


def _sample_resolution_time_s(episode_id: str) -> int:
    """Sample a Jira-realistic resolution wall-clock time in seconds.

    Drawn from §13.1 TAWOS distribution — full range (minutes to a year)
    rather than clipped to our 5-day collection window. Real production
    Jira queues span months for some tickets; a model trained on
    `resolution_time > 5d == distractor` would shortcut, so we sample
    the full empirical distribution for both real and distractor tickets.
    """
    h_bucket = int(hashlib.sha256(
        f"restime-bucket::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    h_within = int(hashlib.sha256(
        f"restime-within::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    threshold = h_bucket / 0xFFFFFFFF
    cum = 0.0
    for low, high, prob in _RESOLUTION_TIME_BUCKETS:
        cum += prob
        if threshold < cum:
            span = high - low
            return low + (h_within % max(1, span))
    return 3600  # 1h fallback


def _sample_comment_count(episode_id: str) -> int:
    """Sample total comment count for this episode per §13.1 distribution.

    Returns the count of comments AFTER the report (i.e. excludes the
    initial summary/description). Resolve counts as a comment. Minimum
    1 (just resolve), maximum 15 (capped for bulk-run wall time bounds).
    """
    h_bucket = int(hashlib.sha256(
        f"commentcount-bucket::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    h_within = int(hashlib.sha256(
        f"commentcount-within::{episode_id}".encode("utf-8")
    ).hexdigest()[:8], 16)
    threshold = h_bucket / 0xFFFFFFFF
    if threshold < 0.39:
        return 1
    if threshold < 0.82:    # 0.39 + 0.43
        return 2 + (h_within % 4)   # 2-5
    if threshold < 0.96:    # 0.82 + 0.14
        return 6 + (h_within % 7)   # 6-12 (range slightly clipped)
    return 13 + (h_within % 3)      # 13-15 (was 15+; capped)


# Closure kinds the LLM is steered toward. Each is a real Jira closure
# category that a real on-call queue produces in volume.
_CLOSURE_KINDS: tuple[str, ...] = (
    "cannot_reproduce",
    "self_resolved",
    "by_design",
    "duplicate",
)


# Maps the V2 resolution outcome → close-note writing style (used to
# pick the resolve step's prompt scaffold). "Fixed" returns None
# meaning "write a fix description".
_RESOLUTION_TO_CLOSURE_KIND: dict[str, str] = {
    "Cannot Reproduce": "cannot_reproduce",
    "Won't Fix":        "self_resolved",
    "Not A Bug":        "by_design",
    "Duplicate":        "duplicate",
    "Timed out":        "self_resolved",   # similar close-note style
}


@dataclass
class ClosurePlan:
    """Decision + content for Rule 5 close-as-noise on one ticket.

    `closure_kind`:
      - "cannot_reproduce": closer can't reproduce the issue
      - "self_resolved":    closer notes the issue resolved on its own
      - "by_design":        closer says the behavior is expected
      - "duplicate":        closer links to an earlier ticket id

    `reference_ticket` is populated only for "duplicate" closures and
    is a deterministic fake id (e.g. "TICKET-49213") so the same
    episode always quotes the same prior ticket across re-runs.
    """

    closed_as_noise: bool
    closure_kind: str = ""
    reference_ticket: str = ""


def plan_closure(episode_id: str, triage_label: str = "") -> ClosurePlan:
    """Derive the close-note style from the sampled resolution outcome.

    V2 step 3 unification: instead of a separate close-as-noise sampler
    that was conditional on `triage_label` (eval-only), we derive the
    ClosurePlan directly from `_sample_resolution`. Single source of
    truth. `triage_label` is kept in the signature for back-compat but
    unused.
    """
    resolution = _sample_resolution(episode_id)
    if resolution == "Fixed":
        return ClosurePlan(closed_as_noise=False)
    kind = _RESOLUTION_TO_CLOSURE_KIND.get(resolution, "self_resolved")
    reference = ""
    if kind == "duplicate":
        # Fake but stable ticket id — range chosen so it looks like a
        # real Jira key from a long-running project.
        h_ref = int(
            hashlib.sha256(
                f"closenoise-ref::{episode_id}".encode("utf-8")
            ).hexdigest()[:8],
            16,
        )
        reference = f"TICKET-{40000 + (h_ref % 19999)}"
    return ClosurePlan(
        closed_as_noise=True,
        closure_kind=kind,
        reference_ticket=reference,
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
    wrong_hyp: "WrongHypothesisPlan | None" = None,
    closure: "ClosurePlan | None" = None,
    evidence_override: EvidenceSlice | None = None,
) -> tuple[str, str]:
    """Shared prompt scaffold for ack / hypothesis / redirect / resolve.

    Differences between steps are encoded in the system message
    (persona + step-specific guidance) and in the user message
    (step-specific framing of "what you're contributing"). Same
    sanitizer guardrails apply.

    Phase 4 additions:
      - `wrong_hyp` steers the hypothesis step toward a deliberately
        wrong technical theory, and primes the redirect step to
        correct it (independently of misattribution).
      - `closure` swaps the resolve-step framing from "describe the
        fix" to "close as noise/duplicate/by-design/cannot-reproduce".
    """
    persona = persona_for(persona_role)
    symptom = symptom_for(ctx.scenario_family, affected_service=ctx.affected_service)
    char_cap = _char_cap_for(persona_role)

    step_guidance = _STEP_GUIDANCE[step_kind]

    # Phase 4 — closure swap on the resolve step. The "noise" closure
    # personas write SHORT, dismissive close notes — not fix descriptions.
    if step_kind == StepKind.RESOLVE and closure is not None and closure.closed_as_noise:
        step_guidance = _CLOSURE_GUIDANCE[closure.closure_kind]

    system = (
        f"You are continuing a Jira ticket at a large e-commerce company. "
        f"Write as a {persona.role}: {persona.style_descriptor}\n\n"
        "Style rules:\n"
        f"- HARD LENGTH LIMIT: keep total output under {char_cap} characters. "
        f"Aim for {persona.terseness}. Going over is worse than stopping early.\n"
        "- TAWOS-realistic engineer comment median is 200-500 chars. Match that.\n"
        "- Refer to the previous messages as if you've just read them.\n"
        f"- {step_guidance}\n"
        "- Describe symptoms and observations; do not state a definitive "
        "internal cause unless you are the resolver and you have enough "
        "evidence in the thread to justify it.\n\n"
        f"{_OUTPUT_FORMAT_RULES}"
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

    # Phase 4 — wrong-hypothesis framing. Only steers the HYPOTHESIS
    # step (proposing the wrong theory) and the REDIRECT step (so the
    # senior can name the wrong theory and counter it).
    wrong_hyp_block = ""
    if wrong_hyp is not None and wrong_hyp.enabled:
        if step_kind == StepKind.HYPOTHESIS:
            wrong_hyp_block = (
                f"\nFraming hint: from your angle on this, you suspect "
                f"the issue is {wrong_hyp.wrong_theory}. State that as a "
                f"working theory and suggest the next step you'd take to "
                f"check it — don't be 100% confident, but commit to the "
                f"direction.\n"
            )
        elif step_kind == StepKind.REDIRECT:
            wrong_hyp_block += (
                f"\nFraming hint: earlier comments propose that the issue "
                f"is {wrong_hyp.wrong_theory}. After checking, that "
                f"direction doesn't hold up — the logs in this ticket "
                f"point elsewhere. Gently steer the thread away from "
                f"that theory with a one-sentence reason.\n"
            )

    prior_thread = _format_prior_thread(prior)
    # V2: per-step persona-sliced evidence (logs + metrics + trace +
    # k8s + alerts). The slicer enforces the §13.12 access table.
    step_evidence = evidence_override if evidence_override is not None else ctx.evidence
    evidence_block = _format_evidence_block(step_evidence)

    # Phase 4 — close-as-noise framing for the resolve step. We tell the
    # resolver what kind of close to write; the LLM produces the actual
    # short close note.
    closure_block = ""
    if step_kind == StepKind.RESOLVE and closure is not None and closure.closed_as_noise:
        if closure.closure_kind == "duplicate" and closure.reference_ticket:
            closure_block = (
                f"\nClosure style: this ticket is being closed as a "
                f"duplicate of {closure.reference_ticket}. Reference that "
                f"ticket and ask the reporter to follow there if it "
                f"recurs. Two sentences max, no fix description.\n"
            )
        elif closure.closure_kind == "cannot_reproduce":
            closure_block = (
                "\nClosure style: this is being closed because no one "
                "could reproduce the issue. Ask the reporter to reopen "
                "with steps to reproduce if it happens again. Two "
                "sentences max, no fix description.\n"
            )
        elif closure.closure_kind == "self_resolved":
            closure_block = (
                "\nClosure style: the issue appears to have resolved "
                "itself before anyone could action it. Note this and "
                "say monitoring will continue. Two sentences max, no "
                "fix description.\n"
            )
        elif closure.closure_kind == "by_design":
            closure_block = (
                "\nClosure style: after investigation, this is expected "
                "behavior — the user was on a deprecated flow or the "
                "alert thresholds were too sensitive. Explain briefly "
                "without naming a fix. Two sentences max.\n"
            )

    user = (
        f"Symptom the reporter logged: {symptom.headline}\n"
        f"Urgency framing: {symptom.severity_phrasing}\n\n"
        f"Evidence available to YOU right now:\n{evidence_block}\n"
        f"{misattr_block}"
        f"{wrong_hyp_block}"
        f"{closure_block}\n"
        f"Prior thread:\n{prior_thread}\n\n"
        f"Now write your contribution as {persona_role}. Just the comment "
        f"body, in your voice. Reference specific evidence you can see when "
        f"relevant — alert names, metric deltas, log lines, trace IDs — "
        f"the way a real engineer would in a ticket comment."
    )
    assert_clean(user, context=f"{step_kind}.user")
    return system, user


# Per-closure-kind override of resolve's _STEP_GUIDANCE. These are
# framed as positive instructions (not "don't describe a fix") so the
# sanitizer accepts them.
_CLOSURE_GUIDANCE: dict[str, str] = {
    "cannot_reproduce": (
        "Close the ticket as not-reproducible. State that you tried to "
        "reproduce, couldn't, and ask the reporter to reopen with steps."
    ),
    "self_resolved": (
        "Close the ticket noting that the issue resolved itself before "
        "intervention. State you'll keep monitoring."
    ),
    "by_design": (
        "Close the ticket explaining that the observed behavior is "
        "expected. Briefly say why without proposing a code change."
    ),
    "duplicate": (
        "Close the ticket as a duplicate of an earlier ticket. Reference "
        "the prior id and ask the reporter to follow there."
    ),
}


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
    wrong_hyp: "WrongHypothesisPlan | None" = None,
    closure: "ClosurePlan | None" = None,
    evidence_override: EvidenceSlice | None = None,
) -> TimelineStep:
    """Single-step LLM call for any of the follow-up step kinds.

    V2: `evidence_override` is the bundle-sliced EvidenceSlice for this
    step's persona-access pattern (§13.12). When set, replaces
    ctx.evidence for prompt + step storage. Falls back to ctx.evidence
    for V1 callers that haven't switched to the bundle path.
    """
    system, user = _build_followup_prompt(
        step_kind=step_kind,
        persona_role=persona_role,
        ctx=ctx,
        prior=prior,
        misattr=misattr,
        wrong_hyp=wrong_hyp,
        closure=closure,
        evidence_override=evidence_override,
    )
    prompt_hash = _hash_prompt(system, user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    text = _chat_with_usage(
        llm.base_url, llm.model, messages,
        temperature=llm.temperature,
        max_tokens=_max_tokens_for(persona_role, default=llm.max_tokens),
        timeout=llm.timeout_s,
    )
    if not text or text.startswith("__ERROR__"):
        raise RuntimeError(
            f"LM Studio call failed at step={step_kind} for "
            f"episode={ctx.episode_id}: "
            f"{text[:200] if text else 'empty response'}"
        )
    # Soft cleanup before the hard sanitizer reject.
    text = _redact_lab_tokens(text)
    leaks = find_lab_tokens(text)
    if leaks:
        _USAGE_TRACKER.n_leak_rejections += 1
        raise RuntimeError(
            f"LLM output at step={step_kind} contained lab-leakage tokens "
            f"{leaks[:4]} for episode={ctx.episode_id}. Refusing to ship."
        )
    avatar = avatar_for(persona_role, ctx.episode_id, salt=avatar_salt)
    step_evidence = evidence_override if evidence_override is not None else ctx.evidence
    return TimelineStep(
        step_kind=step_kind,
        persona_role=persona_role,
        persona_avatar=avatar,
        t_offset_s=t_offset_s,
        context_window_s=context_window_s,
        evidence=step_evidence,
        text=text.strip(),
        body_code=_body_code_for_step(persona_role, step_evidence),
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


# ---------------------------------------------------------------------------
# Step 3 — variable-length step sequence builder
# ---------------------------------------------------------------------------


@dataclass
class StepSpec:
    """Declarative spec for one middle step in the timeline.

    The generator turns each StepSpec into one LLM call. Resolve is added
    separately by the caller (always last); report is always first.
    """

    step_kind: str
    persona_role: str
    t_offset_s: int
    context_window_s: int
    avatar_salt: str


# Personas to rotate through for extra hypothesis steps (when comment_count
# > 3). Order is deterministic on episode_id. Includes a mix of backend /
# frontend / db / senior so a 10-comment thread reads like multiple
# engineers chiming in, not one persona repeating itself.
_EXTRA_HYPOTHESIS_PERSONAS: tuple[str, ...] = (
    "backend-eng",
    "frontend-eng",
    "junior-eng",
    "senior-sre",
)


def _pick_extra_persona(episode_id: str, slot_idx: int, components: list[str]) -> str:
    """Pick a persona for extra-hypothesis slot `slot_idx`.

    For infra-touching faults (Redis / Postgres / cache), inject a
    `db-team` persona into the rotation occasionally — that's what
    real production tickets look like.
    """
    is_infra = any(
        ("redis" in (c or "").lower() or "postgres" in (c or "").lower())
        for c in components
    )
    pool = list(_EXTRA_HYPOTHESIS_PERSONAS)
    if is_infra and slot_idx % 3 == 1:
        return "db-team"
    h = int(
        hashlib.sha256(
            f"extra-persona::{episode_id}::{slot_idx}".encode("utf-8")
        ).hexdigest()[:8],
        16,
    )
    return pool[h % len(pool)]


def _build_step_sequence(
    *,
    episode_id: str,
    comment_count: int,
    misattr_enabled: bool,
    wrong_hyp_enabled: bool,
    components_seen: list[str],
) -> list[StepSpec]:
    """Build the middle-step sequence (between report and resolve) for
    the sampled `comment_count`. Resolve takes 1 of the comment slots
    so middle steps = comment_count - 1.

    Slot policy:
      slot 1: ack            (oncall-sre)
      slot 2: hypothesis     (backend/frontend/junior, by episode)
      slot 3: redirect       (senior-sre, ONLY if misattr or wrong_hyp)
      slot 4+: extra hypotheses (rotating personas; includes db-team
              for infra-touching faults)

    `comment_count == 1` → no middle steps (report + resolve only).
    """
    middle_target = comment_count - 1   # resolve = 1 of the comments
    if middle_target <= 0:
        return []

    middle: list[StepSpec] = []

    # Slot 1 — ack
    if len(middle) < middle_target:
        middle.append(StepSpec(
            step_kind=StepKind.ACK,
            persona_role="oncall-sre",
            t_offset_s=180,
            context_window_s=180,
            avatar_salt="ack",
        ))

    # Slot 2 — hypothesis
    if len(middle) < middle_target:
        hypo_role = _pick_hypothesis_persona(episode_id)
        middle.append(StepSpec(
            step_kind=StepKind.HYPOTHESIS,
            persona_role=hypo_role,
            t_offset_s=420,
            context_window_s=300,
            avatar_salt="hyp",
        ))

    # Slot 3 — redirect (conditional)
    needs_redirect = misattr_enabled or wrong_hyp_enabled
    if needs_redirect and len(middle) < middle_target:
        middle.append(StepSpec(
            step_kind=StepKind.REDIRECT,
            persona_role="senior-sre",
            t_offset_s=900,
            context_window_s=900,
            avatar_salt="redir",
        ))

    # Slots 4+ — extra hypotheses with rotating personas
    extra_idx = 0
    while len(middle) < middle_target:
        extra_idx += 1
        # Increasing t_offset to keep the thread chronologically sensible.
        t_offset = 1200 + extra_idx * 600   # +20min, +30min, +40min...
        persona = _pick_extra_persona(episode_id, extra_idx, components_seen)
        middle.append(StepSpec(
            step_kind=StepKind.HYPOTHESIS,
            persona_role=persona,
            t_offset_s=t_offset,
            context_window_s=min(1800, t_offset),
            avatar_salt=f"extra{extra_idx}",
        ))

    return middle


@dataclass
class FullTimelineInputs:
    """Bundles everything generate_full_timeline needs.

    Kept separate from ReportContext so a caller assembling a ticket
    doesn't need to know about misattribution mechanics — the
    generator decides per episode.

    `triage_label` is consumed by Phase 4 for closure sampling (Rule 5):
    `noise` and `borderline` windows can sample close-as-noise; reading
    it never leaks because the label only drives a sampling decision
    and is never injected into LLM prompts.

    V2 additions:
    `global_triage_path` and `alerts_path` route `build_evidence` to
    the right derived/raw files. Optional — when None, V2 falls back
    to V1 single-channel mode (still produces a valid timeline).
    `source_injection_id` flows through to TicketTimeline for §13.4
    coverage tracking.
    """

    window_row: dict[str, Any]
    inputs: WindowEvidenceInputs
    severity_seen: str
    candidate_downstream_services: list[str]
    triage_label: str = ""   # "ticket_worthy" / "borderline" / "noise"
    # V2 paths — when set, generator routes through multi-channel
    # evidence bundle (§13.12); when None, falls back to legacy
    # single-channel logs only.
    global_triage_path: Path | None = None
    alerts_path: Path | None = None
    source_injection_id: str | None = None


def generate_full_timeline(
    bundle: FullTimelineInputs,
    *,
    llm: LLMConfig | None = None,
) -> "TicketTimeline":
    """Generate report -> ack -> hypothesis -> [redirect] -> resolve.

    Step list semantics:
      - `redirect` is emitted when EITHER misattribution OR wrong-
        hypothesis fires. Both samplers feed in their framing through
        the prompt scaffold; the redirect persona's job is to correct
        whatever wrong direction the thread took.
      - When `closure.closed_as_noise` is True, the resolve step's
        prompt is swapped from "describe the fix" to a Rule 5 close
        note (cannot_reproduce / self_resolved / by_design / duplicate).
        The timeline still ends in `resolve` — short close notes are
        their own valid form.

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
    wrong_hyp = plan_wrong_hypothesis(episode_id)
    # V2 step 3 — sample resolution outcome and resolution_time from
    # the §13.1 TAWOS-empirical distributions. closure_plan is now
    # derived from the resolution (single source of truth).
    sampled_resolution = _sample_resolution(episode_id)
    sampled_resolution_time_s = _sample_resolution_time_s(episode_id)
    closure = plan_closure(episode_id)
    sampled_comment_count = _sample_comment_count(episode_id)

    # The reporter "sees" the misattributed service if misattribution
    # was sampled — that's the whole point of Rule 3. Otherwise they
    # see the actual affected service.
    reporter_service = misattr.wrong_service if misattr.enabled else correct_service
    components_seen = (
        [misattr.wrong_service] if misattr.enabled else [correct_service]
    )

    scenario_family = row["scenario_family"]
    symptom = symptom_for(scenario_family, affected_service=reporter_service)

    # V2 — build the multi-channel evidence bundle ONCE per ticket. The
    # per-step slicer projects it down to what each persona can see.
    # When global_triage_path / alerts_path are None, we fall back to
    # legacy single-channel mode for backward compatibility with V1
    # callers (still produces a valid timeline, just no metric/k8s/alert
    # channels).
    components_for_bundle = sorted(
        {correct_service, *bundle.candidate_downstream_services}
    )
    ev_bundle: EvidenceBundle | None = None
    if bundle.global_triage_path and bundle.alerts_path:
        shadow_record = _lookup_shadow_record(
            bundle.inputs.run_dir, episode_id,
        )
        ev_bundle = build_evidence(
            run_dir=bundle.inputs.run_dir,
            episode_id=episode_id,
            components=components_for_bundle,
            global_triage_path=bundle.global_triage_path,
            alerts_path=bundle.alerts_path,
            symptom_phrase=symptom.headline,
            shadow_record=shadow_record,
        )

    # Step 2 — severity-weighted reporter persona (§11 Open Q1). When
    # the reporter is the oncall-sre (paged before customer impact), the
    # report step sees ack-level evidence (alerts + 1 log + 1 metric +
    # k8s state) instead of just the symptom phrase. This gives the
    # corpus a realistic mix of "engineer-first" and "customer-first"
    # report voices.
    reporter_persona_role = _pick_report_persona(episode_id, bundle.severity_seen)

    # Build per-step EvidenceSlices from the bundle (V2) or fall back
    # to the legacy single-channel slice (V1). Reporter persona drives
    # which slice config the report step uses — cs-agent gets the
    # "report" slice (symptom only), oncall-sre gets the "ack" slice.
    report_slice_kind = (
        StepKind.ACK if reporter_persona_role == "oncall-sre" else StepKind.REPORT
    )
    if ev_bundle is not None:
        report_evidence = _slice_bundle_to_evidence(
            ev_bundle, report_slice_kind,
            time_window_start=bundle.inputs.window_start_iso,
            time_window_end=bundle.inputs.window_end_iso,
        )
    else:
        report_evidence = build_report_evidence(bundle.inputs)

    ctx = ReportContext(
        episode_id=episode_id,
        affected_service=reporter_service,
        scenario_family=scenario_family,
        severity_seen=bundle.severity_seen,
        evidence=report_evidence,
    )

    def _step_evidence(step_kind: str) -> EvidenceSlice | None:
        """V2: per-step bundle slice. V1: None (uses ctx.evidence)."""
        if ev_bundle is None:
            return None
        return _slice_bundle_to_evidence(
            ev_bundle, step_kind,
            time_window_start=bundle.inputs.window_start_iso,
            time_window_end=bundle.inputs.window_end_iso,
        )

    # 1. REPORT — persona varies per severity (§11 Q1). The body_code is
    #    set inside generate_report_step now, so we don't override it
    #    here.
    report_step = generate_report_step(
        ctx, llm=llm, persona_role=reporter_persona_role,
    )
    steps: list[TimelineStep] = [report_step]

    # V2 step 3 — build the variable-length middle step sequence based
    # on the sampled comment_count. The sequence policy is in
    # `_build_step_sequence`; here we just drive it.
    middle_specs = _build_step_sequence(
        episode_id=episode_id,
        comment_count=sampled_comment_count,
        misattr_enabled=misattr.enabled,
        wrong_hyp_enabled=wrong_hyp.enabled,
        components_seen=components_seen,
    )
    for spec in middle_specs:
        step = _generate_followup_step(
            step_kind=spec.step_kind,
            persona_role=spec.persona_role,
            avatar_salt=spec.avatar_salt,
            t_offset_s=spec.t_offset_s,
            context_window_s=spec.context_window_s,
            ctx=ctx,
            prior=steps,
            misattr=misattr,
            wrong_hyp=wrong_hyp,
            llm=llm,
            evidence_override=_step_evidence(spec.step_kind),
        )
        steps.append(step)

    # Last step — RESOLVE. Always present. Closure plan (derived from
    # resolution outcome above) swaps the resolve persona's prompt to
    # a short close note when resolution != "Fixed".
    # t_offset_s scales with the prior thread length so longer threads
    # have a longer time-to-resolution in the timeline narrative.
    resolve_t_offset = max(
        1800, (middle_specs[-1].t_offset_s + 600) if middle_specs else 1800
    )
    resolve_step = _generate_followup_step(
        step_kind=StepKind.RESOLVE,
        persona_role="fix-author",
        avatar_salt="resolve",
        t_offset_s=resolve_t_offset,
        context_window_s=resolve_t_offset,
        ctx=ctx,
        prior=steps,
        misattr=misattr,
        wrong_hyp=wrong_hyp,
        closure=closure,
        llm=llm,
        evidence_override=_step_evidence(StepKind.RESOLVE),
    )
    steps.append(resolve_step)

    # V2 ticket-level fields. description_code is the full Move A signature
    # joined with newlines (empty allowed per §13.3 rule 3c). Resolution
    # defaults to "Fixed" unless close-as-noise sampled (§13.1 resolution
    # distribution gets fuller treatment in §13.8 step 3).
    description_code = ""
    log_signature_source = ""
    evidence_bundle_hash = ""
    if ev_bundle is not None:
        description_code = "\n".join(ev_bundle.log_lines)
        log_signature_source = ev_bundle.log_lines_source
        evidence_bundle_hash = _hash_evidence_bundle(ev_bundle)

    versions = stamp_versions()
    return TicketTimeline(
        ticket_id=f"HMN-{episode_id}",
        source_episode_id=episode_id,
        source_dataset_run_id=row["dataset_run_id"],
        source_injection_id=bundle.source_injection_id,
        affected_services_seen=[reporter_service],
        severity_seen=bundle.severity_seen,
        components_seen=components_seen,
        is_misattributed=misattr.enabled,
        closed_as_noise=closure.closed_as_noise,
        steps=steps,
        description_code=description_code,
        # V2 step 3 — sampled from §13.1 TAWOS distributions
        resolution=sampled_resolution,
        resolution_time_s=sampled_resolution_time_s,
        is_distractor=False,            # §13.5 distractors are minted separately
        is_followup_of=None,            # §13.9 #3 followups are minted separately
        log_signature_source=log_signature_source,
        evidence_bundle_hash=evidence_bundle_hash,
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
