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


def _build_memory_text(timeline_ticket: dict) -> str:
    """Flatten the humanized timeline into one memory_text blob.

    Format: `[persona_role @ +Ns]: <step text>`, separated by blank
    lines. The persona-role marker survives BM25 / embedding indexing
    cleanly because it's a plain ASCII token; downstream retrieval
    sees the full multi-author thread.
    """
    parts: list[str] = []
    for step in timeline_ticket.get("timeline") or []:
        role = step.get("persona_role") or "unknown"
        t = step.get("t_offset_s")
        body = (step.get("text") or "").strip()
        if not body:
            continue
        header = f"[{role} @ +{int(t) if isinstance(t, (int, float)) else '?'}s]:"
        parts.append(f"{header}\n{body}")
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
) -> list[JiraMemoryIssue]:
    """Return the humanized v5-large corpus as a JiraMemoryIssue list.

    Each entry corresponds 1:1 to a legacy `jira-memory-corpus.jsonl`
    row (matched on `incident_episode_id`). Tickets whose source
    episode has no legacy counterpart are skipped — that should never
    happen for v5-large since the humanizer was driven off the legacy
    corpus itself.
    """
    global_dir = Path(global_dir)
    legacy_path = global_dir / "jira-memory-corpus.jsonl"
    humanized_path = (
        global_dir / "jira-shadow-humanized-v1" / humanized_subdir / "timeline.jsonl"
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
        memory_text = _build_memory_text(ticket)
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
    return out
