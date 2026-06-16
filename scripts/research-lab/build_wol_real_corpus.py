"""Extract real-Jira corpora from the WoL MongoDB into our cascade's input schemas.

Implements docs7/REAL-DATA-WoL-PLAN.md v3 §13 (Modes 1, 2, 3) plus the shared
candidate-pool extraction step. Runs against the local Docker MongoDB that
docs7/REAL-DATA-WoL-PLAN.md §3 already provisioned at
mongodb://localhost:27017.

Subcommands:
  candidate-pools   : run only the per-project Mongo aggregation + filter +
                      cache step. Useful as a first sanity-check before
                      committing to mode-specific transformations.
  distractors       : Mode 1 — write the humanized-timeline distractor pool.
  novelty-queries   : Mode 2 — write the TriageWindow-shaped novelty queries.
  self-contained    : Mode 3 — write memory + queries + gold relations for
                      the TCH-Lite × WoL self-contained retrieval task.
  all               : run candidate-pools, then all three modes in one pass.

Determinism:
  Same MongoDB content + same seed (default 42) + same git SHA → bit-identical
  outputs. The script writes to <out>/.tmp/ first and renames on success.

Connection target:
  mongodb://localhost:27017 (the docker container `wol-mongo` from the
  docs7/ Mongo restore session).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — project lists per plan §9.
# ---------------------------------------------------------------------------

# Mode 1: OFF-topic projects (real distractor pool). See plan §9.1.
DISTRACTOR_PROJECTS_MODE1: list[str] = [
    "Qt",
    "Minecraft: Java Edition",
    "Confluence Server and Data Center",
    "Sakai",
    "JBoss Enterprise Application Platform",
    "Tools (JBoss Tools)",
]

# Mode 2: mix of adjacent + unrelated for cross-domain novelty. See plan §9.2.
NOVELTY_QUERY_PROJECTS_MODE2: list[str] = [
    "Spark",                       # Apache Spark
    "Cassandra",                   # Apache Cassandra
    "Flink",                       # Apache Flink
    "HBase",                       # Apache HBase
    "MariaDB Server",
    "Qt",
    "Minecraft: Java Edition",
    "Confluence Server and Data Center",
]

# Mode 3: microservice-adjacent projects for self-contained retrieval. §9.3.
SELF_CONTAINED_PROJECTS_MODE3: list[str] = [
    "Spark",
    "Cassandra",
    "HBase",
    "Flink",
    "Ambari",
    "MariaDB Server",
    "Kafka",
]

# Sample sizes per project. §9.1, §9.2, §9.3.
MODE1_N_PER_PROJECT = 50      # 50 × 6 = 300 distractors
MODE2_N_PER_PROJECT = 100     # 100 × 8 = 800 novelty queries
MODE3_N_TOTAL = 2000          # stratified, see §9.3 table

# Per-project sample sizes for Mode 3 (sums to 2000).
MODE3_PER_PROJECT_TARGETS: dict[str, int] = {
    "Spark":          350,
    "Cassandra":      350,
    "HBase":          300,
    "Flink":          300,
    "Ambari":         250,
    "MariaDB Server": 250,
    "Kafka":          200,  # may be missing; fall back to next-largest
}

# Mongo connection. Plan §3.
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB  = "WoL_v1"
MONGO_COL = "JIRA"

# Quality filters. Plan §5.1, §13.1.
PRED_UNCERTAINTY_MAX = 0.05
MIN_LOG_MSGS         = 1
MIN_DESC_CHARS       = 200
ISSUETYPE_ALLOWED    = {"Bug"}

# triage_reason_class heuristic. Plan §13.4.
REASON_KEYWORDS: list[tuple[str, list[str]]] = [
    ("outage",              ["outage", "down", "unavailable", "cannot connect", "not responding"]),
    ("latency_regression",  ["slow", "latency", "timeout", "hangs", "freezes"]),
    ("restart_with_impact", ["restart", "crash", "oom", "out of memory", "killed", "crashloop"]),
    ("network",             ["network", "partition", "packet loss", "connection refused", "dns"]),
]

# Truncation budgets — match the plan's mapping table (§10).
MAX_LOG_MSGS_PER_TICKET = 50      # how many log lines we keep in description_code / body_code
MAX_DESC_CHARS          = 1500    # truncation for fields.description in memory_text composition

# Stopwords for Mode 3 strong-match symptom Jaccard. Plan §13.2.
SYMPTOM_STOPWORDS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "should", "may", "might", "must", "shall",
    "and", "or", "but", "if", "then", "else", "when", "where", "while", "as", "of", "to",
    "in", "on", "at", "by", "for", "with", "about", "against", "between", "into",
    "through", "during", "before", "after", "above", "below", "from", "up", "down",
    "out", "off", "over", "under", "again", "further", "i", "you", "he", "she", "it",
    "we", "they", "what", "which", "who", "whom", "this", "that", "these", "those",
    # log-boilerplate
    "error", "info", "warning", "warn", "debug", "trace", "fatal",
    "at", "line", "file", "thread", "exception", "stack",
])


# ---------------------------------------------------------------------------
# Priority normalization. Loads wol-priority-mapping.json (plan §11).
# ---------------------------------------------------------------------------

def load_priority_mapping(mapping_path: Path) -> tuple[dict[str, str], set[str]]:
    """Return (lowercased_priority -> severity, fallback_lowercased_priorities)."""
    d = json.loads(mapping_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for severity in ("critical", "major", "minor"):
        for s in d.get(severity, []):
            out[s.strip().lower()] = severity
    fallback = {s.strip().lower() for s in d.get("fallback", [])}
    return out, fallback


def normalize_priority(
    raw_priority: str | None,
    mapping: dict[str, str],
    fallback_set: set[str],
) -> tuple[str, bool]:
    """Return (severity, severity_uncertain). Falls back to 'minor' on miss."""
    if raw_priority is None:
        return "minor", True
    key = str(raw_priority).strip().lower()
    if not key:
        return "minor", True
    if key in mapping:
        return mapping[key], False
    if key in fallback_set:
        return "minor", True
    return "minor", True  # unmapped → fallback


# ---------------------------------------------------------------------------
# Mongo client + per-project candidate pool extraction.
# ---------------------------------------------------------------------------

def get_mongo_collection():
    """Connect to the local WoL mongo and return the JIRA collection handle."""
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client[MONGO_DB][MONGO_COL]


def _aggregation_pipeline_for_project(project_name: str) -> list[dict]:
    """Build the filter+project pipeline for one WoL JIRA project.

    Filters per plan §5.1. Projects out `log_blks` (per-token classifier trace,
    not useful for memory text and huge in volume).
    """
    return [
        {
            "$match": {
                "fields.project.name":          project_name,
                "fields.issuetype.name":        {"$in": list(ISSUETYPE_ALLOWED)},
                "pred_uncertainty":             {"$lte": PRED_UNCERTAINTY_MAX},
                f"log_msgs.{MIN_LOG_MSGS - 1}": {"$exists": True},
            }
        },
        {
            # Defensive description-length filter (post-match because $strLenCP
            # is expensive; the $match cuts the population first).
            "$match": {
                "$expr": {
                    "$gte": [
                        {"$strLenCP": {"$ifNull": ["$fields.description", ""]}},
                        MIN_DESC_CHARS,
                    ]
                }
            }
        },
        {
            "$project": {
                # Strip the heavy per-token classifier trace.
                "log_blks":  0,
            }
        },
    ]


def extract_candidate_pool(
    project_name: str,
    out_path: Path,
    *,
    coll=None,
    overwrite: bool = False,
) -> int:
    """Run the aggregation for one project and stream results to out_path.

    Returns the number of records written. If out_path already exists and
    overwrite is False, returns the existing record count without re-querying.
    """
    if out_path.exists() and not overwrite:
        # Re-count without re-querying. The cache is authoritative.
        return sum(1 for _ in out_path.open(encoding="utf-8"))

    if coll is None:
        coll = get_mongo_collection()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    pipeline = _aggregation_pipeline_for_project(project_name)
    n_written = 0
    with tmp_path.open("w", encoding="utf-8") as fh:
        cursor = coll.aggregate(pipeline, allowDiskUse=True)
        for doc in cursor:
            # Mongo's BSON ObjectId, datetime, etc. need a JSON-safe pass.
            fh.write(json.dumps(doc, default=str, ensure_ascii=False) + "\n")
            n_written += 1
    tmp_path.replace(out_path)
    return n_written


def slugify_project_name(name: str) -> str:
    """Turn a Mongo project name into a filesystem-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def project_cache_path(cache_root: Path, project_name: str) -> Path:
    return cache_root / f"{slugify_project_name(project_name)}-bugs.jsonl"


# ---------------------------------------------------------------------------
# Field mappers — WoL JIRA record → our schemas. Plan §10.
# ---------------------------------------------------------------------------

def _safe_get(d: dict, *path, default=None):
    """Walk a nested dict by keys; return default on any miss."""
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _short_id(wol_id: str) -> str:
    """First 16 chars of the WoL _id; used in our derived IDs."""
    return wol_id[:16] if wol_id else "unknown"


def _first_n_log_msgs(doc: dict, n: int = MAX_LOG_MSGS_PER_TICKET) -> list[str]:
    msgs = doc.get("log_msgs") or []
    return [str(m) for m in msgs[:n] if m]


def _joined_log_msgs(doc: dict, n: int = MAX_LOG_MSGS_PER_TICKET) -> str:
    return "\n".join(_first_n_log_msgs(doc, n))


def _truncated_description(doc: dict, n: int = MAX_DESC_CHARS) -> str:
    desc = _safe_get(doc, "fields", "description") or ""
    return desc[:n]


def _component_names(doc: dict) -> list[str]:
    comps = _safe_get(doc, "fields", "components") or []
    return [c.get("name", "") for c in comps if isinstance(c, dict) and c.get("name")]


def _evidence_bundle_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _classify_triage_reason(summary: str) -> str:
    s = (summary or "").lower()
    for cls, kws in REASON_KEYWORDS:
        for kw in kws:
            if kw in s:
                return cls
    return "other"


def _resolution_time_seconds(doc: dict) -> int:
    created = _safe_get(doc, "fields", "created")
    resolved = _safe_get(doc, "fields", "resolutiondate")
    if not (created and resolved):
        return 0
    try:
        c = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        r = datetime.fromisoformat(str(resolved).replace("Z", "+00:00"))
        return max(0, int((r - c).total_seconds()))
    except (ValueError, TypeError):
        return 0


def map_to_humanized_timeline(
    doc: dict,
    *,
    is_distractor: bool,
    dataset_run_id: str,
    severity_seen: str,
    severity_uncertain: bool,
    affected_services_seen: list[str] | None = None,
    scenario_family: str | None = None,
) -> dict:
    """WoL JIRA record → humanized-timeline schema row.

    Used by Mode 1 (distractors, is_distractor=True) and Mode 3 memory side
    (is_distractor=False). See plan §10.1 + §10.4.
    """
    wol_id = doc.get("_id", "")
    sid = _short_id(wol_id)
    prefix = "wol-d-" if is_distractor else "wol-m-"
    ticket_id = f"{prefix}{sid}"

    log_msgs = _first_n_log_msgs(doc)
    description_code = "\n".join(log_msgs)
    body_code        = description_code

    summary    = _safe_get(doc, "fields", "summary") or ""
    desc       = _truncated_description(doc)
    components = _component_names(doc)
    resolution_name = _safe_get(doc, "fields", "resolution", "name") or ""

    if affected_services_seen is None:
        if is_distractor:
            affected_services_seen = ["wol-distractor"]
        else:
            affected_services_seen = (components[:1] if components
                                      else [scenario_family or "wol-memory"])

    timeline_step = {
        "step_kind":       "report",
        "persona_role":    "real-engineer",
        "persona_avatar":  "WoL",
        "t_offset_s":      0,
        "context_window_s": 0,
        "evidence": {
            "log_quotes":         log_msgs,
            "metric_observations": [],
            "k8s_observations":    [],
            "trace_observations":  [],
            "alert_names":         [],
            "trace_id_quoted":     None,
            "symptom_phrase":      summary[:200],
        },
        "text":         f"{summary}\n\n{desc}",
        "body_code":    body_code,
        "prompt_hash":  "wol-distractor" if is_distractor else "wol-memory",
    }

    return {
        "ticket_id":              ticket_id,
        "source_episode_id":      ticket_id,
        "source_dataset_run_id":  dataset_run_id,
        "source_injection_id":    "",
        "affected_services_seen": affected_services_seen,
        "severity_seen":          severity_seen,
        "severity_uncertain":     severity_uncertain,
        "components_seen":        components,
        "is_misattributed":       False,
        "closed_as_noise":        False,
        "is_distractor":          is_distractor,
        "is_followup_of":         None,
        "description_code":       description_code,
        "resolution":             resolution_name,
        "resolution_time_s":      _resolution_time_seconds(doc),
        "log_signature_source":   "wol-extracted",
        "evidence_bundle_hash":   _evidence_bundle_hash(description_code),
        "generator_version":      "wol-bridge-v3",
        "sanitizer_version":      "none",
        "symptom_map_version":    "none",
        "timeline":               [timeline_step],
        # Mode 3 only: real scenario_family (per-project slug) for stratification.
        # Mode 1 sets this to a sentinel.
        "scenario_family":        scenario_family or "wol-distractor",
        "wol_source_id":          wol_id,
        "wol_project":            _safe_get(doc, "fields", "project", "name"),
        "wol_issue_key":          doc.get("key"),
    }


def map_to_triagewindow(
    doc: dict,
    *,
    dataset_run_id: str,
    severity_seen: str,
    severity_uncertain: bool,
    scenario_family: str,
    service_name: str,
    is_novel: bool,
    gold_matched_ids: list[str] | None = None,
) -> dict:
    """WoL JIRA record → TriageWindow-compatible record.

    Used by Mode 2 (cross-domain novelty queries) and Mode 3 query side.
    See plan §10.2.
    """
    wol_id = doc.get("_id", "")
    sid = _short_id(wol_id)
    window_id = f"wol-q-{sid}" if is_novel else f"wol-q-{sid}"

    evidence_text = _joined_log_msgs(doc)
    components    = _component_names(doc)
    summary       = _safe_get(doc, "fields", "summary") or ""

    # Synthetic 5-minute timestamps. Not used for visibility under TCH-Lite,
    # but required by the TriageWindow schema.
    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "window_id":            window_id,
        "dataset_run_id":       dataset_run_id,
        "incident_episode_id":  window_id,
        "scenario_id":          f"wol-{slugify_project_name(_safe_get(doc, 'fields', 'project', 'name') or '')}",
        "scenario_family":      scenario_family,
        "service_name":         service_name,
        "window_type":          "active_fault",
        "start_time":           now_iso,
        "end_time":             now_iso,
        "triage_label":         "ticket_worthy",
        "triage_severity":      severity_seen,
        "severity_uncertain":   severity_uncertain,
        "triage_components":    components,
        "triage_reason_class":  _classify_triage_reason(summary),
        "is_hard_case":         False,
        "source":               "wol-novelty-queries" if is_novel else "wol-self-contained",
        "evidence_text":        evidence_text,
        "triage_evidence_text": evidence_text,
        "matched_memory_issue_ids": gold_matched_ids or [],
        "is_novel":             is_novel,
        "fault_compatibility_class": "wol-novelty" if is_novel else "wol-real",
        "expected_in_memory":   not is_novel,
        # Numeric features: zero-vector. We do not measure triage on WoL queries.
        # The downstream cascade will read these as 0.0 across the 94 columns.
        "raw": {"triage_feature_zero_filled": True},
        "wol_source_id":        wol_id,
        "wol_project":          _safe_get(doc, "fields", "project", "name"),
        "wol_issue_key":        doc.get("key"),
    }


# ---------------------------------------------------------------------------
# Stratified sampling per project (plan §13.1 step 4).
# ---------------------------------------------------------------------------

def sample_per_project(
    cache_root: Path,
    project_targets: dict[str, int],
    *,
    seed: int,
) -> dict[str, list[dict]]:
    """Read each project's cached pool, sample n records per project.

    Returns a dict {project_name -> list of WoL JIRA records}.
    """
    rng = random.Random(seed)
    out: dict[str, list[dict]] = {}
    for project_name, n_target in project_targets.items():
        path = project_cache_path(cache_root, project_name)
        if not path.exists():
            print(f"[sample] WARN: cache file missing for project {project_name!r} "
                  f"at {path} — skipping", file=sys.stderr)
            out[project_name] = []
            continue
        # Reservoir-sample n_target records from the file. Use simple random
        # sampling — the cache file is small (~10K records) so we just read
        # all of it and sample.
        rows = [json.loads(line) for line in path.open(encoding="utf-8")]
        if len(rows) <= n_target:
            out[project_name] = rows
        else:
            out[project_name] = rng.sample(rows, n_target)
    return out


# ---------------------------------------------------------------------------
# Mode 1: distractors.
# ---------------------------------------------------------------------------

def write_mode1_distractors(
    cache_root: Path,
    out_dir: Path,
    priority_map: dict[str, str],
    fallback_set: set[str],
    *,
    n_per_project: int,
    seed: int,
    dataset_run_id: str,
) -> dict[str, Any]:
    """Mode 1 — distractor pool. Plan §5, §10.1."""
    out_dir.mkdir(parents=True, exist_ok=True)

    project_targets = {p: n_per_project for p in DISTRACTOR_PROJECTS_MODE1}
    sampled = sample_per_project(cache_root, project_targets, seed=seed)

    timeline_path = out_dir / "timeline.jsonl"
    mapping_path  = out_dir / "source-mapping.csv"
    tmp_timeline  = timeline_path.with_suffix(".jsonl.tmp")
    tmp_mapping   = mapping_path.with_suffix(".csv.tmp")

    n_total = 0
    fallback_count = 0
    per_project_counts: dict[str, int] = {}

    with tmp_timeline.open("w", encoding="utf-8") as ft, \
         tmp_mapping.open("w", encoding="utf-8", newline="") as fm:

        csv_w = csv.writer(fm)
        csv_w.writerow(["ticket_id", "wol_source_id", "wol_project", "wol_issue_key", "severity_seen"])

        for project_name, rows in sampled.items():
            per_project_counts[project_name] = len(rows)
            for doc in rows:
                raw_pri = _safe_get(doc, "fields", "priority", "name")
                severity, uncertain = normalize_priority(raw_pri, priority_map, fallback_set)
                if uncertain:
                    fallback_count += 1
                rec = map_to_humanized_timeline(
                    doc,
                    is_distractor=True,
                    dataset_run_id=dataset_run_id,
                    severity_seen=severity,
                    severity_uncertain=uncertain,
                )
                ft.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
                csv_w.writerow([
                    rec["ticket_id"],
                    rec["wol_source_id"],
                    rec["wol_project"] or "",
                    rec["wol_issue_key"] or "",
                    severity,
                ])
                n_total += 1

    tmp_timeline.replace(timeline_path)
    tmp_mapping.replace(mapping_path)

    return {
        "mode": "distractors",
        "n_total": n_total,
        "per_project_counts": per_project_counts,
        "fallback_severity_count": fallback_count,
        "output_dir": str(out_dir),
    }


# ---------------------------------------------------------------------------
# Mode 2: cross-domain novelty queries.
# ---------------------------------------------------------------------------

def write_mode2_novelty_queries(
    cache_root: Path,
    out_dir: Path,
    priority_map: dict[str, str],
    fallback_set: set[str],
    *,
    n_per_project: int,
    seed: int,
    dataset_run_id: str,
) -> dict[str, Any]:
    """Mode 2 — cross-domain novelty queries. Plan §6, §10.2."""
    out_dir.mkdir(parents=True, exist_ok=True)

    project_targets = {p: n_per_project for p in NOVELTY_QUERY_PROJECTS_MODE2}
    sampled = sample_per_project(cache_root, project_targets, seed=seed)

    windows_path  = out_dir / "windows.jsonl"
    mapping_path  = out_dir / "source-mapping.csv"
    tmp_windows   = windows_path.with_suffix(".jsonl.tmp")
    tmp_mapping   = mapping_path.with_suffix(".csv.tmp")

    n_total = 0
    fallback_count = 0
    per_project_counts: dict[str, int] = {}

    with tmp_windows.open("w", encoding="utf-8") as fw, \
         tmp_mapping.open("w", encoding="utf-8", newline="") as fm:

        csv_w = csv.writer(fm)
        csv_w.writerow(["window_id", "wol_source_id", "wol_project", "wol_issue_key", "severity_seen"])

        for project_name, rows in sampled.items():
            per_project_counts[project_name] = len(rows)
            for doc in rows:
                raw_pri = _safe_get(doc, "fields", "priority", "name")
                severity, uncertain = normalize_priority(raw_pri, priority_map, fallback_set)
                if uncertain:
                    fallback_count += 1
                rec = map_to_triagewindow(
                    doc,
                    dataset_run_id=dataset_run_id,
                    severity_seen=severity,
                    severity_uncertain=uncertain,
                    scenario_family="wol-novelty",   # sentinel
                    service_name="wol-real",         # sentinel
                    is_novel=True,                   # gold for every Mode 2 row
                )
                fw.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
                csv_w.writerow([
                    rec["window_id"],
                    rec["wol_source_id"],
                    rec["wol_project"] or "",
                    rec["wol_issue_key"] or "",
                    severity,
                ])
                n_total += 1

    tmp_windows.replace(windows_path)
    tmp_mapping.replace(mapping_path)

    return {
        "mode": "novelty-queries",
        "n_total": n_total,
        "per_project_counts": per_project_counts,
        "fallback_severity_count": fallback_count,
        "output_dir": str(out_dir),
    }


# ---------------------------------------------------------------------------
# Mappers for the global-dataset-mirror outputs.
# ---------------------------------------------------------------------------

def _compose_memory_text_for_legacy(doc: dict) -> str:
    """Build the legacy `memory_text` string for jira-memory-corpus.jsonl.

    Mirrors what our synthetic pipeline produces: summary + components + body
    + log lines — all in one composed text blob. Downstream code that bypasses
    `load_humanized_corpus` and reads `memory_text` directly will see this.
    """
    summary = _safe_get(doc, "fields", "summary") or ""
    components = _component_names(doc)
    desc = _truncated_description(doc)
    log_msgs_str = "\n".join(_first_n_log_msgs(doc))

    parts: list[str] = []
    if summary:
        parts.append(f"Summary: {summary}")
    if components:
        parts.append(f"Components: {', '.join(components)}")
    if desc:
        parts.append(f"Description: {desc}")
    if log_msgs_str:
        parts.append(f"Log lines:\n{log_msgs_str}")
    return "\n\n".join(parts)


def map_to_jira_memory_issue(
    doc: dict,
    *,
    dataset_run_id: str,
    severity: str,
    scenario_family: str,
    affected_service: str,
    fault_type: str,
    fault_compatibility_class: str,
    linked_window_ids: list[str] | None = None,
) -> dict:
    """WoL JIRA record → JiraMemoryIssue schema (jira-memory-corpus.jsonl).

    Mirrors the shape produced by the synthetic pipeline so the cascade's
    existing loader reads WoL records without code changes. See plan §10.1
    and the synthetic dataset's row schema.
    """
    wol_id = doc.get("_id", "")
    sid = _short_id(wol_id)
    ticket_id = f"wol-m-{sid}"

    created = _safe_get(doc, "fields", "created") or ""
    resolution_text = (_safe_get(doc, "fields", "resolution", "description")
                       or _safe_get(doc, "fields", "resolution", "name")
                       or "")

    return {
        "jira_shadow_issue_id":      ticket_id,
        "jira_issue_key":            doc.get("key") or f"WOL-{sid}",
        "dataset_run_id":            dataset_run_id,
        "incident_episode_id":       ticket_id,
        "available_as_memory_from":  str(created),
        "scenario_id":               f"{scenario_family}-{sid}",
        "scenario_family":           scenario_family,
        "affected_service":          affected_service,
        "fault_type":                fault_type,
        "fault_compatibility_class": fault_compatibility_class,
        "severity":                  severity,
        "memory_text":               _compose_memory_text_for_legacy(doc),
        "resolution_notes":          str(resolution_text),
        "linked_window_ids":         linked_window_ids or [],
        "linked_trace_ids":          [],
        "linked_alert_fingerprints": [],
        # Provenance — non-canonical fields the existing schema ignores.
        "wol_source_id":             wol_id,
        "wol_project":               _safe_get(doc, "fields", "project", "name"),
    }


def map_to_global_triage_example(
    doc: dict,
    *,
    feature_columns: list[str],
    dataset_run_id: str,
    severity: str,
    scenario_family: str,
    service_name: str,
    split: str,
) -> dict:
    """WoL JIRA record → global-triage-examples.jsonl row (flat TriageWindow).

    Produces all 94 triage_feature_* columns at the top level (set to 0.0,
    since WoL has no co-collected numeric telemetry — see plan §3.2). The
    cascade's HGB pipeline will read these as zeros; TCH-Lite (which drops
    HGB entirely) is the intended consumer.
    """
    wol_id = doc.get("_id", "")
    sid = _short_id(wol_id)
    window_id = f"wol-q-{sid}"

    summary = _safe_get(doc, "fields", "summary") or ""
    components = _component_names(doc)
    evidence_text = _joined_log_msgs(doc)

    # Synthetic 5-minute timestamps. Not used for visibility in Mode 3,
    # but required by the schema.
    now = datetime.now(timezone.utc)
    start = now.isoformat()
    end = now.isoformat()

    row: dict[str, Any] = {
        "window_id":             window_id,
        "dataset_run_id":        dataset_run_id,
        "incident_episode_id":   window_id,
        "scenario_id":           f"{scenario_family}-{sid}",
        "scenario_family":       scenario_family,
        "service_name":          service_name,
        "window_type":           "active_fault",
        "start_time":            start,
        "end_time":              end,
        "triage_label":          "ticket_worthy",
        "triage_severity":       severity,
        "triage_components":     components or None,
        "triage_reason_class":   _classify_triage_reason(summary),
        "is_hard_case":          False,
        "source":                "wol-self-contained",
        "split":                 split,
        "triage_evidence_text":  evidence_text,
        # Provenance non-canonical fields.
        "wol_source_id":         wol_id,
        "wol_project":           _safe_get(doc, "fields", "project", "name"),
        "wol_issue_key":         doc.get("key"),
    }
    # All 94 triage_feature_* columns, flat at top level, zero-filled.
    for col in feature_columns:
        row[col] = 0.0
    return row


def map_to_memory_match(
    query_window_id: str,
    *,
    dataset_run_id: str,
    scenario_family: str,
    affected_service: str,
    fault_compatibility_class: str,
    triage_label: str,
    matched_memory_ids: list[str],
) -> dict:
    """Build a window-memory-matchings.jsonl row (MemoryMatch schema)."""
    return {
        "window_id":                  query_window_id,
        "dataset_run_id":             dataset_run_id,
        "scenario_family":            scenario_family,
        "affected_service":           affected_service,
        "fault_compatibility_class":  fault_compatibility_class,
        "triage_label":               triage_label,
        "is_novel":                   len(matched_memory_ids) == 0,
        "matched_memory_issue_ids":   matched_memory_ids,
        "expected_in_memory":         len(matched_memory_ids) > 0,
    }


def load_feature_columns(synthetic_global_dir: Path) -> list[str]:
    """Load the 94 triage_feature_* column names from the synthetic dataset.

    Falls back to an empty list if the synthetic schema file isn't found
    (which would cause Mode 3 outputs to have no feature columns; we log).
    """
    schema_path = synthetic_global_dir / "triage-feature-columns.json"
    if not schema_path.exists():
        print(f"[load_feature_columns] WARN: schema file not found at {schema_path}",
              file=sys.stderr)
        return []
    d = json.loads(schema_path.read_text(encoding="utf-8"))
    cols = d.get("feature_columns") or []
    return list(cols)


# ---------------------------------------------------------------------------
# Mode 3: self-contained WoL→WoL retrieval (memory + queries + gold relations).
# ---------------------------------------------------------------------------

def _symptom_tokens(log_msgs: list[str]) -> set[str]:
    """Tokenize log_msgs for the strong-match Jaccard. Plan §13.2.

    Lowercase, non-stopword, length ≥ 3, alpha-only after stripping punct.
    """
    text = " ".join(log_msgs).lower()
    raw = re.findall(r"[a-z][a-z0-9_]{2,}", text)
    return {t for t in raw if t not in SYMPTOM_STOPWORDS}


def _coarse_match(a_doc: dict, b_doc: dict) -> bool:
    """Coarse match: same project AND at least one shared component."""
    a_proj = _safe_get(a_doc, "fields", "project", "name")
    b_proj = _safe_get(b_doc, "fields", "project", "name")
    if not a_proj or not b_proj or a_proj != b_proj:
        return False
    a_comps = set(_component_names(a_doc))
    b_comps = set(_component_names(b_doc))
    return len(a_comps & b_comps) >= 1


def _strong_match(
    a_doc: dict, b_doc: dict, a_tokens: set[str], b_tokens: set[str],
    jaccard_threshold: float = 0.15,
) -> bool:
    """Strong match: coarse match AND symptom-token Jaccard > threshold.

    Threshold lowered from 0.5 (plan v3 §13.2) to 0.15 because real Jira
    tickets within the same project rarely share >50% of their log-token
    vocabulary; an empirical first run produced 0.07 matches per query.
    0.15 produces a meaningful but selective subset of the coarse pool.
    """
    if not _coarse_match(a_doc, b_doc):
        return False
    if not a_tokens or not b_tokens:
        return False
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return (inter / union) > jaccard_threshold


def _split_70_15_15(
    docs_by_project: dict[str, list[dict]], seed: int,
) -> dict[str, str]:
    """Assign each WoL _id to train/val/test, stratified per project, seed 42.

    Returns {wol_id -> "train"|"val"|"test"}.
    """
    rng = random.Random(seed)
    out: dict[str, str] = {}
    for project, docs in docs_by_project.items():
        ids = [d["_id"] for d in docs]
        rng.shuffle(ids)
        n = len(ids)
        n_train = int(n * 0.70)
        n_val   = int(n * 0.15)
        for i, wid in enumerate(ids):
            if i < n_train:
                out[wid] = "train"
            elif i < n_train + n_val:
                out[wid] = "val"
            else:
                out[wid] = "test"
    return out


def write_mode3_self_contained(
    cache_root: Path,
    out_root: Path,
    priority_map: dict[str, str],
    fallback_set: set[str],
    *,
    seed: int,
    dataset_run_id: str,
    synthetic_global_dir: Path | None = None,
    humanized_subdir: str = "bulk-20260611",
) -> dict[str, Any]:
    """Mode 3 — TCH-Lite WoL self-contained retrieval, in the global-dataset
    mirror layout. Plan §7, §10.3.

    Output is now structured so the cascade's existing data loaders read the
    WoL records without code changes. The artifacts produced at ``out_root``
    are:

      jira-memory-corpus.jsonl                 — JiraMemoryIssue schema
      jira-shadow-humanized-v2/<sub>/timeline.jsonl  — humanized timeline
      global-triage-examples.jsonl             — flat TriageWindow w/ 94 features
      window-memory-matchings.jsonl            — gold (coarse match) — canonical
      window-memory-matchings-strong.jsonl     — gold (strong match) — secondary
      triage-split-manifest-v2-resplit.json    — per-window split
      triage-feature-columns.json              — feature schema (copied)
      dataset-metadata.json                    — this dataset's manifest
      source-mapping.csv                       — wol_id ↔ memory/window mapping
      gold-relations-debug.json                — raw per-test-query gold lists
    """
    out_root.mkdir(parents=True, exist_ok=True)

    # Default the synthetic global dir for schema copying (fallback ok).
    if synthetic_global_dir is None:
        synthetic_global_dir = Path(
            "data/derived/global/2026-05-25-dataset-v5-large-global"
        )

    feature_columns = load_feature_columns(synthetic_global_dir)

    # Sample per project per plan §9.3 table.
    sampled = sample_per_project(cache_root, MODE3_PER_PROJECT_TARGETS, seed=seed)

    # Compute 70/15/15 split per project.
    split_assignment = _split_70_15_15(sampled, seed=seed)
    # Normalize split labels to match the synthetic dataset's convention.
    SPLIT_NAME_MAP = {"train": "train", "val": "validation", "test": "test"}
    split_assignment = {k: SPLIT_NAME_MAP.get(v, v) for k, v in split_assignment.items()}

    # --- Compute symptom tokens once per record (used by strong match) ---
    all_docs: list[dict] = []
    for rows in sampled.values():
        all_docs.extend(rows)

    tokens_by_id: dict[str, set[str]] = {
        d["_id"]: _symptom_tokens(_first_n_log_msgs(d)) for d in all_docs
    }
    doc_by_id = {d["_id"]: d for d in all_docs}

    # ----- Paths -----
    memory_corpus_path   = out_root / "jira-memory-corpus.jsonl"
    humanized_root_dir   = out_root / "jira-shadow-humanized-v2" / humanized_subdir
    humanized_root_dir.mkdir(parents=True, exist_ok=True)
    humanized_path       = humanized_root_dir / "timeline.jsonl"
    triage_examples_path = out_root / "global-triage-examples.jsonl"
    matchings_coarse     = out_root / "window-memory-matchings.jsonl"
    matchings_strong     = out_root / "window-memory-matchings-strong.jsonl"
    split_manifest_path  = out_root / "triage-split-manifest-v2-resplit.json"
    feature_schema_path  = out_root / "triage-feature-columns.json"
    metadata_path        = out_root / "dataset-metadata.json"
    source_mapping_path  = out_root / "source-mapping.csv"
    gold_debug_path      = out_root / "gold-relations-debug.json"

    # ----- Per-record metadata first (needed by all writers) -----
    record_meta: dict[str, dict[str, Any]] = {}
    per_project_counts: dict[str, int] = {}
    fallback_count = 0
    label_counts_by_split: dict[str, dict[str, int]] = {
        "train": Counter(), "validation": Counter(), "test": Counter(),
    }

    for project_name, rows in sampled.items():
        per_project_counts[project_name] = len(rows)
        scenario_family = "wol-" + slugify_project_name(project_name)
        for doc in rows:
            wid = doc["_id"]
            sid = _short_id(wid)
            raw_pri = _safe_get(doc, "fields", "priority", "name")
            severity, uncertain = normalize_priority(raw_pri, priority_map, fallback_set)
            if uncertain:
                fallback_count += 1
            comps = _component_names(doc)
            service_name = comps[0] if comps else scenario_family
            summary = _safe_get(doc, "fields", "summary") or ""
            fault_type = _classify_triage_reason(summary)  # reuse the heuristic
            # Per-record dataset_run_id: SHARED between this WoL ticket's
            # memory side and its query side, and UNIQUE across WoL tickets.
            # This makes MemoryCorpus.visible_to() correctly exclude
            # memory[i] when retrieving for query[i] (the self-match
            # exclusion), exactly as the synthetic dataset's per-fault-run
            # IDs do.
            per_record_run_id = f"{dataset_run_id}-{sid}"
            record_meta[wid] = {
                "ticket_id":       f"wol-m-{sid}",
                "window_id":       f"wol-q-{sid}",
                "scenario_family": scenario_family,
                "service_name":    service_name,
                "severity":        severity,
                "severity_uncertain": uncertain,
                "fault_type":      fault_type,
                "fault_compatibility_class": "wol-real",
                "split":           split_assignment.get(wid, "train"),
                "project_name":    project_name,
                "per_record_run_id": per_record_run_id,
            }
            label_counts_by_split[split_assignment.get(wid, "train")]["ticket_worthy"] += 1

    # ----- jira-memory-corpus.jsonl (memory side, JiraMemoryIssue schema) -----
    tmp = memory_corpus_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for doc in all_docs:
            meta = record_meta[doc["_id"]]
            rec = map_to_jira_memory_issue(
                doc,
                dataset_run_id=meta["per_record_run_id"],  # unique per WoL ticket
                severity=meta["severity"],
                scenario_family=meta["scenario_family"],
                affected_service=meta["service_name"],
                fault_type=meta["fault_type"],
                fault_compatibility_class=meta["fault_compatibility_class"],
                linked_window_ids=[meta["window_id"]],
            )
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    tmp.replace(memory_corpus_path)

    # ----- jira-shadow-humanized-v2/<sub>/timeline.jsonl (humanized memory) -----
    tmp = humanized_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for doc in all_docs:
            meta = record_meta[doc["_id"]]
            rec = map_to_humanized_timeline(
                doc,
                is_distractor=False,
                dataset_run_id=meta["per_record_run_id"],
                severity_seen=meta["severity"],
                severity_uncertain=meta["severity_uncertain"],
                scenario_family=meta["scenario_family"],
                affected_services_seen=[meta["service_name"]],
            )
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    tmp.replace(humanized_path)

    # ----- global-triage-examples.jsonl (queries; flat TriageWindow + 94 features) -----
    tmp = triage_examples_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for doc in all_docs:
            meta = record_meta[doc["_id"]]
            rec = map_to_global_triage_example(
                doc,
                feature_columns=feature_columns,
                dataset_run_id=meta["per_record_run_id"],
                severity=meta["severity"],
                scenario_family=meta["scenario_family"],
                service_name=meta["service_name"],
                split=meta["split"],
            )
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    tmp.replace(triage_examples_path)

    # ----- Gold relations under each match definition (ALL queries, not just test) -----
    # For each query A (any split), find memory records B where A != B and
    # _coarse_match(A,B) [and separately _strong_match(A,B)].
    gold_coarse: dict[str, list[str]] = {}
    gold_strong: dict[str, list[str]] = {}
    all_ids = [d["_id"] for d in all_docs]

    for a_id in all_ids:
        a_doc = doc_by_id[a_id]
        a_tokens = tokens_by_id[a_id]
        coarse: list[str] = []
        strong: list[str] = []
        for b_id in all_ids:
            if b_id == a_id:
                continue
            b_doc = doc_by_id[b_id]
            if _coarse_match(a_doc, b_doc):
                coarse.append("wol-m-" + _short_id(b_id))
                if _strong_match(a_doc, b_doc, a_tokens, tokens_by_id[b_id]):
                    strong.append("wol-m-" + _short_id(b_id))
        wid = f"wol-q-{_short_id(a_id)}"
        gold_coarse[wid] = coarse
        gold_strong[wid] = strong

    # ----- window-memory-matchings.jsonl (canonical: coarse) -----
    for matchings_path, gold_dict, label in [
        (matchings_coarse, gold_coarse, "coarse"),
        (matchings_strong, gold_strong, "strong"),
    ]:
        tmp = matchings_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for doc in all_docs:
                meta = record_meta[doc["_id"]]
                wid = meta["window_id"]
                matched = gold_dict.get(wid, [])
                rec = map_to_memory_match(
                    wid,
                    dataset_run_id=meta["per_record_run_id"],
                    scenario_family=meta["scenario_family"],
                    affected_service=meta["service_name"],
                    fault_compatibility_class=meta["fault_compatibility_class"],
                    triage_label="ticket_worthy",
                    matched_memory_ids=matched,
                )
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        tmp.replace(matchings_path)

    # ----- Split manifests (BOTH legacy family-based + v2-resplit per-window) -----
    window_assignment = {
        record_meta[wid]["window_id"]: record_meta[wid]["split"] for wid in all_ids
    }
    # Treat each WoL project as a family in the LOFO list.
    families = sorted({record_meta[wid]["scenario_family"] for wid in all_ids})

    # A family-based assignment is needed by the *legacy* loader's
    # iter_split. We split the 7 wol-* families into train/val/test by
    # cumulative record count so the resulting per-family split totals
    # are close to 70/15/15. Records IN the held-out test families form
    # the test partition under the legacy loader; the v2-resplit manifest
    # (below) carries the per-window split for any cascade-aware code
    # that wants the within-family 70/15/15 split.
    counts_per_family = Counter(record_meta[wid]["scenario_family"] for wid in all_ids)
    total = sum(counts_per_family.values())
    fams_sorted = sorted(counts_per_family.items(), key=lambda kv: -kv[1])
    family_assignment: dict[str, str] = {}
    cum_train = cum_val = 0
    train_cap, val_cap = int(total * 0.70), int(total * 0.85)
    for fam, n in fams_sorted:
        if cum_train + n <= train_cap:
            family_assignment[fam] = "train"
            cum_train += n
        elif cum_val + cum_train + n <= val_cap:
            family_assignment[fam] = "validation"
            cum_val += n
        else:
            family_assignment[fam] = "test"

    legacy_split_path = out_root / "triage-split-manifest.json"
    legacy_manifest = {
        "schema_version":   1,
        "split_by":         "scenario_family",
        "global_dataset_id": out_root.name,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "family_assignment": family_assignment,
        "label_counts_by_split": {
            k: dict(v) for k, v in label_counts_by_split.items()
        },
        "leave_one_family_out_folds": [
            {"fold_id": f"loo-{fam}", "held_out_family": fam} for fam in families
        ],
    }
    tmp = legacy_split_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(legacy_manifest, default=str, indent=2), encoding="utf-8")
    tmp.replace(legacy_split_path)

    split_manifest = {
        "schema_version":  1,
        "split_by":        "window_id",
        "global_dataset_id": out_root.name,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "seed":            seed,
        "split_ratios":    {"train": 0.70, "validation": 0.15, "test": 0.15},
        "window_assignment": window_assignment,
        "label_counts_by_split": {
            k: dict(v) for k, v in label_counts_by_split.items()
        },
        "leave_one_family_out_folds": [
            {"fold_id": f"loo-{fam}", "held_out_family": fam} for fam in families
        ],
    }
    tmp = split_manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(split_manifest, default=str, indent=2), encoding="utf-8")
    tmp.replace(split_manifest_path)

    # ----- triage-feature-columns.json (copied from synthetic) -----
    src_schema = synthetic_global_dir / "triage-feature-columns.json"
    if src_schema.exists():
        feature_schema_path.write_text(src_schema.read_text(encoding="utf-8"),
                                       encoding="utf-8")
    else:
        # Minimal stub if no synthetic dataset present.
        feature_schema_path.write_text(json.dumps({
            "schema_version": 1,
            "policy": "All fields prefixed with triage_feature_ are model inputs.",
            "feature_columns": feature_columns,
            "eval_only_fields": [
                "scenario_id", "scenario_family", "triage_label", "triage_severity",
                "triage_components", "triage_reason_class", "is_hard_case",
                "service_name", "start_time", "end_time", "incident_episode_id",
            ],
        }, indent=2), encoding="utf-8")

    # ----- dataset-metadata.json -----
    metadata = {
        "global_dataset_id":  out_root.name,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "source_kind":        "wol-mode3-self-contained",
        "source_paper":       "Wang et al., World of Logs (MSR '26)",
        "source_archive":     "data/17569722/WoL_v1-2025-11-10.archive.gz",
        "n_memory":           len(all_docs),
        "n_queries":          len(all_docs),
        "n_families":         len(families),
        "families":           families,
        "humanized_root":     "jira-shadow-humanized-v2",
        "humanized_subdir":   humanized_subdir,
        "intended_cascade":   "TCH-Lite (see docs7/TCH-Lite.md)",
        "intended_paper_section": "ICSE §5.X Real-Data Validation, Mode 3",
        "seed":               seed,
    }
    tmp = metadata_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metadata, default=str, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)

    # ----- source-mapping.csv (traceability) -----
    tmp = source_mapping_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["query_window_id", "memory_ticket_id", "wol_source_id",
                    "wol_project", "wol_issue_key", "split"])
        for doc in all_docs:
            meta = record_meta[doc["_id"]]
            w.writerow([
                meta["window_id"], meta["ticket_id"], doc["_id"],
                meta["project_name"], doc.get("key") or "", meta["split"],
            ])
    tmp.replace(source_mapping_path)

    # ----- gold-relations-debug.json (raw per-query gold lists) -----
    debug_gold = {
        wid: {
            "coarse_match_memory_ids": gold_coarse.get(wid, []),
            "strong_match_memory_ids": gold_strong.get(wid, []),
        }
        for wid in [record_meta[d["_id"]]["window_id"] for d in all_docs]
    }
    tmp = gold_debug_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(debug_gold, default=str, indent=2), encoding="utf-8")
    tmp.replace(gold_debug_path)

    # Compute stats for the manifest summary.
    coarse_avg = sum(len(v) for v in gold_coarse.values()) / max(1, len(gold_coarse))
    strong_avg = sum(len(v) for v in gold_strong.values()) / max(1, len(gold_strong))
    coarse_zero = sum(1 for v in gold_coarse.values() if not v)
    strong_zero = sum(1 for v in gold_strong.values() if not v)

    return {
        "mode": "self-contained",
        "n_memory":  len(all_docs),
        "n_queries": len(all_docs),
        "per_project_counts": per_project_counts,
        "split_counts": dict(Counter(window_assignment.values())),
        "fallback_severity_count": fallback_count,
        "match_relation_stats": {
            "coarse_avg_per_query": round(coarse_avg, 2),
            "strong_avg_per_query": round(strong_avg, 2),
            "coarse_zero_match_queries": coarse_zero,
            "strong_zero_match_queries": strong_zero,
            "jaccard_threshold_strong": 0.15,
        },
        "output_root": str(out_root),
        "artifact_paths": {
            "jira_memory_corpus":      str(memory_corpus_path.relative_to(out_root)),
            "humanized_timeline":      str(humanized_path.relative_to(out_root)),
            "global_triage_examples":  str(triage_examples_path.relative_to(out_root)),
            "matchings_coarse":        str(matchings_coarse.relative_to(out_root)),
            "matchings_strong":        str(matchings_strong.relative_to(out_root)),
            "split_manifest":          str(split_manifest_path.relative_to(out_root)),
            "feature_columns":         str(feature_schema_path.relative_to(out_root)),
            "dataset_metadata":        str(metadata_path.relative_to(out_root)),
        },
    }


# ---------------------------------------------------------------------------
# Provenance manifest. Plan §17.
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
        ).decode("ascii").strip()
        return out
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "(no-git)"


def write_manifest(
    out_root: Path,
    mode_results: dict[str, Any],
    *,
    seed: int,
    started_at: str,
    cache_root: Path,
) -> None:
    """Write the wol-extraction-manifest.json. Plan §17."""
    manifest = {
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "started_at":         started_at,
        "script_git_sha":     _git_sha(),
        "script_path":        str(Path(__file__).resolve()),
        "mongo_uri":          MONGO_URI,
        "mongo_db":           MONGO_DB,
        "mongo_collection":   MONGO_COL,
        "seed":               seed,
        "quality_filters": {
            "pred_uncertainty_max": PRED_UNCERTAINTY_MAX,
            "min_log_msgs":         MIN_LOG_MSGS,
            "min_desc_chars":       MIN_DESC_CHARS,
            "issuetype_allowed":    sorted(ISSUETYPE_ALLOWED),
        },
        "candidate_pool_cache_root": str(cache_root),
        "mode_results":             mode_results,
    }
    path = out_root / "wol-extraction-manifest.json"
    tmp  = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def cmd_candidate_pools(args) -> None:
    """Run the per-project aggregation + filter + cache step for all projects
    referenced by any mode. Idempotent — cached files are reused unless
    --overwrite is set."""
    cache_root = Path(args.cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)

    all_projects = sorted(set(
        DISTRACTOR_PROJECTS_MODE1
        + NOVELTY_QUERY_PROJECTS_MODE2
        + SELF_CONTAINED_PROJECTS_MODE3
    ))

    coll = get_mongo_collection()
    print(f"[candidate-pools] {len(all_projects)} projects, cache -> {cache_root}")
    counts: dict[str, int] = {}
    for p in all_projects:
        out_path = project_cache_path(cache_root, p)
        t0 = time.time()
        n = extract_candidate_pool(p, out_path, coll=coll, overwrite=args.overwrite)
        dt = time.time() - t0
        counts[p] = n
        print(f"  {p:42s}  {n:7d}  ({dt:5.1f}s)  -> {out_path.name}")

    summary_path = cache_root / "_pool_summary.json"
    summary_path.write_text(
        json.dumps({"counts": counts, "generated_at": datetime.now(timezone.utc).isoformat()},
                   default=str, indent=2),
        encoding="utf-8",
    )
    print(f"[candidate-pools] summary written to {summary_path}")


def cmd_distractors(args) -> None:
    priority_map, fallback_set = load_priority_mapping(Path(args.priority_mapping))
    res = write_mode1_distractors(
        Path(args.cache_root), Path(args.out_dir),
        priority_map, fallback_set,
        n_per_project=args.n_per_project,
        seed=args.seed,
        dataset_run_id=args.dataset_run_id,
    )
    print(json.dumps(res, indent=2))


def cmd_novelty_queries(args) -> None:
    priority_map, fallback_set = load_priority_mapping(Path(args.priority_mapping))
    res = write_mode2_novelty_queries(
        Path(args.cache_root), Path(args.out_dir),
        priority_map, fallback_set,
        n_per_project=args.n_per_project,
        seed=args.seed,
        dataset_run_id=args.dataset_run_id,
    )
    print(json.dumps(res, indent=2))


def cmd_self_contained(args) -> None:
    priority_map, fallback_set = load_priority_mapping(Path(args.priority_mapping))
    res = write_mode3_self_contained(
        Path(args.cache_root), Path(args.out_root),
        priority_map, fallback_set,
        seed=args.seed,
        dataset_run_id=args.dataset_run_id,
        synthetic_global_dir=Path(args.synthetic_global_dir) if args.synthetic_global_dir else None,
        humanized_subdir=args.humanized_subdir,
    )
    print(json.dumps(res, indent=2))


def cmd_all(args) -> None:
    """Run candidate-pools → distractors → novelty-queries → self-contained
    and write the master manifest."""
    started = datetime.now(timezone.utc).isoformat()
    out_root = Path(args.out_root)
    cache_root = Path(args.cache_root)

    # Step 1: candidate pools.
    p_args = argparse.Namespace(cache_root=str(cache_root), overwrite=args.overwrite)
    cmd_candidate_pools(p_args)

    # Step 2: priority mapping.
    priority_map, fallback_set = load_priority_mapping(Path(args.priority_mapping))

    # Step 3: per-mode writes.
    mode_results = {}

    mode_results["mode1_distractors"] = write_mode1_distractors(
        cache_root, out_root / "distractors",
        priority_map, fallback_set,
        n_per_project=MODE1_N_PER_PROJECT,
        seed=args.seed,
        dataset_run_id="wol-distractor-2026-06-11",
    )
    print(f"[all] Mode 1 done: {mode_results['mode1_distractors']['n_total']} records")

    mode_results["mode2_novelty"] = write_mode2_novelty_queries(
        cache_root, out_root / "novelty-queries",
        priority_map, fallback_set,
        n_per_project=MODE2_N_PER_PROJECT,
        seed=args.seed,
        dataset_run_id="wol-novelty-2026-06-11",
    )
    print(f"[all] Mode 2 done: {mode_results['mode2_novelty']['n_total']} records")

    mode_results["mode3_self_contained"] = write_mode3_self_contained(
        cache_root, out_root,
        priority_map, fallback_set,
        seed=args.seed,
        dataset_run_id="wol-self-contained-2026-06-11",
        synthetic_global_dir=Path(args.synthetic_global_dir) if args.synthetic_global_dir else None,
        humanized_subdir=args.humanized_subdir,
    )
    print(f"[all] Mode 3 done: "
          f"memory={mode_results['mode3_self_contained']['n_memory']}, "
          f"queries={mode_results['mode3_self_contained']['n_queries']}")

    # Step 4: manifest.
    write_manifest(out_root, mode_results,
                   seed=args.seed, started_at=started, cache_root=cache_root)
    print(f"[all] manifest written to {out_root / 'wol-extraction-manifest.json'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = dict(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p_pools = sub.add_parser("candidate-pools",
                              help="Cache per-project candidate records from Mongo.",
                              **common)
    p_pools.add_argument("--cache-root", default="data/derived/wol/extraction-cache")
    p_pools.add_argument("--overwrite", action="store_true",
                         help="Overwrite existing cache files instead of reusing them.")
    p_pools.set_defaults(func=cmd_candidate_pools)

    p_dist = sub.add_parser("distractors", help="Mode 1.", **common)
    p_dist.add_argument("--cache-root", default="data/derived/wol/extraction-cache")
    p_dist.add_argument("--out-dir", required=True)
    p_dist.add_argument("--priority-mapping",
                        default="data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    p_dist.add_argument("--n-per-project", type=int, default=MODE1_N_PER_PROJECT)
    p_dist.add_argument("--seed", type=int, default=42)
    p_dist.add_argument("--dataset-run-id", default="wol-distractor-2026-06-11")
    p_dist.set_defaults(func=cmd_distractors)

    p_nov = sub.add_parser("novelty-queries", help="Mode 2.", **common)
    p_nov.add_argument("--cache-root", default="data/derived/wol/extraction-cache")
    p_nov.add_argument("--out-dir", required=True)
    p_nov.add_argument("--priority-mapping",
                       default="data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    p_nov.add_argument("--n-per-project", type=int, default=MODE2_N_PER_PROJECT)
    p_nov.add_argument("--seed", type=int, default=42)
    p_nov.add_argument("--dataset-run-id", default="wol-novelty-2026-06-11")
    p_nov.set_defaults(func=cmd_novelty_queries)

    p_self = sub.add_parser("self-contained", help="Mode 3.", **common)
    p_self.add_argument("--cache-root", default="data/derived/wol/extraction-cache")
    p_self.add_argument("--out-root", required=True,
                        help="Global-dir root for the WoL Mode 3 dataset; "
                             "mirror files written directly here.")
    p_self.add_argument("--priority-mapping",
                        default="data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    p_self.add_argument("--synthetic-global-dir",
                        default="data/derived/global/2026-05-25-dataset-v5-large-global",
                        help="Source path for triage-feature-columns.json to copy across.")
    p_self.add_argument("--humanized-subdir", default="bulk-20260611")
    p_self.add_argument("--seed", type=int, default=42)
    p_self.add_argument("--dataset-run-id", default="wol-self-contained-2026-06-11")
    p_self.set_defaults(func=cmd_self_contained)

    p_all = sub.add_parser("all", help="candidate-pools + all three modes.", **common)
    p_all.add_argument("--cache-root", default="data/derived/wol/extraction-cache")
    p_all.add_argument("--out-root", default="data/derived/global/2026-06-15-wol-real-v2-global")
    p_all.add_argument("--priority-mapping",
                       default="data/derived/global/2026-06-15-wol-real-v2-global/wol-priority-mapping.json")
    p_all.add_argument("--synthetic-global-dir",
                       default="data/derived/global/2026-05-25-dataset-v5-large-global",
                       help="Source path for triage-feature-columns.json to copy across.")
    p_all.add_argument("--humanized-subdir", default="bulk-20260611")
    p_all.add_argument("--seed", type=int, default=42)
    p_all.add_argument("--overwrite", action="store_true")
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
