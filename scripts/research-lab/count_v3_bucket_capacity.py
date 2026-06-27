"""Count v3 bucket capacities — 24 projects × 12 buckets, no quality filters.

Grounds the cap / ratio decisions for build_wol_real_corpus_v3.py.

Buckets, mirroring v2's taxonomy:
  ticket_worthy  : Bug + resolution=Fixed
  borderline_*   : Bug + resolution ∈ {Duplicate, Incomplete, Cannot Reproduce}  (3 sub-buckets)
  noise_*        : Bug + resolution ∈ {Won't Fix, Invalid, Not a Bug, Not A Problem}  (4)
  regular_*      : issuetype ∈ {Improvement, New Feature, Question, Documentation, Wish}  (5)
"""
from __future__ import annotations
import json
from collections import defaultdict
from pymongo import MongoClient

PROJECTS = [
    "Spark", "Cassandra", "HBase", "Flink", "Ambari", "Kafka", "MariaDB Server",
    "Hive", "IMPALA", "Geode", "Infinispan",
    "Hadoop HDFS", "Hadoop YARN", "Hadoop Common",
    "Solr", "Apache Drill", "Beam", "Mesos",
    "ActiveMQ", "Camel", "CXF",
    "Ignite", "Derby", "Apache Arrow",
]

BUCKETS = {
    "ticket_worthy":     ("Bug", "Fixed"),
    "borderline_dup":    ("Bug", "Duplicate"),
    "borderline_inc":    ("Bug", "Incomplete"),
    "borderline_cnr":    ("Bug", "Cannot Reproduce"),
    "noise_wf":          ("Bug", "Won't Fix"),
    "noise_inv":         ("Bug", "Invalid"),
    "noise_nab":         ("Bug", {"$in": ["Not a Bug", "Not A Bug"]}),
    "noise_nap":         ("Bug", "Not A Problem"),
    "regular_improve":   ("Improvement", None),
    "regular_newfeat":   ("New Feature", None),
    "regular_question":  ("Question", None),
    "regular_doc":       ("Documentation", None),
    "regular_wish":      ("Wish", None),
}


def main():
    coll = MongoClient("mongodb://localhost:27017")["WoL_v1"]["JIRA"]

    capacity = defaultdict(dict)
    bucket_totals = {}

    print(f"{'Bucket':<22}", end="")
    for p in PROJECTS:
        # Print 8-char project abbreviations
        abbrev = p.replace("Apache ", "").replace("Hadoop ", "H-")[:7]
        print(f" {abbrev:>7}", end="")
    print("   TOTAL")
    print("-" * (22 + 24*8 + 8))

    for bucket_name, (issuetype, resolution) in BUCKETS.items():
        bucket_total = 0
        for project in PROJECTS:
            q = {
                "fields.project.name":   project,
                "fields.issuetype.name": issuetype,
            }
            if resolution is not None:
                q["fields.resolution.name"] = resolution
            n = coll.count_documents(q)
            capacity[bucket_name][project] = n
            bucket_total += n
        bucket_totals[bucket_name] = bucket_total

        # Print row
        print(f"{bucket_name:<22}", end="")
        for p in PROJECTS:
            n = capacity[bucket_name][p]
            print(f" {n:>7}", end="")
        print(f"   {bucket_total:>6}")

    # Roll-up summary
    print()
    print(f"{'Bucket':<22} {'Total':>10}")
    print("-" * 35)
    tw = bucket_totals["ticket_worthy"]
    border = sum(v for k, v in bucket_totals.items() if k.startswith("borderline_"))
    noise_bug = sum(v for k, v in bucket_totals.items() if k.startswith("noise_"))
    noise_reg = sum(v for k, v in bucket_totals.items() if k.startswith("regular_"))

    print(f"{'TICKET_WORTHY (Bug+Fixed)':<25} {tw:>10}")
    print(f"{'BORDERLINE TOTAL':<25} {border:>10}")
    print(f"{'NOISE (Bug, 4 resolutions)':<25} {noise_bug:>10}")
    print(f"{'REGULAR (non-Bug issuetypes)':<25} {noise_reg:>10}")
    print("-" * 35)
    print(f"{'GRAND TOTAL':<25} {tw + border + noise_bug + noise_reg:>10}")

    with open("scripts/research-lab/wol_v3_bucket_capacity.json", "w") as fh:
        json.dump({
            "projects":       PROJECTS,
            "buckets":        list(BUCKETS),
            "capacity":       capacity,
            "bucket_totals":  bucket_totals,
            "rollups": {
                "ticket_worthy": tw,
                "borderline":    border,
                "noise_bug":     noise_bug,
                "regular":       noise_reg,
            },
        }, fh, indent=2)
    print("\nSaved -> scripts/research-lab/wol_v3_bucket_capacity.json")


if __name__ == "__main__":
    main()
