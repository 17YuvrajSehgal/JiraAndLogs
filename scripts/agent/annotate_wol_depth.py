"""Annotate WoL `global-triage-examples.jsonl` with depth field.

Closes RQ-B2 WoL gap. The WoL test set's published predictions all
carried `n_prior_family_tickets = 0` because depth wasn't computed at
build time. This script adds `n_prior_same_project_tickets` per window
by counting WoL memory tickets in the same `wol_project` that were
`available_as_memory_from <= window.start_time`.

The annotation is in-place (writes back to the same JSONL). A backup
is written to `<file>.bak` first. Idempotent — re-running just
overwrites the field.

Usage:
    PYTHONPATH=src python scripts/agent/annotate_wol_depth.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        --inplace
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


log = logging.getLogger(__name__)


def _parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    # WoL memory uses `2016-02-15T21:53:19.000+0000`
    # WoL windows use `2026-06-11T15:03:46.138093+00:00`
    # Both ISO-8601; let datetime.fromisoformat handle both.
    try:
        # Normalize "+0000" to "+00:00" for fromisoformat
        if len(s) >= 5 and s[-5] in ("+", "-") and ":" not in s[-3:]:
            s = s[:-2] + ":" + s[-2:]
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _build_memory_timeline(
    memory_path: Path,
) -> dict[str, list[datetime]]:
    """Return wol_project → sorted list of available_as_memory_from times."""
    by_project: dict[str, list[datetime]] = defaultdict(list)
    with memory_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            proj = d.get("wol_project")
            amf = d.get("available_as_memory_from")
            if not proj or not amf:
                continue
            ts = _parse_ts(amf)
            if ts is not None:
                by_project[proj].append(ts)
    for proj in by_project:
        by_project[proj].sort()
    return dict(by_project)


def _n_prior(
    timeline: list[datetime],
    window_ts: datetime,
) -> int:
    """Binary-search the timeline; return count of memories available
    before or at `window_ts`."""
    from bisect import bisect_right
    return bisect_right(timeline, window_ts)


def annotate(
    examples_path: Path,
    memory_path: Path,
    *,
    inplace: bool = True,
    backup: bool = True,
    out_path: Path | None = None,
) -> dict:
    """Add `n_prior_same_project_tickets` to every window row.

    Returns a stats dict (n_windows, n_with_project, ...).
    """
    timeline = _build_memory_timeline(memory_path)
    log.info("loaded memory timeline: %d projects (%s)",
             len(timeline), {p: len(ts) for p, ts in timeline.items()})

    if backup and inplace:
        backup_path = examples_path.with_suffix(examples_path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copyfile(examples_path, backup_path)
            log.info("backup written: %s", backup_path)

    rows_out: list[dict] = []
    n_with_project = 0
    n_with_ts = 0
    depth_hist: dict[str, int] = defaultdict(int)

    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            proj = row.get("wol_project")
            start_str = row.get("start_time") or row.get("end_time")
            window_ts = _parse_ts(start_str) if start_str else None
            if proj and window_ts is not None:
                n_with_project += 1
                n_with_ts += 1
                ts_list = timeline.get(proj, [])
                n_prior = _n_prior(ts_list, window_ts)
            else:
                n_prior = 0
            row["n_prior_same_project_tickets"] = n_prior
            rows_out.append(row)
            depth_hist[_bucket(n_prior)] += 1

    target = out_path or examples_path
    with target.open("w", encoding="utf-8") as fh:
        for r in rows_out:
            fh.write(json.dumps(r) + "\n")

    return {
        "n_windows": len(rows_out),
        "n_with_project": n_with_project,
        "n_with_ts": n_with_ts,
        "depth_buckets": dict(depth_hist),
        "output": str(target),
    }


def _bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n <= 10:
        return "1-10"
    if n <= 50:
        return "11-50"
    if n <= 200:
        return "51-200"
    return "201+"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True,
                   help="WoL dataset root")
    p.add_argument("--inplace", action="store_true",
                   help="overwrite global-triage-examples.jsonl (default)")
    p.add_argument("--out", type=Path, default=None,
                   help="output path; ignored when --inplace")
    p.add_argument("--no-backup", action="store_true",
                   help="skip the .bak file on inplace writes")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    examples = args.global_dir / "global-triage-examples.jsonl"
    memory = args.global_dir / "jira-memory-corpus.jsonl"
    if not examples.exists():
        raise SystemExit(f"missing {examples}")
    if not memory.exists():
        raise SystemExit(f"missing {memory}")

    out_path = examples if args.inplace else (args.out or examples.with_suffix(".annotated.jsonl"))

    stats = annotate(
        examples, memory,
        inplace=args.inplace,
        backup=not args.no_backup,
        out_path=out_path,
    )

    print()
    print("=" * 70)
    print(f"  annotate_wol_depth — {args.global_dir.name}")
    print("=" * 70)
    print(f"  n_windows:              {stats['n_windows']}")
    print(f"  n_with_project + ts:    {stats['n_with_ts']}")
    print(f"  output:                 {stats['output']}")
    print()
    print(f"  Depth buckets after annotation:")
    for b in ("0", "1-10", "11-50", "51-200", "201+"):
        c = stats["depth_buckets"].get(b, 0)
        bar = "#" * min(40, c // max(1, stats["n_windows"] // 40))
        print(f"    {b:<8} {c:>5}  {bar}")
    print("=" * 70)


if __name__ == "__main__":
    main()
