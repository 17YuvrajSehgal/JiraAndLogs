"""Build the final options matrix for WoL pool expansion.

Three project-scope options × two filter variants:
  Option A — current 7 Apache projects
  Option B — 7 + Hive + IMPALA + Geode + Infinispan (microservice-adjacent)
  Option C — full distributed-systems set (~20 projects: data stores, processing,
             messaging, container platforms)

Filter variants:
  - All filters dropped (no pred_uncertainty, no desc>=200, no log_msgs>=1)
  - log_msgs>=1 only (no pred_uncertainty, no desc>=200, but require >=1 log msg)

Reports Bug-only counts and all-issuetype counts.
"""
from __future__ import annotations

import json
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "WoL_v1"
MONGO_COL = "JIRA"

OPTION_A_PROJECTS = [
    "Spark", "Cassandra", "HBase", "Flink",
    "Ambari", "Kafka", "MariaDB Server",
]

OPTION_B_EXTRA = ["Hive", "IMPALA", "Geode", "Infinispan"]

# Option C: distributed-systems extended.
# Picked for distributed/microservice-relevant vocabulary.
OPTION_C_EXTRA = [
    "Hive", "IMPALA", "Geode", "Infinispan",      # B's adds
    "Hadoop HDFS", "Hadoop YARN", "Hadoop Common",  # Hadoop ecosystem
    "Solr",                                          # Distributed search
    "Apache Drill",                                  # Distributed SQL
    "Beam",                                          # Distributed processing
    "Mesos",                                         # Cluster manager
    "ActiveMQ",                                      # Distributed messaging
    "Camel",                                         # Integration / routing
    "CXF",                                           # Services framework
    "Ignite",                                        # In-memory grid
    "Derby",                                         # Embedded database
    "Apache Arrow",                                  # Columnar in-memory
]


def opt_b_projects():
    return OPTION_A_PROJECTS + OPTION_B_EXTRA


def opt_c_projects():
    return OPTION_A_PROJECTS + OPTION_C_EXTRA


def count_bug(coll, projects, *, require_logs=False):
    m = {
        "fields.project.name": {"$in": projects},
        "fields.issuetype.name": "Bug",
    }
    if require_logs:
        m["log_msgs.0"] = {"$exists": True}
    return coll.count_documents(m)


def count_any(coll, projects, *, require_logs=False):
    m = {"fields.project.name": {"$in": projects}}
    if require_logs:
        m["log_msgs.0"] = {"$exists": True}
    return coll.count_documents(m)


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    coll = client[MONGO_DB][MONGO_COL]

    options = {
        "A. Apache-7 (current)":          OPTION_A_PROJECTS,
        "B. Microservice-extended (+4)":   opt_b_projects(),
        "C. Distributed-systems (+17)":    opt_c_projects(),
    }

    results = {}

    print("=" * 110)
    print("WoL JIRA pool capacity — options matrix")
    print("All variants drop `pred_uncertainty` and `description >= 200 chars`.")
    print("=" * 110)

    for label, projects in options.items():
        bug_no_logs   = count_bug(coll, projects, require_logs=False)
        bug_with_logs = count_bug(coll, projects, require_logs=True)
        any_no_logs   = count_any(coll, projects, require_logs=False)
        any_with_logs = count_any(coll, projects, require_logs=True)
        results[label] = {
            "n_projects": len(projects),
            "projects": projects,
            "bug_no_logs": bug_no_logs,
            "bug_with_logs": bug_with_logs,
            "any_no_logs": any_no_logs,
            "any_with_logs": any_with_logs,
            "logs_filter_loss_bug": bug_no_logs - bug_with_logs,
            "logs_filter_loss_any": any_no_logs - any_with_logs,
        }

    # Print summary table
    print()
    print(f"  {'Option':<32} | {'Projects':>8} | {'Bug':>10} | {'Bug+logs':>10} | {'AllIssue':>10} | {'AllIss+logs':>12}")
    print("  " + "-" * 100)
    for label, r in results.items():
        print(f"  {label:<32} | {r['n_projects']:>8} | "
              f"{r['bug_no_logs']:>10,} | {r['bug_with_logs']:>10,} | "
              f"{r['any_no_logs']:>10,} | {r['any_with_logs']:>12,}")

    print()
    print("## Logs-filter loss (how many rows the logs filter drops)")
    print(f"  {'Option':<32} | {'Bug loss':>10} | {'Any loss':>10}")
    print("  " + "-" * 60)
    for label, r in results.items():
        print(f"  {label:<32} | {r['logs_filter_loss_bug']:>10,} | {r['logs_filter_loss_any']:>10,}")

    # Per-project Bug+logs breakdown for option C, so user can audit
    print()
    print("## Option C — per-project Bug count with log_msgs>=1 filter")
    print(f"  {'Project':<32} | {'Bug+logs':>10}")
    print("  " + "-" * 50)
    proj_breakdown = {}
    for p in opt_c_projects():
        n = count_bug(coll, [p], require_logs=True)
        proj_breakdown[p] = n
        in_a = "*" if p in OPTION_A_PROJECTS else " "
        print(f"  {in_a}{p:<31} | {n:>10,}")
    total_c = sum(proj_breakdown.values())
    print("  " + "-" * 50)
    print(f"  {'TOTAL':<32} | {total_c:>10,}")

    out_path = "scripts/research-lab/wol_options_matrix.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"options": results, "option_c_per_project_bug_with_logs": proj_breakdown},
            fh, indent=2,
        )
    print()
    print(f"Saved structured results to: {out_path}")


if __name__ == "__main__":
    main()
