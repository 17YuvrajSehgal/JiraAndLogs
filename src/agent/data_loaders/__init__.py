"""Dataset loaders — produce `EvaluationCase`s from on-disk artifacts.

Three datasets are supported (or will be); each gets its own loader that
knows the directory layout + filename conventions. The output is always
a list of `EvaluationCase` the harness can consume.

Available loaders:
  - `load_ob_cases` — Online Boutique (`<global_dir>/global-triage-examples.jsonl`
    + `comparison/v2a-resplit/per-window-predictions.jsonl` for gold).

OTel Demo + WoL loaders will land in Phase 2.
"""

from .ob_loader import load_ob_cases
from .otel_demo_loader import load_otel_demo_cases
from .wol_loader import WOL_PREDICTIONS_PATHS, load_wol_cases

__all__ = [
    "load_ob_cases",
    "load_otel_demo_cases",
    "load_wol_cases",
    "WOL_PREDICTIONS_PATHS",
]
