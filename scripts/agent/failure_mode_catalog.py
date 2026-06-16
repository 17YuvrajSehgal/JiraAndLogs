"""Build the failure-mode catalog from per-window traces.

Closes RQ-D6 (NEW): "what's the failure-mode distribution for tool-use
(hallucinated tools, empty responses, looping, budget exhaustion, tool
errors)?"

Reads a trace directory (`--trace-root`), walks every per-window JSON,
extracts every ToolResult, and aggregates failure modes by:
  - tool_name
  - failure_mode
  - per-window-vs-fleet (a window can have 0..N failures across its
    4 tool invocations)

Writes a JSON catalog with the per-tool histogram, plus per-mode
exemplar window_ids so a reviewer can sanity-check the categories.

Usage:
    PYTHONPATH=src python scripts/agent/failure_mode_catalog.py \\
        --trace-root data/agent_runs/v5/traces/smoke-2026-05-25-dataset-v5-large-global \\
        --output results/ob/3.6-failure-mode-catalog/catalog.json
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

# Allow `python scripts/agent/failure_mode_catalog.py` (no PYTHONPATH).
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.tool_protocol import FAILURE_MODES


log = logging.getLogger(__name__)


def _iter_tool_results(trace: dict) -> list[dict]:
    """Pull every ToolResult dict out of a per-window trace.

    Each `evidence_request` skill emits one ToolResult in the
    `skill_end` event's `output.extra.tool_result`.
    """
    out: list[dict] = []
    for ev in trace.get("events") or []:
        if ev.get("kind") != "skill_end":
            continue
        skill = ev.get("skill") or ""
        # Heuristic: evidence-request skills all start with "request_".
        # Could read the skill registry instead, but for catalog
        # purposes the prefix is a reliable filter.
        if not skill.startswith("request_"):
            continue
        out_dict = (ev.get("output") or {}).get("extra") or {}
        tr = out_dict.get("tool_result")
        if isinstance(tr, dict):
            out.append(tr)
    return out


def build_catalog(trace_root: Path) -> dict:
    """Scan trace_root and produce the catalog."""
    n_traces = 0
    n_tool_invocations = 0
    per_tool: dict[str, Counter] = defaultdict(Counter)        # tool -> {mode -> count}
    per_mode_examples: dict[str, list[dict]] = defaultdict(list)
    windows_with_any_failure: set[str] = set()
    windows_with_only_success: set[str] = set()
    all_windows: set[str] = set()

    for tf in sorted(trace_root.glob("*.json")):
        try:
            with open(tf, encoding="utf-8") as f:
                trace = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("skipping unreadable trace %s: %s", tf, e)
            continue
        n_traces += 1
        wid = trace.get("bundle_id") or tf.stem
        all_windows.add(wid)

        tool_results = _iter_tool_results(trace)
        if not tool_results:
            continue

        had_failure = False
        for tr in tool_results:
            n_tool_invocations += 1
            tool = str(tr.get("tool_name") or "unknown")
            mode = tr.get("failure_mode")
            if mode is None:
                per_tool[tool]["__success__"] += 1
                continue
            had_failure = True
            per_tool[tool][mode] += 1
            # Keep up to 3 exemplars per mode (with full context for review)
            if len(per_mode_examples[mode]) < 3:
                per_mode_examples[mode].append({
                    "window_id": wid,
                    "tool_name": tool,
                    "args": tr.get("args"),
                    "error": tr.get("error"),
                })

        if had_failure:
            windows_with_any_failure.add(wid)
        else:
            windows_with_only_success.add(wid)

    # Build the catalog
    catalog: dict = {
        "trace_root": str(trace_root),
        "n_traces": n_traces,
        "n_windows_with_tool_calls": (
            len(windows_with_any_failure) + len(windows_with_only_success)
        ),
        "n_tool_invocations": n_tool_invocations,
        "n_windows_any_failure": len(windows_with_any_failure),
        "n_windows_all_success": len(windows_with_only_success),
        "per_tool_breakdown": {
            tool: dict(modes) for tool, modes in per_tool.items()
        },
        "fleet_totals_by_mode": {
            mode: sum(per_tool[tool].get(mode, 0) for tool in per_tool)
            for mode in FAILURE_MODES
        },
        "fleet_success_count": sum(
            per_tool[tool].get("__success__", 0) for tool in per_tool
        ),
        "per_mode_examples": {
            mode: per_mode_examples[mode] for mode in FAILURE_MODES
        },
    }

    # Cross-check: per-tool sums should equal n_tool_invocations
    summed = sum(
        sum(modes.values()) for modes in per_tool.values()
    )
    catalog["sanity_check"] = {
        "summed_per_tool": summed,
        "n_tool_invocations": n_tool_invocations,
        "match": summed == n_tool_invocations,
    }
    return catalog


def format_catalog(catalog: dict) -> str:
    """Pretty-print the catalog as a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("  Failure-mode catalog — RQ-D6 closure")
    lines.append("=" * 70)
    lines.append(f"  Trace root:                  {catalog['trace_root']}")
    lines.append(f"  n_traces:                    {catalog['n_traces']}")
    lines.append(f"  n_windows_with_tool_calls:   {catalog['n_windows_with_tool_calls']}")
    lines.append(f"  n_tool_invocations:          {catalog['n_tool_invocations']}")
    lines.append(f"  n_windows_any_failure:       {catalog['n_windows_any_failure']}")
    lines.append(f"  n_windows_all_success:       {catalog['n_windows_all_success']}")
    lines.append("")
    lines.append("Fleet totals by failure mode:")
    fleet_success = catalog["fleet_success_count"]
    n_inv = catalog["n_tool_invocations"] or 1
    lines.append(f"  success                       {fleet_success}  ({fleet_success / n_inv:.1%})")
    for mode in FAILURE_MODES:
        count = catalog["fleet_totals_by_mode"][mode]
        lines.append(f"  {mode:<30}  {count}  ({count / n_inv:.1%})")
    lines.append("")
    lines.append("Per-tool breakdown:")
    for tool, modes in sorted(catalog["per_tool_breakdown"].items()):
        total = sum(modes.values())
        s = modes.get("__success__", 0)
        lines.append(f"  {tool} (total={total}, success={s}):")
        for mode in FAILURE_MODES:
            v = modes.get(mode, 0)
            if v > 0:
                lines.append(f"    {mode}: {v}")
    lines.append("")
    lines.append("Per-mode exemplars (up to 3 each):")
    for mode in FAILURE_MODES:
        examples = catalog["per_mode_examples"].get(mode) or []
        lines.append(f"  {mode}:")
        if not examples:
            lines.append(f"    (none observed)")
        for ex in examples:
            lines.append(
                f"    - tool={ex['tool_name']} "
                f"window={ex['window_id'][:80]} "
                f"err={ex.get('error') or '-'}"
            )
    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--trace-root", type=Path, required=True,
        help="Per-window trace directory written by AgentRunner",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="Write JSON catalog here. If unset, prints to stdout only.",
    )
    p.add_argument(
        "--text-output", type=Path, default=None,
        help="Also write the human-readable text report here.",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    if not args.trace_root.is_dir():
        raise SystemExit(f"trace root not found: {args.trace_root}")

    catalog = build_catalog(args.trace_root)
    text = format_catalog(catalog)
    print(text)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(catalog, indent=2),
            encoding="utf-8",
        )
        print(f"[failure_mode_catalog] wrote JSON -> {args.output}")
    if args.text_output is not None:
        args.text_output.parent.mkdir(parents=True, exist_ok=True)
        args.text_output.write_text(text, encoding="utf-8")
        print(f"[failure_mode_catalog] wrote text -> {args.text_output}")


if __name__ == "__main__":
    main()
