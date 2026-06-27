"""WoL JIRA pool capacity with ALL quality filters removed.

Two sweeps:
  A) 7 Apache projects only, with pred_uncertainty + desc>=200 + log_msgs>=1 all dropped.
     Reports per-project, per-issuetype counts.
  B) Entire WoL JIRA collection (no project filter), all quality filters dropped.
     Reports global totals + top-50 projects by count.

Designed to answer: "if we relax everything, how big can the pool get?"
"""
from __future__ import annotations

import json
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "WoL_v1"
MONGO_COL = "JIRA"

APACHE7 = [
    "Spark", "Cassandra", "HBase", "Flink",
    "Ambari", "Kafka", "MariaDB Server",
]

# Issuetype groupings we report on
ISSUETYPE_GROUPS = {
    "Bug":               ["Bug"],
    "Improvement":       ["Improvement"],
    "New Feature":       ["New Feature"],
    "Task / Sub-task":   ["Task", "Sub-task", "Subtask"],
    "Question":          ["Question"],
    "Documentation":     ["Documentation"],
    "Wish":              ["Wish"],
    "Test / Other":      ["Test", "Story", "Epic", "Brainstorming"],
}


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    coll = client[MONGO_DB][MONGO_COL]

    grand_total_collection = coll.estimated_document_count()
    print("=" * 100)
    print(f"WoL JIRA total documents (no filter): {grand_total_collection:,}")
    print("=" * 100)
    print()

    # ----------------------------------------------------------------
    # Sweep A: 7 Apache projects, no quality filters, by issuetype
    # ----------------------------------------------------------------
    print("## SWEEP A — 7 Apache projects, NO quality filters")
    print("   (no pred_uncertainty, no desc-length, no log_msgs)")
    print()

    header = f"  {'Project':<20} | " + " | ".join(f"{g:<14}" for g in ISSUETYPE_GROUPS) + " | {:<8}".format("TOTAL")
    print(header)
    print("  " + "-" * (len(header) - 2))

    per_project_totals = {}
    per_issuetype_totals = {g: 0 for g in ISSUETYPE_GROUPS}
    grand_total_apache7 = 0

    for project in APACHE7:
        row_cells = []
        proj_total = 0
        for group, types in ISSUETYPE_GROUPS.items():
            n = coll.count_documents({
                "fields.project.name":  project,
                "fields.issuetype.name": {"$in": types},
            })
            row_cells.append(f"{n:<14}")
            per_issuetype_totals[group] += n
            proj_total += n
        # All issuetypes in this project (catches anything outside our groupings)
        proj_all = coll.count_documents({"fields.project.name": project})
        per_project_totals[project] = proj_all
        grand_total_apache7 += proj_all
        print(f"  {project:<20} | " + " | ".join(row_cells) + f" | {proj_all:<8}")

    # Sum line
    print("  " + "-" * (len(header) - 2))
    sum_cells = [f"{per_issuetype_totals[g]:<14}" for g in ISSUETYPE_GROUPS]
    print(f"  {'TOTAL':<20} | " + " | ".join(sum_cells) + f" | {grand_total_apache7:<8}")
    print()

    # ----------------------------------------------------------------
    # Sweep B: entire WoL JIRA, no quality filters, by issuetype
    # ----------------------------------------------------------------
    print()
    print("## SWEEP B — ENTIRE WoL JIRA, NO quality filters, NO project filter")
    print()

    print(f"  {'Issuetype':<24} | {'Count':>12}")
    print("  " + "-" * 40)
    sweep_b_total = 0
    for group, types in ISSUETYPE_GROUPS.items():
        n = coll.count_documents({"fields.issuetype.name": {"$in": types}})
        sweep_b_total += n
        print(f"  {group:<24} | {n:>12,}")
    print("  " + "-" * 40)
    # Grand global total — includes any issuetype outside our 8 groupings
    print(f"  {'(any issuetype)':<24} | {grand_total_collection:>12,}")
    print(f"  {'(sum of groups above)':<24} | {sweep_b_total:>12,}")

    # ----------------------------------------------------------------
    # Sweep C: top-50 projects globally (Bug only, no quality filters)
    # ----------------------------------------------------------------
    print()
    print()
    print("## SWEEP C — top-50 projects by Bug count (no quality filters)")
    print()
    pipeline = [
        {"$match": {"fields.issuetype.name": "Bug"}},
        {"$group": {"_id": "$fields.project.name", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 50},
    ]
    print(f"  {'Rank':>4} {'Project':<48} | {'Bug count':>10}")
    print("  " + "-" * 70)
    top_projects = []
    for i, row in enumerate(coll.aggregate(pipeline, allowDiskUse=True), start=1):
        proj = row["_id"] or "(unknown)"
        n = row["n"]
        in_seven = "*" if proj in APACHE7 else " "
        print(f"  {i:>4} {in_seven}{proj:<47} | {n:>10,}")
        top_projects.append({"rank": i, "project": proj, "bug_count": n, "in_apache7": proj in APACHE7})

    # ----------------------------------------------------------------
    # Sweep D: same but ALL issuetypes
    # ----------------------------------------------------------------
    print()
    print()
    print("## SWEEP D — top-50 projects by ALL-issuetype count (no quality filters)")
    print()
    pipeline = [
        {"$group": {"_id": "$fields.project.name", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 50},
    ]
    print(f"  {'Rank':>4} {'Project':<48} | {'Total':>10}")
    print("  " + "-" * 70)
    top_projects_all = []
    for i, row in enumerate(coll.aggregate(pipeline, allowDiskUse=True), start=1):
        proj = row["_id"] or "(unknown)"
        n = row["n"]
        in_seven = "*" if proj in APACHE7 else " "
        print(f"  {i:>4} {in_seven}{proj:<47} | {n:>10,}")
        top_projects_all.append({"rank": i, "project": proj, "total": n, "in_apache7": proj in APACHE7})

    # Persist results
    out = {
        "collection_total": grand_total_collection,
        "sweep_a_apache7_no_filters": {
            "per_project_total": per_project_totals,
            "per_issuetype_total": per_issuetype_totals,
            "grand_total": grand_total_apache7,
        },
        "sweep_b_entire_collection_no_filters": {
            "by_issuetype_group": {
                group: coll.count_documents({"fields.issuetype.name": {"$in": types}})
                for group, types in ISSUETYPE_GROUPS.items()
            },
            "any_issuetype": grand_total_collection,
        },
        "sweep_c_top50_bug_only": top_projects,
        "sweep_d_top50_all_issuetypes": top_projects_all,
    }
    out_path = "scripts/research-lab/wol_pool_unfiltered_sweep.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print()
    print(f"Saved structured results to: {out_path}")


if __name__ == "__main__":
    main()
