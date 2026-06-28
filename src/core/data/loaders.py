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


def load_window_memory_matchings(
    global_dir: Path,
    *,
    filename: str = "window-memory-matchings.jsonl",
) -> dict[str, MemoryMatch]:
    """Load window→memory gold relation.

    Default = coarse-relation gold. Pass
    `filename="window-memory-matchings-strong.jsonl"` to load the
    strong-relation gold — closes RQ-A7 strong-match paper claim.
    WoL ships both files; OB ships coarse only.
    """
    rows = _read_jsonl(global_dir / filename)
    return {row["window_id"]: MemoryMatch.from_row(row) for row in rows}


def load_split_manifest(global_dir: Path) -> SplitManifest:
    with (global_dir / "triage-split-manifest.json").open("r", encoding="utf-8") as fh:
        manifest = SplitManifest.from_row(json.load(fh))
    # Prefer the per-window v2-resplit (OB/OTel). WoL ships no resplit, so it
    # keeps the family-based split. This makes the cascades/comparison evaluate
    # on the SAME per-window split the agent loaders + the paper use.
    resplit = global_dir / "triage-split-manifest-v2-resplit.json"
    if resplit.exists():
        try:
            wa = json.loads(resplit.read_text(encoding="utf-8")).get("window_assignment")
            if wa:
                manifest.window_assignment = {str(k): str(v) for k, v in wa.items()}
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # fall back to family-based split
    return manifest


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
        """Copy is_novel + matched_memory_issue_ids + expected_in_memory from matchings onto windows."""
        for w in self.windows:
            match = self.matchings.get(w.window_id)
            if match is None:
                continue
            w.matched_memory_issue_ids = list(match.matched_memory_issue_ids)
            w.is_novel = match.is_novel
            w.fault_compatibility_class = match.fault_compatibility_class
            # D12.3: orphan-fault ground truth flag.
            w.expected_in_memory = match.expected_in_memory


def load_dataset(
    global_dir: str | Path,
    *,
    matchings_file: str = "window-memory-matchings.jsonl",
) -> LoadedDataset:
    """One-shot loader for the global derived directory.

    `matchings_file` defaults to coarse-relation gold. Set to
    `"window-memory-matchings-strong.jsonl"` (env var
    `STRONG_RELATION=1` is also honored by cascade runners) to load
    the strong-relation gold for RQ-A7 closure.
    """
    import os as _os
    global_dir = Path(global_dir)
    if not global_dir.is_dir():
        raise FileNotFoundError(f"Global derived dir not found: {global_dir}")
    # Env-var override (so cascade runners can flip relations without
    # plumbing through every PipelineRunner signature).
    if _os.environ.get("STRONG_RELATION", "").strip() == "1":
        matchings_file = "window-memory-matchings-strong.jsonl"
    ds = LoadedDataset(
        global_dir=global_dir,
        feature_columns=load_feature_columns(global_dir),
        split_manifest=load_split_manifest(global_dir),
        windows=load_global_triage_examples(global_dir),
        memory_corpus=load_memory_corpus(global_dir),
        matchings=load_window_memory_matchings(global_dir, filename=matchings_file),
    )
    ds.attach_matchings()
    return ds
