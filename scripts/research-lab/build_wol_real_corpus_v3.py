"""Build the WoL v3-plus dataset — 24 distributed-systems projects, no quality filters,
maximum pool utilization (~78K total rows).

Replaces v2's "augment over v1" architecture with a fresh, single-pass build:
  * 24 projects (Option C from the pool-expansion sweep, 2026-06-17)
  * No `pred_uncertainty` filter (was ≤ 0.05 in v1/v2)
  * No `description ≥ 200 chars` filter (was in v1/v2)
  * No `log_msgs ≥ 1` filter (was on Bug rows in v1/v2; redundant given Mongo data)
  * Text truncation bumped 4× (200 log lines / 6000 desc chars)
  * NO class-ratio constraint — uses full availability per bucket
  * Memory corpus ~38K Bug+Fixed rows (was 2K in v1/v2)
  * Two new borderline sub-buckets capture all Bug rows that didn't fit v2's taxonomy:
      borderline_unresolved : Bug + resolution=null (12,671 in 24-project pool)
      borderline_other_res  : Bug + resolution ∉ known set (3,093 in 24-project pool)

Output schema is IDENTICAL to v2 so the cascade pipelines, agent harness, and
training scripts all consume v3 without code changes — only the path changes.

Family-to-split: strict superset of v2. Test families preserved (Kafka, MariaDB)
so v3 predictions on test are directly comparable to v2's.

CLI:
  python -m scripts.research-lab.build_wol_real_corpus_v3 build \\
      --out-global-dir data/derived/global/2026-06-17-wol-real-v3-global \\
      [--seed 42] [--target-tw 38642] [--target-border 25619] [--target-noise 13879]

The script imports field mappers from v1 (`build_wol_real_corpus.py`) and
clustering / quota logic from v2 (`build_wol_real_corpus_v2.py`) so the v3
output is shape-compatible with v2 by construction.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse v1's field mappers (we override their global truncation constants below).
import build_wol_real_corpus as v1   # noqa: E402
# Reuse v2's quota + clustering helpers.
import build_wol_real_corpus_v2 as v2  # noqa: E402


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v3 constants
# ---------------------------------------------------------------------------

# Option C — 24 distributed-systems projects.
PROJECTS_V3: list[str] = [
    "Spark", "Cassandra", "HBase", "Flink", "Ambari", "Kafka", "MariaDB Server",
    "Hive", "IMPALA", "Geode", "Infinispan",
    "Hadoop HDFS", "Hadoop YARN", "Hadoop Common",
    "Solr", "Apache Drill", "Beam", "Mesos",
    "ActiveMQ", "Camel", "CXF",
    "Ignite", "Derby", "Apache Arrow",
]

# Per-project target ratios for quota distribution. Derived from each project's
# ticket_worthy (Bug+Fixed) capacity measured 2026-06-17 against Mongo.
# Sum across projects ≈ 1.0.
TW_CAPACITY = {
    "Spark": 2558, "Cassandra": 2121, "HBase": 2433, "Flink": 2098,
    "Ambari": 3084, "Kafka": 1147, "MariaDB Server": 5626,
    "Hive": 1894, "IMPALA": 1931, "Geode": 1651, "Infinispan": 1,
    "Hadoop HDFS": 1014, "Hadoop YARN": 827, "Hadoop Common": 1144,
    "Solr": 903, "Apache Drill": 1169, "Beam": 1005, "Mesos": 1125,
    "ActiveMQ": 944, "Camel": 1214, "CXF": 1116,
    "Ignite": 1346, "Derby": 1231, "Apache Arrow": 1060,
}
_TW_TOTAL = sum(TW_CAPACITY.values())
PROJECT_TARGET_RATIOS_V3: dict[str, float] = {
    p: n / _TW_TOTAL for p, n in TW_CAPACITY.items()
}

# Family-to-split assignment — strict superset of v2.
FAMILY_ASSIGNMENT_V3: dict[str, str] = {
    # v2's families — keep test/val unchanged for direct comparability
    "wol-spark":           "train",
    "wol-cassandra":       "train",
    "wol-hbase":           "train",
    "wol-flink":           "train",
    "wol-ambari":          "validation",
    "wol-kafka":           "test",
    "wol-mariadb-server":  "test",
    # 17 new families — all train
    "wol-hive":            "train",
    "wol-impala":          "train",
    "wol-geode":           "train",
    "wol-infinispan":      "train",
    "wol-hadoop-hdfs":     "train",
    "wol-hadoop-yarn":     "train",
    "wol-hadoop-common":   "train",
    "wol-solr":            "train",
    "wol-apache-drill":    "train",
    "wol-beam":            "train",
    "wol-mesos":           "train",
    "wol-activemq":        "train",
    "wol-camel":           "train",
    "wol-cxf":             "train",
    "wol-ignite":          "train",
    "wol-derby":           "train",
    "wol-apache-arrow":    "train",
}

# Bucket taxonomy — extends v2 with two new borderline sub-buckets for v3-plus.
TICKET_WORTHY_RESOLUTION  = "Fixed"
BORDERLINE_RESOLUTIONS    = ["Duplicate", "Incomplete", "Cannot Reproduce"]
NOISE_RESOLUTIONS         = ["Won't Fix", "Invalid", "Not a Bug", "Not A Problem"]
REGULAR_ISSUETYPES        = ["Improvement", "New Feature", "Question",
                              "Documentation", "Wish"]

# v3-plus only — the union of all "known" Bug resolutions used to filter the
# `borderline_other_res` bucket. Anything Bug NOT in this set AND NOT null
# falls into borderline_other_res.
ALL_KNOWN_BUG_RESOLUTIONS = (
    [TICKET_WORTHY_RESOLUTION]
    + BORDERLINE_RESOLUTIONS
    + NOISE_RESOLUTIONS
    + ["Not A Bug"]  # variant spelling that Mongo carries alongside "Not a Bug"
)

# Default caps (CLI-overridable). v3-plus uses full availability per bucket.
# Total target ≈ 78,140 = 38,642 TW + 25,619 borderline + 13,879 noise.
DEFAULT_TARGET_TW       = 38642   # full Bug+Fixed pool
DEFAULT_TARGET_BORDER   = 25619   # full borderline pool (3 orig + 2 new sub-buckets)
DEFAULT_TARGET_NOISE    = 13879   # full noise+regular pool (capped at availability)

# Within noise: 55/45 split between resolution-based and issuetype-based.
NOISE_RESOLUTION_FRACTION = 0.55
NOISE_REGULAR_FRACTION    = 0.45

# Duplicate-link taxonomy — same as v2.
DUPLICATE_LINK_TYPES_TIGHT = v2.DUPLICATE_LINK_TYPES_TIGHT

# Text truncation — bumped 4× from v1/v2 defaults.
MAX_LOG_MSGS_PER_TICKET_V3 = 200    # was 50
MAX_DESC_CHARS_V3          = 6000   # was 1500

# Mongo connection — same as v1/v2.
MONGO_URI = v1.MONGO_URI
MONGO_DB  = v1.MONGO_DB
MONGO_COL = v1.MONGO_COL


# ---------------------------------------------------------------------------
# Override v1's truncation constants for the bigger v3 limits.
# Field mappers in v1 read these via _first_n_log_msgs() and _truncated_description().
# ---------------------------------------------------------------------------

v1.MAX_LOG_MSGS_PER_TICKET = MAX_LOG_MSGS_PER_TICKET_V3
v1.MAX_DESC_CHARS          = MAX_DESC_CHARS_V3


# ---------------------------------------------------------------------------
# Strong-match Jaccard threshold
# ---------------------------------------------------------------------------

# Same as v1 (set to 0.15 after empirical calibration on real Jira data).
STRONG_MATCH_JACCARD_THRESHOLD = 0.15


# ---------------------------------------------------------------------------
# Bucket harvesting — NO quality filters (the load-bearing v3 change)
# ---------------------------------------------------------------------------


def harvest_bucket_v3(
    coll,
    *,
    project_name: str,
    bucket_filter: dict,
    cache_path: Path,
    overwrite: bool = False,
) -> int:
    """Extract one (project, bucket) slice from Mongo with NO quality filters.

    Differs from v2's `_harvest_bucket` in exactly two ways:
      1. No `pred_uncertainty` ≤ 0.05 predicate.
      2. No `description ≥ 200 chars` $expr.
      3. No `log_msgs.{N-1} $exists` predicate.

    Only the explicit bucket_filter (issuetype + optional resolution) is applied.
    `log_blks` is still projected out (it's enormous per-token data we never use).

    Returns the number of records written to cache_path.
    """
    if cache_path.exists() and not overwrite:
        return sum(1 for _ in cache_path.open(encoding="utf-8"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    match = {"fields.project.name": project_name, **bucket_filter}

    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    n = 0
    with tmp.open("w", encoding="utf-8") as fh:
        cursor = coll.find(
            match,
            projection={"log_blks": 0},
            no_cursor_timeout=True,
        )
        try:
            for doc in cursor:
                fh.write(json.dumps(doc, default=str, ensure_ascii=False) + "\n")
                n += 1
        finally:
            cursor.close()
    tmp.replace(cache_path)
    return n


def harvest_all_buckets_v3(
    cache_root: Path,
    *,
    overwrite: bool = False,
) -> dict[str, v2.BucketCapacity]:
    """Run the full Mongo harvest for v3's bucket taxonomy.

    Buckets:
      ticket_worthy:                       Bug + Fixed
      borderline_{duplicate,incomplete,cannot-reproduce}:  Bug + each resolution
      noise_{wont-fix,invalid,not-a-bug,not-a-problem}:    Bug + each resolution
      regular_{improvement,new-feature,question,documentation,wish}: each issuetype

    Returns {bucket_name -> BucketCapacity}.
    """
    coll = v1.get_mongo_collection()
    capacities: dict[str, v2.BucketCapacity] = {}

    bucket_defs: list[tuple[str, dict]] = []
    bucket_defs.append((
        "ticket_worthy",
        {"fields.issuetype.name": "Bug",
         "fields.resolution.name": TICKET_WORTHY_RESOLUTION},
    ))
    for res in BORDERLINE_RESOLUTIONS:
        bucket_defs.append((
            f"borderline_{v1.slugify_project_name(res)}",
            {"fields.issuetype.name": "Bug", "fields.resolution.name": res},
        ))
    # v3-plus new bucket #1: Bug + resolution=null (truly unresolved)
    bucket_defs.append((
        "borderline_unresolved",
        {"fields.issuetype.name": "Bug", "fields.resolution": None},
    ))
    # v3-plus new bucket #2: Bug + resolution in any named value NOT already bucketed
    bucket_defs.append((
        "borderline_other_res",
        {"fields.issuetype.name": "Bug",
         "fields.resolution.name": {"$nin": ALL_KNOWN_BUG_RESOLUTIONS, "$ne": None}},
    ))
    for res in NOISE_RESOLUTIONS:
        bucket_defs.append((
            f"noise_{v1.slugify_project_name(res)}",
            {"fields.issuetype.name": "Bug",
             "fields.resolution.name": (
                 {"$in": ["Not a Bug", "Not A Bug"]} if res == "Not a Bug" else res
             )},
        ))
    for it in REGULAR_ISSUETYPES:
        bucket_defs.append((
            f"regular_{v1.slugify_project_name(it)}",
            {"fields.issuetype.name": it},
        ))

    for bucket_name, bucket_filter in bucket_defs:
        per_project: dict[str, int] = {}
        for project in PROJECTS_V3:
            slug = v1.slugify_project_name(project)
            cache_path = cache_root / bucket_name / f"{slug}.jsonl"
            n = harvest_bucket_v3(
                coll,
                project_name=project,
                bucket_filter=bucket_filter,
                cache_path=cache_path,
                overwrite=overwrite,
            )
            per_project[project] = n
            log.info("  harvest %s / %s -> n=%d", bucket_name, project, n)
        capacities[bucket_name] = v2.BucketCapacity(bucket_name, per_project)
        log.info("BUCKET %s total: %d", bucket_name, capacities[bucket_name].total())

    return capacities


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def label_from_bucket(bucket_name: str) -> str:
    if bucket_name == "ticket_worthy":
        return "ticket_worthy"
    if bucket_name.startswith("borderline_"):
        return "borderline"
    if bucket_name.startswith("noise_") or bucket_name.startswith("regular_"):
        return "noise"
    raise ValueError(f"unknown bucket {bucket_name!r}")


def sample_pool_v3(
    cache_root: Path,
    *,
    quotas_per_bucket: dict[str, dict[str, int]],
    seed: int,
) -> list[dict]:
    """Read cached bucket JSONLs and randomly sample to the quota.

    Returns a flat list of Mongo docs, each tagged with `_bucket` so the
    caller can route to the right triage_label.
    """
    rng = random.Random(seed)
    out: list[dict] = []
    for bucket_name, per_project_quota in quotas_per_bucket.items():
        for project, n_target in per_project_quota.items():
            if n_target <= 0:
                continue
            slug = v1.slugify_project_name(project)
            cache_path = cache_root / bucket_name / f"{slug}.jsonl"
            if not cache_path.exists():
                log.warning("  cache missing: %s — skipping", cache_path)
                continue
            rows = [json.loads(line) for line in cache_path.open(encoding="utf-8")]
            if not rows:
                continue
            picked = rows if len(rows) <= n_target else rng.sample(rows, n_target)
            for d in picked:
                d["_bucket"] = bucket_name
                d["_project"] = project
            out.extend(picked)
            log.info("  sampled %s / %s: n=%d / %d available",
                     bucket_name, project, len(picked), len(rows))
    return out


# ---------------------------------------------------------------------------
# Gold relations (coarse + strong)
# ---------------------------------------------------------------------------


def _symptom_tokens(log_msgs: list[str]) -> set[str]:
    """Tokenize log_msgs for the strong-match Jaccard. Reuses v1's stopword set."""
    text = " ".join(log_msgs).lower()
    raw = re.findall(r"[a-z][a-z0-9_]{2,}", text)
    return {t for t in raw if t not in v1.SYMPTOM_STOPWORDS}


def _coarse_match(a_doc: dict, b_doc: dict) -> bool:
    """Same project AND at least one shared component."""
    a_proj = v1._safe_get(a_doc, "fields", "project", "name")
    b_proj = v1._safe_get(b_doc, "fields", "project", "name")
    if not a_proj or not b_proj or a_proj != b_proj:
        return False
    a_comps = set(v1._component_names(a_doc))
    b_comps = set(v1._component_names(b_doc))
    return len(a_comps & b_comps) >= 1


def _strong_match(
    a_doc: dict, b_doc: dict, a_tokens: set[str], b_tokens: set[str],
    *, threshold: float = STRONG_MATCH_JACCARD_THRESHOLD,
) -> bool:
    """Coarse match AND symptom-token Jaccard > threshold."""
    if not _coarse_match(a_doc, b_doc):
        return False
    if not a_tokens or not b_tokens:
        return False
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return (inter / union) > threshold


def compute_gold_relations(
    memory_docs: list[dict],
    query_docs: list[dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """For each TICKET_WORTHY query, find matching memory items under coarse / strong.

    Memory items are the same docs that are also tagged `ticket_worthy` on the
    query side — but the search excludes self-matches (b_doc._id != a_doc._id).
    Non-TW queries (borderline / noise) get empty gold by construction; this
    function does not emit rows for them — the caller writes empty rows for
    those windows.

    Returns (coarse, strong) dicts keyed on window_id.
    """
    # Index memory docs by their _id for fast lookup
    mem_by_id = {d["_id"]: d for d in memory_docs}
    mem_tokens = {wid: _symptom_tokens(v1._first_n_log_msgs(d))
                  for wid, d in mem_by_id.items()}
    # Pre-index memory by project for faster O(N*M_proj) instead of O(N*M)
    mem_by_project: dict[str, list[str]] = defaultdict(list)
    for mid, mdoc in mem_by_id.items():
        proj = v1._safe_get(mdoc, "fields", "project", "name") or ""
        mem_by_project[proj].append(mid)

    coarse: dict[str, list[str]] = {}
    strong: dict[str, list[str]] = {}

    for q_doc in query_docs:
        if q_doc.get("_bucket") != "ticket_worthy":
            continue  # Only TW queries have non-empty gold by design
        q_id = q_doc["_id"]
        q_proj = v1._safe_get(q_doc, "fields", "project", "name") or ""
        q_tokens = _symptom_tokens(v1._first_n_log_msgs(q_doc))
        q_wid = f"wol-q-{v1._short_id(q_id)}"

        cand_ids = mem_by_project.get(q_proj, [])

        c_list: list[str] = []
        s_list: list[str] = []
        for m_id in cand_ids:
            if m_id == q_id:
                continue
            m_doc = mem_by_id[m_id]
            if _coarse_match(q_doc, m_doc):
                c_list.append("wol-m-" + v1._short_id(m_id))
                if _strong_match(q_doc, m_doc, q_tokens, mem_tokens[m_id]):
                    s_list.append("wol-m-" + v1._short_id(m_id))
        coarse[q_wid] = c_list
        strong[q_wid] = s_list

    return coarse, strong


# ---------------------------------------------------------------------------
# Field mappers — produce v2-compatible row shapes
# ---------------------------------------------------------------------------


def map_query_v3(
    doc: dict,
    *,
    dataset_run_id: str,
    triage_label: str,
    bucket_name: str,
    priority_map: dict[str, str],
    fallback_set: set[str],
    split: str | None,
    feature_columns: list[str],
    incident_episode_id: str | None = None,
) -> dict:
    """Mongo doc -> global-triage-examples.jsonl row (TW or non-TW).

    Identical shape to v1's `map_to_global_triage_example` (flat 94 feature
    columns) for TW rows, and v2's `map_to_triagewindow_v2` for borderline/
    noise rows. Unified here.
    """
    wol_id   = doc.get("_id", "")
    sid      = v1._short_id(wol_id)
    window_id = f"wol-q-{sid}"

    log_msgs   = v1._first_n_log_msgs(doc)
    summary    = v1._safe_get(doc, "fields", "summary") or ""
    desc       = v1._truncated_description(doc)
    components = v1._component_names(doc)

    # Build evidence_text from logs; fall back to summary+desc for log-less tickets.
    if log_msgs:
        evidence_text = "\n".join(log_msgs)
    else:
        evidence_text = f"{summary}\n\n{desc}".strip()

    raw_pri = v1._safe_get(doc, "fields", "priority", "name")
    severity, uncertain = v1.normalize_priority(raw_pri, priority_map, fallback_set)

    project_name = v1._safe_get(doc, "fields", "project", "name") or ""
    scenario_family = f"wol-{v1.slugify_project_name(project_name)}"
    service_name = components[0] if components else scenario_family

    now_iso = datetime.now(timezone.utc).isoformat()

    row: dict[str, Any] = {
        "window_id":            window_id,
        "dataset_run_id":       dataset_run_id,
        "incident_episode_id":  incident_episode_id or window_id,
        "scenario_id":          f"{scenario_family}-{sid}",
        "scenario_family":      scenario_family,
        "service_name":         service_name,
        "window_type":          "active_fault",
        "start_time":           now_iso,
        "end_time":             now_iso,
        "triage_label":         triage_label,
        "triage_severity":      severity,
        "severity_uncertain":   uncertain,
        "triage_components":    components or None,
        "triage_reason_class":  v1._classify_triage_reason(summary),
        "is_hard_case":         False,
        "source":               f"wol-v3-{bucket_name}",
        "triage_evidence_text": evidence_text,
        "fault_compatibility_class": "wol-real",
        "wol_source_id":        wol_id,
        "wol_project":          project_name,
        "wol_issue_key":        doc.get("key"),
    }
    if split:
        row["split"] = split
    # All 94 triage_feature_* columns, flat at top level, zero-filled.
    for col in feature_columns:
        row[col] = 0.0
    return row


# ---------------------------------------------------------------------------
# Duplicate clustering — reuse v2's union-find but tag the v3 incident scheme
# ---------------------------------------------------------------------------


def cluster_duplicate_links_v3(
    rows: list[dict],
    cache_root: Path,
) -> dict[str, str]:
    """Build connected components over Jira `is duplicate of` / `Cloners` / `Cause`
    link types, restricted to row pairs where BOTH endpoints survived sampling.

    Returns {window_id -> shared_incident_episode_id}.
    """
    # Index our row pool by Jira key
    row_by_jirakey: dict[str, dict] = {}
    for r in rows:
        jkey = r.get("wol_issue_key")
        if jkey:
            row_by_jirakey[jkey] = r

    # Walk every bucket cache to find the raw docs with link info
    doc_by_jirakey: dict[str, dict] = {}
    for cache_jsonl in cache_root.rglob("*.jsonl"):
        for line in cache_jsonl.open(encoding="utf-8"):
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            jkey = doc.get("key")
            if jkey in row_by_jirakey:
                doc_by_jirakey[jkey] = doc

    # Union-find keyed on Jira key
    parent: dict[str, str] = {k: k for k in row_by_jirakey}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    n_edges = 0
    for jkey, doc in doc_by_jirakey.items():
        links = v1._safe_get(doc, "fields", "issuelinks") or []
        for link in links:
            if not isinstance(link, dict):
                continue
            ltype = v1._safe_get(link, "type", "name") or ""
            if ltype not in DUPLICATE_LINK_TYPES_TIGHT:
                continue
            for direction in ("inwardIssue", "outwardIssue"):
                tgt = link.get(direction)
                if isinstance(tgt, dict):
                    tgt_key = tgt.get("key")
                    if tgt_key and tgt_key in parent:
                        union(jkey, tgt_key)
                        n_edges += 1

    # Build cluster map
    clusters: dict[str, list[str]] = defaultdict(list)
    for jkey in parent:
        clusters[find(jkey)].append(jkey)

    n_multi = sum(1 for c in clusters.values() if len(c) > 1)
    log.info("Duplicate-link clustering: %d edges -> %d clusters (%d multi-ticket)",
             n_edges, len(clusters), n_multi)

    out: dict[str, str] = {}
    for cluster in clusters.values():
        if len(cluster) <= 1:
            continue
        cluster.sort()
        root_jkey = cluster[0]
        root_window_id = row_by_jirakey[root_jkey]["window_id"]
        incident_id = f"wol-incident-{root_window_id[len('wol-q-'):]}"
        for jkey in cluster:
            window_id = row_by_jirakey[jkey]["window_id"]
            out[window_id] = incident_id

    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def load_feature_columns(synthetic_global_dir: Path) -> list[str]:
    schema_path = synthetic_global_dir / "triage-feature-columns.json"
    if not schema_path.exists():
        log.warning("Feature-columns schema not found at %s — using empty list",
                    schema_path)
        return []
    d = json.loads(schema_path.read_text(encoding="utf-8"))
    return list(d.get("feature_columns") or [])


def write_v3_outputs(
    out_dir: Path,
    *,
    memory_docs: list[dict],
    query_rows: list[dict],
    sampled_docs: list[dict],
    coarse_gold: dict[str, list[str]],
    strong_gold: dict[str, list[str]],
    priority_map: dict[str, str],
    fallback_set: set[str],
    feature_columns: list[str],
    family_assignment: dict[str, str],
    label_counts: dict[str, dict[str, int]],
    seed: int,
    n_multi_clusters: int,
    capacities: dict[str, v2.BucketCapacity],
    dataset_run_id_root: str,
    started_at: str,
) -> None:
    """Write every artifact in the v2-compatible directory layout."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. jira-memory-corpus.jsonl (memory side, JiraMemoryIssue schema)
    mem_path = out_dir / "jira-memory-corpus.jsonl"
    tmp = mem_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for doc in memory_docs:
            wol_id = doc["_id"]
            sid    = v1._short_id(wol_id)
            project_name = v1._safe_get(doc, "fields", "project", "name") or ""
            scenario_family = f"wol-{v1.slugify_project_name(project_name)}"
            components = v1._component_names(doc)
            service_name = components[0] if components else scenario_family
            raw_pri = v1._safe_get(doc, "fields", "priority", "name")
            severity, _ = v1.normalize_priority(raw_pri, priority_map, fallback_set)
            summary = v1._safe_get(doc, "fields", "summary") or ""
            fault_type = v1._classify_triage_reason(summary)
            per_record_run_id = f"{dataset_run_id_root}-{sid}"
            rec = v1.map_to_jira_memory_issue(
                doc,
                dataset_run_id=per_record_run_id,
                severity=severity,
                scenario_family=scenario_family,
                affected_service=service_name,
                fault_type=fault_type,
                fault_compatibility_class="wol-real",
                linked_window_ids=[f"wol-q-{sid}"],
            )
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    tmp.replace(mem_path)
    log.info("  wrote jira-memory-corpus.jsonl (%d rows)", len(memory_docs))

    # 2. jira-shadow-humanized-v2/bulk-20260617/timeline.jsonl
    hum_root = out_dir / "jira-shadow-humanized-v2" / "bulk-20260617"
    hum_root.mkdir(parents=True, exist_ok=True)
    hum_path = hum_root / "timeline.jsonl"
    tmp = hum_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for doc in memory_docs:
            wol_id = doc["_id"]
            sid    = v1._short_id(wol_id)
            project_name = v1._safe_get(doc, "fields", "project", "name") or ""
            scenario_family = f"wol-{v1.slugify_project_name(project_name)}"
            components = v1._component_names(doc)
            service_name = components[0] if components else scenario_family
            raw_pri = v1._safe_get(doc, "fields", "priority", "name")
            severity, uncertain = v1.normalize_priority(raw_pri, priority_map, fallback_set)
            per_record_run_id = f"{dataset_run_id_root}-{sid}"
            rec = v1.map_to_humanized_timeline(
                doc,
                is_distractor=False,
                dataset_run_id=per_record_run_id,
                severity_seen=severity,
                severity_uncertain=uncertain,
                scenario_family=scenario_family,
                affected_services_seen=[service_name],
            )
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    tmp.replace(hum_path)
    log.info("  wrote jira-shadow-humanized-v2/bulk-20260617/timeline.jsonl")

    # 3. global-triage-examples.jsonl (all queries: TW + borderline + noise)
    ex_path = out_dir / "global-triage-examples.jsonl"
    tmp = ex_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in query_rows:
            r_clean = {k: v for k, v in r.items() if not k.startswith("_")}
            fh.write(json.dumps(r_clean, default=str, ensure_ascii=False) + "\n")
    tmp.replace(ex_path)
    log.info("  wrote global-triage-examples.jsonl (%d rows)", len(query_rows))

    # 4. window-memory-matchings.jsonl (coarse) + window-memory-matchings-strong.jsonl
    for gold_dict, fname, label in [
        (coarse_gold, "window-memory-matchings.jsonl",        "coarse"),
        (strong_gold, "window-memory-matchings-strong.jsonl", "strong"),
    ]:
        gpath = out_dir / fname
        tmp = gpath.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in query_rows:
                wid = r["window_id"]
                matched = gold_dict.get(wid, [])
                is_novel = (r["triage_label"] == "ticket_worthy") and (len(matched) == 0)
                # Non-TW windows get empty gold; harness treats empty as "doesn't contribute to Hit@K"
                rec = {
                    "window_id":                  wid,
                    "dataset_run_id":             r["dataset_run_id"],
                    "scenario_family":            r["scenario_family"],
                    "affected_service":           r["service_name"],
                    "fault_compatibility_class":  r["fault_compatibility_class"],
                    "triage_label":               r["triage_label"],
                    "is_novel":                   is_novel,
                    "matched_memory_issue_ids":   matched,
                    "expected_in_memory":         len(matched) > 0,
                    "match_strength":             label if matched else "empty",
                }
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        tmp.replace(gpath)
        log.info("  wrote %s", fname)

    # 5. triage-split-manifest.json
    split_path = out_dir / "triage-split-manifest.json"
    manifest = {
        "schema_version":   1,
        "split_by":         "scenario_family",
        "global_dataset_id": out_dir.name,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "started_at":       started_at,
        "family_assignment": family_assignment,
        "label_counts_by_split": label_counts,
        "leave_one_family_out_folds": [
            {"fold_id": f"loo-{fam}", "held_out_family": fam}
            for fam in sorted(family_assignment)
        ],
        "seed": seed,
        "version": "v3",
        "comparable_to": "2026-06-15-wol-real-v2-global",
    }
    split_path.write_text(
        json.dumps(manifest, default=str, indent=2) + "\n", encoding="utf-8",
    )
    log.info("  wrote triage-split-manifest.json")

    # 6. triage-feature-columns.json (copy from synthetic OB)
    fcol_path = out_dir / "triage-feature-columns.json"
    fcol_path.write_text(
        json.dumps({
            "schema_version": 1,
            "policy": "All fields prefixed with triage_feature_ are model inputs.",
            "feature_columns": feature_columns,
            "eval_only_fields": [
                "scenario_id", "scenario_family", "triage_label", "triage_severity",
                "triage_components", "triage_reason_class", "is_hard_case",
                "source", "is_novel", "matched_memory_issue_ids",
                "triage_evidence_text",
            ],
        }, indent=2),
        encoding="utf-8",
    )
    log.info("  wrote triage-feature-columns.json (%d cols)", len(feature_columns))

    # 7. wol-priority-mapping.json (copy verbatim from v2)
    pmap_src = Path("data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    if pmap_src.exists():
        shutil.copy2(pmap_src, out_dir / "wol-priority-mapping.json")

    # 8. dataset-metadata.json
    meta = {
        "global_dataset_id":  out_dir.name,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "started_at":         started_at,
        "source_kind":        "wol-v3-fresh-build",
        "version":            "v3",
        "comparable_to":      "2026-06-15-wol-real-v2-global",
        "n_projects":         len(PROJECTS_V3),
        "projects":           PROJECTS_V3,
        "n_memory":           len(memory_docs),
        "n_queries":          len(query_rows),
        "n_ticket_worthy":    sum(1 for r in query_rows if r["triage_label"] == "ticket_worthy"),
        "n_borderline":       sum(1 for r in query_rows if r["triage_label"] == "borderline"),
        "n_noise":            sum(1 for r in query_rows if r["triage_label"] == "noise"),
        "n_multi_incident_clusters": n_multi_clusters,
        "label_counts_by_split": label_counts,
        "bucket_capacities":  {bn: c.total() for bn, c in capacities.items()},
        "v3_changes_from_v2": {
            "pred_uncertainty_filter": "REMOVED (was <= 0.05)",
            "description_min_chars":   "REMOVED (was 200)",
            "log_msgs_min":            "REMOVED (was 1)",
            "MAX_LOG_MSGS_PER_TICKET": f"{MAX_LOG_MSGS_PER_TICKET_V3} (was 50)",
            "MAX_DESC_CHARS":          f"{MAX_DESC_CHARS_V3} (was 1500)",
            "projects":                f"{len(PROJECTS_V3)} (was 7)",
        },
        "seed":               seed,
    }
    (out_dir / "dataset-metadata.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8",
    )
    log.info("  wrote dataset-metadata.json")

    # 9. source-mapping.csv
    sm_path = out_dir / "source-mapping.csv"
    tmp = sm_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["window_id", "triage_label", "wol_source_id",
                    "wol_project", "wol_issue_key", "scenario_family"])
        for r in query_rows:
            w.writerow([
                r["window_id"], r["triage_label"], r["wol_source_id"],
                r.get("wol_project", ""), r.get("wol_issue_key", "") or "",
                r["scenario_family"],
            ])
    tmp.replace(sm_path)
    log.info("  wrote source-mapping.csv")

    # 10. README.md
    n_tw     = meta["n_ticket_worthy"]
    n_border = meta["n_borderline"]
    n_noise  = meta["n_noise"]
    n_total  = meta["n_queries"]
    trivial_baseline = max(n_tw, n_border, n_noise) / max(1, n_total)
    readme = f"""# World of Logs (WoL) v3 — Apache Jira incident dataset, Option C scope

Fresh build replacing v2 (`2026-06-15-wol-real-v2-global`) with significantly
expanded project scope and relaxed quality filters.

## Headline numbers

- **{n_total:,} total query rows** ({n_tw:,} ticket_worthy / {n_border:,} borderline / {n_noise:,} noise)
- **{len(memory_docs):,} memory items** (Bug + Fixed across {len(PROJECTS_V3)} Apache projects)
- **{n_multi_clusters} multi-ticket incidents** (via Jira `is duplicate of` / `Cloners` / `Cause` links)
- **Trivial-baseline triage accuracy**: {trivial_baseline:.3f} (majority class fraction)

## Project scope ({len(PROJECTS_V3)} projects)

{', '.join(PROJECTS_V3)}

## Family-to-split assignment

| Split | Families |
|---|---|
| train      | {', '.join(sorted(f for f, s in family_assignment.items() if s == 'train'))} |
| validation | {', '.join(sorted(f for f, s in family_assignment.items() if s == 'validation'))} |
| test       | {', '.join(sorted(f for f, s in family_assignment.items() if s == 'test'))} |

**Test families preserved from v2** — Kafka + MariaDB-Server — so v3 predictions
on the test split are directly comparable to v2's.

## Label distribution by split

```
{json.dumps(label_counts, indent=2)}
```

## Quality filters

**ALL DROPPED in v3**:
- ~~`pred_uncertainty ≤ 0.05`~~ — removed
- ~~`description ≥ 200 chars`~~ — removed
- ~~`log_msgs ≥ 1`~~ — removed (was redundant given description filter anyway)

Only the bucket-defining filters remain:
- `ticket_worthy`: issuetype=Bug, resolution=Fixed
- `borderline_*`: issuetype=Bug, resolution ∈ {{Duplicate, Incomplete, Cannot Reproduce}}
- `noise_*`: issuetype=Bug, resolution ∈ {{Won't Fix, Invalid, Not a Bug, Not A Problem}}
- `regular_*`: issuetype ∈ {{Improvement, New Feature, Question, Documentation, Wish}}

## Text truncation (bumped 4× from v2)

| Field | v2 | v3 |
|---|---:|---:|
| MAX_LOG_MSGS_PER_TICKET | 50 | {MAX_LOG_MSGS_PER_TICKET_V3} |
| MAX_DESC_CHARS | 1,500 | {MAX_DESC_CHARS_V3} |

Note: dense bi-encoder (all-MiniLM-L6-v2) truncates at ~1500 chars internally,
so the bigger limits primarily benefit BM25, the LLM verifier, and KG extraction.

## File inventory

| File | Rows | Purpose |
|---|---|---|
| `global-triage-examples.jsonl` | {n_total:,} | Per-ticket "window" rows |
| `jira-memory-corpus.jsonl` | {len(memory_docs):,} | Memory items (Bug+Fixed) |
| `jira-shadow-humanized-v2/bulk-20260617/timeline.jsonl` | {len(memory_docs):,} | Memory humanized timeline |
| `window-memory-matchings.jsonl` | {n_total:,} | Coarse gold (project + ≥1 shared component) |
| `window-memory-matchings-strong.jsonl` | {n_total:,} | Strong gold (coarse + Jaccard > {STRONG_MATCH_JACCARD_THRESHOLD}) |
| `triage-split-manifest.json` | — | Family → split assignment |
| `triage-feature-columns.json` | — | 94 zero-filled numeric features |
| `dataset-metadata.json` | — | Build provenance |
| `source-mapping.csv` | — | Per-row WoL→derived mapping |
| `wol-priority-mapping.json` | — | Severity normalization |

## Reproducibility

- Source archive: `data/wol/WoL_v1-2025-11-10.archive.gz`
- MongoDB: `mongodb://localhost:27017`, db=`WoL_v1`, collection=`JIRA`
- Build script: `scripts/research-lab/build_wol_real_corpus_v3.py`
- Random seed: {seed}
- Strong-match Jaccard threshold: {STRONG_MATCH_JACCARD_THRESHOLD}

## What needs follow-up work (not blocking the v3 release)

- **KG extraction over memory + windows**: ~12-15 hours at LM Studio rates
  (`qwen3.6-35b-a3b`, temperature 0). Until that runs, the KG retriever returns
  empty matches.
- **Cascade prediction re-runs**: BiEncoder, BM25, Hybrid-RRF, KG, LogSeq2Vec
  on the v3 test split (~24 hrs total).
- **BiEncoder re-fine-tune**: Recommended given new vocabulary (~3 hrs).
- **Agent harness re-run** on v3 test rows for paper headline numbers (~30 min).
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    log.info("  wrote README.md")


# ---------------------------------------------------------------------------
# Main build pipeline
# ---------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    out_dir = Path(args.out_global_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Priority mapping (copy from v2) ---
    pmap_src = Path("data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    if not pmap_src.exists():
        sys.exit(f"ERROR: priority mapping not found at {pmap_src}")
    priority_map, fallback_set = v1.load_priority_mapping(pmap_src)

    # --- 2. Feature columns (94 from synthetic OB) ---
    synth_dir = Path("data/derived/global/2026-06-15-wol-real-v2-global")
    feature_columns = load_feature_columns(synth_dir)
    log.info("Loaded %d numeric feature columns", len(feature_columns))

    # --- 3. Harvest Mongo (or use cache) ---
    cache_root = Path(args.cache_root or out_dir / ".pool_cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    log.info("Harvesting %d projects x 13 buckets from Mongo into %s",
             len(PROJECTS_V3), cache_root)
    capacities = harvest_all_buckets_v3(cache_root, overwrite=args.overwrite_cache)

    # --- 4. Decide quotas per (bucket, project) ---
    quotas_per_bucket: dict[str, dict[str, int]] = {}

    # TW: target args.target_tw, distributed across projects by TW capacity ratio.
    tw_cap = capacities["ticket_worthy"]
    tw_target = min(args.target_tw, tw_cap.total())
    quotas_per_bucket["ticket_worthy"] = v2._distribute_quota(
        tw_target, tw_cap, PROJECT_TARGET_RATIOS_V3,
    )
    log.info("Ticket_worthy: target=%d, capacity=%d -> using %d",
             args.target_tw, tw_cap.total(), sum(quotas_per_bucket["ticket_worthy"].values()))

    # Borderline: split target across 3 sub-buckets proportional to availability.
    border_cap_total = sum(c.total() for n, c in capacities.items() if n.startswith("borderline_"))
    border_target = min(args.target_border, border_cap_total)
    for bname in [n for n in capacities if n.startswith("borderline_")]:
        cap = capacities[bname]
        sub_target = round(border_target * cap.total() / max(1, border_cap_total))
        quotas_per_bucket[bname] = v2._distribute_quota(
            sub_target, cap, PROJECT_TARGET_RATIOS_V3,
        )
    log.info("Borderline: target=%d, capacity=%d", args.target_border, border_cap_total)

    # Noise: 55/45 split between resolution-noise (4) and regular-noise (5).
    noise_cap_res = sum(c.total() for n, c in capacities.items() if n.startswith("noise_"))
    noise_cap_reg = sum(c.total() for n, c in capacities.items() if n.startswith("regular_"))
    noise_target = min(args.target_noise, noise_cap_res + noise_cap_reg)
    noise_res_target = min(round(noise_target * NOISE_RESOLUTION_FRACTION), noise_cap_res)
    noise_reg_target = min(noise_target - noise_res_target, noise_cap_reg)
    log.info("Noise: target=%d, res=%d, reg=%d", args.target_noise,
             noise_res_target, noise_reg_target)

    for bname in [n for n in capacities if n.startswith("noise_")]:
        cap = capacities[bname]
        sub_target = round(noise_res_target * cap.total() / max(1, noise_cap_res))
        quotas_per_bucket[bname] = v2._distribute_quota(
            sub_target, cap, PROJECT_TARGET_RATIOS_V3,
        )
    for bname in [n for n in capacities if n.startswith("regular_")]:
        cap = capacities[bname]
        sub_target = round(noise_reg_target * cap.total() / max(1, noise_cap_reg))
        quotas_per_bucket[bname] = v2._distribute_quota(
            sub_target, cap, PROJECT_TARGET_RATIOS_V3,
        )

    # --- 5. Sample + field-map ---
    log.info("Sampling pools to quotas...")
    sampled_docs = sample_pool_v3(
        cache_root,
        quotas_per_bucket=quotas_per_bucket,
        seed=args.seed,
    )
    log.info("Sampled %d total docs", len(sampled_docs))

    # Field-map every doc
    dataset_run_id_root = f"wol-v3-{out_dir.name}"
    query_rows: list[dict] = []
    for doc in sampled_docs:
        bucket = doc["_bucket"]
        label = label_from_bucket(bucket)
        project_name = v1._safe_get(doc, "fields", "project", "name") or ""
        scenario_family = f"wol-{v1.slugify_project_name(project_name)}"
        split = FAMILY_ASSIGNMENT_V3.get(scenario_family)
        sid = v1._short_id(doc.get("_id", ""))
        per_record_run_id = f"{dataset_run_id_root}-{sid}"
        row = map_query_v3(
            doc,
            dataset_run_id=per_record_run_id,
            triage_label=label,
            bucket_name=bucket,
            priority_map=priority_map,
            fallback_set=fallback_set,
            split=split,
            feature_columns=feature_columns,
        )
        query_rows.append(row)

    # --- 6. Duplicate-link clustering ---
    log.info("Clustering by Jira duplicate-links...")
    cluster_map = cluster_duplicate_links_v3(query_rows, cache_root)
    for r in query_rows:
        wid = r["window_id"]
        if wid in cluster_map:
            r["incident_episode_id"] = cluster_map[wid]
    cluster_sizes = Counter(cluster_map.values())
    n_multi_clusters = sum(1 for sz in cluster_sizes.values() if sz > 1)

    # --- 7. Gold relations (only TW queries have gold) ---
    log.info("Computing gold relations (coarse + strong, TW queries only)...")
    memory_docs = [d for d in sampled_docs if d["_bucket"] == "ticket_worthy"]
    coarse_gold, strong_gold = compute_gold_relations(memory_docs, sampled_docs)

    coarse_avg = sum(len(v) for v in coarse_gold.values()) / max(1, len(coarse_gold))
    strong_avg = sum(len(v) for v in strong_gold.values()) / max(1, len(strong_gold))
    coarse_zero = sum(1 for v in coarse_gold.values() if not v)
    log.info("  coarse: avg=%.2f matches/query, %d/%d queries have zero matches",
             coarse_avg, coarse_zero, len(coarse_gold))
    log.info("  strong: avg=%.2f matches/query", strong_avg)

    # --- 8. Label counts by split ---
    label_counts: dict[str, dict[str, int]] = {
        s: {"ticket_worthy": 0, "borderline": 0, "noise": 0}
        for s in ("train", "validation", "test")
    }
    for r in query_rows:
        s = FAMILY_ASSIGNMENT_V3.get(r["scenario_family"], "train")
        label_counts[s][r["triage_label"]] += 1
    for split, counts in label_counts.items():
        log.info("  %s: %s", split, counts)

    # --- 9. Write all outputs ---
    log.info("Writing v3 artifacts to %s ...", out_dir)
    write_v3_outputs(
        out_dir,
        memory_docs=memory_docs,
        query_rows=query_rows,
        sampled_docs=sampled_docs,
        coarse_gold=coarse_gold,
        strong_gold=strong_gold,
        priority_map=priority_map,
        fallback_set=fallback_set,
        feature_columns=feature_columns,
        family_assignment=FAMILY_ASSIGNMENT_V3,
        label_counts=label_counts,
        seed=args.seed,
        n_multi_clusters=n_multi_clusters,
        capacities=capacities,
        dataset_run_id_root=dataset_run_id_root,
        started_at=started_at,
    )

    # --- 10. Summary ---
    print()
    print("=" * 80)
    print(" WoL v3 build complete")
    print("=" * 80)
    print(f"  Output:        {out_dir}")
    print(f"  Memory items:  {len(memory_docs):>6}")
    print(f"  Query rows:    {len(query_rows):>6}")
    n_tw     = sum(1 for r in query_rows if r["triage_label"] == "ticket_worthy")
    n_border = sum(1 for r in query_rows if r["triage_label"] == "borderline")
    n_noise  = sum(1 for r in query_rows if r["triage_label"] == "noise")
    print(f"    ticket_worthy: {n_tw:>4}")
    print(f"    borderline:    {n_border:>4}")
    print(f"    noise:         {n_noise:>4}")
    print(f"  Multi-incident clusters: {n_multi_clusters}")
    trivial = max(n_tw, n_border, n_noise) / max(1, len(query_rows))
    print(f"  Trivial baseline triage_acc: {trivial:.4f}")
    print()
    print("  Next steps (manually):")
    print("    1. Re-extract KG over new memory + windows: scripts/agent/extract_*_entities.py")
    print("    2. Re-run cascade: scripts/research-lab/run_*_wol_mode3.py --global-dir <v3>")
    print("    3. Re-fine-tune BiEncoder: scripts/research-lab/run_biencoder_wol_mode3.py --train")
    print("    4. Re-run agent eval: scripts/agent/smoke_wol.py --global-dir <v3>")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="Build the v3 dataset from scratch")
    p.add_argument("--out-global-dir", required=True,
                   help="Output dir, e.g. data/derived/global/2026-06-17-wol-real-v3-global")
    p.add_argument("--cache-root", default=None,
                   help="Per-bucket Mongo cache (default: <out>/.pool_cache/)")
    p.add_argument("--overwrite-cache", action="store_true",
                   help="Re-query Mongo even if cache files exist")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--target-tw",     type=int, default=DEFAULT_TARGET_TW)
    p.add_argument("--target-border", type=int, default=DEFAULT_TARGET_BORDER)
    p.add_argument("--target-noise",  type=int, default=DEFAULT_TARGET_NOISE)
    p.set_defaults(func=cmd_build)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
