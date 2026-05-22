#!/usr/bin/env python3
"""
Build per-run triage examples from a validated research-lab run.

Reads:
  data/runs/<DATASET_RUN_ID>/telemetry_windows.jsonl
  data/runs/<DATASET_RUN_ID>/episodes.jsonl
  deploy/research-lab/scenarios/**/*.yaml          (optional, for authored
                                                    triage block)

Writes:
  data/derived/<DATASET_RUN_ID>/triage_examples.jsonl
  data/derived/<DATASET_RUN_ID>/triage_window_labels.jsonl  (labels only,
                                                             matches the
                                                             TriageWindowLabel
                                                             schema)
  data/derived/<DATASET_RUN_ID>/triage_build_manifest.json

The contract this satisfies lives in docs/triage-task-contract.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from triage_labels import (
    SCRIPT_VERSION,
    build_triage_label_record,
    numeric_features_for_window,
    read_jsonl,
    repo_root_from_script,
    utc_now,
    write_json,
    write_jsonl,
)


def build_triage_dataset(
    repo_root: Path,
    dataset_run_id: str,
    output_root: Path | None = None,
    scenarios_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    runs_root = repo_root / "data" / "runs"
    run_dir = runs_root / dataset_run_id
    if not run_dir.exists():
        raise FileNotFoundError(
            f"Raw run not found at {run_dir}. Collect the run first with "
            f"start-dataset-run.ps1 and run-scenario.ps1."
        )

    if output_root is None:
        output_root = repo_root / "data" / "derived"
    out_dir = output_root / dataset_run_id

    examples_path = out_dir / "triage_examples.jsonl"
    labels_path = out_dir / "triage_window_labels.jsonl"
    manifest_path = out_dir / "triage_build_manifest.json"

    if examples_path.exists() and not force:
        raise FileExistsError(
            f"{examples_path} already exists. Re-run with --force to overwrite."
        )

    if scenarios_root is None:
        scenarios_root = repo_root / "deploy" / "research-lab" / "scenarios"

    windows = read_jsonl(run_dir / "telemetry_windows.jsonl")
    episodes = read_jsonl(run_dir / "episodes.jsonl")
    episode_by_id: dict[str, dict[str, Any]] = {
        str(e.get("incident_episode_id")): e for e in episodes if e.get("incident_episode_id")
    }

    label_records: list[dict[str, Any]] = []
    example_records: list[dict[str, Any]] = []

    label_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    for window in windows:
        episode_id = window.get("incident_episode_id")
        episode = episode_by_id.get(str(episode_id)) if episode_id else None
        label_record = build_triage_label_record(
            window=window,
            episode=episode,
            scenarios_root=scenarios_root,
            dataset_run_id=dataset_run_id,
        )
        label_records.append(label_record)
        label_counts[label_record["triage_label"]] = (
            label_counts.get(label_record["triage_label"], 0) + 1
        )
        source_counts[label_record["source"]] = (
            source_counts.get(label_record["source"], 0) + 1
        )

        features = numeric_features_for_window(window, episode, run_dir=run_dir)
        example_record: dict[str, Any] = {
            "window_id": label_record["telemetry_window_id"],
            "dataset_run_id": dataset_run_id,
            "incident_episode_id": label_record["incident_episode_id"],
            "scenario_id": label_record["scenario_id"],
            "scenario_family": label_record["scenario_family"],
            "window_type": label_record["window_type"],
            "service_name": window.get("service_name"),
            "start_time": window.get("start_time"),
            "end_time": window.get("end_time"),
            "triage_label": label_record["triage_label"],
            "triage_severity": label_record["triage_severity"],
            "triage_components": label_record["triage_components"],
            "triage_reason_class": label_record["triage_reason_class"],
            "is_hard_case": label_record["is_hard_case"],
            "source": label_record["source"],
            **features,
        }
        example_records.append(example_record)

    write_jsonl(labels_path, label_records)
    write_jsonl(examples_path, example_records)

    manifest = {
        "schema_version": 1,
        "builder": "build_triage_dataset.py",
        "builder_version": SCRIPT_VERSION,
        "dataset_run_id": dataset_run_id,
        "generated_at": utc_now(),
        "input_window_count": len(windows),
        "output_label_count": len(label_records),
        "output_example_count": len(example_records),
        "label_counts": label_counts,
        "source_counts": source_counts,
        "outputs": {
            "triage_examples": str(examples_path.relative_to(repo_root).as_posix()),
            "triage_window_labels": str(labels_path.relative_to(repo_root).as_posix()),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", required=True, help="Run id under data/runs/.")
    parser.add_argument(
        "--output-root",
        default=None,
        help="Override the derived output root (default: data/derived/).",
    )
    parser.add_argument(
        "--scenarios-root",
        default=None,
        help="Override the scenarios root (default: deploy/research-lab/scenarios/).",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs.")
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    output_root = Path(args.output_root) if args.output_root else None
    scenarios_root = Path(args.scenarios_root) if args.scenarios_root else None

    manifest = build_triage_dataset(
        repo_root=repo_root,
        dataset_run_id=args.dataset_run_id,
        output_root=output_root,
        scenarios_root=scenarios_root,
        force=args.force,
    )
    print(
        f"Wrote {manifest['output_example_count']} triage examples for "
        f"{args.dataset_run_id}. Labels: {manifest['label_counts']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())