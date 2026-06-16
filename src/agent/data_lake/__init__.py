"""Data lake — serves the ReAct tool requests from raw run files.

Per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5.2. Reads raw OB / OTel Demo
collection runs under `data/runs/` and `data/otel-demo-runs/`. Static
service dependencies for WoL aren't applicable (no live telemetry).

Public:
  - `RawRunDataLake` — main entry; constructed with a runs_root.
"""

from .raw_run import RawRunDataLake

__all__ = ["RawRunDataLake"]
