"""D0.2 human adjudication tooling.

Loads a borderline / hard-case telemetry window from a per-run derived
dataset, blanks the scenario-authored label, presents trace + log +
metric evidence to a reviewer, captures a human label back into
`triage_window_labels.jsonl` with `source: human_adjudicated`.

See `dataset-todo.md` Phase D0 and `docs/triage-task-contract.md`.
"""

__version__ = "0.1.0"
