"""Aggregate a per-call telemetry JSONL into an experiment summary.

Reads `data/llm_telemetry/<experiment>.jsonl` (produced by `TokenLogger`)
and emits `<experiment>.summary.json` with totals, per-skill +
per-provider breakdown, and monetary equivalents at hosted-model rates.

The paper's "Compute resources" subsection consumes these summaries
directly — one row per experiment.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .cost_table import lookup as lookup_cost, monetary_equivalent_baselines


def load_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Read all per-call records from a JSONL telemetry file."""
    if not jsonl_path.exists():
        return []
    records = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                # Don't let one bad line kill the summary; record it.
                records.append({
                    "_parse_error": True,
                    "_lineno": lineno,
                    "_error": str(e)[:200],
                })
    return records


def summarise(jsonl_path: Path) -> dict[str, Any]:
    """Build a summary dict from one experiment's JSONL.

    Returns a JSON-serialisable dict with these top-level keys:
        experiment, started_at, finished_at, wall_seconds,
        n_calls, n_failed, n_parse_errors,
        total_prompt_tokens, total_completion_tokens, total_tokens,
        total_cost_usd,
        per_skill[{skill}], per_provider[{provider}],
        monetary_equivalent_usd[{provider:model}]
    """
    records = load_records(jsonl_path)
    valid = [r for r in records if not r.get("_parse_error")]
    parse_errors = [r for r in records if r.get("_parse_error")]

    if not valid:
        return {
            "experiment": jsonl_path.stem,
            "n_calls": 0,
            "n_parse_errors": len(parse_errors),
            "note": "no valid records",
        }

    # Totals
    total_prompt = sum(int(r.get("prompt_tokens", 0)) for r in valid)
    total_completion = sum(int(r.get("completion_tokens", 0)) for r in valid)
    total_cost = sum(float(r.get("cost_usd", 0.0)) for r in valid)
    n_failed = sum(1 for r in valid if not r.get("success", False))

    # Timestamps for wall-clock
    started_at, finished_at, wall_seconds = _compute_wallclock(valid)

    # Per-skill breakdown
    per_skill: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "n_calls": 0, "n_failed": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "total_latency_ms": 0,
    })
    for r in valid:
        s = r.get("skill") or "<unspecified>"
        per_skill[s]["n_calls"] += 1
        if not r.get("success", False):
            per_skill[s]["n_failed"] += 1
        per_skill[s]["prompt_tokens"] += int(r.get("prompt_tokens", 0))
        per_skill[s]["completion_tokens"] += int(r.get("completion_tokens", 0))
        per_skill[s]["total_tokens"] += int(r.get("total_tokens", 0)) or (
            int(r.get("prompt_tokens", 0)) + int(r.get("completion_tokens", 0))
        )
        per_skill[s]["cost_usd"] += float(r.get("cost_usd", 0.0))
        per_skill[s]["total_latency_ms"] += int(r.get("latency_ms", 0))

    # Round costs for readability
    for s in per_skill:
        per_skill[s]["cost_usd"] = round(per_skill[s]["cost_usd"], 6)

    # Per-provider breakdown
    per_provider: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "n_calls": 0,
        "prompt_tokens": 0, "completion_tokens": 0,
        "cost_usd": 0.0,
    })
    for r in valid:
        p = r.get("provider") or "<unspecified>"
        per_provider[p]["n_calls"] += 1
        per_provider[p]["prompt_tokens"] += int(r.get("prompt_tokens", 0))
        per_provider[p]["completion_tokens"] += int(r.get("completion_tokens", 0))
        per_provider[p]["cost_usd"] += float(r.get("cost_usd", 0.0))
    for p in per_provider:
        per_provider[p]["cost_usd"] = round(per_provider[p]["cost_usd"], 6)

    # Monetary equivalents at hosted-model rates
    equivalents: dict[str, float] = {}
    for baseline in monetary_equivalent_baselines():
        key = f"{baseline.provider}:{baseline.model}"
        equivalents[key] = round(
            baseline.cost_usd(total_prompt, total_completion), 4,
        )

    return {
        "experiment": jsonl_path.stem,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_seconds": wall_seconds,
        "n_calls": len(valid),
        "n_failed": n_failed,
        "n_parse_errors": len(parse_errors),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": round(total_cost, 6),
        "per_skill": dict(per_skill),
        "per_provider": dict(per_provider),
        "monetary_equivalent_usd": equivalents,
    }


def write_summary(
    jsonl_path: Path,
    output_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Compute summary; write to `<stem>.summary.json` next to the JSONL.

    Returns (output_path, summary_dict)."""
    summary = summarise(jsonl_path)
    if output_path is None:
        output_path = jsonl_path.parent / f"{jsonl_path.stem}.summary.json"
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return output_path, summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_wallclock(records: list[dict]) -> tuple[str | None, str | None, float]:
    """Return (started_at_iso, finished_at_iso, wall_seconds).

    If timestamps are absent / unparseable, falls back to sum of latencies
    as a wall_seconds approximation (with a clear cap).
    """
    timestamps = []
    for r in records:
        ts = r.get("ts")
        if not ts:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
        except ValueError:
            continue
    if timestamps:
        t_min = min(timestamps)
        t_max = max(timestamps)
        return (
            t_min.isoformat(timespec="milliseconds"),
            t_max.isoformat(timespec="milliseconds"),
            round((t_max - t_min).total_seconds(), 1),
        )
    # Fallback: use latencies (lower bound on wall time)
    total_ms = sum(int(r.get("latency_ms", 0)) for r in records)
    return None, None, round(total_ms / 1000.0, 1)
