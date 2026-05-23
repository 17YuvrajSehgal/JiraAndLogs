"""Data layer: schemas + jsonl loaders + split iteration."""

from .schema import TriageWindow, JiraMemoryIssue, MemoryMatch, SplitManifest
from .loaders import (
    load_global_triage_examples,
    load_memory_corpus,
    load_window_memory_matchings,
    load_split_manifest,
    load_feature_columns,
    load_dataset,
    LoadedDataset,
)
from .splits import iter_split, iter_lofo_folds

__all__ = [
    "TriageWindow",
    "JiraMemoryIssue",
    "MemoryMatch",
    "SplitManifest",
    "LoadedDataset",
    "load_global_triage_examples",
    "load_memory_corpus",
    "load_window_memory_matchings",
    "load_split_manifest",
    "load_feature_columns",
    "load_dataset",
    "iter_split",
    "iter_lofo_folds",
]
