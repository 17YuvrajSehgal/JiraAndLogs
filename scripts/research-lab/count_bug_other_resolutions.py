"""Verify Bug-other-resolution count for v3-plus.

Counts Bug rows in the 24-project scope whose resolution is NOT in any of the
buckets v3 currently has. Also breaks down by specific resolution value so we
know what 'other' actually contains.
"""
from collections import Counter
from pymongo import MongoClient

PROJECTS = [
    "Spark", "Cassandra", "HBase", "Flink", "Ambari", "Kafka", "MariaDB Server",
    "Hive", "IMPALA", "Geode", "Infinispan",
    "Hadoop HDFS", "Hadoop YARN", "Hadoop Common",
    "Solr", "Apache Drill", "Beam", "Mesos",
    "ActiveMQ", "Camel", "CXF",
    "Ignite", "Derby", "Apache Arrow",
]

KNOWN_RESOLUTIONS = [
    "Fixed",
    "Duplicate", "Incomplete", "Cannot Reproduce",
    "Won't Fix", "Invalid", "Not a Bug", "Not A Bug", "Not A Problem",
]

coll = MongoClient("mongodb://localhost:27017")["WoL_v1"]["JIRA"]

# Total Bug rows in 24 projects, any resolution (including null/missing)
total_bug = coll.count_documents({
    "fields.project.name": {"$in": PROJECTS},
    "fields.issuetype.name": "Bug",
})
print(f"Total Bug rows (24 projects, any resolution): {total_bug:,}")

# Bug rows with a known resolution
known_count = 0
for res in KNOWN_RESOLUTIONS:
    n = coll.count_documents({
        "fields.project.name": {"$in": PROJECTS},
        "fields.issuetype.name": "Bug",
        "fields.resolution.name": res,
    })
    known_count += n
    print(f"  {res:30s} {n:>7,}")
print(f"  {'KNOWN TOTAL':30s} {known_count:>7,}")

print()
print(f"Bug-other expected: {total_bug - known_count:,}")

# Bug rows with resolution NOT in known set
other_count = coll.count_documents({
    "fields.project.name": {"$in": PROJECTS},
    "fields.issuetype.name": "Bug",
    "fields.resolution.name": {"$nin": KNOWN_RESOLUTIONS},
})
print(f"Bug-other (resolution NOT IN known set, includes null): {other_count:,}")

# Break down by specific other-resolution values
print()
print("=" * 60)
print("Bug-other resolution breakdown (top 25)")
print("=" * 60)
pipeline = [
    {"$match": {
        "fields.project.name": {"$in": PROJECTS},
        "fields.issuetype.name": "Bug",
        "fields.resolution.name": {"$nin": KNOWN_RESOLUTIONS},
    }},
    {"$group": {"_id": "$fields.resolution.name", "n": {"$sum": 1}}},
    {"$sort": {"n": -1}},
    {"$limit": 25},
]
running_total = 0
for row in coll.aggregate(pipeline, allowDiskUse=True):
    res_name = row["_id"] if row["_id"] is not None else "(null / unresolved)"
    n = row["n"]
    running_total += n
    print(f"  {res_name:35s} {n:>6,}")
print(f"  {'(running total top 25)':35s} {running_total:>6,}")

# How many have resolution=null (truly unresolved)
n_null = coll.count_documents({
    "fields.project.name": {"$in": PROJECTS},
    "fields.issuetype.name": "Bug",
    "fields.resolution": None,
})
print()
print(f"  Bug rows with resolution = null (truly unresolved): {n_null:,}")
