"""Phase B WoL augmentation — fixes triage + pages-per-incident red flags.

Closes the methodology red flags from DOCS/docs8/QnA.md §Q5:

  Red flag #1: WoL was 100% `ticket_worthy` → triage_acc trivial baseline = 1.000.
  Red flag #2: Every WoL row was a one-window incident → pages-per-incident trivially 1.000.

This script extends the v1 2000-row pool with:

  - ~2,400 `borderline` rows  (real Apache Jira w/ resolution ∈ {Duplicate, Incomplete,
                                Cannot Reproduce} — engineer judged "need more info or
                                already covered.")
  - ~5,100 `noise` rows       (real Apache Jira w/ resolution ∈ {Won't Fix, Invalid,
                                Not a Bug, Not A Problem} → "not actionable", PLUS
                                real Apache Jira w/ issuetype ∈ {Improvement, New Feature,
                                Question, Documentation, Wish} → "regular data": in-domain
                                non-bug text.)
  - Duplicate-link clustering — Jira `is duplicate of` / `duplicates` links group related
                                tickets under a shared `incident_episode_id`, making the
                                pages-per-incident metric non-trivial.

Resulting v2 dataset shape (target): ~9,500 rows, label split 21% / 25% / 54%
(matches OB ratio per the Q6 decision).

Per-project stratification follows the existing ticket_worthy distribution
where Mongo capacity allows. When a project lacks enough rows in a bucket
(e.g. MariaDB Server has zero non-bug issuetypes), the deficit is redistributed
proportionally across projects that have headroom.

Outputs go to a NEW global directory (default
`data/derived/global/2026-06-15-wol-real-v2-global/`) so v1 remains intact.

Invariant files copied verbatim from v1:
  - jira-memory-corpus.jsonl        (memory unchanged — same 2000 ticket_worthy past tickets)
  - jira-shadow-humanized-v2/       (memory-side humanised timeline)
  - triage-feature-columns.json     (94 columns, all zero-filled on WoL)
  - distractors/                    (Mode 1 OFF-topic — independent of Mode 3 augmentation)
  - novelty-queries/                (Mode 2 OOD — independent)

Files regenerated:
  - global-triage-examples.jsonl    (2000 v1 ticket_worthy + ~7500 new borderline/noise)
  - triage-split-manifest.json      (family-split unchanged; label_counts updated)
  - window-memory-matchings.jsonl   (coarse gold; new rows have empty matched_memory_issue_ids)
  - window-memory-matchings-strong.jsonl
  - dataset-metadata.json
  - README.md                       (with full provenance of new pools)
  - wol-extraction-manifest.json

Known deferred work (not blocking):
  - v2_kg_extractions_windows/      LLM KG extraction over new rows is multi-hour. The KG
                                    retriever will return empty matches for these rows
                                    until a separate extraction pass runs.
  - tch-lite-refit/*.jsonl          Cascade predictions need re-running on the new test
                                    split. See `scripts/research-lab/run_*_wol_mode3.py`.

Usage:

    python scripts/research-lab/build_wol_real_corpus_v2.py augment \\
        --source-global-dir data/derived/global/2026-06-11-wol-real-global \\
        --out-global-dir    data/derived/global/2026-06-15-wol-real-v2-global

    # Optional flags:
    #   --skip-mongo-harvest    (use cached project-pool JSONLs if already extracted)
    #   --cluster-duplicates    (default ON; groups related tickets into incidents)
    #   --target-borderline 2400 --target-noise 5100
    #   --seed 42
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Reuse v1 utilities. We don't import the *modes* from v1 — only the field
# mappers and helpers. The mode-specific writers (Mode 1 distractors, Mode 2
# novelty) are independent of the augmentation pass.
sys.path.insert(0, str(Path(__file__).parent))
from build_wol_real_corpus import (  # type: ignore
    MONGO_URI,
    MONGO_DB,
    MONGO_COL,
    PRED_UNCERTAINTY_MAX,
    MIN_DESC_CHARS,
    MIN_LOG_MSGS,
    REASON_KEYWORDS,
    SELF_CONTAINED_PROJECTS_MODE3,
    SYMPTOM_STOPWORDS,
    _classify_triage_reason,
    _component_names,
    _evidence_bundle_hash,
    _first_n_log_msgs,
    _joined_log_msgs,
    _safe_get,
    _short_id,
    _truncated_description,
    get_mongo_collection,
    load_priority_mapping,
    normalize_priority,
    slugify_project_name,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase B constants
# ---------------------------------------------------------------------------

# Resolutions / issuetypes used for new pools. Verified against Mongo
# 2026-06-15: counts in DOCS/docs8/QnA.md §Q6 measured availability table.

BORDERLINE_RESOLUTIONS: list[str] = [
    "Duplicate",          # 2009 across 7 projects after quality filters
    "Incomplete",         # 710
    "Cannot Reproduce",   # 966
]

NOISE_RESOLUTIONS: list[str] = [
    "Won't Fix",          # 612
    "Invalid",            # 646
    "Not a Bug",          # 420 (also "Not A Bug" via $in below)
    "Not A Problem",      # 1006
]

REGULAR_ISSUETYPES: list[str] = [
    "Improvement",        # 2083 (the big one)
    "New Feature",        # 96
    "Question",           # 111
    "Documentation",      # 26
    "Wish",               # 19
]

# Per-project ratios for distributing borderline/noise/regular quotas.
# These match the existing 2000 ticket_worthy distribution. When a project
# can't hit its quota in a bucket, the deficit redistributes to projects
# with headroom (greedy fill — see _distribute_quota).
PROJECT_TARGET_RATIOS: dict[str, float] = {
    "Spark":          0.175,
    "Cassandra":      0.175,
    "HBase":          0.150,
    "Flink":          0.150,
    "Ambari":         0.125,
    "MariaDB Server": 0.125,
    "Kafka":          0.100,
}

# Phase B default targets (Q6 §6.3 — match OB ratio at 21% / 25% / 54% scale).
DEFAULT_TARGET_BORDERLINE = 2400
DEFAULT_TARGET_NOISE_PLUS_REGULAR = 5100

# Within the noise+regular budget, how much comes from each kind. Determined by
# availability: regular issuetypes have ~2.3K headroom; resolution-based noise
# has ~2.7K headroom; total budget is 5.1K. Use a 55/45 split tilted toward
# resolution-noise (the more defensible signal — engineer explicit close).
NOISE_RESOLUTION_FRACTION = 0.55
NOISE_REGULAR_FRACTION    = 0.45

# Duplicate-link clustering — which Jira link types collapse tickets into one
# incident. "is duplicate of" is the tightest; "relates to" is broader and
# included only when both endpoints are within our pool (avoids over-clustering).
DUPLICATE_LINK_TYPES_TIGHT  = {"Duplicate", "Cloners", "Cause", "Caused", "Caused by"}
DUPLICATE_LINK_TYPES_BROAD  = {"Relates", "Reference", "Related"}

# Output paths within global_dir
EXAMPLES_FNAME            = "global-triage-examples.jsonl"
MEMORY_FNAME              = "jira-memory-corpus.jsonl"
SPLIT_MANIFEST_FNAME      = "triage-split-manifest.json"
GOLD_COARSE_FNAME         = "window-memory-matchings.jsonl"
GOLD_STRONG_FNAME         = "window-memory-matchings-strong.jsonl"
DATASET_META_FNAME        = "dataset-metadata.json"
README_FNAME              = "README.md"
EXTRACTION_MANIFEST_FNAME = "wol-extraction-manifest.json"
FEATURE_COLUMNS_FNAME     = "triage-feature-columns.json"
PRIORITY_MAP_FNAME        = "wol-priority-mapping.json"

INVARIANT_DIRS_TO_COPY = [
    "jira-shadow-humanized-v2",
    "distractors",
    "novelty-queries",
    "v2_kg_extractions",        # memory-side KG extractions — unchanged (memory is unchanged)
]
INVARIANT_FILES_TO_COPY = [
    MEMORY_FNAME,
    FEATURE_COLUMNS_FNAME,
    PRIORITY_MAP_FNAME,
    "source-mapping.csv",
    "wol-priority-mapping.json",
]


# ---------------------------------------------------------------------------
# Quota distribution — handles per-project capacity gracefully
# ---------------------------------------------------------------------------


@dataclass
class BucketCapacity:
    """How many rows each project has available in a given Mongo bucket."""
    bucket_name: str
    per_project: dict[str, int]   # project_name -> available count

    def total(self) -> int:
        return sum(self.per_project.values())


def _distribute_quota(
    target_total: int,
    capacity: BucketCapacity,
    target_ratios: dict[str, float],
) -> dict[str, int]:
    """Decide how many rows to take from each project to hit `target_total`.

    Algorithm:
      1. Allocate each project its target_ratios share of `target_total`.
      2. For any project whose share exceeds its capacity, cap at capacity and
         redistribute the deficit to projects with headroom, proportional to
         their remaining capacity.
      3. Repeat until either total met or all projects at capacity.

    Returns {project_name -> n_to_sample}. Sum may be < target if capacity is
    insufficient overall — caller logs and proceeds with what's available.
    """
    quotas = {p: 0 for p in target_ratios}
    pending = target_total

    # Pass 1: ideal allocation
    for p, ratio in target_ratios.items():
        ideal = round(target_total * ratio)
        actual = min(ideal, capacity.per_project.get(p, 0))
        quotas[p] = actual
        pending -= actual

    # Pass 2..N: redistribute deficit to projects with remaining capacity
    safety = 16
    while pending > 0 and safety > 0:
        safety -= 1
        remaining_capacity = {
            p: capacity.per_project.get(p, 0) - quotas[p]
            for p in target_ratios
            if capacity.per_project.get(p, 0) - quotas[p] > 0
        }
        total_rem = sum(remaining_capacity.values())
        if total_rem == 0:
            log.warning(
                "Bucket %s — only %d/%d rows available; %d short across all projects",
                capacity.bucket_name,
                target_total - pending,
                target_total,
                pending,
            )
            break
        for p, rem in remaining_capacity.items():
            if pending <= 0:
                break
            share = min(rem, max(1, round(pending * rem / total_rem)))
            quotas[p] += share
            pending -= share

    return quotas


# ---------------------------------------------------------------------------
# Mongo extraction — one bucket
# ---------------------------------------------------------------------------


def _harvest_bucket(
    coll,
    *,
    project_name: str,
    bucket_filter: dict,
    needs_logs: bool,
    cache_path: Path,
    overwrite: bool = False,
) -> int:
    """Extract a (project, bucket) slice from Mongo and stream to cache_path.

    bucket_filter is merged with the standard quality filters (description
    length, pred_uncertainty, optional log_msgs presence).

    Returns the number of records written. Re-counts existing cache when
    `overwrite=False`.
    """
    if cache_path.exists() and not overwrite:
        return sum(1 for _ in cache_path.open(encoding="utf-8"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    quality = {
        "fields.project.name":  project_name,
        "pred_uncertainty":     {"$lte": PRED_UNCERTAINTY_MAX},
        "$expr": {"$gte": [
            {"$strLenCP": {"$ifNull": ["$fields.description", ""]}},
            MIN_DESC_CHARS,
        ]},
    }
    if needs_logs:
        quality[f"log_msgs.{MIN_LOG_MSGS - 1}"] = {"$exists": True}

    match = {**quality, **bucket_filter}

    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    n = 0
    with tmp_path.open("w", encoding="utf-8") as fh:
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
    tmp_path.replace(cache_path)
    return n


def harvest_all_buckets(
    cache_root: Path,
    *,
    overwrite: bool = False,
) -> dict[str, BucketCapacity]:
    """Run the full Mongo harvest for all (project, bucket) combinations.

    Returns {bucket_name -> BucketCapacity} indexed by bucket_name.
    """
    coll = get_mongo_collection()
    capacities: dict[str, BucketCapacity] = {}

    bucket_defs: list[tuple[str, dict, bool]] = []
    for res in BORDERLINE_RESOLUTIONS:
        bucket_defs.append((
            f"borderline_{slugify_project_name(res)}",
            {"fields.issuetype.name": "Bug", "fields.resolution.name": res},
            True,
        ))
    for res in NOISE_RESOLUTIONS:
        bucket_defs.append((
            f"noise_{slugify_project_name(res)}",
            {"fields.issuetype.name": "Bug",
             "fields.resolution.name": (
                 {"$in": ["Not a Bug", "Not A Bug"]} if res == "Not a Bug" else res
             )},
            True,
        ))
    for it in REGULAR_ISSUETYPES:
        bucket_defs.append((
            f"regular_{slugify_project_name(it)}",
            {"fields.issuetype.name": it},
            False,    # non-bug docs often lack log_msgs
        ))

    for bucket_name, bucket_filter, needs_logs in bucket_defs:
        per_project: dict[str, int] = {}
        for project in SELF_CONTAINED_PROJECTS_MODE3:
            cache_path = cache_root / bucket_name / f"{slugify_project_name(project)}.jsonl"
            n = _harvest_bucket(
                coll,
                project_name=project,
                bucket_filter=bucket_filter,
                needs_logs=needs_logs,
                cache_path=cache_path,
                overwrite=overwrite,
            )
            per_project[project] = n
            log.info("  harvest %s / %s -> n=%d at %s",
                     bucket_name, project, n, cache_path.name)
        capacities[bucket_name] = BucketCapacity(bucket_name, per_project)
        log.info("BUCKET %s total: %d", bucket_name, capacities[bucket_name].total())

    return capacities


# ---------------------------------------------------------------------------
# Field mapping — Mongo doc -> TriageWindow row (with non-fixed label)
# ---------------------------------------------------------------------------


def map_to_triagewindow_v2(
    doc: dict,
    *,
    dataset_run_id: str,
    triage_label: str,           # "ticket_worthy" | "borderline" | "noise"
    bucket_name: str,            # for source provenance
    priority_map: dict[str, str],
    fallback_set: set[str],
    incident_episode_id: str | None = None,
    split: str | None = None,    # "train" | "validation" | "test"; derived from family
) -> dict:
    """Mongo doc -> global-triage-examples.jsonl row, with explicit label.

    Differs from v1's `map_to_triagewindow` in four ways:
      1. `triage_label` is a parameter (v1 always set "ticket_worthy").
      2. Falls back to (summary + description) for `triage_evidence_text` when
         log_msgs is empty (non-Bug regular data often lacks logs).
      3. `incident_episode_id` overridable for duplicate-link clustering.
      4. `split` field included in output — v1 had it as JSONL-level field;
         omitting it caused `resolve_split()` to silently exclude rows since
         the v1 manifest has no `window_assignment` dict (load_split_manifest
         returns None, and fallback `row.get("split", "")` was empty).
    """
    wol_id   = doc.get("_id", "")
    sid      = _short_id(wol_id)
    window_id = f"wol-q-{sid}"

    log_msgs   = _first_n_log_msgs(doc)
    summary    = _safe_get(doc, "fields", "summary") or ""
    desc       = _truncated_description(doc)
    components = _component_names(doc)

    if log_msgs:
        evidence_text = "\n".join(log_msgs)
    else:
        # Regular-data path: no logs, fall back to summary+desc
        evidence_text = f"{summary}\n\n{desc}".strip()

    raw_pri = _safe_get(doc, "fields", "priority", "name")
    severity, uncertain = normalize_priority(raw_pri, priority_map, fallback_set)

    project_name = _safe_get(doc, "fields", "project", "name") or ""
    scenario_family = f"wol-{slugify_project_name(project_name)}"

    if components:
        service_name = components[0]
    else:
        service_name = "unknown"

    now_iso = datetime.now(timezone.utc).isoformat()

    out = {
        "window_id":            window_id,
        "dataset_run_id":       dataset_run_id,
        "incident_episode_id":  incident_episode_id or window_id,
        "scenario_id":          f"wol-{slugify_project_name(project_name)}-{sid}",
        "scenario_family":      scenario_family,
        "service_name":         service_name,
        "window_type":          "active_fault",
        "start_time":           now_iso,
        "end_time":             now_iso,
        "triage_label":         triage_label,
        "triage_severity":      severity,
        "severity_uncertain":   uncertain,
        "triage_components":    components,
        "triage_reason_class":  _classify_triage_reason(summary),
        "is_hard_case":         False,
        "source":               f"wol-v2-{bucket_name}",
        "triage_evidence_text": evidence_text,
        "fault_compatibility_class": "wol-real",
        "wol_source_id":        wol_id,
        "wol_project":          project_name,
        "wol_issue_key":        doc.get("key"),
        # Numeric features are zero-filled in v1; we don't change that here.
        # The loader will set numeric_features=None on WoL bundles regardless.
    }
    if split:
        out["split"] = split
    return out


# ---------------------------------------------------------------------------
# Duplicate-link clustering — §6.6
# ---------------------------------------------------------------------------


def _extract_link_targets(doc: dict, *, tight_only: bool) -> list[str]:
    """Pull Jira keys (e.g. 'SPARK-13326') of tickets linked to `doc`.

    Walks `fields.issuelinks` and extracts the linked-issue `key` for both
    inward and outward references of the configured link types. Jira `key`
    is the lingua franca across the link graph — the linked-issue object
    carries its own `key` regardless of which collection stored it.
    """
    out: list[str] = []
    links = _safe_get(doc, "fields", "issuelinks") or []
    allowed = DUPLICATE_LINK_TYPES_TIGHT if tight_only else (
        DUPLICATE_LINK_TYPES_TIGHT | DUPLICATE_LINK_TYPES_BROAD
    )
    for link in links:
        if not isinstance(link, dict):
            continue
        ltype = _safe_get(link, "type", "name") or ""
        if ltype not in allowed:
            continue
        for direction in ("inwardIssue", "outwardIssue"):
            tgt = link.get(direction)
            if isinstance(tgt, dict):
                tgt_key = tgt.get("key")
                if tgt_key:
                    out.append(str(tgt_key))
    return out


def cluster_duplicate_links(
    rows: list[dict],
    *,
    cache_root: Path,
    tight_only: bool = True,
) -> dict[str, str]:
    """Build connected components over duplicate-link edges; assign incident_episode_ids.

    Returns {window_id -> shared_incident_episode_id}. Tickets without links
    keep their own window_id as the incident_episode_id.

    Identifier scheme: union-find over **Jira key** (e.g. "SPARK-13326") since
    that's what Jira's `issuelinks.{inwardIssue,outwardIssue}.key` references.
    Mongo `_id` is private; Jira `key` is portable.

    Strategy:
      1. Index rows by Jira key.
      2. Re-read raw Mongo docs from the bucket caches.
      3. Walk doc.fields.issuelinks; union when the target's Jira key is
         also in our row pool.
      4. Group window_ids by cluster root; assign incident_episode_id.
    """
    # Index our row pool by Jira key
    row_by_jirakey: dict[str, dict] = {}
    for r in rows:
        jkey = r.get("wol_issue_key")
        if jkey:
            row_by_jirakey[jkey] = r

    # Build doc lookup keyed on Jira key (only for docs that survived sampling)
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
        for tgt in _extract_link_targets(doc, tight_only=tight_only):
            if tgt in parent:    # only union with rows that survived sampling
                union(jkey, tgt)
                n_edges += 1

    # Build cluster map
    clusters: dict[str, list[str]] = defaultdict(list)
    for jkey in parent:
        clusters[find(jkey)].append(jkey)

    n_multi = sum(1 for c in clusters.values() if len(c) > 1)
    log.info("Duplicate-link clustering: %d edges -> %d clusters (%d multi-ticket)",
             n_edges, len(clusters), n_multi)

    # Map window_id -> incident_episode_id (deterministic: root = sorted-min Jira key)
    out: dict[str, str] = {}
    for cluster in clusters.values():
        cluster.sort()
        root_jkey = cluster[0]
        root_window_id = row_by_jirakey[root_jkey]["window_id"]
        incident_id = f"wol-incident-{root_window_id[len('wol-q-'):]}"
        for jkey in cluster:
            window_id = row_by_jirakey[jkey]["window_id"]
            out[window_id] = incident_id

    return out


# ---------------------------------------------------------------------------
# Sampling + assembly
# ---------------------------------------------------------------------------


def sample_pool(
    cache_root: Path,
    *,
    bucket_names: Iterable[str],
    quotas_per_bucket: dict[str, dict[str, int]],
    seed: int,
) -> list[dict]:
    """Read cached bucket JSONLs and randomly sample to the quota.

    Returns a flat list of Mongo docs, each tagged with `_bucket` so the
    caller can route to the right triage_label.
    """
    rng = random.Random(seed)
    out: list[dict] = []
    for bucket_name in bucket_names:
        per_project_quota = quotas_per_bucket.get(bucket_name, {})
        for project, n_target in per_project_quota.items():
            if n_target <= 0:
                continue
            cache_path = cache_root / bucket_name / f"{slugify_project_name(project)}.jsonl"
            if not cache_path.exists():
                log.warning("  cache missing: %s — skipping", cache_path)
                continue
            rows = [json.loads(line) for line in cache_path.open(encoding="utf-8")]
            if not rows:
                continue
            if len(rows) <= n_target:
                picked = rows
            else:
                picked = rng.sample(rows, n_target)
            for d in picked:
                d["_bucket"] = bucket_name
            out.extend(picked)
            log.info("  sampled %s / %s: n=%d / %d available",
                     bucket_name, project, len(picked), len(rows))
    return out


def label_from_bucket(bucket_name: str) -> str:
    if bucket_name.startswith("borderline_"):
        return "borderline"
    if bucket_name.startswith("noise_"):
        return "noise"
    if bucket_name.startswith("regular_"):
        return "noise"          # regular data folds into the noise class
    raise ValueError(f"unknown bucket {bucket_name!r}")


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def copy_invariants(src: Path, dst: Path) -> None:
    """Copy the files/dirs that don't change between v1 and v2."""
    dst.mkdir(parents=True, exist_ok=True)
    for fname in INVARIANT_FILES_TO_COPY:
        s, d = src / fname, dst / fname
        if s.exists():
            shutil.copy2(s, d)
            log.info("  copied %s", fname)
    for dname in INVARIANT_DIRS_TO_COPY:
        s, d = src / dname, dst / dname
        if s.exists() and not d.exists():
            shutil.copytree(s, d)
            log.info("  copied directory %s", dname)


def write_examples_jsonl(
    src_examples: Path,
    dst_examples: Path,
    new_rows: list[dict],
) -> tuple[int, int]:
    """Concatenate v1's 2000 ticket_worthy rows with new_rows. Returns (n_v1, n_new)."""
    tmp = dst_examples.with_suffix(".jsonl.tmp")
    n_v1 = 0
    with tmp.open("w", encoding="utf-8") as fh:
        # First, the v1 rows verbatim
        with src_examples.open(encoding="utf-8") as src_fh:
            for line in src_fh:
                line = line.strip()
                if not line:
                    continue
                fh.write(line + "\n")
                n_v1 += 1
        # Then, the new rows
        for r in new_rows:
            # Strip the internal _bucket key — it's a build-time annotation only
            r_clean = {k: v for k, v in r.items() if not k.startswith("_")}
            fh.write(json.dumps(r_clean, default=str, ensure_ascii=False) + "\n")
    tmp.replace(dst_examples)
    return n_v1, len(new_rows)


def write_split_manifest(
    src_manifest_path: Path,
    dst_manifest_path: Path,
    new_rows: list[dict],
    family_assignment_v1: dict[str, str],
) -> dict[str, Any]:
    """Update the split manifest's label_counts_by_split with new rows.

    Family assignment stays unchanged (we don't introduce new families). New
    rows ride the existing family assignment — Spark rows go to train, Kafka
    rows to test, etc.
    """
    src = json.loads(src_manifest_path.read_text(encoding="utf-8"))
    label_counts: dict[str, dict[str, int]] = {
        split: dict(counts) for split, counts in src.get("label_counts_by_split", {}).items()
    }
    for split in ("train", "validation", "test"):
        label_counts.setdefault(split, {})
        label_counts[split].setdefault("ticket_worthy", 0)
        label_counts[split].setdefault("borderline", 0)
        label_counts[split].setdefault("noise", 0)

    for r in new_rows:
        family = r.get("scenario_family")
        split = family_assignment_v1.get(family)
        if split is None:
            continue
        label = r["triage_label"]
        label_counts[split][label] = label_counts[split].get(label, 0) + 1

    out = dict(src)
    out["label_counts_by_split"] = label_counts
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["augmented_from"] = src.get("global_dataset_id", "unknown")
    dst_manifest_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return label_counts


def write_gold_matchings(
    src_coarse: Path, src_strong: Path,
    dst_coarse: Path, dst_strong: Path,
    new_rows: list[dict],
) -> None:
    """Copy v1 coarse + strong gold verbatim, then append empty-gold rows for new windows.

    Non-ticket-worthy queries have NO correct retrieval target — they're not
    bug reports, so nothing in the memory corpus is the "right answer." The
    eval harness treats empty gold as "this window does not contribute to
    Hit@K aggregation" (mean-with-filter); triage and novelty metrics still
    apply.
    """
    for src, dst in ((src_coarse, dst_coarse), (src_strong, dst_strong)):
        tmp = dst.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            if src.exists():
                with src.open(encoding="utf-8") as src_fh:
                    for line in src_fh:
                        line = line.strip()
                        if line:
                            fh.write(line + "\n")
            # Append empty-gold rows for new windows so they appear in the
            # gold index (downstream code does `gold.get(window_id, default)`).
            for r in new_rows:
                gold_row = {
                    "window_id":               r["window_id"],
                    "dataset_run_id":          r["dataset_run_id"],
                    "scenario_family":         r["scenario_family"],
                    "affected_service":        r["service_name"],
                    "fault_compatibility_class": r["fault_compatibility_class"],
                    "triage_label":            r["triage_label"],
                    "is_novel":                False,
                    "matched_memory_issue_ids": [],
                    "match_strength":          "empty",
                }
                fh.write(json.dumps(gold_row, default=str, ensure_ascii=False) + "\n")
        tmp.replace(dst)


def write_metadata_and_readme(
    out_dir: Path,
    *,
    n_v1: int,
    n_new_borderline: int,
    n_new_noise: int,
    label_counts: dict[str, dict[str, int]],
    n_multi_incident_clusters: int,
    source_global_id: str,
) -> None:
    meta = {
        "global_dataset_id": out_dir.name,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "source_kind":       "wol-mode3-v2-augmented",
        "augmented_from":    source_global_id,
        "n_memory":          2000,
        "n_queries_v1":      n_v1,
        "n_queries_new":     n_new_borderline + n_new_noise,
        "n_queries_total":   n_v1 + n_new_borderline + n_new_noise,
        "n_borderline_added": n_new_borderline,
        "n_noise_added":      n_new_noise,
        "n_multi_incident_clusters": n_multi_incident_clusters,
        "label_counts_by_split": label_counts,
        "seed":               42,
        "phase_b_red_flags_addressed": [
            "Q5#1 — triage trivial baseline (was 1.000, target ~0.54 matching OB)",
            "Q5#2 — pages-per-incident structural triviality (1:1 → multi-ticket clusters)",
        ],
    }
    (out_dir / DATASET_META_FNAME).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = f"""# World of Logs (WoL) v2 — Phase B augmented

Augmented from `{source_global_id}` on {datetime.now(timezone.utc).isoformat()}.

## What changed vs v1

v1 had **2000 ticket_worthy rows** with no noise / borderline → triage accuracy was
mathematically meaningless (trivial baseline = 1.000). v2 adds **~{n_new_borderline + n_new_noise}
new rows** from the same 7 Apache projects, harvested from the same WoL MongoDB.

| Label | v1 | v2 | Source |
|---|---:|---:|---|
| ticket_worthy | {n_v1} | {n_v1} | unchanged — original Mode 3 pool (resolution=Fixed bugs) |
| borderline | 0 | {n_new_borderline} | real Apache Jira w/ resolution ∈ {{Duplicate, Incomplete, Cannot Reproduce}} |
| noise | 0 | {n_new_noise} | real Apache Jira w/ resolution ∈ {{Won't Fix, Invalid, Not a Bug, Not A Problem}} OR issuetype ∈ {{Improvement, New Feature, Question, Documentation, Wish}} |

## Multi-ticket incidents

{n_multi_incident_clusters} clusters of 2+ tickets share an `incident_episode_id` via Jira
`is duplicate of` / `Cloners` / `Cause` link types. This makes the pages-per-incident
metric non-trivial — the StateLayer's suppression rule now has multi-ticket sequences to
exercise on WoL test rows.

## Label distribution by split

```
{json.dumps(label_counts, indent=2)}
```

## What stays unchanged

- `jira-memory-corpus.jsonl` — 2000 ticket_worthy past tickets, exactly as v1
- `jira-shadow-humanized-v2/` — memory-side humanised timeline, unchanged
- `triage-feature-columns.json` — 94 columns, all zero-filled on WoL (no telemetry)
- `distractors/` — Mode 1 OFF-topic, independent of augmentation
- `novelty-queries/` — Mode 2 OOD, independent
- `v2_kg_extractions/` — memory-side KG extractions, unchanged

## What needs follow-up work (not blocking the v2 release)

- `v2_kg_extractions_windows/` — the LLM KG extractor must be re-run over the new ~{n_new_borderline + n_new_noise}
  windows. The KG retriever returns empty matches for these rows until that pass runs.
  Estimated cost: ~3 hours at LM Studio rates with `qwen3.6-35b-a3b` temperature=0.
- `tch-lite-refit/*-predictions.jsonl` — cascade predictions must be re-generated on the
  new test split using `scripts/research-lab/run_*_wol_mode3.py`. Estimated: ~6 wall-hours.

## Closes red flags from DOCS/docs8/QnA.md §Q5

- **#1 (triage trivial baseline)** — single-class structure removed; trivial baseline
  drops from 1.000 → ~{1 - (n_v1 / (n_v1 + n_new_borderline + n_new_noise)):.2f} (depends on final ratio).
- **#2 (1:1 ticket-incident mapping)** — Jira link clustering produces
  {n_multi_incident_clusters} multi-ticket clusters; pages-per-incident becomes a real signal.

## Provenance

Sourced from the same WoL v1 archive (`data/wol/WoL_v1-2025-11-10.archive.gz`) via the same
MongoDB instance (`mongodb://localhost:27017`, db=`WoL_v1`, collection=`JIRA`). Quality
filters identical to v1 (`pred_uncertainty ≤ 0.05`, `description ≥ 200 chars`,
`log_msgs ≥ 1` for Bug rows; logs filter relaxed for non-Bug rows since regular tickets
often lack log content). Build script: `scripts/research-lab/build_wol_real_corpus_v2.py`.
"""
    (out_dir / README_FNAME).write_text(readme, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_augment(args: argparse.Namespace) -> None:
    src = Path(args.source_global_dir).resolve()
    dst = Path(args.out_global_dir).resolve()
    if not src.exists():
        sys.exit(f"ERROR: source global dir not found: {src}")

    # --- 0. Set up output dir + copy invariants ---
    dst.mkdir(parents=True, exist_ok=True)
    log.info("Copying invariant files/dirs from v1...")
    copy_invariants(src, dst)

    # --- 1. Load priority map for severity normalisation ---
    priority_map, fallback_set = load_priority_mapping(dst / PRIORITY_MAP_FNAME)

    # --- 2. Harvest Mongo (or use cache) ---
    cache_root = Path(args.cache_root or dst / ".pool_cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    log.info("Harvesting pools from Mongo (or using cache at %s)...", cache_root)
    capacities = harvest_all_buckets(cache_root, overwrite=False)

    # --- 3. Decide quotas per bucket per project ---
    # Borderline budget: split across the 3 resolution buckets proportional to availability.
    borderline_total_cap = sum(c.total() for n, c in capacities.items() if n.startswith("borderline_"))
    borderline_target = min(args.target_borderline, borderline_total_cap)
    log.info("Borderline budget: target=%d, capacity=%d -> using %d",
             args.target_borderline, borderline_total_cap, borderline_target)

    # Noise budget: split between resolution-noise (4 buckets) and regular-noise (5 buckets)
    noise_total_cap = sum(c.total() for n, c in capacities.items()
                          if n.startswith("noise_") or n.startswith("regular_"))
    noise_target = min(args.target_noise, noise_total_cap)
    log.info("Noise+Regular budget: target=%d, capacity=%d -> using %d",
             args.target_noise, noise_total_cap, noise_target)

    quotas_per_bucket: dict[str, dict[str, int]] = {}

    # Allocate borderline across its 3 sub-buckets proportional to capacity
    borderline_buckets = [n for n in capacities if n.startswith("borderline_")]
    for bname in borderline_buckets:
        cap = capacities[bname]
        sub_target = round(borderline_target * cap.total() / max(1, borderline_total_cap))
        quotas_per_bucket[bname] = _distribute_quota(sub_target, cap, PROJECT_TARGET_RATIOS)

    # Allocate noise across its 9 sub-buckets, split 55/45 between resolution/regular
    res_noise_cap = sum(c.total() for n, c in capacities.items() if n.startswith("noise_"))
    reg_noise_cap = sum(c.total() for n, c in capacities.items() if n.startswith("regular_"))
    res_noise_budget = round(noise_target * NOISE_RESOLUTION_FRACTION)
    reg_noise_budget = noise_target - res_noise_budget
    # Cap each budget at the pool's actual capacity
    res_noise_budget = min(res_noise_budget, res_noise_cap)
    reg_noise_budget = min(reg_noise_budget, reg_noise_cap)
    log.info("Noise split: resolution=%d (cap %d), regular=%d (cap %d)",
             res_noise_budget, res_noise_cap, reg_noise_budget, reg_noise_cap)

    for bname in [n for n in capacities if n.startswith("noise_")]:
        cap = capacities[bname]
        sub_target = round(res_noise_budget * cap.total() / max(1, res_noise_cap))
        quotas_per_bucket[bname] = _distribute_quota(sub_target, cap, PROJECT_TARGET_RATIOS)
    for bname in [n for n in capacities if n.startswith("regular_")]:
        cap = capacities[bname]
        sub_target = round(reg_noise_budget * cap.total() / max(1, reg_noise_cap))
        quotas_per_bucket[bname] = _distribute_quota(sub_target, cap, PROJECT_TARGET_RATIOS)

    # --- 4. Sample + field-map ---
    log.info("Sampling pools to quotas...")
    sampled_docs = sample_pool(
        cache_root,
        bucket_names=list(capacities.keys()),
        quotas_per_bucket=quotas_per_bucket,
        seed=args.seed,
    )
    log.info("Sampled %d docs total", len(sampled_docs))

    # Load family→split mapping so we can stamp each new row with its split
    # (resolve_split() falls back to row["split"] when window_assignment is absent)
    src_manifest = src / SPLIT_MANIFEST_FNAME
    src_split = json.loads(src_manifest.read_text(encoding="utf-8"))
    family_assignment = src_split.get("family_assignment", {})

    new_rows: list[dict] = []
    dataset_run_id = f"wol-v2-{dst.name}"
    for doc in sampled_docs:
        bucket = doc.get("_bucket", "unknown")
        label = label_from_bucket(bucket)
        project_name = _safe_get(doc, "fields", "project", "name") or ""
        scenario_family = f"wol-{slugify_project_name(project_name)}"
        split = family_assignment.get(scenario_family)
        row = map_to_triagewindow_v2(
            doc,
            dataset_run_id=dataset_run_id,
            triage_label=label,
            bucket_name=bucket,
            priority_map=priority_map,
            fallback_set=fallback_set,
            split=split,
        )
        # Preserve wol_source_id for clustering
        row["wol_source_id"] = doc.get("_id", "")
        new_rows.append(row)

    # --- 5. Duplicate-link clustering (§6.6) ---
    n_multi = 0
    if args.cluster_duplicates:
        log.info("Clustering by Jira duplicate-links...")
        clusters = cluster_duplicate_links(new_rows, cache_root=cache_root, tight_only=True)
        for r in new_rows:
            wid = r["window_id"]
            if wid in clusters:
                r["incident_episode_id"] = clusters[wid]
        n_multi = len({cid for cid in clusters.values()})
        # Refine: only count clusters that actually merge >1 window
        cluster_sizes = Counter(clusters.values())
        n_multi = sum(1 for sz in cluster_sizes.values() if sz > 1)

    # --- 6. Write output JSONLs ---
    log.info("Writing global-triage-examples.jsonl...")
    n_v1, n_new = write_examples_jsonl(
        src_examples=src / EXAMPLES_FNAME,
        dst_examples=dst / EXAMPLES_FNAME,
        new_rows=new_rows,
    )
    log.info("  %d v1 rows + %d new rows = %d total", n_v1, n_new, n_v1 + n_new)

    # --- 7. Update split manifest ---
    family_assignment_v1 = family_assignment    # already loaded above for split-tagging

    log.info("Updating split manifest...")
    label_counts = write_split_manifest(
        src_manifest_path=src_manifest,
        dst_manifest_path=dst / SPLIT_MANIFEST_FNAME,
        new_rows=new_rows,
        family_assignment_v1=family_assignment_v1,
    )
    for split, counts in label_counts.items():
        log.info("  %s: %s", split, counts)

    # --- 8. Gold matchings ---
    log.info("Writing gold matchings (empty gold for non-ticket-worthy)...")
    write_gold_matchings(
        src_coarse=src / GOLD_COARSE_FNAME,
        src_strong=src / GOLD_STRONG_FNAME,
        dst_coarse=dst / GOLD_COARSE_FNAME,
        dst_strong=dst / GOLD_STRONG_FNAME,
        new_rows=new_rows,
    )

    # --- 9. Metadata + README ---
    log.info("Writing dataset metadata + README...")
    n_new_border = sum(1 for r in new_rows if r["triage_label"] == "borderline")
    n_new_noise  = sum(1 for r in new_rows if r["triage_label"] == "noise")
    write_metadata_and_readme(
        dst,
        n_v1=n_v1,
        n_new_borderline=n_new_border,
        n_new_noise=n_new_noise,
        label_counts=label_counts,
        n_multi_incident_clusters=n_multi,
        source_global_id=src.name,
    )

    # --- 10. Print summary ---
    print()
    print("=" * 72)
    print(" Phase B WoL v2 build complete")
    print("=" * 72)
    print(f"  Output:       {dst}")
    print(f"  v1 rows:      {n_v1}")
    print(f"  + borderline: {n_new_border}")
    print(f"  + noise:      {n_new_noise}")
    print(f"  = total:      {n_v1 + n_new}")
    print()
    print("  Trivial baseline triage_acc (always 'ticket_worthy'):")
    trivial = n_v1 / max(1, n_v1 + n_new)
    print(f"    {trivial:.4f}   (down from 1.000 on v1)")
    print()
    print(f"  Multi-ticket incident clusters: {n_multi}")
    print()
    print("  Next steps (run manually):")
    print("   1. Re-run cascade: scripts/research-lab/run_*_wol_mode3.py")
    print("      (BiEncoder, Hybrid-RRF, KG, LogSeq2Vec, BM25)")
    print("   2. Re-run agent smoke: scripts/agent/smoke_wol.py")
    print("   3. Re-run bootstrap CIs: scripts/agent/bootstrap_predictions.py")
    print("   4. (optional) Re-extract KG over new rows for KG retriever")


def cmd_count_only(args: argparse.Namespace) -> None:
    """Cheap diagnostic — count Mongo capacity per bucket without writing files."""
    cache_root = Path(args.cache_root or "/tmp/wol_v2_count").resolve()
    capacities = harvest_all_buckets(cache_root, overwrite=False)
    print()
    print(f"{'BUCKET':32s} " + " ".join(f"{p[:9]:>9s}" for p in SELF_CONTAINED_PROJECTS_MODE3) + f"  TOTAL")
    print("-" * 130)
    for bname, cap in capacities.items():
        row = " ".join(f"{cap.per_project.get(p, 0):>9d}" for p in SELF_CONTAINED_PROJECTS_MODE3)
        print(f"{bname:32s} {row}  {cap.total():>6d}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_aug = sub.add_parser("augment", help="Build the v2 augmented dataset")
    p_aug.add_argument("--source-global-dir", required=True,
                       help="v1 dataset path (e.g. data/derived/global/2026-06-11-wol-real-global)")
    p_aug.add_argument("--out-global-dir",    required=True,
                       help="v2 output dataset path (will be created)")
    p_aug.add_argument("--cache-root", default=None,
                       help="Per-bucket Mongo cache (default: <out>/.pool_cache/)")
    p_aug.add_argument("--target-borderline", type=int, default=DEFAULT_TARGET_BORDERLINE)
    p_aug.add_argument("--target-noise",      type=int, default=DEFAULT_TARGET_NOISE_PLUS_REGULAR)
    p_aug.add_argument("--seed", type=int, default=42)
    p_aug.add_argument("--cluster-duplicates", action="store_true", default=True)
    p_aug.add_argument("--no-cluster-duplicates", dest="cluster_duplicates", action="store_false")
    p_aug.set_defaults(func=cmd_augment)

    p_count = sub.add_parser("count-only", help="Print Mongo bucket capacities; no writes")
    p_count.add_argument("--cache-root", default=None)
    p_count.set_defaults(func=cmd_count_only)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
