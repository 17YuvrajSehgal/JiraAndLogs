"""One-time bootstrap: load all three datasets into their dedicated
Neo4j databases (neo4j-ob, neo4j-otel, neo4j-wol).

After this runs once, switching datasets at agent-run time costs zero
KG-reload time: the agent just connects to the right database via
NEO4J_DATABASE env var (or the canonical mapping in Neo4jConfig.from_env).

Per IMPROVEMENTS.md §1.1 Option C: one Neo4j instance, three databases,
no cross-dataset contamination, KGs persist between dataset switches.

Usage:
    PYTHONPATH=src python scripts/agent/load_all_datasets_to_neo4j.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path("C:/workplace/JiraAndLogs")

DATASETS = [
    ("2026-05-25-dataset-v5-large-global", "neo4j-ob"),
    ("2026-06-09-otel-demo-v1-global",     "neo4j-otel"),
    ("2026-06-11-wol-real-global",         "neo4j-wol"),
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", choices=["llm", "rules"], default="llm")
    p.add_argument("--skip", nargs="*", default=[],
                   help="Dataset IDs (or DB names) to skip.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    skips = set(args.skip or [])

    print(f"[bootstrap] target instance: {PROJECT_ROOT}")
    print(f"[bootstrap] datasets: {len(DATASETS)} (source={args.source})")
    print()

    for dataset_id, db_name in DATASETS:
        if dataset_id in skips or db_name in skips:
            print(f"[skip] {dataset_id} -> {db_name}")
            continue
        global_dir = PROJECT_ROOT / "data/derived/global" / dataset_id
        if not global_dir.is_dir():
            print(f"[skip] {dataset_id}: missing {global_dir}", file=sys.stderr)
            continue
        kg_file = global_dir / "v2_kg_extractions" / "all_extractions.jsonl"
        if not kg_file.is_file():
            print(f"[skip] {dataset_id}: no KG extractions at {kg_file}",
                  file=sys.stderr)
            continue

        cmd = [
            sys.executable, "-m",
            "v2_advanced.proposal_d_knowledge_graph.reload_neo4j",
            "--global-dir", str(global_dir),
            "--source", args.source,
            "--database", db_name,
        ]
        print(f"\n[run] {dataset_id} -> {db_name}")
        print(f"      {' '.join(cmd)}")
        if args.dry_run:
            continue
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        if result.returncode != 0:
            print(f"[FAIL] {dataset_id} reload exited {result.returncode}",
                  file=sys.stderr)
            sys.exit(result.returncode)

    print("\n[bootstrap] done.")


if __name__ == "__main__":
    main()
