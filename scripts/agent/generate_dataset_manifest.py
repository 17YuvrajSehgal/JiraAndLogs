"""Generate a checksum manifest for a publishable dataset directory.

Writes `MANIFEST.sha256.json` at the dataset root listing every file
with sha256 + size + mtime. This is the "lock" step — any future
modification (intentional or not) will be detectable by re-computing
the hashes.

Excludes itself, any pre-existing MANIFEST*.json, and any `.tmp`
files. Skips empty dirs.

Usage:
    PYTHONPATH=src python scripts/agent/generate_dataset_manifest.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, default=None,
                   help="Defaults to <global-dir>/MANIFEST.sha256.json")
    p.add_argument("--exclude", nargs="*", default=[],
                   help="Top-level subdir names to exclude (e.g. comparison training_runs)")
    args = p.parse_args()
    excludes = set(args.exclude or [])

    base = args.global_dir.resolve()
    if not base.is_dir():
        print(f"ERROR: not a directory: {base}", file=sys.stderr)
        sys.exit(2)

    out_path = args.output or (base / "MANIFEST.sha256.json")
    out_name = out_path.name

    entries: list[dict] = []
    total_bytes = 0
    for path in sorted(base.rglob("*")):
        if path.is_dir():
            continue
        if path.name.startswith("MANIFEST") or path.name.endswith(".tmp"):
            continue
        if path.name == out_name:
            continue
        rel = path.relative_to(base).as_posix()
        if excludes and rel.split("/", 1)[0] in excludes:
            continue
        size = path.stat().st_size
        sha = _sha256_of(path)
        entries.append({
            "path": rel,
            "size_bytes": size,
            "sha256": sha,
        })
        total_bytes += size
        if len(entries) % 100 == 0:
            print(f"  ... {len(entries)} files hashed", file=sys.stderr)

    manifest = {
        "dataset_id": base.name,
        "n_files": len(entries),
        "total_size_bytes": total_bytes,
        "files": entries,
    }
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  wrote {out_path}  ({len(entries)} files, "
          f"{total_bytes / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
