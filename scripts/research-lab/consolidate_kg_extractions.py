"""Safety-net helper: rebuild v2_kg_extractions/all_extractions.jsonl from
per-ticket cache files.

extract_tickets_cli.py only writes the consolidated JSONL at the very
end of the run. If extraction is interrupted (laptop hang, ctrl-c, OOM
on LM Studio), the per-ticket cache files are durable but the
consolidated file the Neo4j loader expects won't exist.

This script reads every <ticket_id>__<hash>.json under the cache dir
and emits a fresh all_extractions.jsonl. Safe to run repeatedly; it
just overwrites the consolidated file.

Usage:
    python scripts/research-lab/consolidate_kg_extractions.py \\
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--source", choices=["llm", "rules"], default="llm")
    args = ap.parse_args()

    source_dir = {"llm": "v2_kg_extractions", "rules": "v2_kg_extractions_rules"}[args.source]
    cache_dir = args.global_dir / source_dir / "ticket"
    if not cache_dir.exists():
        print(f"[consolidate] cache dir {cache_dir} does not exist", file=sys.stderr)
        return 1

    out_path = args.global_dir / source_dir / "all_extractions.jsonl"
    n_files = 0
    n_skipped = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for jf in sorted(cache_dir.glob("*.json")):
            try:
                d = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                n_skipped += 1
                continue
            fh.write(json.dumps(d) + "\n")
            n_files += 1

    print(f"[consolidate] wrote {n_files} extractions to {out_path} "
          f"({n_skipped} skipped — malformed JSON)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
