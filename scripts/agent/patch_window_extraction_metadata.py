"""Patch `family` + `severity` metadata in existing window extractions.

Use when upstream global-triage-examples.jsonl had `scenario_family` /
`triage_severity` backfilled AFTER window-LLM-extraction was already run.
The LLM extractor (proposal_d.extractor.extract_from_window) does NOT
pass family or severity into the prompt — they are only stored as
metadata on the output — so a pure metadata refresh is safe and avoids
hours of LLM re-running.

Updates both:
  - `<global>/v2_kg_extractions_windows/all_extractions.jsonl`
  - `<global>/v2_kg_extractions_windows/window/<wid>__<hash>.json` (per-window cache)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_window_metadata_map(examples_path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            wid = r.get("window_id")
            if not wid:
                continue
            out[wid] = {
                "family": r.get("scenario_family") or "",
                "severity": r.get("window_type") or "",
            }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out-dir", default="v2_kg_extractions_windows")
    args = p.parse_args()

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    cache_dir = args.global_dir / args.out_dir
    consolidated = cache_dir / "all_extractions.jsonl"
    window_dir = cache_dir / "window"

    for p_ in (examples_path, consolidated):
        if not p_.exists():
            print(f"ERROR: missing {p_}", file=sys.stderr)
            sys.exit(2)

    wmap = _build_window_metadata_map(examples_path)
    print(f"  loaded metadata for {len(wmap)} windows")

    # Pass 1: patch consolidated all_extractions.jsonl
    out_lines: list[str] = []
    n_changed = 0
    with consolidated.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line.rstrip("\n"))
            wid = r.get("window_id", "")
            meta = wmap.get(wid)
            if meta:
                if r.get("family") != meta["family"]:
                    r["family"] = meta["family"]
                    n_changed += 1
                if r.get("severity") != meta["severity"]:
                    r["severity"] = meta["severity"]
            out_lines.append(json.dumps(r, ensure_ascii=False))
    tmp = consolidated.with_suffix(consolidated.suffix + ".tmp")
    tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    tmp.replace(consolidated)
    print(f"  all_extractions.jsonl: {len(out_lines)} rows, {n_changed} family-changed")

    # Pass 2: patch per-window cache files
    if window_dir.is_dir():
        n_cache_changed = 0
        cache_files = sorted(window_dir.glob("*.json"))
        for cf in cache_files:
            r = json.loads(cf.read_text(encoding="utf-8"))
            wid = r.get("window_id", "")
            meta = wmap.get(wid)
            if not meta:
                continue
            changed = False
            if r.get("family") != meta["family"]:
                r["family"] = meta["family"]
                changed = True
            if r.get("severity") != meta["severity"]:
                r["severity"] = meta["severity"]
                changed = True
            if changed:
                cf.write_text(json.dumps(r, indent=2), encoding="utf-8")
                n_cache_changed += 1
        print(f"  per-window cache: {len(cache_files)} files, {n_cache_changed} updated")


if __name__ == "__main__":
    main()
