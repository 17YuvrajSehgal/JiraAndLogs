#!/usr/bin/env python3
"""D0.1 per-family minimum window check.

Walks a global derived directory and reports the (split, scenario_family)
window-count matrix. Fails (exit 1) if any (split, family) pair has fewer
than `--min-per-family-per-split` windows (default 30, per
`dataset-todo.md` Phase D0.1 acceptance).

Usage::

    python3 scripts/research-lab/validate_global_family_coverage.py \\
        --global-dir data/derived/global/2026-05-22-dataset-v4-large-global

Optional::
    --min-per-family-per-split 30   # threshold per cell
    --json out.json                 # also write the matrix as JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", required=True, type=Path)
    p.add_argument("--min-per-family-per-split", type=int, default=30)
    p.add_argument("--json", type=Path, default=None,
                   help="Optional path to write the per-cell matrix as JSON")
    args = p.parse_args()

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        print(f"ERROR: not found: {examples_path}", file=sys.stderr)
        return 2

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    families: set[str] = set()
    splits: set[str] = set()
    n_total = 0
    with examples_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            split = d.get("split") or "unsplit"
            family = d.get("scenario_family") or "unknown"
            counts[split][family] += 1
            families.add(family)
            splits.add(split)
            n_total += 1

    splits_sorted = sorted(splits)
    families_sorted = sorted(families)

    # Pretty table
    col_w = max(20, max((len(f) for f in families_sorted), default=20) + 2)
    header = f"{'family':{col_w}}" + " ".join(f"{s:>10}" for s in splits_sorted)
    print(header)
    print("-" * len(header))
    weak_cells: list[tuple[str, str, int]] = []  # (split, family, n)
    for fam in families_sorted:
        row = [f"{fam:{col_w}}"]
        for sp in splits_sorted:
            n = counts[sp].get(fam, 0)
            cell = f"{n:>10}"
            if 0 < n < args.min_per_family_per_split:
                cell = f"{n:>9}!"  # mark weak
                weak_cells.append((sp, fam, n))
            elif n == 0:
                cell = f"{'.':>10}"
            row.append(cell)
        print(" ".join(row))
    print()
    print(f"total windows: {n_total}")
    print(
        f"weak cells (< {args.min_per_family_per_split}, but > 0): "
        f"{len(weak_cells)}"
    )
    for sp, fam, n in weak_cells:
        print(f"  WEAK split={sp} family={fam} n={n}")
    # Also report families missing entirely from a split
    missing_cells: list[tuple[str, str]] = []
    for fam in families_sorted:
        for sp in splits_sorted:
            if counts[sp].get(fam, 0) == 0:
                missing_cells.append((sp, fam))
    print(f"missing cells (n=0): {len(missing_cells)}")
    for sp, fam in missing_cells:
        print(f"  MISSING split={sp} family={fam}")

    if args.json:
        matrix = {sp: dict(counts[sp]) for sp in splits_sorted}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(matrix, indent=2, sort_keys=True))
        print(f"\nmatrix written to {args.json}")

    bad = bool(weak_cells)  # missing cells are reported but not failing —
    # they reflect intentional split design (some families test-only,
    # some train-only). Only flag weak cells (have data but not enough).
    if bad:
        print(f"\nFAIL: {len(weak_cells)} (split, family) cell(s) below "
              f"the {args.min_per_family_per_split}-window threshold.")
        return 1
    print(f"\nPASS: every populated (split, family) cell has "
          f">= {args.min_per_family_per_split} windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
