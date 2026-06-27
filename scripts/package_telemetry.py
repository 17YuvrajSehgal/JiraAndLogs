#!/usr/bin/env python3
"""
Import raw telemetry runs into MongoDB and dump to .archive.gz for public release.

Usage:
    python scripts/package_telemetry.py otel          # OTel Demo only
    python scripts/package_telemetry.py ob            # Online Boutique only
    python scripts/package_telemetry.py all           # both (default)
    python scripts/package_telemetry.py otel --drop   # drop DB first (clean reimport)
    python scripts/package_telemetry.py otel --no-dump  # import only, skip mongodump

Creates (in data/published/):
    otel-demo/otel_demo_v1_raw.archive.gz
    online-boutique/ob_v1_raw.archive.gz
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
MONGODUMP  = r"C:\Program Files\MongoDB\Tools\100\bin\mongodump.exe"
BASE       = Path("C:/workplace/JiraAndLogs/data")
PUBLISHED  = BASE / "published"

# Window type tokens in filenames — ordered longest first to avoid partial matches
WINDOW_TYPES = ["pre_fault_baseline", "active_fault", "recovery_window", "observation_window"]

# raw/ subdirs → (mongo collection name, insert batch size)
TELEMETRY_DIRS = {
    "loki":                  ("loki_logs",              30),
    "prometheus":            ("prometheus_metrics",     100),
    "prometheus_supplement": ("prometheus_supplement",  100),
    "kubernetes":            ("kubernetes_events",      100),
    "tempo":                 ("tempo_traces",             5),  # ~10 MB docs — small batches
}


def parse_filename(stem, run_id):
    """Return {incident_episode_id, window_type, service_name} from a raw filename stem."""
    suffix = stem.removeprefix(run_id + "-")
    for wt in WINDOW_TYPES:
        marker = f"-{wt}-"
        if marker in suffix:
            episode_suffix, service = suffix.split(marker, 1)
            return {
                "incident_episode_id": f"{run_id}-{episode_suffix}",
                "window_type": wt,
                "service_name": service,
            }
    return None


def import_raw_dir(db, run_id, raw_dir):
    ep_ctx_coll  = db["episode_contexts"]
    run_ctx_coll = db["run_contexts"]

    for subdir_name, (coll_name, batch_size) in TELEMETRY_DIRS.items():
        subdir = raw_dir / subdir_name
        if not subdir.exists():
            continue
        coll = db[coll_name]
        batch, count = [], 0
        for f in sorted(subdir.glob("*.json")):
            stem = f.stem

            # Per-episode context file (one per episode per telemetry type)
            if stem.startswith("episode-context-"):
                episode_id = stem.removeprefix("episode-context-")
                data = json.loads(f.read_bytes())
                ep_ctx_coll.insert_one({
                    "run_id": run_id,
                    "incident_episode_id": f"{run_id}-{episode_id}" if not episode_id.startswith(run_id) else episode_id,
                    "telemetry_type": subdir_name,
                    "data": data,
                })
                continue

            # Run-level context file (one per telemetry type per run)
            if stem == "run-context":
                data = json.loads(f.read_bytes())
                run_ctx_coll.insert_one({"run_id": run_id, "telemetry_type": subdir_name, "data": data})
                continue

            meta = parse_filename(stem, run_id)
            if meta is None:
                print(f"    WARNING: cannot parse filename: {f.name}", flush=True)
                continue
            data = json.loads(f.read_bytes())
            batch.append({"run_id": run_id, **meta, "data": data})
            count += 1
            if len(batch) >= batch_size:
                coll.insert_many(batch)
                batch = []
        if batch:
            coll.insert_many(batch)
        print(f"    {subdir_name:26s} {count} docs", flush=True)


def import_jsonl(coll, path, extra=None, batch_size=500):
    if not path.exists():
        return 0
    batch, total = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            if extra:
                doc.update(extra)
            batch.append(doc)
            total += 1
            if len(batch) >= batch_size:
                coll.insert_many(batch)
                batch = []
    if batch:
        coll.insert_many(batch)
    return total


def import_json_doc(coll, path, extra=None):
    if not path.exists():
        return
    doc = json.loads(path.read_bytes())
    if extra:
        doc.update(extra)
    coll.insert_one(doc)


def package_app(runs_dir: Path, db_name: str, drop: bool = False):
    client = MongoClient(MONGO_URI)
    db = client[db_name]

    if drop:
        print(f"  Dropping {db_name} ...", flush=True)
        client.drop_database(db_name)
        db = client[db_name]

    already = set(db["manifests"].distinct("run_id"))
    runs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    print(f"  {len(runs)} runs found, {len(already)} already imported", flush=True)

    for run_dir in runs:
        run_id = run_dir.name
        if run_id in already:
            print(f"  [skip] {run_id}", flush=True)
            continue

        t0 = time.time()
        print(f"\n  [{run_id}]", flush=True)
        import_raw_dir(db, run_id, run_dir / "raw")

        n = import_jsonl(db["episodes"],           run_dir / "episodes.jsonl",          {"run_id": run_id})
        print(f"    {'episodes':26s} {n} docs", flush=True)
        n = import_jsonl(db["alerts"],             run_dir / "alerts.jsonl",            {"run_id": run_id})
        print(f"    {'alerts':26s} {n} docs", flush=True)
        n = import_jsonl(db["run_windows"],        run_dir / "telemetry_windows.jsonl", {"run_id": run_id})
        print(f"    {'run_windows':26s} {n} docs", flush=True)
        n = import_jsonl(db["jira_shadow_issues"], run_dir / "jira_shadow_issues.jsonl",{"run_id": run_id})
        print(f"    {'jira_shadow_issues':26s} {n} docs", flush=True)
        import_json_doc(db["manifests"], run_dir / "manifest.json", {"run_id": run_id})
        print(f"    {'manifest':26s} 1 doc  ({time.time()-t0:.0f}s)", flush=True)

    client.close()


def dump_archive(db_name: str, archive_path: Path):
    print(f"\n  Dumping {db_name} -> {archive_path.name} ...", flush=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [MONGODUMP, f"--db={db_name}", f"--archive={archive_path}", "--gzip"],
        capture_output=True, text=True
    )
    print(result.stderr, flush=True)
    if result.returncode != 0:
        print(f"  ERROR: mongodump failed\n{result.stdout}", flush=True)
    else:
        size_mb = round(archive_path.stat().st_size / 1_048_576, 1)
        print(f"  Archive size: {size_mb} MB", flush=True)


if __name__ == "__main__":
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    dataset = args[0] if args else "all"
    drop    = "--drop"    in flags
    no_dump = "--no-dump" in flags

    if dataset in ("otel", "all"):
        print("\n=== OTel Demo (otel_demo_v1_raw) ===")
        t = time.time()
        package_app(BASE / "otel-demo-runs", "otel_demo_v1_raw", drop=drop)
        print(f"  Import finished in {(time.time()-t)/60:.1f} min", flush=True)
        if not no_dump:
            dump_archive("otel_demo_v1_raw", PUBLISHED / "otel-demo" / "otel_demo_v1_raw.archive.gz")

    if dataset in ("ob", "all"):
        print("\n=== Online Boutique (ob_v1_raw) ===")
        t = time.time()
        package_app(BASE / "runs", "ob_v1_raw", drop=drop)
        print(f"  Import finished in {(time.time()-t)/60:.1f} min", flush=True)
        if not no_dump:
            dump_archive("ob_v1_raw", PUBLISHED / "online-boutique" / "ob_v1_raw.archive.gz")
