"""Fetch Bug + resolution=Fixed counts for Options A/B/C with no quality filters,
so the final comparison table has all cells filled in."""
from pymongo import MongoClient

A = ["Spark", "Cassandra", "HBase", "Flink", "Ambari", "Kafka", "MariaDB Server"]
B_EXTRA = ["Hive", "IMPALA", "Geode", "Infinispan"]
C_EXTRA = B_EXTRA + [
    "Hadoop HDFS", "Hadoop YARN", "Hadoop Common",
    "Solr", "Apache Drill", "Beam", "Mesos",
    "ActiveMQ", "Camel", "CXF",
    "Ignite", "Derby", "Apache Arrow",
]

coll = MongoClient("mongodb://localhost:27017")["WoL_v1"]["JIRA"]


def bug_fixed(projects):
    return coll.count_documents({
        "fields.project.name": {"$in": projects},
        "fields.issuetype.name": "Bug",
        "fields.resolution.name": "Fixed",
    })


print(f"Option A (7 Apache):                 Bug+Fixed = {bug_fixed(A):>7,}")
print(f"Option B (11 Microservice-extended): Bug+Fixed = {bug_fixed(A + B_EXTRA):>7,}")
print(f"Option C (24 Distributed-systems):   Bug+Fixed = {bug_fixed(A + C_EXTRA):>7,}")
