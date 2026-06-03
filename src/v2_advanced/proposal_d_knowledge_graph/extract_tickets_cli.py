"""CLI — run LLM extraction on every V2 humanized ticket, cache per-ticket.

After this script completes:
  data/derived/global/<id>/v2_kg_extractions/ticket/*.json     (one per ticket)

Re-runs are cheap (cached).

Usage:
    PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --humanized-subdir bulk-20260531
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from v2_advanced.shared import LMStudioClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig
from .extractor import batch_extract_tickets

log = get_logger("phase_d.extract_cli")


_FAMILY_SLUG = re.compile(r"-r\d+-(.+?)-202\d{5}T\d{6}Z")


def _family_from_episode(t: dict) -> str:
    eid = t.get("source_episode_id", "") or ""
    m = _FAMILY_SLUG.search(eid)
    return m.group(1) if m else ""


def _build_text(t: dict) -> str:
    """Concatenate description_code + per-step timeline into a single text
    blob the LLM will read."""
    parts = []
    dc = (t.get("description_code") or "").strip()
    if dc:
        parts.append(f"[description_code]\n{dc}")
    for step in t.get("timeline") or []:
        role = step.get("persona_role") or "unknown"
        t_off = step.get("t_offset_s")
        body = (step.get("text") or "").strip()
        if not body:
            continue
        header = f"[{role} @ +{int(t_off) if isinstance(t_off, (int, float)) else '?'}s]:"
        parts.append(f"{header}\n{body}")
        bc = (step.get("body_code") or "").strip()
        if bc:
            parts.append(f">> code/logs:\n{bc}")
    return "\n\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    p.add_argument("--humanized-subdir", default="bulk-20260531")
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    p.add_argument("--model", default="local-model")
    p.add_argument("--limit", type=int, default=0,
                   help="only extract from the first N tickets (0 = all)")
    p.add_argument("--out", type=str, default="v2_kg_extractions",
                   help="cache dir (relative to global-dir)")
    args = p.parse_args()

    timeline_path = args.global_dir / args.humanized_root / args.humanized_subdir / "timeline.jsonl"
    if not timeline_path.exists():
        raise SystemExit(f"V2 timeline not found at {timeline_path}")

    cache_dir = args.global_dir / args.out
    cache_dir.mkdir(parents=True, exist_ok=True)

    with log_step(log, "load_timeline", path=str(timeline_path)):
        tickets = []
        with timeline_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                t = json.loads(line)
                t_pruned = {
                    "ticket_id": t.get("ticket_id"),
                    "memory_text": _build_text(t),
                    "severity_seen": ", ".join(t.get("severity_seen", []) or []),
                    "source_episode_id": t.get("source_episode_id", ""),
                    "_raw_ticket": t,
                }
                tickets.append(t_pruned)
        log.info("tickets loaded", n=len(tickets))

    if args.limit > 0:
        tickets = tickets[: args.limit]
        log.info("limiting to first N", n=len(tickets))

    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model)
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(
            f"LM Studio is not reachable at {args.lm_studio_url}. "
            "Start LM Studio's local server and load a model first."
        )
    log.info("LM Studio reachable", url=args.lm_studio_url)

    extractions = batch_extract_tickets(
        client,
        tickets,
        cache_dir=cache_dir,
        text_field="memory_text",
        id_field="ticket_id",
        severity_field="severity_seen",
        timestamp_field="source_episode_id",
        family_extractor=lambda t: _family_from_episode(t.get("_raw_ticket", {})),
        progress_every=10,
    )

    # Summary stats
    n_with_services = sum(1 for e in extractions if e.affected_services)
    n_with_errors = sum(1 for e in extractions if e.error_classes)
    n_with_root_cause = sum(1 for e in extractions if e.root_cause)
    n_with_symptoms = sum(1 for e in extractions if e.symptoms)
    n_empty = sum(1 for e in extractions if not (e.affected_services or e.error_classes or e.root_cause or e.symptoms))
    log.info(
        "extraction summary",
        total=len(extractions),
        with_services=n_with_services,
        with_errors=n_with_errors,
        with_root_cause=n_with_root_cause,
        with_symptoms=n_with_symptoms,
        empty=n_empty,
    )

    # Also write a single consolidated JSONL for convenience.
    consolidated = cache_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext.as_dict()) + "\n")
    log.info("consolidated extractions written", path=str(consolidated))


if __name__ == "__main__":
    main()
