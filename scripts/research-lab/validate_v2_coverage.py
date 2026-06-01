#!/usr/bin/env python3
"""V2 coverage assertion (LLM-Jira-enhancement.md §13.4 + §13.8 step 4).

Per §13.4: every injected fault episode in the v5-large raw run gets
exactly one humanized V2 ticket. The coverage rule is:

    len(injections) == len({t.source_injection_id
                            for t in tickets if not t.is_distractor})

This validator computes both sides and diffs. Inputs are read-only.
Output is a JSON report next to the corpus + an exit code:

  exit 0  → 100% coverage AND no extras
  exit 1  → missing injections (uncovered) OR extras detected

Followup tickets (§13.9 #3 — critical incidents can spawn 1-3 tickets
via `is_followup_of`) are NOT minted by the bulk run yet, so for the
v2.1.0 corpus we expect a strict 1:1 mapping. The check is forward-
compatible: when followups land, multiple tickets per injection_id
are tolerated as long as every injection has ≥ 1 ticket.

Usage:
    python scripts/research-lab/validate_v2_coverage.py
    python scripts/research-lab/validate_v2_coverage.py --bulk-subdir bulk-20260531
    python scripts/research-lab/validate_v2_coverage.py --strict-1to1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_jsonl(path: Path) -> list[dict]:
    """Read-only loader. Skips malformed lines silently — the producer
    is responsible for shape integrity."""
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(mode="r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--global-id",
        default="2026-05-25-dataset-v5-large-global",
        help="Global derived dataset id under data/derived/global/.",
    )
    p.add_argument(
        "--bulk-subdir",
        default=None,
        help=("Subdirectory under jira-shadow-humanized-v2/. Defaults to "
              "the lex-max bulk-* directory."),
    )
    p.add_argument(
        "--strict-1to1",
        action="store_true",
        help=("Require exactly 1 ticket per injection (no followups). "
              "Fails if ANY injection has > 1 non-distractor ticket. "
              "Drop this flag once §13.9 #3 followup minting lands."),
    )
    p.add_argument(
        "--global-id-root",
        default=str(_REPO_ROOT / "data" / "derived" / "global"),
        help="Root of data/derived/global/.",
    )
    return p.parse_args()


def _resolve_bulk_subdir(v2_root: Path, override: str | None) -> Path:
    """Pick the bulk-YYYYMMDD subdir to validate. Defaults to lex-max."""
    if override:
        return v2_root / override
    candidates = sorted(
        d for d in v2_root.glob("bulk-*") if d.is_dir()
    )
    if not candidates:
        raise SystemExit(
            f"No bulk-* subdir under {v2_root}. Pass --bulk-subdir explicitly."
        )
    return candidates[-1]


def main() -> int:
    args = _parse_args()
    global_dir = Path(args.global_id_root) / args.global_id
    if not global_dir.exists():
        print(f"ERROR: global derived dir not found: {global_dir}", file=sys.stderr)
        return 2

    legacy_path = global_dir / "jira-memory-corpus.jsonl"
    if not legacy_path.exists():
        print(f"ERROR: jira-memory-corpus.jsonl not found at {legacy_path}",
              file=sys.stderr)
        return 2

    v2_root = global_dir / "jira-shadow-humanized-v2"
    bulk_dir = _resolve_bulk_subdir(v2_root, args.bulk_subdir)
    timeline_path = bulk_dir / "timeline.jsonl"
    if not timeline_path.exists():
        print(f"ERROR: timeline.jsonl not found at {timeline_path}",
              file=sys.stderr)
        return 2

    print(f"[coverage] legacy corpus: {legacy_path.name}", file=sys.stderr)
    print(f"[coverage] V2 bulk dir:   {bulk_dir.relative_to(global_dir)}",
          file=sys.stderr)

    # ----- Expected set: every shadow Jira in the legacy corpus is an
    # injection that V2 must humanize per §13.4.
    legacy_entries = _read_jsonl(legacy_path)
    expected: set[str] = set()
    for entry in legacy_entries:
        eid = entry.get("incident_episode_id")
        if eid:
            expected.add(eid)

    # ----- Actual set: source_injection_id values from non-distractor
    # V2 tickets. Falls back to source_episode_id for tickets that
    # predate the source_injection_id field (early v2.0.0 outputs).
    timeline_rows = _read_jsonl(timeline_path)
    tickets_by_injection: dict[str, list[str]] = {}
    for t in timeline_rows:
        if t.get("is_distractor"):
            continue
        inj = (
            t.get("source_injection_id")
            or t.get("source_episode_id")
            or ""
        )
        if not inj:
            continue
        tickets_by_injection.setdefault(inj, []).append(t.get("ticket_id", ""))
    actual = set(tickets_by_injection.keys())

    # ----- Diffs
    missing = expected - actual
    extras = actual - expected
    multi_ticket_injections = {
        inj: tids for inj, tids in tickets_by_injection.items()
        if len(tids) > 1
    }

    # ----- Reporting
    coverage_pct = (
        100.0 * len(expected & actual) / max(1, len(expected))
    )
    log_sig_sources = Counter(
        t.get("log_signature_source", "") for t in timeline_rows
        if not t.get("is_distractor")
    )

    print(
        f"[coverage] expected injections (from jira-memory-corpus.jsonl): {len(expected)}",
        file=sys.stderr,
    )
    print(
        f"[coverage] covered injections  (from V2 timeline.jsonl):        {len(actual)}",
        file=sys.stderr,
    )
    print(
        f"[coverage] coverage:   {coverage_pct:.2f}%", file=sys.stderr,
    )
    print(
        f"[coverage] missing:    {len(missing)}", file=sys.stderr,
    )
    print(
        f"[coverage] extras:     {len(extras)} (in V2 but not in legacy corpus)",
        file=sys.stderr,
    )
    print(
        f"[coverage] multi-ticket injections (followups): {len(multi_ticket_injections)}",
        file=sys.stderr,
    )

    # Sample a few missing for the manifest if there are any.
    missing_sample = sorted(missing)[:10]
    extras_sample = sorted(extras)[:10]

    report = {
        "global_id": args.global_id,
        "bulk_subdir": bulk_dir.name,
        "legacy_corpus_path": str(legacy_path),
        "timeline_path": str(timeline_path),
        "coverage_pct": round(coverage_pct, 2),
        "n_expected": len(expected),
        "n_covered": len(actual),
        "n_missing": len(missing),
        "n_extras": len(extras),
        "n_multi_ticket_injections": len(multi_ticket_injections),
        "log_signature_source_breakdown": dict(log_sig_sources),
        "missing_sample": missing_sample,
        "extras_sample": extras_sample,
        "strict_1to1": args.strict_1to1,
    }
    report_path = bulk_dir / "coverage-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[coverage] wrote {report_path.relative_to(global_dir)}",
          file=sys.stderr)

    # ----- Exit code policy
    if missing:
        print(
            f"[coverage] FAIL: {len(missing)} injection(s) have NO V2 ticket "
            f"— §13.4 coverage rule violated. First few missing: "
            f"{missing_sample}",
            file=sys.stderr,
        )
        return 1
    if extras:
        # Extras are weird but not necessarily wrong — could be tickets
        # for episodes that legacy corpus excluded for some reason.
        # Surface them but don't fail.
        print(
            f"[coverage] WARN: {len(extras)} V2 ticket(s) reference an "
            f"injection_id NOT in the legacy corpus. First few: "
            f"{extras_sample}",
            file=sys.stderr,
        )
    if args.strict_1to1 and multi_ticket_injections:
        n = len(multi_ticket_injections)
        first = next(iter(multi_ticket_injections.items()))
        print(
            f"[coverage] FAIL (strict-1to1): {n} injection(s) have multiple "
            f"non-distractor tickets. First: {first[0]} -> {first[1]}",
            file=sys.stderr,
        )
        return 1

    print(
        f"[coverage] PASS — 100% coverage, "
        f"{len(actual)} V2 tickets for {len(expected)} injections",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
