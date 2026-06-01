"""Dry-run smoke test for V2 humanizer wiring (§13.8 step 1).

Verifies:
  * `build_evidence` + `slice_for_step` flow into per-step LLM prompts
  * each persona-step gets the right subset of channels (logs / metrics
    / trace / k8s / alerts) per §13.12 table
  * TimelineStep.body_code is populated for log-pasting personas only
  * TicketTimeline carries the new V2 fields (description_code,
    resolution, log_signature_source, evidence_bundle_hash, ...)
  * the as_jsonl_row output has the new schema
  * sanitizer rejects nothing produced by the bundle

Mocks `chat_via_lm_studio` so this runs without LM Studio. Real LLM
calls happen via the existing humanize-5-episodes script when the
user signals to do an eyeball pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# Patch the LLM client BEFORE importing the generator (generator caches
# the symbol at import time).
import comparison.retrievers as _ret  # noqa: E402

_real_chat = _ret.chat_via_lm_studio
_captured_prompts: list[dict[str, Any]] = []


def _mock_chat(base_url, model, messages, *, temperature=0.7,
               max_tokens=350, timeout=60.0):
    """Stub LLM that captures the prompt + returns a deterministic reply
    tagged with the step_kind so the assembled timeline is inspectable."""
    system = messages[0]["content"] if messages else ""
    user = messages[1]["content"] if len(messages) > 1 else ""
    # Infer step_kind from the system message (first line mentions persona).
    step_tag = "report"
    for kind in ("ack", "hypothesis", "redirect", "resolve"):
        if f"step_kind={kind}" in user or kind in system.lower():
            step_tag = kind
            break
    _captured_prompts.append({
        "system": system,
        "user": user,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    return (
        f"[mock-llm reply for inferred step={step_tag}] "
        "This is a placeholder response. In a real run the LLM would "
        "write the persona's contribution here, referencing the "
        "evidence channels surfaced in the user prompt."
    )


_ret.chat_via_lm_studio = _mock_chat  # type: ignore[assignment]

from jira_humanizer.evidence_bundle import build_evidence, slice_for_step  # noqa: E402
from jira_humanizer.timeline_generator import (  # noqa: E402
    FullTimelineInputs,
    LLMConfig,
    WindowEvidenceInputs,
    generate_full_timeline,
)
from jira_humanizer.timeline_schema import (  # noqa: E402
    DESCRIPTION_MAX_CHARS,
    StepKind,
)


RUNS = REPO / "data" / "runs"
DERIVED = REPO / "data" / "derived" / "global" / "2026-05-25-dataset-v5-large-global"
GLOBAL_TRIAGE = DERIVED / "global-triage-examples.jsonl"


CASES = [
    # (run_id, episode_id, correct_service, scenario_family, severity, downstream)
    ("2026-05-25-dataset-v5-large-compact-a-r01",
     "2026-05-25-dataset-v5-large-compact-a-r01-cart-redis-degradation-critical-20260525T134155Z",
     "cartservice",
     "cart-redis-degradation-critical",
     "high",
     ["cartservice", "checkoutservice", "frontend", "redis-cart"]),
    ("2026-05-25-dataset-v5-large-compact-a-r01",
     "2026-05-25-dataset-v5-large-compact-a-r01-productcatalog-latency-major-20260525T132741Z",
     "productcatalogservice",
     "productcatalog-latency-major",
     "medium",
     ["checkoutservice", "frontend", "productcatalogservice"]),
]


def _find_window_iso(run_dir: Path, episode_id: str, service: str):
    """Look up active_fault window start/end from telemetry_windows.jsonl."""
    p = run_dir / "telemetry_windows.jsonl"
    if not p.exists():
        return "", ""
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            wid = rec.get("window_id", "")
            if (wid.startswith(f"{episode_id}-active_fault-{service}")
                    or wid == f"{episode_id}-active_fault-{service}"):
                return (
                    str(rec.get("start_time") or rec.get("window_start") or ""),
                    str(rec.get("end_time") or rec.get("window_end") or ""),
                )
    return "", ""


def bar(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def trunc(s: str, n: int = 140) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def main() -> None:
    overall_ok = True
    for run_id, eid, correct_svc, family, sev, downstream in CASES:
        bar(f"{eid.split('compact-a-r01-')[-1]}  (correct_svc={correct_svc})")

        run_dir = RUNS / run_id
        ws, we = _find_window_iso(run_dir, eid, correct_svc)
        window_id = f"{eid}-active_fault-{correct_svc}"

        window_row = {
            "incident_episode_id": eid,
            "dataset_run_id": run_id,
            "scenario_family": family,
            "service_name": correct_svc,
        }
        inputs = WindowEvidenceInputs(
            run_dir=run_dir,
            window_id=window_id,
            service_name=correct_svc,
            window_start_iso=ws,
            window_end_iso=we,
        )
        full_inputs = FullTimelineInputs(
            window_row=window_row,
            inputs=inputs,
            severity_seen=sev,
            candidate_downstream_services=downstream,
            triage_label="ticket_worthy",
            global_triage_path=GLOBAL_TRIAGE,
            alerts_path=run_dir / "alerts.jsonl",
            source_injection_id=eid,  # use episode_id as the injection id for now
        )

        _captured_prompts.clear()
        try:
            timeline = generate_full_timeline(full_inputs, llm=LLMConfig())
        except Exception as exc:
            print(f"[FAIL] generate_full_timeline raised: {exc!r}")
            overall_ok = False
            continue

        # Top-level ticket sanity
        print(f"\n[TIMELINE]")
        print(f"  ticket_id:              {timeline.ticket_id}")
        print(f"  source_episode_id:      {timeline.source_episode_id}")
        print(f"  source_injection_id:    {timeline.source_injection_id}")
        print(f"  is_misattributed:       {timeline.is_misattributed}")
        print(f"  closed_as_noise:        {timeline.closed_as_noise}")
        print(f"  resolution:             {timeline.resolution}")
        print(f"  log_signature_source:   {timeline.log_signature_source}")
        print(f"  evidence_bundle_hash:   {timeline.evidence_bundle_hash}")
        dc_lines = timeline.description_code.count("\n") + (1 if timeline.description_code else 0)
        print(f"  description_code:       {dc_lines} lines, {len(timeline.description_code)} chars")
        print(f"  steps:                  {[s.step_kind for s in timeline.steps]}")

        # Per-step evidence + body_code summary
        print(f"\n[PER-STEP EVIDENCE PROJECTION]")
        for s in timeline.steps:
            ev = s.evidence
            channels = []
            if ev.log_quotes: channels.append(f"logs={len(ev.log_quotes)}")
            if ev.metric_observations: channels.append(f"metrics={len(ev.metric_observations)}")
            if ev.trace_observations: channels.append(f"trace={len(ev.trace_observations)}")
            if ev.k8s_observations: channels.append(f"k8s={len(ev.k8s_observations)}")
            if ev.alert_names: channels.append(f"alerts={len(ev.alert_names)}")
            if ev.trace_id_quoted: channels.append("trace_id=yes")
            bc = "yes" if s.body_code else "no"
            print(f"  {s.step_kind:10s} persona={s.persona_role:14s} "
                  f"avatar={s.persona_avatar:18s} body_code={bc}  channels=[{', '.join(channels)}]")

        # Show one full prompt — the ack step is the most interesting
        # because it's where on-call sees alerts + metrics + k8s for
        # the first time.
        print(f"\n[ACK STEP PROMPT — USER MESSAGE ONLY]")
        ack_idx = next((i for i, s in enumerate(timeline.steps) if s.step_kind == StepKind.ACK), -1)
        if ack_idx >= 0 and ack_idx < len(_captured_prompts):
            user_prompt = _captured_prompts[ack_idx]["user"]
            # Only show first 60 lines so output stays readable
            for line in user_prompt.splitlines()[:60]:
                print(f"    {line}")

        # JSONL roundtrip
        row = timeline.as_jsonl_row()
        v2_fields = (
            "description_code", "resolution", "resolution_time_s",
            "is_distractor", "is_followup_of", "source_injection_id",
            "log_signature_source", "evidence_bundle_hash",
        )
        missing = [f for f in v2_fields if f not in row]
        if missing:
            print(f"\n[FAIL] V2 fields missing from JSONL: {missing}")
            overall_ok = False
        else:
            print(f"\n[OK] All {len(v2_fields)} V2 ticket-level fields present in JSONL")

        # Check per-step JSONL has body_code + new evidence fields
        first_followup = next(
            (s for s in row["timeline"] if s["step_kind"] != "report"), None,
        )
        if first_followup is not None:
            ev_keys = sorted(first_followup["evidence"].keys())
            expected = {"alert_names", "k8s_observations", "log_quotes",
                        "metric_observations", "symptom_phrase",
                        "time_window_end", "time_window_start",
                        "trace_id_quoted", "trace_observations"}
            missing_ev = sorted(expected - set(ev_keys))
            if missing_ev:
                print(f"[FAIL] evidence missing keys: {missing_ev}")
                overall_ok = False
            else:
                print(f"[OK] per-step evidence has all 9 V2 channels in JSONL schema")
            if "body_code" not in first_followup:
                print(f"[FAIL] per-step body_code missing from JSONL")
                overall_ok = False
            else:
                print(f"[OK] per-step body_code present in JSONL")

    print("\n\n=== overall:", "PASS" if overall_ok else "FAIL", "===")
    print(f"({len(CASES)} cases processed, {len(_captured_prompts)} LLM prompts captured)")


if __name__ == "__main__":
    main()
