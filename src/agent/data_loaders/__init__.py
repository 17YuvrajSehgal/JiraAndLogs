"""Dataset loaders — produce `EvaluationCase`s from on-disk artifacts.

One loader per dataset; each knows the directory layout + filename
conventions for its source data. The output is always a list of
`EvaluationCase` the harness can consume.

Available loaders:
  - `load_ob_cases` — Online Boutique (telemetry + synthetic Jira).
  - `load_otel_demo_cases` — OpenTelemetry Demo (polyglot telemetry).
  - `load_wol_cases` — World-of-Logs (real Apache Jira tickets, no
    telemetry; sets `extra={}` so the 3 telemetry tools auto-drop).

Each loader is also responsible for setting the right `bundle.extra`
markers (`k8s_events_fetchable`, `trace_summary_fetchable`,
`metric_snapshots_fetchable`) so the CapabilitiesObserver fires the
right flags for ReAct-tool fetchability.
"""

from .ob_loader import load_ob_cases
from .otel_demo_loader import load_otel_demo_cases
from .window_extractions import (
    DEFAULT_RELATIVE_PATH as WINDOW_EXTRACTIONS_DEFAULT_PATH,
    WindowEntities,
    WindowExtractionsStore,
)
from .wol_loader import WOL_PREDICTIONS_PATHS, load_wol_cases

__all__ = [
    "load_ob_cases",
    "load_otel_demo_cases",
    "load_wol_cases",
    "WOL_PREDICTIONS_PATHS",
    "WindowEntities",
    "WindowExtractionsStore",
    "WINDOW_EXTRACTIONS_DEFAULT_PATH",
]
