"""Split + leave-one-family-out iterators."""

from __future__ import annotations

from typing import Iterator

from .schema import SplitManifest, TriageWindow


def iter_split(
    windows: list[TriageWindow],
    manifest: SplitManifest,
    split: str,
) -> Iterator[TriageWindow]:
    """Yield only windows in the requested split (train|validation|test)."""
    for w in windows:
        if manifest.split_of(w.scenario_family) == split:
            yield w


def iter_lofo_folds(
    windows: list[TriageWindow],
    manifest: SplitManifest,
) -> Iterator[tuple[str, list[TriageWindow], list[TriageWindow]]]:
    """Yield (held_out_family, train_windows, eval_windows) for each LOFO fold.

    The eval set contains every window for the held-out family. The train set
    contains every other window, regardless of its train/val/test slot in
    the default split. This matches docs/dataset-v4-plan.md and the existing
    run_triage_benchmark.py LOFO implementation.
    """
    for family in manifest.leave_one_family_out_folds:
        train: list[TriageWindow] = []
        eval_: list[TriageWindow] = []
        for w in windows:
            (eval_ if w.scenario_family == family else train).append(w)
        if eval_:
            yield family, train, eval_
