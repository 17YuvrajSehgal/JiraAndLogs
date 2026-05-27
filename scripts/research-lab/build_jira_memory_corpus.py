#!/usr/bin/env python3
"""
Build the time-ordered Jira memory corpus across all runs that match a
dataset run prefix.

The memory corpus is the system memory the Jira-as-memory architecture
retrieves from. Each issue carries `available_as_memory_from` so evaluation
can enforce time-ordering (a window can only retrieve issues that existed
before the window's start time).

Reads:
  data/runs/<prefix>*/jira_shadow_issues.jsonl
  data/runs/<prefix>*/episodes.jsonl

Writes:
  data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-corpus.jsonl
  data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-build-manifest.json

The corpus and its rules live in docs/triage-task-contract.md and
docs/dataset-v4-plan.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from triage_labels import (
    SCRIPT_VERSION,
    fault_compatibility_class,
    read_jsonl,
    repo_root_from_script,
    scenario_family_for,
    utc_now,
    write_json,
    write_jsonl,
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def _first_nonempty(*candidates: Any) -> str | None:
    for candidate in candidates:
        text = _coerce_text(candidate).strip()
        if text:
            return text
    return None


def _memory_text(issue: dict[str, Any]) -> str:
    metadata = issue.get("metadata") or {}
    summary = _coerce_text(metadata.get("summary"))
    description = _coerce_text(metadata.get("description"))
    components = metadata.get("components") or []
    components_text = ", ".join(str(c) for c in components)
    labels = metadata.get("labels") or []
    labels_text = ", ".join(str(label) for label in labels)
    # comments_body may be a string (single blob, as our generator emits)
    # OR a list-of-strings (legacy schema). Handle both — splitting a
    # string on "---" lets us recover individual comments when the
    # humanizer (src/jira_humanizer/rewrite.py) has joined them with
    # `\n\n---\n\n` as separators. Take up to first 3 comments to keep
    # memory_text scannable.
    raw_comments = metadata.get("comments_body") or []
    comment_chunks: list[str] = []
    if isinstance(raw_comments, str):
        for chunk in raw_comments.split("\n---\n"):
            chunk = chunk.strip()
            if chunk:
                comment_chunks.append(chunk)
    elif isinstance(raw_comments, list):
        comment_chunks = [_coerce_text(c) for c in raw_comments if _coerce_text(c)]

    parts: list[str] = []
    if summary:
        parts.append(f"Summary: {summary}")
    if components_text:
        parts.append(f"Components: {components_text}")
    if labels_text:
        parts.append(f"Labels: {labels_text}")
    if description:
        parts.append(f"Description: {description}")
    for i, chunk in enumerate(comment_chunks[:3], start=1):
        # Cap each chunk length so a few long comments don't drown
        # description / labels in BM25 scoring.
        parts.append(f"Comment {i}: {chunk[:300]}")
    return "\n".join(parts)


def _resolution_notes(issue: dict[str, Any]) -> str | None:
    metadata = issue.get("metadata") or {}
    raw_comments = metadata.get("comments_body") or []
    if isinstance(raw_comments, str):
        chunks = [c.strip() for c in raw_comments.split("\n---\n") if c.strip()]
        if len(chunks) > 1:
            return chunks[-1][:300]
    elif isinstance(raw_comments, list) and len(raw_comments) > 1:
        return _coerce_text(raw_comments[-1])
    return _first_nonempty(metadata.get("resolution"), metadata.get("resolution_note"))


def _fault_type_for(episode: dict[str, Any] | None) -> str | None:
    if not episode:
        return None
    ground_truth = episode.get("ground_truth")
    if isinstance(ground_truth, dict) and ground_truth.get("fault_type"):
        return str(ground_truth["fault_type"])
    return None


def _affected_service_for(
    issue: dict[str, Any], episode: dict[str, Any] | None
) -> str | None:
    metadata = issue.get("metadata") or {}
    components = metadata.get("components") or []
    if components:
        return str(components[0])
    if episode:
        services = episode.get("affected_services") or []
        if services:
            return str(services[0])
    return None


def build_jira_memory_corpus(
    repo_root: Path,
    dataset_run_prefix: str,
    global_dataset_id: str,
    runs_root: Path | None = None,
    output_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if runs_root is None:
        runs_root = repo_root / "data" / "runs"
    if output_root is None:
        output_root = repo_root / "data" / "derived" / "global"
    out_dir = output_root / global_dataset_id
    corpus_path = out_dir / "jira-memory-corpus.jsonl"
    manifest_path = out_dir / "jira-memory-build-manifest.json"

    if corpus_path.exists() and not force:
        raise FileExistsError(
            f"{corpus_path} already exists. Re-run with --force to overwrite."
        )

    matched_runs = sorted(
        path for path in runs_root.glob(f"{dataset_run_prefix}*") if path.is_dir()
    )
    if not matched_runs:
        print(
            f"warning: no runs matched prefix '{dataset_run_prefix}' under {runs_root}. "
            f"Writing an empty corpus.",
            file=sys.stderr,
        )

    corpus_entries: list[dict[str, Any]] = []
    per_run_counts: dict[str, int] = {}
    skipped_no_created_at = 0

    for run_dir in matched_runs:
        dataset_run_id = run_dir.name
        issues = read_jsonl(run_dir / "jira_shadow_issues.jsonl")
        episodes = read_jsonl(run_dir / "episodes.jsonl")
        episode_by_id = {
            str(e.get("incident_episode_id")): e for e in episodes if e.get("incident_episode_id")
        }
        run_count = 0
        for issue in issues:
            metadata = issue.get("metadata") or {}
            created_at = metadata.get("created_at") or issue.get("created_at")
            if not created_at:
                skipped_no_created_at += 1
                continue
            episode_id = issue.get("incident_episode_id")
            episode = episode_by_id.get(str(episode_id)) if episode_id else None
            scenario_id = (
                str(episode.get("scenario_id")) if episode and episode.get("scenario_id") else None
            )
            fault_type = _fault_type_for(episode)
            entry = {
                "jira_shadow_issue_id": issue.get("jira_shadow_issue_id"),
                "jira_issue_key": issue.get("jira_issue_key"),
                "dataset_run_id": dataset_run_id,
                "incident_episode_id": episode_id,
                "scenario_id": scenario_id,
                "scenario_family": scenario_family_for(scenario_id),
                "affected_service": _affected_service_for(issue, episode),
                "fault_type": fault_type,
                "fault_compatibility_class": fault_compatibility_class(fault_type),
                "severity": (episode or {}).get("severity"),
                "available_as_memory_from": created_at,
                "memory_text": _memory_text(issue),
                "resolution_notes": _resolution_notes(issue),
                "linked_window_ids": list((episode or {}).get("telemetry_window_ids", []) or []),
                "linked_alert_fingerprints": list((episode or {}).get("alert_fingerprints", []) or []),
                "linked_trace_ids": list((episode or {}).get("trace_ids", []) or []),
            }
            corpus_entries.append(entry)
            run_count += 1
        per_run_counts[dataset_run_id] = run_count

    corpus_entries.sort(key=lambda e: (str(e.get("available_as_memory_from")), str(e.get("jira_shadow_issue_id"))))

    write_jsonl(corpus_path, corpus_entries)
    manifest = {
        "schema_version": 1,
        "builder": "build_jira_memory_corpus.py",
        "builder_version": SCRIPT_VERSION,
        "dataset_run_prefix": dataset_run_prefix,
        "global_dataset_id": global_dataset_id,
        "generated_at": utc_now(),
        "matched_run_count": len(matched_runs),
        "matched_run_ids": [r.name for r in matched_runs],
        "corpus_entry_count": len(corpus_entries),
        "per_run_entry_counts": per_run_counts,
        "skipped_issues_missing_created_at": skipped_no_created_at,
        "outputs": {
            "jira_memory_corpus": str(corpus_path.relative_to(repo_root).as_posix()),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-run-prefix",
        required=True,
        help="Run id prefix. All runs whose name starts with this prefix are included.",
    )
    parser.add_argument("--global-dataset-id", required=True, help="Global dataset id for the output directory.")
    parser.add_argument("--runs-root", default=None, help="Override the raw runs root.")
    parser.add_argument("--output-root", default=None, help="Override the derived global output root.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs.")
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    runs_root = Path(args.runs_root) if args.runs_root else None
    output_root = Path(args.output_root) if args.output_root else None

    manifest = build_jira_memory_corpus(
        repo_root=repo_root,
        dataset_run_prefix=args.dataset_run_prefix,
        global_dataset_id=args.global_dataset_id,
        runs_root=runs_root,
        output_root=output_root,
        force=args.force,
    )
    print(
        f"Wrote {manifest['corpus_entry_count']} Jira memory corpus entries "
        f"from {manifest['matched_run_count']} runs to {manifest['outputs']['jira_memory_corpus']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())