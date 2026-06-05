"""Adapter: humanized timeline.jsonl -> list[JiraMemoryIssue].

The legacy `jira-memory-corpus.jsonl` and the humanized
`bulk-<date>/timeline.jsonl` have different schemas:

  Legacy: one row per Jira issue with `memory_text` = the synthetic
          ticket body (Summary + Components + Labels + Description +
          comments_body, all in one string). 100% lab-contaminated per
          the text-field leakage canary (commit b704cb8).

  Humanized: one row per ticket with `timeline` = list of step
             contributions, each carrying persona_role / persona_avatar
             / text / step_kind. Sanitizer-verified clean.

This adapter flattens the humanized rows into the `JiraMemoryIssue`
shape the existing memorygraph + loganalyzer code already consumes,
so the pipelines can be A/B'd against the legacy corpus without any
upstream code changes beyond the optional `humanized_subdir` flag on
MemoryGraphPipeline.

Field policy:
  * `memory_text` — built from the timeline step texts only. Persona
    roles are inlined as `[persona_role]:` markers so the entity
    extractor can still find Components-style fields the natural way
    (engineers do write things like "checkoutservice and frontend"
    in real comments). Includes NO scenario / family vocabulary.
  * `resolution_notes` — the resolve-step text.
  * `linked_trace_ids` is intentionally emptied; legacy populated it
    with literal trace IDs that dominated embeddings on v5-quick.
  * The metadata fields (`scenario_family`, `affected_service`,
    `fault_type`, …) carry over from the legacy entry for the same
    `incident_episode_id`. They are used by the time-ordering corpus
    (`MemoryCorpus.visible_to(window)`) and by ground-truth retrieval
    eval — NOT as model inputs. The production-realism contract
    (`docs/triage-task-contract.md` §Field Policy) already bars these
    from any model.
"""

from __future__ import annotations

import json
from pathlib import Path

from loganalyzer.data.schema import JiraMemoryIssue


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(mode="r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _looks_like_trace(line: str) -> bool:
    """Heuristic: a line is "trace-like" if it mentions a span id,
    trace id, latency_ms, percentile (p50/p95/p99), or 'span'."""
    s = line.lower()
    return any(
        k in s
        for k in (
            "traceid", "trace_id", "spanid", "span_id", "span ",
            "p50", "p95", "p99", "latency_ms", "duration_ms",
        )
    )


def _looks_like_k8s(line: str) -> bool:
    """Heuristic: a line is "k8s-like" if it mentions pod / deployment /
    OOM / CrashLoop / restart / kubelet / unschedulable."""
    s = line.lower()
    return any(
        k in s
        for k in (
            "pod ", "pod_", "kubelet", "deployment", "oom",
            "crashloopbackoff", "imagepullbackoff", "containerstatuses",
            "restartcount", "restart count", "unschedulable",
            "nodename", "back-off restarting",
        )
    )


def _mask_lines_in_block(text: str, *, mask_logs: bool, mask_traces: bool, mask_k8s: bool) -> str:
    """Phase C channel-masking. Walk lines, drop those that match the
    masked channel(s). Logs = the residual after traces+k8s are filtered.

    Concretely:
      - mask_traces=True drops lines that look trace-like
      - mask_k8s=True drops lines that look k8s-like
      - mask_logs=True drops *the rest* (i.e. plain log lines that
        don't match either of the above)

    If a block becomes empty after masking, the whole block is dropped.
    """
    out_lines = []
    for line in text.splitlines():
        is_trace = _looks_like_trace(line)
        is_k8s = _looks_like_k8s(line)
        is_other_log = not (is_trace or is_k8s) and line.strip() != ""
        if mask_traces and is_trace:
            continue
        if mask_k8s and is_k8s:
            continue
        if mask_logs and is_other_log:
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def _build_memory_text(
    timeline_ticket: dict,
    *,
    mask_logs: bool = False,
    mask_traces: bool = False,
    mask_k8s: bool = False,
) -> str:
    """Flatten the humanized timeline into one memory_text blob.

    Format: `[persona_role @ +Ns]: <step text>`, separated by blank
    lines. The persona-role marker survives BM25 / embedding indexing
    cleanly because it's a plain ASCII token; downstream retrieval
    sees the full multi-author thread.

    V2 addition: when `description_code` (ticket-level) and `body_code`
    (per-step) are present, they're surfaced into the memory_text so
    BM25 / embedding retrieval can match on the engineer-vocabulary
    log content. `description_code` is placed FIRST (leading-text
    weight matters for both BM25 and short-doc embeddings); per-step
    `body_code` follows the prose body of its step. V1 tickets simply
    don't have these fields, so this branch no-ops for V1.

    Phase C channel-masking: mask_{logs,traces,k8s} drop the
    corresponding lines from `description_code` and `body_code` blocks
    so we can ablate which channel carries retrieval signal.
    """
    parts: list[str] = []
    any_mask = mask_logs or mask_traces or mask_k8s

    # V2 — ticket-level description_code is the highest-signal engineer-
    # vocabulary content. Leads the memory_text so BM25 weights it.
    description_code = (timeline_ticket.get("description_code") or "").strip()
    if description_code:
        if any_mask:
            description_code = _mask_lines_in_block(
                description_code,
                mask_logs=mask_logs, mask_traces=mask_traces, mask_k8s=mask_k8s,
            )
        if description_code:
            parts.append(f"[description_code]\n{description_code}")

    for step in timeline_ticket.get("timeline") or []:
        role = step.get("persona_role") or "unknown"
        t = step.get("t_offset_s")
        body = (step.get("text") or "").strip()
        if not body:
            continue
        header = f"[{role} @ +{int(t) if isinstance(t, (int, float)) else '?'}s]:"
        parts.append(f"{header}\n{body}")
        # V2 — per-step body_code (raw log lines this persona pasted).
        body_code = (step.get("body_code") or "")
        if body_code:
            body_code = body_code.strip()
            if any_mask and body_code:
                body_code = _mask_lines_in_block(
                    body_code,
                    mask_logs=mask_logs, mask_traces=mask_traces, mask_k8s=mask_k8s,
                )
            if body_code:
                parts.append(
                    f">> log lines pasted by {role}:\n{body_code}"
                )
    return "\n\n".join(parts)


def _build_resolution_notes(timeline_ticket: dict) -> str:
    """Pick out the resolve-step text. Falls back to the last step if
    no explicit resolve step is present (shouldn't happen, but defensive)."""
    steps = timeline_ticket.get("timeline") or []
    for step in reversed(steps):
        if step.get("step_kind") == "resolve":
            return (step.get("text") or "").strip()
    if steps:
        return (steps[-1].get("text") or "").strip()
    return ""


def load_humanized_corpus(
    global_dir: Path,
    humanized_subdir: str = "bulk-20260529",
    *,
    humanized_root: str = "jira-shadow-humanized-v1",
    extra_distractor_path: Path | None = None,
    mask_logs: bool = False,
    mask_traces: bool = False,
    mask_k8s: bool = False,
) -> list[JiraMemoryIssue]:
    """Return the humanized v5-large corpus as a JiraMemoryIssue list.

    Each entry corresponds 1:1 to a legacy `jira-memory-corpus.jsonl`
    row (matched on `incident_episode_id`). Tickets whose source
    episode has no legacy counterpart are skipped — that should never
    happen for v5-large since the humanizer was driven off the legacy
    corpus itself.

    V2 args (added 2026-06-01):
      humanized_root:
        Subdir under `global_dir` to read the humanized corpus from.
        Default `"jira-shadow-humanized-v1"` (V1 baseline). Set to
        `"jira-shadow-humanized-v2"` for the V2 corpus (multi-channel
        evidence + engineer voice + description_code).
      extra_distractor_path:
        Optional path to a `timeline.jsonl` of `is_distractor=true`
        rows (e.g. `.../jira-shadow-humanized-v2-distractors/mint-20260601/timeline.jsonl`).
        When set, the distractor rows are appended to the returned
        corpus so retrieval evaluation can measure top-1 precision
        against the distractor set per §13.6.
    """
    global_dir = Path(global_dir)
    legacy_path = global_dir / "jira-memory-corpus.jsonl"
    humanized_path = (
        global_dir / humanized_root / humanized_subdir / "timeline.jsonl"
    )

    if not legacy_path.exists():
        raise FileNotFoundError(
            f"Legacy memory corpus not found at {legacy_path}; needed for "
            f"metadata carry-over (scenario_family, affected_service, etc)."
        )
    if not humanized_path.exists():
        raise FileNotFoundError(
            f"Humanized timeline not found at {humanized_path}. "
            f"Re-run humanize_v5_large_bulk.py or pass --humanized-subdir."
        )

    # Index legacy by episode for metadata lookup.
    legacy_by_episode: dict[str, dict] = {}
    for row in _read_jsonl(legacy_path):
        ep = row.get("incident_episode_id") or ""
        if ep:
            legacy_by_episode[ep] = row

    humanized_rows = _read_jsonl(humanized_path)
    out: list[JiraMemoryIssue] = []
    skipped_no_legacy = 0
    for ticket in humanized_rows:
        ep_id = ticket.get("source_episode_id") or ""
        legacy = legacy_by_episode.get(ep_id)
        if legacy is None:
            skipped_no_legacy += 1
            continue
        memory_text = _build_memory_text(
            ticket,
            mask_logs=mask_logs, mask_traces=mask_traces, mask_k8s=mask_k8s,
        )
        resolution_notes = _build_resolution_notes(ticket)
        out.append(JiraMemoryIssue(
            jira_shadow_issue_id=legacy.get("jira_shadow_issue_id", ""),
            jira_issue_key=legacy.get("jira_issue_key", ""),
            dataset_run_id=legacy.get("dataset_run_id", ""),
            incident_episode_id=ep_id,
            available_as_memory_from=legacy.get("available_as_memory_from", ""),
            scenario_id=legacy.get("scenario_id", ""),
            scenario_family=legacy.get("scenario_family", ""),
            affected_service=legacy.get("affected_service", ""),
            fault_type=legacy.get("fault_type", ""),
            fault_compatibility_class=legacy.get(
                "fault_compatibility_class", ""
            ),
            severity=legacy.get("severity", ""),
            memory_text=memory_text,
            resolution_notes=resolution_notes,
            linked_window_ids=list(legacy.get("linked_window_ids", []) or []),
            # Trace IDs were a major v5-quick leakage vector — strip them.
            linked_trace_ids=[],
            linked_alert_fingerprints=list(
                legacy.get("linked_alert_fingerprints", []) or []
            ),
            raw={},
        ))
    if skipped_no_legacy:
        # Soft warning printed once; not a hard fail because metadata
        # carry-over is best-effort.
        import sys
        print(
            f"[humanized_loader] WARNING: skipped {skipped_no_legacy} humanized "
            f"tickets with no matching legacy entry",
            file=sys.stderr,
        )

    # V2 — append distractor tickets if requested. Distractors have
    # `is_distractor=true` and `source_injection_id=None`; they have
    # NO matching legacy entry by design, so they can't carry legacy
    # metadata. We mint a stable available_as_memory_from from the
    # earliest legacy timestamp so the time-ordering corpus shows
    # them as visible to every window.
    if extra_distractor_path is not None and extra_distractor_path.exists():
        # Use the earliest legacy timestamp as the "always visible"
        # anchor so distractors are visible to every test window.
        anchor = min(
            (r.get("available_as_memory_from", "") for r in legacy_by_episode.values()),
            default="2000-01-01T00:00:00Z",
        )
        distractor_rows = _read_jsonl(extra_distractor_path)
        n_distractors = 0
        for ticket in distractor_rows:
            if not ticket.get("is_distractor"):
                continue
            memory_text = _build_memory_text(
            ticket,
            mask_logs=mask_logs, mask_traces=mask_traces, mask_k8s=mask_k8s,
        )
            resolution_notes = _build_resolution_notes(ticket)
            out.append(JiraMemoryIssue(
                jira_shadow_issue_id=ticket.get("ticket_id", ""),
                jira_issue_key=ticket.get("ticket_id", ""),
                dataset_run_id="",
                incident_episode_id=ticket.get("source_episode_id", ""),
                available_as_memory_from=anchor,
                # Mark scenario_family with a synthetic value so the
                # ground-truth retrieval evaluator can never match
                # a window to a distractor as a true positive.
                scenario_id="__DISTRACTOR__",
                scenario_family="__DISTRACTOR__",
                affected_service="",
                fault_type="",
                fault_compatibility_class="",
                severity=ticket.get("severity_seen", "medium"),
                memory_text=memory_text,
                resolution_notes=resolution_notes,
                linked_window_ids=[],
                linked_trace_ids=[],
                linked_alert_fingerprints=[],
                raw={"is_distractor": True},
            ))
            n_distractors += 1
        import sys
        print(
            f"[humanized_loader] appended {n_distractors} distractor tickets "
            f"from {extra_distractor_path.name}",
            file=sys.stderr,
        )

    return out
