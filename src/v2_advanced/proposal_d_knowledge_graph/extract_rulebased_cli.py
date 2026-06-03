"""Rule-based ticket extraction CLI — no LM Studio needed.

Produces the same on-disk format as `extract_tickets_cli.py` but uses
the deterministic rule-based extractor. Useful for:
  1. Running Phase D end-to-end without LM Studio.
  2. Establishing a "rules" baseline to compare against the LLM approach.

Usage:
    python -m v2_advanced.proposal_d_knowledge_graph.extract_rulebased_cli \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from v2_advanced.shared import get_logger, log_step
from .rule_extractor import extract_from_ticket_rules

log = get_logger("phase_d.extract_rules")


_FAMILY_SLUG = re.compile(r"-r\d+-(.+?)-202\d{5}T\d{6}Z")


def _family_from_episode(eid: str) -> str:
    m = _FAMILY_SLUG.search(eid or "")
    return m.group(1) if m else ""


def _build_text(t: dict) -> str:
    parts = []
    dc = (t.get("description_code") or "").strip()
    if dc:
        parts.append(dc)
    for step in t.get("timeline") or []:
        body = (step.get("text") or "").strip()
        if body:
            parts.append(body)
        bc = (step.get("body_code") or "").strip()
        if bc:
            parts.append(bc)
    return "\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    p.add_argument("--humanized-subdir", default="bulk-20260531")
    p.add_argument("--out", default="v2_kg_extractions_rules")
    args = p.parse_args()

    # IMPORTANT: we read via the humanized loader so each ticket gets the
    # SHADOW ID (jira_shadow_issue_id, the legacy stable identifier used
    # in gold matchings). The V2 timeline's "ticket_id" (HMN-...) doesn't
    # match the gold IDs and would cause every retrieval to miss.
    from memorygraph.humanized_loader import load_humanized_corpus
    issues = load_humanized_corpus(
        args.global_dir, humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
    )

    out_dir = args.global_dir / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ticket").mkdir(exist_ok=True)
    log.info("loaded humanized issues", n=len(issues))

    extractions = []
    with log_step(log, "rule_based_extract", n=len(issues)):
        for iss in issues:
            tid = iss.jira_shadow_issue_id           # the gold-matching ID
            text = iss.memory_text or ""
            sev = iss.severity or ""
            ep = iss.incident_episode_id or ""
            family = iss.scenario_family or _family_from_episode(ep)
            ext = extract_from_ticket_rules(
                ticket_id=tid, ticket_text=text,
                severity=sev, family=family, timestamp=ep,
            )
            extractions.append(ext)
            # Cache per-ticket for parity with LLM extractor
            (out_dir / "ticket" / f"{tid}.json").write_text(
                json.dumps(ext.as_dict(), indent=2), encoding="utf-8",
            )

    n_with_services = sum(1 for e in extractions if e.affected_services)
    n_with_errors = sum(1 for e in extractions if e.error_classes)
    n_with_root_cause = sum(1 for e in extractions if e.root_cause)
    n_with_symptoms = sum(1 for e in extractions if e.symptoms)
    log.info(
        "rule-based extraction complete",
        total=len(extractions),
        with_services=n_with_services,
        with_errors=n_with_errors,
        with_root_cause=n_with_root_cause,
        with_symptoms=n_with_symptoms,
    )

    consolidated = out_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext.as_dict()) + "\n")
    log.info("consolidated extractions written", path=str(consolidated))


if __name__ == "__main__":
    main()
