"""Verify the actual v2 dataset utilization vs Mongo capacity.

Three precise numbers:
  1. Bug + resolution=Fixed pool under strict v1 filters → what ticket_worthy actually samples from
  2. Bug-of-any-resolution pool under strict v1 filters → what all v2 buckets (TW + borderline + noise-bug) sample from
  3. Any-issuetype pool under strict v1 filters → maximum v2 capacity including non-Bug regular noise
"""
from __future__ import annotations
from pymongo import MongoClient

APACHE7 = ["Spark", "Cassandra", "HBase", "Flink", "Ambari", "Kafka", "MariaDB Server"]

PRED_U = 0.05
DESC_MIN = 200

BASE_QUALITY = {
    "fields.project.name": {"$in": APACHE7},
    "pred_uncertainty": {"$lte": PRED_U},
    "log_msgs.0": {"$exists": True},
    "$expr": {"$gte": [
        {"$strLenCP": {"$ifNull": ["$fields.description", ""]}},
        DESC_MIN,
    ]},
}


def main():
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)
    coll = client["WoL_v1"]["JIRA"]

    # 1. Bug + resolution=Fixed (the ticket_worthy pool)
    q1 = {**BASE_QUALITY, "fields.issuetype.name": "Bug", "fields.resolution.name": "Fixed"}
    n1 = coll.count_documents(q1)

    # 2. Bug of any resolution (TW + borderline-Bug + noise-Bug share this pool)
    q2 = {**BASE_QUALITY, "fields.issuetype.name": "Bug"}
    n2 = coll.count_documents(q2)

    # 3. Any issuetype (everything: Bug pools + non-Bug regular noise)
    q3 = {**BASE_QUALITY}
    n3 = coll.count_documents(q3)

    print("=" * 90)
    print("Current v2 utilization vs Mongo capacity")
    print("Filters held: pred_uncertainty <= 0.05, desc >= 200, log_msgs >= 1")
    print("=" * 90)
    print()
    print(f"  {'Pool':<55} | {'Available':>10} | {'v2 uses':>8}")
    print("  " + "-" * 84)
    print(f"  {'Bug + resolution=Fixed (ticket_worthy source)':<55} | {n1:>10,} | {2000:>8}")
    print(f"  {'Bug (any resolution; TW + borderline + bug-noise)':<55} | {n2:>10,} | {'9,341':>8}")
    print(f"  {'Any issuetype (max under v1 filters)':<55} | {n3:>10,} | {'9,341':>8}")
    print()
    print("v2 dataset breakdown (from data/.../dataset-metadata.json):")
    print("  - ticket_worthy : 2,000  (Bug + Fixed)")
    print("  - borderline    : 2,399  (Bug + Duplicate/Incomplete/Cannot Reproduce)")
    print("  - noise         : 4,942  (Bug + Won't Fix/Invalid/Not a Bug/Not A Problem")
    print("                            OR non-Bug Improvement/New Feature/Question/Documentation/Wish)")
    print("  - TOTAL         : 9,341")


if __name__ == "__main__":
    main()
