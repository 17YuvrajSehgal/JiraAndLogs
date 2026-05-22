#!/usr/bin/env python3
"""
Build the global triage dataset by stitching per-run triage examples and
memory matchings into a single corpus with scenario-family splits.

Reads:
  data/derived/<prefix>*/triage_examples.jsonl
  data/derived/<prefix>*/window_memory_matchings.jsonl
  data/derived/global/<GLOBAL_DATASET_ID>/jira-memory-corpus.jsonl

Writes:
  data/derived/global/<GLOBAL_DATASET_ID>/global-triage-examples.jsonl
  data/derived/global/<GLOBAL_DATASET_ID>/window-memory-matchings.jsonl
  data/derived/global/<GLOBAL_DATASET_ID>/triage-split-manifest.json
  data/derived/global/<GLOBAL_DATASET_ID>/triage-feature-columns.json
  data/derived/global/<GLOBAL_DATASET_ID>/global-triage-build-manifest.json

Splits hold out scenario families, not runs. See
docs/triage-task-contract.md and docs/dataset-v4-plan.md.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from triage_labels import (
    SCRIPT_VERSION,
    read_jsonl,
    repo_root_from_script,
    utc_now,
    write_json,
    write_jsonl,
)


def _family_split_assignment(
    families: list[str],
    explicit_train: list[str] | None,
    explicit_validation: list[str] | None,
    explicit_test: list[str] | None,
) -> dict[str, str]:
    """Assign each scenario family to train/validation/test. Honors explicit
    overrides; otherwise uses a deterministic hash-based assignment biased
    toward train.

    Hash assignment: hash(family) modulo 10
      0,1  -> test
      2,3  -> validation
      4..9 -> train
    """
    assignment: dict[str, str] = {}
    explicit_train_set = set(explicit_train or [])
    explicit_validation_set = set(explicit_validation or [])
    explicit_test_set = set(explicit_test or [])

    for family in sorted(set(families)):
        if family in explicit_test_set:
            assignment[family] = "test"
        elif family in explicit_validation_set:
            assignment[family] = "validation"
        elif family in explicit_train_set:
            assignment[family] = "train"
        else:
            bucket = int(hashlib.sha256(family.encode("utf-8")).hexdigest(), 16) % 10
            if bucket < 2:
                assignment[family] = "test"
            elif bucket < 4:
                assignment[family] = "validation"
            else:
                assignment[family] = "train"
    return assignment


def _validate_no_family_overlap(assignment: dict[str, str]) -> None:
    """Triage families must appear in exactly one split. Detect accidental
    overlap from misconfiguration."""
    seen: dict[str, str] = {}
    for family, split in assignment.items():
        prior = seen.get(family)
        if prior is not None and prior != split:
            raise ValueError(
                f"Scenario family '{family}' assigned to both '{prior}' and '{split}'."
            )
        seen[family] = split


def _feature_columns(examples: list[dict[str, Any]]) -> list[str]:
    """Collect the production-safe numeric feature column names from the
    per-run triage examples. Conservative: only fields starting with
    'triage_feature_' are exposed as model inputs."""
    seen: set[str] = set()
    columns: list[str] = []
    for example in examples:
        for key in example:
            if key.startswith("triage_feature_") and key not in seen:
                columns.append(key)
                seen.add(key)
    return sorted(columns)


def build_global_triage_dataset(
    repo_root: Path,
    dataset_run_prefix: str,
    global_dataset_id: str,
    derived_root: Path | None = None,
    train_families: list[str] | None = None,
    validation_families: list[str] | None = None,
    test_families: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if derived_root is None:
        derived_root = repo_root / "data" / "derived"
    global_dir = derived_root / "global" / global_dataset_id

    examples_path = global_dir / "global-triage-examples.jsonl"
    matchings_path = global_dir / "window-memory-matchings.jsonl"
    split_path = global_dir / "triage-split-manifest.json"
    features_path = global_dir / "triage-feature-columns.json"
    manifest_path = global_dir / "global-triage-build-manifest.json"

    if examples_path.exists() and not force:
        raise FileExistsError(
            f"{examples_path} already exists. Re-run with --force to overwrite."
        )

    matched_run_dirs = sorted(
        path
        for path in derived_root.glob(f"{dataset_run_prefix}*")
        if path.is_dir() and (path / "triage_examples.jsonl").exists()
    )

    all_examples: list[dict[str, Any]] = []
    all_matchings: list[dict[str, Any]] = []
    per_run_counts: dict[str, dict[str, int]] = {}

    for run_dir in matched_run_dirs:
        dataset_run_id = run_dir.name
        examples = read_jsonl(run_dir / "triage_examples.jsonl")
        matchings = read_jsonl(run_dir / "window_memory_matchings.jsonl")
        all_examples.extend(examples)
        all_matchings.extend(matchings)
        per_run_counts[dataset_run_id] = {
            "examples": len(examples),
            "matchings": len(matchings),
        }

    if not all_examples:
        print(
            f"warning: no per-run triage_examples found under {derived_root} "
            f"matching prefix '{dataset_run_prefix}'. Writing empty global outputs.",
            file=sys.stderr,
        )

    families = [str(e.get("scenario_family") or "unknown") for e in all_examples]
    family_split = _family_split_assignment(
        families,
        explicit_train=train_families,
        explicit_validation=validation_families,
        explicit_test=test_families,
    )
    _validate_no_family_overlap(family_split)

    label_counts_by_split: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for example in all_examples:
        family = str(example.get("scenario_family") or "unknown")
        split = family_split.get(family, "train")
        example["split"] = split
        label = str(example.get("triage_label", "noise"))
        label_counts_by_split[split][label] += 1

    feature_columns = _feature_columns(all_examples)

    write_jsonl(examples_path, all_examples)
    write_jsonl(matchings_path, all_matchings)

    split_manifest = {
        "schema_version": 1,
        "global_dataset_id": global_dataset_id,
        "split_by": "scenario_family",
        "family_assignment": family_split,
        "leave_one_family_out_folds": [
            {"fold_id": f"loo-{family}", "held_out_family": family}
            for family in sorted(set(families))
            if family and family != "unknown"
        ],
        "label_counts_by_split": {
            split: dict(counts) for split, counts in label_counts_by_split.items()
        },
        "generated_at": utc_now(),
    }
    write_json(split_path, split_manifest)

    write_json(
        features_path,
        {
            "schema_version": 1,
            "feature_columns": feature_columns,
            "policy": "All fields prefixed with triage_feature_ are model inputs. Other fields are eval-only.",
            "eval_only_fields": [
                "scenario_id",
                "scenario_family",
                "triage_label",
                "triage_severity",
                "triage_components",
                "triage_reason_class",
                "is_hard_case",
                "source",
                "is_novel",
                "matched_memory_issue_ids",
                "triage_evidence_text",
            ],
        },
    )

    manifest = {
        "schema_version": 1,
        "builder": "build_global_triage_dataset.py",
        "builder_version": SCRIPT_VERSION,
        "dataset_run_prefix": dataset_run_prefix,
        "global_dataset_id": global_dataset_id,
        "generated_at": utc_now(),
        "matched_run_count": len(matched_run_dirs),
        "matched_run_ids": [r.name for r in matched_run_dirs],
        "per_run_counts": per_run_counts,
        "global_example_count": len(all_examples),
        "global_matching_count": len(all_matchings),
        "family_count": len(set(families)),
        "feature_column_count": len(feature_columns),
        "outputs": {
            "global_triage_examples": str(examples_path.relative_to(repo_root).as_posix()),
            "window_memory_matchings": str(matchings_path.relative_to(repo_root).as_posix()),
            "triage_split_manifest": str(split_path.relative_to(repo_root).as_posix()),
            "triage_feature_columns": str(features_path.relative_to(repo_root).as_posix()),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-prefix", required=True)
    parser.add_argument("--global-dataset-id", required=True)
    parser.add_argument("--derived-root", default=None)
    parser.add_argument(
        "--train-families",
        nargs="*",
        default=None,
        help="Override: families forced to the train split.",
    )
    parser.add_argument("--validation-families", nargs="*", default=None)
    parser.add_argument("--test-families", nargs="*", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    derived_root = Path(args.derived_root) if args.derived_root else None

    manifest = build_global_triage_dataset(
        repo_root=repo_root,
        dataset_run_prefix=args.dataset_run_prefix,
        global_dataset_id=args.global_dataset_id,
        derived_root=derived_root,
        train_families=args.train_families,
        validation_families=args.validation_families,
        test_families=args.test_families,
        force=args.force,
    )
    print(
        f"Wrote {manifest['global_example_count']} triage examples across "
        f"{manifest['family_count']} scenario families from "
        f"{manifest['matched_run_count']} runs."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())