#!/usr/bin/env python3
"""
Compute ground-truth memory-match labels for every telemetry window in a
dataset run.

For each window, finds the past Jira issues in the time-ordered memory
corpus that genuinely match — sharing scenario family, affected service,
and a compatible fault class — under the time-ordering and own-run
exclusion rules from docs/triage-task-contract.md.

Reads:
  data/runs/<DATASET_RUN_ID>/telemetry_windows.jsonl
  data/runs/<DATASET_RUN_ID>/episodes.jsonl
  data/derived/<DATASET_RUN_ID>/triage_examples.jsonl
  data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-corpus.jsonl

Writes:
  data/derived/<DATASET_RUN_ID>/window_memory_matchings.jsonl
  data/derived/<DATASET_RUN_ID>/window_memory_matchings_manifest.json
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


def compute_matches(
    window_start_time: str,
    window_run_id: str,
    window_family: str,
    window_affected_service: str | None,
    window_fault_class: str,
    corpus: list[dict[str, Any]],
) -> list[str]:
    """Return matched memory issue ids respecting time-ordering and
    own-run exclusion."""
    matched: list[str] = []
    if not window_start_time:
        return matched
    for entry in corpus:
        if entry.get("dataset_run_id") == window_run_id:
            continue  # own-run exclusion
        memory_from = entry.get("available_as_memory_from")
        if not memory_from or str(memory_from) >= str(window_start_time):
            continue  # time-ordering: memory must precede the window
        if entry.get("scenario_family") != window_family:
            continue
        if window_affected_service and entry.get("affected_service") != window_affected_service:
            continue
        if entry.get("fault_compatibility_class") != window_fault_class:
            continue
        issue_id = entry.get("jira_shadow_issue_id")
        if issue_id:
            matched.append(str(issue_id))
    return matched


def build_window_memory_matchings(
    repo_root: Path,
    dataset_run_id: str,
    global_dataset_id: str,
    runs_root: Path | None = None,
    derived_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if runs_root is None:
        runs_root = repo_root / "data" / "runs"
    if derived_root is None:
        derived_root = repo_root / "data" / "derived"

    run_dir = runs_root / dataset_run_id
    derived_run_dir = derived_root / dataset_run_id
    corpus_path = derived_root / "global" / global_dataset_id / "jira-memory-corpus.jsonl"
    out_path = derived_run_dir / "window_memory_matchings.jsonl"
    manifest_path = derived_run_dir / "window_memory_matchings_manifest.json"

    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists. Re-run with --force to overwrite."
        )
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"Memory corpus not found at {corpus_path}. Run "
            f"build_jira_memory_corpus.py first."
        )
    if not run_dir.exists():
        raise FileNotFoundError(
            f"Raw run not found at {run_dir}."
        )

    windows = read_jsonl(run_dir / "telemetry_windows.jsonl")
    episodes = read_jsonl(run_dir / "episodes.jsonl")
    episode_by_id = {
        str(e.get("incident_episode_id")): e for e in episodes if e.get("incident_episode_id")
    }
    triage_examples = read_jsonl(derived_run_dir / "triage_examples.jsonl")
    triage_by_window = {
        str(t.get("window_id")): t for t in triage_examples if t.get("window_id")
    }
    corpus = read_jsonl(corpus_path)

    out_records: list[dict[str, Any]] = []
    novel_count = 0
    matched_count = 0
    ticket_worthy_count = 0

    for window in windows:
        window_id = str(window.get("telemetry_window_id", window.get("window_id", "")))
        triage = triage_by_window.get(window_id) or {}
        episode_id = window.get("incident_episode_id")
        episode = episode_by_id.get(str(episode_id)) if episode_id else None
        scenario_id = (
            triage.get("scenario_id")
            or (episode or {}).get("scenario_id")
            or window.get("scenario_id")
        )
        family = triage.get("scenario_family") or scenario_family_for(scenario_id)
        affected_services = list((episode or {}).get("affected_services") or [])
        affected_service = affected_services[0] if affected_services else None
        fault_type = None
        ground_truth = (episode or {}).get("ground_truth")
        if isinstance(ground_truth, dict):
            fault_type = ground_truth.get("fault_type")
        fault_class = fault_compatibility_class(fault_type)

        triage_label = triage.get("triage_label", "noise")
        matches: list[str] = []
        is_novel = False

        if triage_label in {"ticket_worthy", "borderline"}:
            matches = compute_matches(
                window_start_time=str(window.get("start_time") or ""),
                window_run_id=dataset_run_id,
                window_family=family,
                window_affected_service=affected_service,
                window_fault_class=fault_class,
                corpus=corpus,
            )
            if triage_label == "ticket_worthy":
                ticket_worthy_count += 1
                if matches:
                    matched_count += 1
                else:
                    is_novel = True
                    novel_count += 1

        record = {
            "window_id": window_id,
            "dataset_run_id": dataset_run_id,
            "triage_label": triage_label,
            "scenario_family": family,
            "affected_service": affected_service,
            "fault_compatibility_class": fault_class,
            "matched_memory_issue_ids": matches,
            "is_novel": is_novel,
        }
        out_records.append(record)

    write_jsonl(out_path, out_records)
    manifest = {
        "schema_version": 1,
        "builder": "build_window_memory_matchings.py",
        "builder_version": SCRIPT_VERSION,
        "dataset_run_id": dataset_run_id,
        "global_dataset_id": global_dataset_id,
        "generated_at": utc_now(),
        "window_count": len(out_records),
        "ticket_worthy_count": ticket_worthy_count,
        "matched_count": matched_count,
        "novel_count": novel_count,
        "corpus_entry_count": len(corpus),
        "outputs": {
            "window_memory_matchings": str(out_path.relative_to(repo_root).as_posix()),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", required=True)
    parser.add_argument("--global-dataset-id", required=True)
    parser.add_argument("--runs-root", default=None)
    parser.add_argument("--derived-root", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    runs_root = Path(args.runs_root) if args.runs_root else None
    derived_root = Path(args.derived_root) if args.derived_root else None

    manifest = build_window_memory_matchings(
        repo_root=repo_root,
        dataset_run_id=args.dataset_run_id,
        global_dataset_id=args.global_dataset_id,
        runs_root=runs_root,
        derived_root=derived_root,
        force=args.force,
    )
    print(
        f"Wrote memory matchings for {manifest['window_count']} windows in "
        f"{args.dataset_run_id}: {manifest['ticket_worthy_count']} ticket-worthy, "
        f"{manifest['matched_count']} matched, {manifest['novel_count']} novel."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())