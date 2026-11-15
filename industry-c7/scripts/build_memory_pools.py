"""Build per-project incident-memory pools from The Public Jira Dataset.

The localization memory does not need logs: ANY resolved, fix-linked past
issue can vote with its fix commit's files. PJD supplies the full fixed
history per tracker, which multiplies the memory pools far beyond the
log-bearing query sets (and memory value scales with pool density --
measured in 10-challenge7-results.md).

Per project, emits data/c7-benchmark/<project>-memory.jsonl:
  {key, issuetype, created, resolved, summary, text, fix_time, fix_shas,
   gold_files}
and <project>-dupclusters.json: {key: cluster_id} from PJD "Duplicate"
issue links (union-find), for the memory firewall.

Also emits <project>-created.json: {key: created_iso} for ALL issues of the
tracker prefix, so query-side firewalls can use true creation times.

Usage:
    python scripts/c7/build_memory_pools.py --project qt mongodb kafka mariadb
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_benchmark import OUT as BENCH_OUT  # noqa: E402
from mine_benchmark import (MAX_FIX_COMMITS, PROJECTS,  # noqa: E402
                            REPOS, TEST_PATH, fetch_file_lists,
                            link_commits)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-memory")

# Verified by probing each project's key prefix against every collection
# in JiraReposAnon rather than assuming from the project name: 20 Apache
# trackers, and infinispan/wildfly/keycloak live under RedHat, not their
# own. Probe output: all 27 found, none unmapped.
PJD_COLLECTION = {
    # Apache tracker
    "kafka": "Apache", "hive": "Apache", "hadoop": "Apache",
    "hbase": "Apache", "ambari": "Apache", "cassandra": "Apache",
    "spark": "Apache", "flink": "Apache", "groovy": "Apache",
    "camel": "Apache", "phoenix": "Apache", "impala": "Apache",
    "ignite": "Apache", "pdfbox": "Apache", "derby": "Apache",
    "solr": "Apache", "pig": "Apache", "geode": "Apache",
    "drill": "Apache", "beam": "Apache",
    # their own trackers
    "mariadb": "MariaDB", "mongodb": "MongoDB", "qt": "Qt",
    "sakai": "Sakai",
    # Red Hat tracker, NOT a per-project one
    "infinispan": "RedHat", "wildfly": "RedHat", "keycloak": "RedHat",
}
MEM_TEXT_CHARS = 4_000


def union_find_clusters(pairs: list[tuple[str, str]]) -> dict[str, str]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return {k: find(k) for k in parent}


def build(project: str) -> dict:
    from pymongo import MongoClient
    cfg = PROJECTS[project]
    prefix = cfg["key_prefix"]
    coll = MongoClient("localhost", 27017)["JiraReposAnon"][PJD_COLLECTION[project]]

    linked, _ = link_commits(cfg["git_dir"], prefix, cfg.get("link_via", "subject"))
    # the SAME cap the benchmark uses, imported rather than retyped.
    # These were 10 and 3 respectively: an issue with five fix commits
    # could be an instance you must localize but never a memory entry
    # that votes. Two rules where there is one decision, and they had
    # already drifted once. Costs 1.3% of kafka's pool, 0.1% of hive's.
    linked = {k: sorted(v, key=lambda c: c["ts"]) for k, v in linked.items()
              if 1 <= len(v) <= MAX_FIX_COMMITS}
    log.info("%s: %d keys linked at 1-%d commits", project,
             len(linked), MAX_FIX_COMMITS)

    rows, created_map, dup_pairs = [], {}, []
    # hadoop's key_prefix is a LIST (HADOOP, HDFS, YARN, MAPREDUCE) --
    # one tracker, four prefixes. f"^{prefix}-" on a list interpolates
    # the repr and matches nothing, so hadoop silently produced an empty
    # pool: 0 issues, 0 memory, no error. link_commits already handles
    # the list; only this query did not.
    prefixes = [prefix] if isinstance(prefix, str) else list(prefix)
    key_re = "^(" + "|".join(prefixes) + ")-"
    cur = coll.find(
        {"key": {"$regex": key_re}},
        {"key": 1, "fields.summary": 1, "fields.description": 1,
         "fields.created": 1, "fields.resolutiondate": 1,
         "fields.resolution.name": 1, "fields.issuetype.name": 1,
         "fields.issuelinks": 1})
    n_seen = n_fixed = 0
    for d in cur:
        n_seen += 1
        key, f = d["key"], d.get("fields") or {}
        if f.get("created"):
            created_map[key] = f["created"]
        for l in (f.get("issuelinks") or []):
            # Trackers name this link type differently: Apache and Red Hat
            # use "Duplicate", Sakai uses "3 - Duplicate". An exact match
            # silently finds zero duplicates on Sakai's 43,351 issues and
            # quietly disables firewall rule 2 for that project, so match on
            # the word rather than the whole label.
            if "duplicate" in (((l.get("type") or {}).get("name")) or "").lower():
                other = ((l.get("outwardIssue") or l.get("inwardIssue") or {})
                         .get("key"))
                if other:
                    dup_pairs.append((key, other))
        if ((f.get("resolution") or {}).get("name")) not in ("Fixed", "Done"):
            continue
        n_fixed += 1
        commits = linked.get(key)
        if not commits:
            continue
        rows.append({
            "key": key,
            "issuetype": (f.get("issuetype") or {}).get("name"),
            "created": f.get("created"),
            "resolved": f.get("resolutiondate"),
            "summary": f.get("summary") or "",
            "text": (f.get("description") or "")[:MEM_TEXT_CHARS],
            "fix_time": max(c["ts"] for c in commits),
            "fix_shas": [c["sha"] for c in commits],
        })
    log.info("%s: tracker issues=%d fixed=%d fixed+linked=%d",
             project, n_seen, n_fixed, len(rows))

    # gold files via the miner's sha cache (local full clones: fast)
    shas = [s for r in rows for s in r["fix_shas"]]
    cache = fetch_file_lists(cfg["git_dir"], shas, REPOS / f"cache-{project}.json")
    kept = []
    for r in rows:
        gold = set()
        for sha in r["fix_shas"]:
            for status, path in cache.get(sha, []):
                if (status == "M" and path.endswith(cfg["src_ext"])
                        and not TEST_PATH.search(path)):
                    gold.add(path)
        if gold:
            r["gold_files"] = sorted(gold)
            kept.append(r)
    log.info("%s: memory entries with source gold = %d", project, len(kept))

    BENCH_OUT.mkdir(parents=True, exist_ok=True)
    with (BENCH_OUT / f"{project}-memory.jsonl").open("w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    clusters = union_find_clusters(dup_pairs)
    (BENCH_OUT / f"{project}-dupclusters.json").write_text(
        json.dumps(clusters), encoding="utf-8")
    (BENCH_OUT / f"{project}-created.json").write_text(
        json.dumps(created_map), encoding="utf-8")
    return {"project": project, "tracker_issues": n_seen, "fixed": n_fixed,
            "fixed_linked": len(rows), "memory_with_gold": len(kept),
            "dup_cluster_keys": len(clusters)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", nargs="+", required=True,
                    choices=list(PJD_COLLECTION))
    args = ap.parse_args()
    out = {}
    for p in args.project:
        out[p] = build(p)
    path = BENCH_OUT / "memory-pools-datasheet.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.update(out)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    for p, s in out.items():
        print(p, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
