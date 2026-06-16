"""Bundle a publishable dataset into a single zip.

Per-dataset layout, two variants:

    data/published/<friendly-name>/simple_dataset.zip   (derived global only — small, fast)
    data/published/<friendly-name>/full_dataset.zip     (raw + derived + global — full reproducibility)

Each zip is self-describing:
    <dataset-id>/README.md              # complete, no external references
    <dataset-id>/MANIFEST.sha256.json   # sha256 + size for every file
    <dataset-id>/...                    # data

Uses ZIP_STORED for already-compressed files (.gz, .zip, .archive, .pdf)
and ZIP_DEFLATED for everything else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path("C:/workplace/JiraAndLogs")

PRECOMPRESSED_SUFFIXES = {".gz", ".zip", ".archive", ".pdf", ".tar", ".tgz", ".bz2", ".xz", ".zst"}

# Mapping: friendly slug -> (dataset id, raw-source roots filter)
DATASETS = {
    "online-boutique": {
        "dataset_id": "2026-05-25-dataset-v5-large-global",
        "raw_id_prefix": "2026-05-25-dataset-v5-large-",
        "raw_root_name": "runs",
    },
    "otel-demo": {
        "dataset_id": "2026-06-09-otel-demo-v1-global",
        "raw_id_prefix": "2026-06-09-otel-demo-v1-",
        "raw_root_name": "otel-demo-runs",
    },
    "world-of-logs": {
        "dataset_id": "2026-06-15-wol-real-v2-global",   # v2 refresh 2026-06-16 (Phase B augmented)
        "raw_id_prefix": None,
        "raw_root_name": "wol",   # full dir; gzipped-only inclusion handled below
    },
}


def _zip_compression_for(path: Path) -> int:
    if path.suffix.lower() in PRECOMPRESSED_SUFFIXES:
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _enumerate_simple(
    dataset_id: str, project_root: Path,
) -> list[tuple[Path, str]]:
    """Derived global directory only.

    Returns (source_path, archive_rel_to_dataset_root)."""
    src_dir = project_root / "data/derived/global" / dataset_id
    if not src_dir.is_dir():
        raise SystemExit(f"missing source dir: {src_dir}")
    out: list[tuple[Path, str]] = []
    for f in sorted(src_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith("MANIFEST") or f.name.endswith(".tmp"):
            continue
        rel = f.relative_to(src_dir).as_posix()
        out.append((f, rel))
    return out


def _enumerate_full(
    slug: str, dataset_id: str, project_root: Path,
) -> list[tuple[Path, str]]:
    """Derived global + per-run derived + raw runs (per-dataset)."""
    cfg = DATASETS[slug]
    pref = cfg["raw_id_prefix"]
    raw_dir_name = cfg["raw_root_name"]
    base = project_root
    out: list[tuple[Path, str]] = []

    # 1) Derived global (mounted under data/derived/global/<id>/)
    src_dir = base / "data/derived/global" / dataset_id
    for f in sorted(src_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith("MANIFEST") or f.name.endswith(".tmp"):
            continue
        rel = f.relative_to(src_dir).as_posix()
        out.append((f, f"data/derived/global/{dataset_id}/{rel}"))

    # 2) Per-run derived caches (data/derived/<dataset-prefix>-*-r##/)
    if pref:
        for d in sorted((base / "data/derived").iterdir()):
            if not d.is_dir(): continue
            if not d.name.startswith(pref): continue
            if d.name == dataset_id: continue   # the global lives in derived/global/, but make sure we don't double-include
            for f in sorted(d.rglob("*")):
                if not f.is_file(): continue
                if f.name.endswith(".tmp"): continue
                rel = f.relative_to(base / "data/derived").as_posix()
                out.append((f, f"data/derived/{rel}"))

    # 3) Raw runs
    if slug == "world-of-logs":
        # WoL: only include the gzipped archive + license/paper; drop the uncompressed .archive
        wol_dir = base / "data/wol"
        for f in sorted(wol_dir.iterdir()):
            if not f.is_file(): continue
            if f.name == "WoL_v1-2025-11-10.archive":
                continue  # bit-identical to .gz, save 14 GB
            out.append((f, f"data/wol/{f.name}"))
        # Cross-corpus gold (lives at data/derived/, but logically belongs to WoL evaluation)
        cc_gold = base / "data/derived/cross-corpus-kafka-gold.jsonl"
        if cc_gold.exists():
            out.append((cc_gold, "data/derived/cross-corpus-kafka-gold.jsonl"))
    else:
        # OB / OTel: include all per-dataset raw run dirs
        raw_root = base / "data" / raw_dir_name
        for d in sorted(raw_root.iterdir()):
            if not d.is_dir(): continue
            if pref and not d.name.startswith(pref): continue
            for f in sorted(d.rglob("*")):
                if not f.is_file(): continue
                if f.name.endswith(".tmp"): continue
                rel = f.relative_to(raw_root).as_posix()
                out.append((f, f"data/{raw_dir_name}/{rel}"))

    return out


def _build_manifest_in_memory(
    entries: list[tuple[Path, str]],
) -> tuple[bytes, int]:
    items: list[dict] = []
    total = 0
    print(f"  hashing {len(entries)} files for manifest ...")
    t0 = time.time()
    for i, (src, rel) in enumerate(entries, 1):
        size = src.stat().st_size
        items.append({
            "path": rel,
            "size_bytes": size,
            "sha256": _sha256(src),
        })
        total += size
        if i % 500 == 0:
            print(f"    ... {i}/{len(entries)}  ({(time.time()-t0):.0f}s)")
    manifest = {
        "n_files": len(items),
        "total_size_bytes": total,
        "files": items,
    }
    return json.dumps(manifest, indent=2).encode("utf-8"), total


def _write_zip(
    out_path: Path,
    *,
    dataset_id: str,
    readme_bytes: bytes,
    manifest_bytes: bytes,
    entries: list[tuple[Path, str]],
    total_bytes: int,
) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    print(f"  writing {out_path.name} ...")
    t0 = time.time()
    bytes_written = 0
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as zf:
        zf.writestr(f"{dataset_id}/README.md", readme_bytes,
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(f"{dataset_id}/MANIFEST.sha256.json", manifest_bytes,
                    compress_type=zipfile.ZIP_DEFLATED)
        for i, (src, rel) in enumerate(entries, 1):
            arc = f"{dataset_id}/{rel}"
            zf.write(src, arc, compress_type=_zip_compression_for(src))
            bytes_written += src.stat().st_size
            if i % 500 == 0 or i == len(entries):
                pct = 100 * bytes_written / total_bytes if total_bytes else 100
                elapsed = time.time() - t0
                rate = bytes_written / 1024 / 1024 / elapsed if elapsed else 0
                print(f"    ... {i}/{len(entries)}  ({pct:.1f}%, {rate:.0f} MB/s)")
    tmp.replace(out_path)
    print(f"  done  ({(time.time()-t0)/60:.1f} min)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", required=True, choices=list(DATASETS.keys()))
    p.add_argument("--variant", required=True, choices=["simple", "full"])
    p.add_argument("--published-root", type=Path,
                   default=PROJECT_ROOT / "data/published")
    args = p.parse_args()

    cfg = DATASETS[args.slug]
    dataset_id = cfg["dataset_id"]
    out_dir = (args.published_root / args.slug).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"{args.variant}_dataset.zip"

    print(f"[{args.slug}/{args.variant}]  dataset_id={dataset_id}")
    if args.variant == "simple":
        entries = _enumerate_simple(dataset_id, PROJECT_ROOT)
    else:
        entries = _enumerate_full(args.slug, dataset_id, PROJECT_ROOT)
    print(f"  {len(entries)} files to include")

    # Read README from the dataset dir (single source of truth)
    readme_src = PROJECT_ROOT / "data/derived/global" / dataset_id / "README.md"
    readme_bytes = readme_src.read_bytes()

    manifest_bytes, total = _build_manifest_in_memory(entries)
    print(f"  total raw: {total / 1024 / 1024 / 1024:.2f} GB")

    _write_zip(
        out_zip,
        dataset_id=dataset_id,
        readme_bytes=readme_bytes,
        manifest_bytes=manifest_bytes,
        entries=entries,
        total_bytes=total,
    )
    out_size_gb = out_zip.stat().st_size / 1024 / 1024 / 1024
    print(f"  zip: {out_size_gb:.2f} GB ({100*out_size_gb/(total/1024/1024/1024) if total else 0:.0f}% of raw)")


if __name__ == "__main__":
    main()
