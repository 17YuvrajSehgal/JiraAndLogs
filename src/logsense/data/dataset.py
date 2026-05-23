"""Glue: load the v4 global triage labels, then load matching raw Loki
files for each window, and bundle them with the existing memory corpus
and split manifest from loganalyzer.

We deliberately reuse loganalyzer.data.loaders so the source of truth for
labels/splits/memory stays one place across both packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loganalyzer.data.loaders import (
    load_global_triage_examples,
    load_memory_corpus,
    load_split_manifest,
    load_window_memory_matchings,
)
from loganalyzer.data.schema import (
    JiraMemoryIssue,
    MemoryMatch,
    SplitManifest,
    TriageWindow,
)

from .loaders import load_window_logs
from .schema import LabeledWindowLogs


@dataclass
class LogsDataset:
    """Everything the logsense layer needs in memory.

    .labeled_windows skips windows whose raw Loki file isn't on disk - the
    caller decides whether to tolerate partial coverage (a v4-large run
    will have ~3700 windows; missing a handful shouldn't block training).
    """

    global_dir: Path
    runs_root: Path
    split_manifest: SplitManifest
    memory_corpus: list[JiraMemoryIssue]
    matchings: dict[str, MemoryMatch]
    labeled_windows: list[LabeledWindowLogs] = field(default_factory=list)
    missing_window_ids: list[str] = field(default_factory=list)

    def by_split(self, split: str) -> list[LabeledWindowLogs]:
        return [
            lw for lw in self.labeled_windows
            if self.split_manifest.split_of(lw.scenario_family) == split
        ]


def _bind_matchings(window: TriageWindow, match: MemoryMatch | None) -> None:
    if match is None:
        return
    window.matched_memory_issue_ids = list(match.matched_memory_issue_ids)
    window.is_novel = match.is_novel
    window.fault_compatibility_class = match.fault_compatibility_class


def load_logs_dataset(
    global_dir: str | Path,
    runs_root: str | Path,
    *,
    skip_namespace_context: bool = True,
    progress_every: int = 0,
) -> LogsDataset:
    """Load every window's raw Loki logs and attach the triage label.

    skip_namespace_context: drop the namespace-wide context streams to keep
    memory bounded - we mostly only need the labeled service's own logs for
    triage. Flip to False if you want broader cross-service log signal.
    progress_every: if > 0, print "loaded N/total" every N windows.
    """
    global_dir = Path(global_dir)
    runs_root = Path(runs_root)

    triage_windows = load_global_triage_examples(global_dir)
    memory_corpus = load_memory_corpus(global_dir)
    matchings = load_window_memory_matchings(global_dir)
    split_manifest = load_split_manifest(global_dir)

    labeled: list[LabeledWindowLogs] = []
    missing: list[str] = []
    total = len(triage_windows)
    for i, tw in enumerate(triage_windows):
        _bind_matchings(tw, matchings.get(tw.window_id))
        logs = load_window_logs(
            tw.window_id,
            dataset_run_id=tw.dataset_run_id,
            incident_episode_id=tw.incident_episode_id,
            service_name=tw.service_name,
            window_type=tw.window_type,
            start_time=tw.start_time,
            end_time=tw.end_time,
            runs_root=runs_root,
        )
        if logs is None:
            missing.append(tw.window_id)
            continue
        if skip_namespace_context:
            logs.namespace_lines = []
        labeled.append(LabeledWindowLogs(logs=logs, label=tw))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"loaded {i + 1}/{total} windows ({len(missing)} missing)")

    return LogsDataset(
        global_dir=global_dir,
        runs_root=runs_root,
        split_manifest=split_manifest,
        memory_corpus=memory_corpus,
        matchings=matchings,
        labeled_windows=labeled,
        missing_window_ids=missing,
    )
