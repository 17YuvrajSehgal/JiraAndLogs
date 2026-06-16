"""Backfill OTel Demo `scenario_family` from `scenario_id`.

OTel global-triage-examples.jsonl + jira-memory-corpus.jsonl + window-memory-
matchings.jsonl were all built with `scenario_family="unknown"`, which loses
useful inference context for the LLM window-extractor (OB had real family
labels and the LLM used them to infer error_classes like DeadlineExceeded).

Derivation is deterministic from `scenario_id`:
    otel-demo-payment-outage-critical  ->  payment-outage
    otel-demo-kafka-broker-outage-critical  ->  kafka-broker-outage
    otel-demo-baseline-normal-traffic  ->  baseline-normal-traffic

Atomic write: build new content in-memory, write to .tmp, then rename.

Idempotent: re-running on a backfilled file is a no-op since the regex
re-derives the same family.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY_SUFFIX = re.compile(
    r"-(critical|major|minor|warning|low|nearmiss|near-miss|info)$"
)


def derive_family(scenario_id: str) -> str:
    if not scenario_id:
        return "unknown"
    sid = scenario_id
    if sid.startswith("otel-demo-"):
        sid = sid[len("otel-demo-"):]
    sid = SEVERITY_SUFFIX.sub("", sid)
    return sid or "unknown"


def _patch_file_in_place(
    path: Path,
    *,
    family_resolver,  # callable(row) -> str
    dry_run: bool,
) -> tuple[int, int]:
    """Return (n_rows, n_changed)."""
    n_rows = 0
    n_changed = 0
    out_lines: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            r = json.loads(line)
            n_rows += 1
            new_family = family_resolver(r)
            if new_family and new_family != r.get("scenario_family"):
                r["scenario_family"] = new_family
                n_changed += 1
            out_lines.append(json.dumps(r, ensure_ascii=False))

    if dry_run:
        return n_rows, n_changed

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return n_rows, n_changed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="Report counts without writing.")
    args = p.parse_args()

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    memory_path = args.global_dir / "jira-memory-corpus.jsonl"
    matchings_path = args.global_dir / "window-memory-matchings.jsonl"

    for p_ in (examples_path, memory_path, matchings_path):
        if not p_.exists():
            print(f"ERROR: missing {p_}", file=sys.stderr)
            sys.exit(2)

    # Pass 1: examples + memory derive from their own scenario_id.
    def from_self(row: dict) -> str:
        return derive_family(row.get("scenario_id", ""))

    n1, c1 = _patch_file_in_place(
        examples_path, family_resolver=from_self, dry_run=args.dry_run,
    )
    print(f"  global-triage-examples.jsonl: {n1} rows, {c1} updated")

    n2, c2 = _patch_file_in_place(
        memory_path, family_resolver=from_self, dry_run=args.dry_run,
    )
    print(f"  jira-memory-corpus.jsonl:     {n2} rows, {c2} updated")

    # Pass 2: matchings join from examples via window_id.
    # Build window_id -> family map from (already-patched) examples.
    win_to_family: dict[str, str] = {}
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            wid = r.get("window_id")
            fam = r.get("scenario_family")
            if wid and fam:
                win_to_family[wid] = fam

    def from_join(row: dict) -> str:
        return win_to_family.get(row.get("window_id", ""), row.get("scenario_family", "unknown"))

    n3, c3 = _patch_file_in_place(
        matchings_path, family_resolver=from_join, dry_run=args.dry_run,
    )
    print(f"  window-memory-matchings.jsonl:{n3} rows, {c3} updated")

    print(f"\nTotal: {c1 + c2 + c3} rows updated across 3 files "
          f"{'(dry-run, no writes)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
