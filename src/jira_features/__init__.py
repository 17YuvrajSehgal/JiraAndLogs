"""jira_features - per-window features derived from the Jira-as-memory corpus.

This is the foundational layer for every Jira-aware triage model. Given a
window and the visible-at-that-time memory corpus, it produces a fixed-size
numeric feature vector summarising "how does this window look against
prior Jira tickets?".

Time-ordering is enforced via loganalyzer.memory.corpus.MemoryCorpus -
the featurizer never sees an issue created at or after the window's
start_time, and never sees an issue from the window's own dataset_run_id.
That contract is the same one used by the live retriever; production-safe
by construction.

Public entrypoint: JiraMemoryFeaturizer.
"""

from .featurizer import (
    JIRA_FEATURE_COLUMNS,
    JIRA_FEATURE_DESCRIPTIONS,
    JiraMemoryFeaturizer,
)

__all__ = [
    "JIRA_FEATURE_COLUMNS",
    "JIRA_FEATURE_DESCRIPTIONS",
    "JiraMemoryFeaturizer",
]
__version__ = "0.1.0"
