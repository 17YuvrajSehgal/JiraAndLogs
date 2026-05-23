"""Time-ordered Jira memory corpus.

Exposes the set of issues visible to a window at evaluation time, enforcing
the docs/dataset-v4-plan.md visibility rule:

    - available_as_memory_from < window.start_time, and
    - issue.dataset_run_id != window.dataset_run_id (own-run leakage block).

`corpus_mode="flat"` disables both filters for ablation runs only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..data.schema import JiraMemoryIssue, TriageWindow


def _parse_iso(ts: str) -> datetime:
    s = ts.replace("Z", "+00:00")
    if "+" in s[10:]:
        head, tz = s.rsplit("+", 1)
        if "." in head:
            base, frac = head.split(".", 1)
            head = f"{base}.{frac[:6]}"
        s = f"{head}+{tz}"
    elif "-" in s[10:]:
        head, _, tz = s.rpartition("-")
        if "." in head:
            base, frac = head.split(".", 1)
            head = f"{base}.{frac[:6]}"
        s = f"{head}-{tz}"
    return datetime.fromisoformat(s)


CorpusMode = Literal["time_ordered", "flat"]


@dataclass
class MemoryCorpus:
    issues: list[JiraMemoryIssue]
    mode: CorpusMode = "time_ordered"

    def visible_to(self, window: TriageWindow) -> list[JiraMemoryIssue]:
        if self.mode == "flat":
            return list(self.issues)
        window_start = _parse_iso(window.start_time)
        visible: list[JiraMemoryIssue] = []
        for issue in self.issues:
            if issue.dataset_run_id == window.dataset_run_id:
                continue
            if _parse_iso(issue.available_as_memory_from) >= window_start:
                continue
            visible.append(issue)
        return visible

    def by_id(self) -> dict[str, JiraMemoryIssue]:
        return {issue.jira_shadow_issue_id: issue for issue in self.issues}
