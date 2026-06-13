"""Cost table — loads `cost_table.yaml` and exposes `lookup(provider, model)`.

The table is loaded lazily on first access and cached. Re-import or
restart to pick up edits.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CostEntry:
    provider: str
    model: str
    input_per_M_usd: float
    output_per_M_usd: float
    note: str = ""

    def cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Compute USD cost for a single call given token counts."""
        return (
            prompt_tokens * self.input_per_M_usd / 1_000_000.0
            + completion_tokens * self.output_per_M_usd / 1_000_000.0
        )


_TABLE_PATH = Path(__file__).parent / "cost_table.yaml"


@lru_cache(maxsize=1)
def _load_table() -> tuple[list[CostEntry], list[str]]:
    """Parse cost_table.yaml. Returns (entries, equivalent_baselines)."""
    data = yaml.safe_load(_TABLE_PATH.read_text(encoding="utf-8"))
    entries = [
        CostEntry(
            provider=e["provider"],
            model=e["model"],
            input_per_M_usd=float(e["input_per_M_usd"]),
            output_per_M_usd=float(e["output_per_M_usd"]),
            note=e.get("note", ""),
        )
        for e in (data.get("entries") or [])
    ]
    baselines = list(data.get("equivalent_baselines") or [])
    return entries, baselines


def lookup(provider: str, model: str) -> CostEntry:
    """Find the cost entry for (provider, model).

    Falls back to a wildcard entry (model='*') if no exact match exists.
    If neither matches, returns a zero-cost entry with a `note` saying
    so — the caller's telemetry will record "unknown_cost".
    """
    entries, _ = _load_table()
    # Exact match first
    for e in entries:
        if e.provider == provider and e.model == model:
            return e
    # Wildcard fallback
    for e in entries:
        if e.provider == provider and e.model == "*":
            return e
    # Unknown
    return CostEntry(
        provider=provider, model=model,
        input_per_M_usd=0.0, output_per_M_usd=0.0,
        note=f"unknown_cost: (provider={provider!r}, model={model!r}) not in cost_table.yaml",
    )


def monetary_equivalent_baselines() -> list[CostEntry]:
    """Return the cost entries used to compute hosted-equivalent costs
    in the paper's 'Compute resources' subsection."""
    _, baselines = _load_table()
    out = []
    for spec in baselines:
        try:
            provider, model = spec.split(":", 1)
        except ValueError:
            continue
        entry = lookup(provider, model)
        # Only include real entries (non-zero); skip wildcard self-hosted ones
        if entry.input_per_M_usd > 0 or entry.output_per_M_usd > 0:
            out.append(entry)
    return out


def all_entries() -> list[CostEntry]:
    """Returns all parsed cost entries — used by tests + debug."""
    entries, _ = _load_table()
    return list(entries)
