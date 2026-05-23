"""Load the v4 global dataset off disk into typed dataclasses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .schema import JiraMemoryIssue, MemoryMatch, SplitManifest, TriageWindow


def _read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_global_triage_examples(global_dir: Path) -> list[TriageWindow]:
    return [TriageWindow.from_row(row) for row in _read_jsonl(global_dir / "global-triage-examples.jsonl")]


def load_memory_corpus(global_dir: Path) -> list[JiraMemoryIssue]:
    return [JiraMemoryIssue.from_row(row) for row in _read_jsonl(global_dir / "jira-memory-corpus.jsonl")]


def load_window_memory_matchings(global_dir: Path) -> dict[str, MemoryMatch]:
    rows = _read_jsonl(global_dir / "window-memory-matchings.jsonl")
    return {row["window_id"]: MemoryMatch.from_row(row) for row in rows}


def load_split_manifest(global_dir: Path) -> SplitManifest:
    with (global_dir / "triage-split-manifest.json").open("r", encoding="utf-8") as fh:
        return SplitManifest.from_row(json.load(fh))


def load_feature_columns(global_dir: Path) -> list[str]:
    with (global_dir / "triage-feature-columns.json").open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    return list(manifest["feature_columns"])


@dataclass
class LoadedDataset:
    """Everything one call site needs to train + evaluate the analyzer."""

    global_dir: Path
    feature_columns: list[str]
    split_manifest: SplitManifest
    windows: list[TriageWindow]
    memory_corpus: list[JiraMemoryIssue]
    matchings: dict[str, MemoryMatch] = field(default_factory=dict)

    def attach_matchings(self) -> None:
        """Copy is_novel + matched_memory_issue_ids from matchings onto windows."""
        for w in self.windows:
            match = self.matchings.get(w.window_id)
            if match is None:
                continue
            w.matched_memory_issue_ids = list(match.matched_memory_issue_ids)
            w.is_novel = match.is_novel
            w.fault_compatibility_class = match.fault_compatibility_class


def load_dataset(global_dir: str | Path) -> LoadedDataset:
    """One-shot loader for the global derived directory."""
    global_dir = Path(global_dir)
    if not global_dir.is_dir():
        raise FileNotFoundError(f"Global derived dir not found: {global_dir}")
    ds = LoadedDataset(
        global_dir=global_dir,
        feature_columns=load_feature_columns(global_dir),
        split_manifest=load_split_manifest(global_dir),
        windows=load_global_triage_examples(global_dir),
        memory_corpus=load_memory_corpus(global_dir),
        matchings=load_window_memory_matchings(global_dir),
    )
    ds.attach_matchings()
    return ds
