"""Count WoL JIRA pool sizes under different pred_uncertainty thresholds.

Sweeps pred_uncertainty in {0.05, 0.10, 0.20, drop} crossed with our 7 Apache
projects. Reports both the raw Bug counts (current pool composition) and the
relaxed-issuetype counts so the user can see how much pool growth each knob
buys.

Keeps the other quality filters identical to build_wol_real_corpus.py so the
deltas are clean.
"""
from __future__ import annotations

import json
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "WoL_v1"
MONGO_COL = "JIRA"

# Same 7 projects as our locked v2 dataset.
PROJECTS = [
    "Spark",
    "Cassandra",
    "HBase",
    "Flink",
    "Ambari",
    "Kafka",
    "MariaDB Server",
]

# pred_uncertainty thresholds. None = drop the filter entirely.
THRESHOLDS = [0.05, 0.10, 0.20, None]

# Issuetype scopes to report.
ISSUETYPE_SCOPES = {
    "Bug only (current)":          {"fields.issuetype.name": "Bug"},
    "Bug + borderline + noise iss": {
        "fields.issuetype.name": {"$in": [
            "Bug", "Improvement", "New Feature",
            "Question", "Documentation", "Wish",
        ]},
    },
    "Any issuetype":               {},
}

# Shared quality filters (kept identical to build_wol_real_corpus.py).
DESC_MIN = 200
LOG_MIN = 1


def build_match(project, threshold, issuetype_filter, *, require_logs=True, require_desc=True):
    """Construct a Mongo $match document matching the production aggregation."""
    m = {"fields.project.name": project}
    m.update(issuetype_filter)
    if threshold is not None:
        m["pred_uncertainty"] = {"$lte": threshold}
    if require_logs:
        m[f"log_msgs.{LOG_MIN - 1}"] = {"$exists": True}
    if require_desc:
        m["$expr"] = {"$gte": [
            {"$strLenCP": {"$ifNull": ["$fields.description", ""]}},
            DESC_MIN,
        ]}
    return m


def count(coll, match):
    return coll.count_documents(match)


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    coll = client[MONGO_DB][MONGO_COL]

    print("=" * 100)
    print("WoL JIRA pool capacity sweep")
    print(f"Other filters held constant: desc >= {DESC_MIN} chars, log_msgs >= {LOG_MIN}")
    print("=" * 100)

    results = {}

    for scope_label, issuetype_filter in ISSUETYPE_SCOPES.items():
        print()
        print(f"## Scope: {scope_label}")
        # Header row
        header = f"  {'Project':<20} | " + " | ".join(
            f"u<={t:.2f}" if t is not None else "  drop"
            for t in THRESHOLDS
        )
        print(header)
        print("  " + "-" * (len(header) - 2))

        scope_totals = {t: 0 for t in THRESHOLDS}

        for project in PROJECTS:
            row_cells = []
            for t in THRESHOLDS:
                n = count(coll, build_match(project, t, issuetype_filter))
                scope_totals[t] += n
                row_cells.append(f"{n:>6}")
                results[(scope_label, project, t)] = n
            print(f"  {project:<20} | " + " | ".join(row_cells))

        print("  " + "-" * (len(header) - 2))
        total_row = f"  {'TOTAL':<20} | " + " | ".join(
            f"{scope_totals[t]:>6}" for t in THRESHOLDS
        )
        print(total_row)

    print()
    print("=" * 100)
    print("Now sweeping with log_msgs requirement DROPPED (for the 'Any issuetype' scope only).")
    print("Use this when assessing 'how many tickets exist that we'd lose if we kept the logs filter'.")
    print("=" * 100)
    print()
    header = f"  {'Project':<20} | " + " | ".join(
        f"u<={t:.2f}" if t is not None else "  drop"
        for t in THRESHOLDS
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    no_log_totals = {t: 0 for t in THRESHOLDS}
    for project in PROJECTS:
        row_cells = []
        for t in THRESHOLDS:
            n = count(coll, build_match(project, t, {}, require_logs=False))
            no_log_totals[t] += n
            row_cells.append(f"{n:>6}")
        print(f"  {project:<20} | " + " | ".join(row_cells))
    print("  " + "-" * (len(header) - 2))
    total_row = f"  {'TOTAL':<20} | " + " | ".join(
        f"{no_log_totals[t]:>6}" for t in THRESHOLDS
    )
    print(total_row)

    # Persist as JSON for downstream analysis.
    out = {
        "thresholds": [t if t is not None else "drop" for t in THRESHOLDS],
        "filters_held": {
            "desc_min_chars": DESC_MIN,
            "log_msgs_min": LOG_MIN,
        },
        "by_scope_project_threshold": {
            scope_label: {
                project: {
                    (str(t) if t is not None else "drop"): results[(scope_label, project, t)]
                    for t in THRESHOLDS
                }
                for project in PROJECTS
            }
            for scope_label in ISSUETYPE_SCOPES
        },
    }
    out_path = "scripts/research-lab/wol_pool_capacity_sweep.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print()
    print(f"Saved structured results to: {out_path}")


if __name__ == "__main__":
    main()
