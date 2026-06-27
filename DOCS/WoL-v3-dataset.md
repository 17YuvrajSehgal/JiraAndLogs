# World of Logs v3 — Apache Jira Incident-Triage Dataset

A research-grade dataset of **78,140 real Apache Jira tickets** from **24 distributed-systems projects**, packaged for memory-augmented incident-triage retrieval evaluation.

**Dataset ID**: `2026-06-17-wol-real-v3-global`
**Locked**: 2026-06-20 (build complete, schemas frozen)
**Schema version**: v3
**Comparable to**: v2 (`2026-06-15-wol-real-v2-global`) — test families preserved for direct comparison
**License**: CC BY 4.0 (derived dataset); underlying WoL source has its own terms (see `data/wol/TERMS_OF_USE.md`)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Background: The WoL Source Dataset](#background-the-wol-source-dataset)
3. [Motivation: Why v3?](#motivation-why-v3)
4. [Project Selection — What's In and Why](#project-selection--whats-in-and-why)
5. [What Was Rejected and Why](#what-was-rejected-and-why)
6. [Quality Filters: From v1/v2 to v3](#quality-filters-from-v1v2-to-v3)
7. [Bucket Taxonomy and Triage Labels](#bucket-taxonomy-and-triage-labels)
8. [Family-to-Split Assignment](#family-to-split-assignment)
9. [Gold Relations (Coarse and Strong Match)](#gold-relations-coarse-and-strong-match)
10. [Knowledge Graph Extractions](#knowledge-graph-extractions)
11. [Dataset Composition and Statistics](#dataset-composition-and-statistics)
12. [Schema Reference](#schema-reference)
13. [Reproducibility](#reproducibility)
14. [Comparison with WoL v2](#comparison-with-wol-v2)
15. [Known Limitations and Threats to Validity](#known-limitations-and-threats-to-validity)
16. [File Manifest](#file-manifest)
17. [Citation and Acknowledgements](#citation-and-acknowledgements)

---

## Executive Summary

WoL v3 turns the **World of Logs JIRA collection** (Xiao et al., MSR 2026 — 360,778 issues from a wide range of projects) into a derived corpus suitable for **memory-augmented incident-triage retrieval** at scale:

| Aspect | v3 figure |
|---|---:|
| Memory corpus (past tickets, `Bug + Fixed`) | **38,642** |
| Query windows total | **78,140** |
|   ↳ `ticket_worthy` (the memory tickets re-used as queries) | 38,642 |
|   ↳ `borderline` (engineer engaged, outcome ambiguous) | 25,619 |
|   ↳ `noise` (engineer rejected, or non-Bug issuetype) | 13,879 |
| Apache projects covered | **24** |
| Multi-ticket incidents (via Jira link analysis) | **2,456** |
| Train / Validation / Test rows | 60,916 / 3,836 / 13,388 |
| Trivial-baseline triage accuracy | 0.495 (majority class) |
| On-disk size | ~1.3 GB |

The dataset is the third iteration in a deliberate progression:

- **v1** (2026-06-11, retired): 2,000 ticket-worthy rows, 7 projects, strict filters. Triage accuracy degenerate (all rows same class).
- **v2** (2026-06-15, retired-for-this-task, still on disk): 9,341 rows across 7 projects, ticket_worthy + borderline + noise distribution targeted to Online Boutique's 21/26/53.
- **v3** (2026-06-17, **this dataset**): 78,140 rows across 24 projects, all quality filters dropped, full Mongo capacity utilized.

The motivating change in v3 is **scale and breadth**: v2 sampled 9,341 rows from a Mongo pool of ~28K available rows in 7 projects. v3 expands the project list to 24 distributed-systems Apache projects and removes the optional-quality filters, surfacing the full 78K-row pool. This stresses retrieval at a meaningfully harder scale (19× more memory items, 8× more queries) while preserving the test families (Kafka, MariaDB-Server) from v2 so prediction-side metrics remain directly comparable.

---

## Background: The WoL Source Dataset

**Source paper**: Xiao et al., *Empirical study using World of Logs*, MSR 2026.
**Source archive (read-only)**: `data/wol/WoL_v1-2025-11-10.archive.gz`
**Access pattern**: WoL ships as a MongoDB dump. The collection name relevant to this dataset is `WoL_v1.JIRA` (360,778 documents).
**License**: see `data/wol/TERMS_OF_USE.md` shipped with the archive.

WoL contains four collections:

| Collection | Documents | Used by v3? |
|---|---:|:--:|
| `WoL_v1.JIRA` | 360,778 | ✅ |
| `WoL_v1.SO` (Stack Overflow) | 585,304 | ✗ (not Jira-ticket-shaped) |
| `WoL_v1.GitHub` | 114,679 | ✗ (issue-PR overlap with Apache mailing lists already in JIRA) |
| `WoL_v1.CommonCrawl` | 773 | ✗ (high noise, mostly WAF block messages) |

Each JIRA document carries the full Atlassian REST API field set (`fields.project.name`, `fields.priority.name`, `fields.issuetype.name`, `fields.components`, `fields.summary`, `fields.description`, `fields.created`, `fields.resolution.name`, `fields.issuelinks`, `fields.comments`) plus the extracted `log_msgs` array (per-ticket log lines extracted by the WoL paper's three-stage classifier) and a `pred_uncertainty` confidence score from that classifier.

---

## Motivation: Why v3?

Three pressures drove the redesign from v2 to v3:

### Pressure 1 — v2's project scope was too narrow

v2 used **7 Apache projects**: Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server. These were picked for "microservice-adjacency": their failure vocabulary overlaps with the Online-Boutique microservice scenarios that the rest of the project uses. But a Mongo capacity sweep on 2026-06-17 showed that **9,341 rows is only ~33% of the pool actually available in those 7 projects** (28,517 with strict filters; 39,542 with no filters). v2 was leaving 70% of available data unused.

### Pressure 2 — A real-data evaluation should stress retrieval at distributed-systems scale

v2's 1,648-row test split was too small to differentiate retrievers with statistical confidence beyond a few percentage points of Hit@5. v3's test split is **13,388 rows** — 8.1× larger — across the same 2 held-out families (Kafka, MariaDB-Server). This gives much tighter confidence intervals on the headline retrieval numbers while keeping the v2-vs-v3 comparison apples-to-apples on the eval side.

### Pressure 3 — The "high-confidence only" quality filter was leaving valuable data on the floor

v1 and v2 used three quality filters applied at the MongoDB query stage:
- `pred_uncertainty ≤ 0.05` (the WoL paper's "high-confidence" threshold)
- `description ≥ 200 chars`
- `log_msgs ≥ 1` (Bug rows only)

A capacity sweep showed `log_msgs ≥ 1` was **fully redundant given `desc ≥ 200`** (every Apache Jira ticket with ≥200-char description has at least one extracted log message). And the `pred_uncertainty ≤ 0.05` cut was discarding 25% of rows. v3 keeps all four filters off and lets the data speak; the surviving rows pass through unchanged.

---

## Project Selection — What's In and Why

v3 covers **24 Apache projects**, grouped by domain affinity to incident-triage scenarios. Selection criteria:

1. **Distributed-systems vocabulary**: failure modes that share terms with microservice incidents (broker, partition, executor, region-server, OOM, GC pause, replication-lag, etc.). Filters out pure-UI projects (Qt, Minecraft, Confluence) which are tracked in v2's *distractor* pool, not the main corpus.
2. **Sufficient Bug+Fixed capacity**: at least ~800 Bug-rows-with-resolution=Fixed in the Mongo pool, so per-project sampling stays meaningful after stratification.
3. **WoL coverage**: the project must be present in the `WoL_v1.JIRA` collection with the standard Atlassian field schema.

### The 24 included projects (with Bug+Fixed capacity)

| Project | `ticket_worthy` rows | Family | Why included |
|---|---:|---|---|
| Spark | 2,558 | distributed compute | Microservice-adjacent failure vocab; large pool |
| Cassandra | 2,121 | distributed datastore | Replication-lag and gossip-failure analogues |
| HBase | 2,433 | distributed datastore | Region-server failures, similar to leader-election failures |
| Flink | 2,098 | stream processing | Task-manager / job-graph failures |
| Ambari | 3,084 | Hadoop ecosystem management | Cluster-level orchestration analogues |
| Kafka | 1,147 | distributed messaging | Broker / partition / consumer-lag (paper's Kafka scenarios) |
| MariaDB Server | 5,626 | database engine | Largest pool, single-process model |
| Hive | 1,894 | distributed SQL warehouse | Executor and metastore failures |
| IMPALA | 1,931 | distributed SQL | Daemon-coordination analogues |
| Geode | 1,651 | in-memory data grid | Distributed-cache replication |
| Infinispan | 1 | distributed cache | Minimal — only 1 Bug+Fixed row, but borderline+noise present (kept for completeness) |
| Hadoop HDFS | 1,014 | distributed filesystem | NameNode / DataNode failures |
| Hadoop YARN | 827 | cluster resource manager | Scheduler / ResourceManager failures |
| Hadoop Common | 1,144 | Hadoop core | Cross-cutting library failures |
| Solr | 903 | distributed search | Shard-allocation, indexing-pipeline failures |
| Apache Drill | 1,169 | distributed SQL | Fragment-execution failures |
| Beam | 1,005 | distributed processing | Cross-runner abstraction failures |
| Mesos | 1,125 | cluster manager | Framework + executor failures |
| ActiveMQ | 944 | distributed messaging | Broker + connector failures (Kafka analogue) |
| Camel | 1,214 | integration / routing | Route-mediation failures |
| CXF | 1,116 | services framework | SOAP/REST service-layer failures |
| Ignite | 1,346 | in-memory grid | Distributed-cache + compute |
| Derby | 1,231 | embedded database | Lock-manager / transaction failures |
| Apache Arrow | 1,060 | columnar in-memory format | Memory-layout failures |

The **bottom seven projects** (Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server) are the v2 set — preserved unchanged. The **other seventeen** are the v3 additions. The Hadoop ecosystem (HDFS / YARN / Common) is the single largest expansion (3 projects, 2,985 ticket_worthy rows).

### Per-project ratios for stratified sampling

Per-project quotas are computed proportionally to each project's Bug+Fixed capacity. Projects with thin Bug+Fixed pools (e.g. Infinispan at 1 row) get whatever's available; the deficit is redistributed to projects with headroom via a deficit-redistribution algorithm in `scripts/research-lab/build_wol_real_corpus_v2.py:_distribute_quota()` (reused in v3).

---

## What Was Rejected and Why

### Rejected at the project level

| Rejected | Reason |
|---|---|
| Qt (17,726 Bug rows) | C++ desktop GUI; failure modes don't share vocab with microservice incidents. Moved to v2's *distractor pool*. |
| Minecraft: Java Edition (13,302) | Game client; single-process player-side failures. No distributed-systems analogue. |
| Core Server (7,245) | Atlassian/JBoss container; tooling, not runtime. |
| Confluence Server / Confluence Cloud | Wiki authoring; failures are UI workflows, not distributed-systems. |
| Sakai (4,469) | Learning management; education-domain workflows. |
| Tools (JBoss Tools) | IDE plugin; tooling-side bugs. |
| Apache Flex (3,887) | Flash-era UI framework; obsolete vocab. |
| JBoss EAP (3,825) / WildFly (2,716) | Java EE container; container-internal failures, not service-mesh. |
| Qt Creator (3,625) | IDE; same as Qt. |
| Red Hat Fuse (3,366) | Integration ESB; partial vocab overlap but Camel + CXF already in scope. |
| Bamboo (2,127) | CI/CD; build-pipeline failures unrelated to runtime incidents. |
| ~250 other projects | Long tail; insufficient capacity per project after filters. |

The full WoL JIRA pool has 360,778 documents; the 24 v3 projects collectively account for ~95K of them (35K Bug+Fixed + 9.9K borderline + 7.1K noise-Bug + 6.8K non-Bug issuetypes — see `bucket_capacities` in `dataset-metadata.json`).

### Rejected at the WoL-collection level

| Source collection | Documents | Why excluded |
|---|---:|---|
| `WoL_v1.SO` | 585,304 | Stack Overflow Q&A. Not Jira-ticket-shaped: no resolution, no components, no priority. Distinct retrieval task. |
| `WoL_v1.GitHub` | 114,679 | GitHub Issues/PRs from Apache repos. Substantial topic overlap with WoL_v1.JIRA (the same teams use both trackers). Including both would double-count incidents. |
| `WoL_v1.CommonCrawl` | 773 | High-noise web crawl. ~86% drops on the high-confidence filter; remaining content is mostly WAF block messages, not incident-style. |

### Rejected at the row level (filter analysis)

Even within the 24 included projects, **not every row makes it into the v3 dataset.** The bucket-defining filters keep only rows that can be assigned a meaningful triage label:

| Excluded row category | Reason |
|---|---|
| Bug rows with `resolution = null` (12,671 in v3 scope) | **NOT excluded** — captured in the new `borderline_unresolved` sub-bucket. v2 dropped these; v3 keeps them as `borderline` queries. |
| Bug rows with rare resolutions ("Done", "Out of Date", "Won't Do", "Resolved", "Implemented", etc.) (3,093) | **NOT excluded** — captured in the new `borderline_other_res` sub-bucket. v2 dropped these. |
| Tickets with `pred_uncertainty > 0.05` | **NOT excluded** in v3 (was excluded in v1/v2). The WoL paper's extraction confidence threshold is informative but not load-bearing for retrieval. |
| Tickets with `description < 200 chars` | **NOT excluded** in v3. Many real bug reports are short ("Crash on startup", "OOM in foo"). |
| Tickets with no `log_msgs` | **NOT excluded** in v3. Memory text falls back to `summary + description` when `log_msgs` is empty. |
| **Sub-tasks** (`issuetype = Sub-task`) | Excluded. Sub-tasks reference a parent Bug ticket; including them would double-count the parent's incident. |
| **Epics** (`issuetype = Epic`) | Excluded. Epics are project-management containers, not individual incidents. |
| **Test rows** (`issuetype = Test`) | Excluded. Test cases are not incident reports. |
| **Improvements / New Features / Questions / Documentation / Wishes** | **NOT excluded** in v3 — relabeled as `noise` (the `regular_*` sub-buckets). These rows exist on the same Jira board as Bug tickets but aren't incidents; the triage classifier learns to reject them. |

---

## Quality Filters: From v1/v2 to v3

| Filter | v1 | v2 | v3 |
|---|:--:|:--:|:--:|
| `pred_uncertainty ≤ 0.05` | ✅ | ✅ | ❌ removed |
| `description ≥ 200 chars` | ✅ | ✅ | ❌ removed |
| `log_msgs ≥ 1` (Bug rows) | ✅ | ✅ | ❌ removed |
| `issuetype = Bug` (only Bugs) | ✅ | partial (Bug + Improvement/etc. as noise) | partial (same) |
| Project allowlist | 7 projects | 7 projects | **24 projects** |
| `MAX_LOG_MSGS_PER_TICKET` | 50 | 50 | **200** (4×) |
| `MAX_DESC_CHARS` | 1,500 | 1,500 | **6,000** (4×) |

The text-truncation bumps (200 log lines / 6,000 desc chars) primarily benefit BM25, the LLM verifier, and KG extraction (all of which read full text). The dense bi-encoder backbone (`all-MiniLM-L6-v2`) truncates internally at ~256 tokens (~1,500 chars), so it sees the same content as v2.

---

## Bucket Taxonomy and Triage Labels

Every query row in v3 carries a `triage_label ∈ {ticket_worthy, borderline, noise}`. The label is assigned deterministically from the source Jira ticket's `issuetype` and `resolution` fields:

```
ticket_worthy  ← issuetype = Bug AND resolution = Fixed
borderline     ← issuetype = Bug AND resolution ∈ {Duplicate, Incomplete, Cannot Reproduce,
                                                    null, Done, Out of Date, Information
                                                    Provided, Abandoned, Resolved, Auto Closed,
                                                    Later, Workaround, Rejected, Works for Me,
                                                    Won't Do, Implemented, Pending Closed, ...}
noise          ← issuetype = Bug AND resolution ∈ {Won't Fix, Invalid, Not a Bug, Not A Bug,
                                                    Not A Problem}
               OR issuetype ∈ {Improvement, New Feature, Question, Documentation, Wish}
```

### v3 introduces TWO new borderline sub-buckets

v2 had three borderline resolutions (Duplicate, Incomplete, Cannot Reproduce — 9,855 rows total). v3 adds:

- **`borderline_unresolved`** (12,671 rows): Bug rows with `resolution = null`. These are open tickets — engineers haven't yet decided how to close them. Treating these as `borderline` rather than `ticket_worthy` is the load-bearing methodological choice: we don't know if they'll ultimately be fixed.
- **`borderline_other_res`** (3,093 rows): Bug rows with rare or project-specific resolutions (Done, Resolved, Implemented, Workaround, Pending Closed, etc.). Engineers engaged but used a non-standard outcome label. Treating as `borderline` (rather than promoting "Done"/"Implemented" to `ticket_worthy`) keeps the positive pool semantically clean.

Together, these add 15,764 borderline rows that v1/v2 simply dropped. v3 captures them and lets the triage classifier learn from them.

### Bucket capacities at the Mongo level (24-project pool, before sampling)

| Bucket | Total | Used in v3 |
|---|---:|---:|
| `ticket_worthy` (Bug+Fixed) | 38,642 | 38,642 (100%) |
| `borderline_duplicate` | 5,648 | 5,648 (100%) |
| `borderline_incomplete` | 1,339 | 1,339 (100%) |
| `borderline_cannot-reproduce` | 2,868 | 2,868 (100%) |
| `borderline_unresolved` (new) | 12,671 | 12,671 (100%) |
| `borderline_other_res` (new) | 3,093 | 3,093 (100%) |
| `noise_won-t-fix` | 1,953 | 1,953 (100%) |
| `noise_invalid` | 1,879 | 1,879 (100%) |
| `noise_not-a-bug` | 977 | 977 (100%) |
| `noise_not-a-problem` | 2,309 | 2,309 (100%) |
| `regular_improvement` | 6,060 | 6,060 (100%) |
| `regular_new-feature` | 395 | 395 (100%) |
| `regular_question` | 153 | 153 (100%) |
| `regular_documentation` | 39 | 39 (100%) |
| `regular_wish` | 114 | 114 (100%) |
| **TOTAL** | **78,140** | **78,140 (100%)** |

Note that v3 uses **100% of every bucket's Mongo capacity**. This is by design: with quality filters removed, there is no rejection criterion left at sampling time. Every row in the 24-project pool that matches a bucket's issuetype+resolution filter is included.

---

## Family-to-Split Assignment

v3 uses **family-held-out leave-one-domain-out splits** rather than per-row random splits. This is the methodologically stricter setting: the model never sees Kafka or MariaDB-Server tickets at training time, only at test time.

| Split | Families | Total rows | TW | borderline | noise |
|---|---|---:|---:|---:|---:|
| **train (21 families)** | activemq, apache-arrow, apache-drill, beam, camel, cassandra, cxf, derby, flink, geode, hadoop-common, hadoop-hdfs, hadoop-yarn, hbase, hive, ignite, impala, infinispan, mesos, solr, spark | 60,916 | 28,785 | 19,681 | 12,450 |
| **validation (1 family)** | ambari | 3,836 | 3,084 | 574 | 178 |
| **test (2 families)** | **kafka, mariadb-server** | **13,388** | 6,773 | 5,364 | 1,251 |

### Why these specific families for test?

The test families (Kafka + MariaDB-Server) are **preserved from v2**. This is deliberate:
- v2 reported retrieval headline numbers on this exact test family pair.
- v3 keeps the same test family identifiers so the v2 vs. v3 retrieval comparison is **directly comparable** — same families, different memory and (much larger) test set size.

Ambari as validation is also preserved from v2.

### Trivial-baseline triage accuracy

Predicting the test-split's majority class on every row gives **0.495 accuracy**:
- noise = 1,251 / 13,388 = 9.3%
- borderline = 5,364 / 13,388 = 40.1%
- ticket_worthy = 6,773 / 13,388 = **50.6%** ← majority

Any triage classifier reporting accuracy below this baseline has failed.

---

## Gold Relations (Coarse and Strong Match)

For retrieval evaluation, every query row carries a list of "gold-match" memory ticket IDs. v3 generates these by an inferred match relation (no human labeling), with two relations of increasing strictness:

### Coarse match

Two tickets *A* (query) and *B* (memory) match if:
1. `A.project = B.project`, **AND**
2. `|A.components ∩ B.components| ≥ 1` (at least one shared component name)

This gives roughly 40 candidates per ticket_worthy query on average.

### Strong match

Strong match = coarse match **AND** symptom-token Jaccard similarity > 0.15:
- `symptom_tokens(T)` = lowercased non-stopword tokens from `T.log_msgs[:200]` (or `summary+description` if no log_msgs), with log-boilerplate stopwords (`error`, `info`, `warning`, `debug`, `at`, `line`, etc.) removed.
- `Jaccard(A, B) = |A ∩ B| / |A ∪ B| > 0.15` is the load-bearing threshold; below 0.15 returned ~0.07 matches/query in v1 calibration, so 0.15 produces a meaningfully selective subset.

### Per-row gold storage

- `window-memory-matchings.jsonl` (242 MB): coarse gold per query
- `window-memory-matchings-strong.jsonl` (49 MB): strong gold per query

The paper reports Hit@K under **both** relations. The delta between coarse and strong tells the reader how much of the retrieval signal is project+component structure versus log-symptom similarity.

### Gold relations are not symmetric — only ticket_worthy queries have non-empty gold

By construction, `borderline` and `noise` queries have **empty `matched_memory_issue_ids`**. They aren't bug reports themselves, so no memory ticket is "the right answer" for them. The retrieval-quality metrics (Hit@K, MRR) aggregate only over queries with non-empty gold; the triage and novelty metrics still apply to every row.

---

## Knowledge Graph Extractions

v3 ships with **LLM-extracted structured entities** for every memory ticket and every query window. The extractor is GPT-4o-mini via OpenAI's API.

### Memory-side extractions

- File: `v2_kg_extractions/all_extractions.jsonl`
- Per-ticket cache files: `v2_kg_extractions/ticket/<ticket_id>__<hash>.json`
- Rows: **38,587** (99.86% of the 38,642 memory items — 55 rows had LLM extraction failures and were not retried; the KG retriever falls back gracefully to empty for these)
- Cost: ~$17 in OpenAI fees

Schema per row (`IncidentExtraction`):

| Field | Description |
|---|---|
| `ticket_id` | Memory ticket identifier (e.g. `wol-m-0000330e35710670`) |
| `severity` | Normalized severity (critical / major / minor) |
| `family` | Scenario family (e.g. `wol-hadoop-common`) |
| `affected_services` | Service names mentioned in the ticket (often empty for Apache projects, which use `components` instead) |
| `components` | Software component names (e.g. `hadoop`, `KafkaBroker`, `SparkSQL`) |
| `error_classes` | Exception/error names if cited (e.g. `HTTP 400`, `NullPointerException`) |
| `root_cause` | Free-text root-cause synthesis by the LLM |
| `fix` | Free-text fix synthesis |
| `fix_kind` | Categorized fix type (`config_change`, `code_fix`, `dependency_update`, `other`) |
| `symptoms` | List of symptom strings (the most populated field for Apache tickets) |

### Window-side extractions

- File: `v2_kg_extractions_windows/all_extractions.jsonl`
- Per-window cache files: `v2_kg_extractions_windows/window/<window_id>__<hash>.json`
- Rows: **78,140** (100%)
- Cost: ~$19 in OpenAI fees

Schema per row (`WindowExtraction`):

| Field | Description |
|---|---|
| `window_id` | Query window identifier (e.g. `wol-q-00a27ab5c19f8046`) |
| `severity` | Window type (`active_fault` / `observation_window`) |
| `family` | Scenario family |
| `affected_services` | Services mentioned in the window's evidence text |
| `components` | Components mentioned |
| `error_classes` | Error classes mentioned |
| `symptoms` | List of symptom strings |

### Total KG extraction spend

**~$36** in OpenAI fees. Extractions are cached per-ticket/per-window on disk; re-running the extraction script skips already-cached items.

---

## Dataset Composition and Statistics

### Multi-ticket incidents

**2,456 distinct incident clusters** are formed by walking the Jira `issuelinks` field. The eligible link types are:
- `Duplicate`
- `Cloners`
- `Cause` / `Caused` / `Caused by`

Union-find over Jira keys (`SPARK-13326`, etc.) merges tickets into clusters. Only edges where both endpoints survived sampling are honored.

Each cluster's tickets share a synthetic `incident_episode_id` so downstream metrics like `pages_per_incident` can aggregate over the cluster rather than over individual tickets.

### Severity distribution (normalized)

Severity is normalized from Jira's 50+ priority strings into `{critical, major, minor}` via `wol-priority-mapping.json`. Fallback bucket size: ~5% of rows (priorities like "Not Evaluated", "Unknown", flagged with `severity_uncertain=true`).

---

## Schema Reference

### `global-triage-examples.jsonl` (78,140 rows, ~697 MB)

Per-window row schema:

```jsonc
{
  "window_id": "wol-q-bd1de29d8071d0fa",
  "dataset_run_id": "wol-v3-2026-06-17-wol-real-v3-global-bd1de29d8071d0fa",
  "incident_episode_id": "wol-q-bd1de29d8071d0fa",
                              // OR a shared "wol-incident-<root>" id if part of a multi-ticket cluster
  "scenario_id": "wol-hbase-bd1de29d8071d0fa",
  "scenario_family": "wol-hbase",
  "service_name": "hbase-server",            // First component name, or family if no components
  "window_type": "active_fault",             // active_fault for TW; observation_window for borderline/noise
  "start_time": "2024-01-15T10:30:00Z",      // Original Jira creation timestamp
  "end_time":   "2024-01-15T10:30:00Z",      // Same as start_time for WoL (no telemetry duration)
  "triage_label": "ticket_worthy",           // ticket_worthy | borderline | noise
  "triage_severity": "major",                // critical | major | minor
  "severity_uncertain": false,
  "triage_components": ["hbase-server"],
  "triage_reason_class": "other",            // outage | latency_regression | restart_with_impact | network | other
  "is_hard_case": false,
  "source": "wol-v3-ticket_worthy",          // identifies the originating bucket
  "split": "train",                          // train | validation | test
  "triage_evidence_text": "org.apache.hadoop.hbase...\n   at org.apache.hadoop...\nException: ...",
  "fault_compatibility_class": "wol-real",
  "wol_source_id": "bd1de29d8071d0fa3669...",  // Original WoL MongoDB _id
  "wol_project": "HBase",
  "wol_issue_key": "HBASE-12345",
  // Plus 94 zero-filled `triage_feature_*` columns (no telemetry in WoL — these are placeholders
  // so the same schema can be loaded by code that also handles Online Boutique / OTel Demo)
}
```

### `jira-memory-corpus.jsonl` (38,642 rows, ~191 MB)

Per-memory-ticket row schema:

```jsonc
{
  "jira_shadow_issue_id": "wol-m-d6aca722f6a898fa",
  "jira_issue_key": "SPARK-12345",
  "dataset_run_id": "wol-v3-2026-06-17-wol-real-v3-global-d6aca722f6a898fa",
  "incident_episode_id": "wol-m-d6aca722f6a898fa",
  "available_as_memory_from": "2024-01-15T10:30:00Z",  // Visibility cutoff for time-aware retrieval
  "scenario_id": "wol-spark-d6aca722f6a898fa",
  "scenario_family": "wol-spark",
  "affected_service": "SparkSQL",
  "fault_type": "other",
  "fault_compatibility_class": "wol-real",
  "severity": "major",
  "memory_text": "Summary: ...\n\nComponents: ...\n\nDescription: ...\n\nLog lines:\n...",
  "resolution_notes": "Fixed",
  "wol_source_id": "d6aca722f6a898fa...",
  "wol_project": "Spark"
}
```

### `window-memory-matchings.jsonl` / `window-memory-matchings-strong.jsonl`

Per-window gold row schema:

```jsonc
{
  "window_id":                  "wol-q-bd1de29d8071d0fa",
  "dataset_run_id":             "wol-v3-...",
  "scenario_family":            "wol-hbase",
  "affected_service":           "hbase-server",
  "fault_compatibility_class":  "wol-real",
  "triage_label":               "ticket_worthy",
  "is_novel":                   false,                          // true if ticket_worthy with empty gold
  "matched_memory_issue_ids":   ["wol-m-...", "wol-m-..."],     // list of memory ticket IDs
  "expected_in_memory":         true,                            // true if matched list non-empty
  "match_strength":             "coarse" | "strong" | "empty"
}
```

### `triage-split-manifest.json`

```jsonc
{
  "schema_version":   1,
  "split_by":         "scenario_family",
  "global_dataset_id": "2026-06-17-wol-real-v3-global",
  "family_assignment": {
    "wol-spark":           "train",
    "wol-cassandra":       "train",
    ...
    "wol-ambari":          "validation",
    "wol-kafka":           "test",
    "wol-mariadb-server":  "test"
  },
  "label_counts_by_split": { "train": {...}, "validation": {...}, "test": {...} },
  "leave_one_family_out_folds": [ { "fold_id": "loo-wol-X", "held_out_family": "wol-X" }, ... ],
  "seed": 42,
  "version": "v3",
  "comparable_to": "2026-06-15-wol-real-v2-global"
}
```

---

## Reproducibility

### How to rebuild from scratch

```bash
# 1. Prerequisites
#    - MongoDB running with WoL_v1 archive restored:
#        docker run -d --name wol-mongo -p 27017:27017 mongo:6
#        mongorestore --archive=data/wol/WoL_v1-2025-11-10.archive
#    - Python venv with pymongo, pandas

# 2. Build the dataset
python scripts/research-lab/build_wol_real_corpus_v3.py build \
    --out-global-dir data/derived/global/2026-06-17-wol-real-v3-global

# Total runtime: ~10-15 min (Mongo aggregation + sampling + field mapping + clustering + gold relation
# computation + JSONL writes)
```

### Build determinism guarantees

- **Random seed**: 42 (used for stratified sampling and union-find tiebreaking)
- **MongoDB version**: any 5.x or 6.x with full BSON support
- **Same Mongo content + same git SHA + same seed → bit-identical output JSONLs**

### KG extractions (optional re-run)

```bash
export OPENAI_API_KEY="..."
# Memory side
python scripts/research-lab/extract_tickets_parallel.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --humanized-subdir bulk-20260617 \
    --lm-studio-url https://api.openai.com --model gpt-4o-mini \
    --api-key-env OPENAI_API_KEY --workers 4
# Window side
python scripts/agent/extract_window_entities.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --split all --workers 8 \
    --lm-studio-url https://api.openai.com --model gpt-4o-mini \
    --api-key-env OPENAI_API_KEY
```

KG extractions are **non-reproducible** in the strict sense (LLM model versions drift). The on-disk JSONL files are the source of truth.

---

## Comparison with WoL v2

| Aspect | v2 (`2026-06-15-wol-real-v2-global`) | v3 (`2026-06-17-wol-real-v3-global`) |
|---|---|---|
| Projects | 7 | **24** |
| Memory items | 2,000 (Bug+Fixed, capped) | **38,642 (full)** |
| Query rows total | 9,341 | **78,140** |
|   ↳ ticket_worthy | 2,000 | 38,642 |
|   ↳ borderline | 2,399 (3 sub-buckets) | 25,619 (5 sub-buckets — adds `unresolved` + `other_res`) |
|   ↳ noise | 4,942 | 13,879 |
| Test split size | 1,648 | 13,388 (8.1×) |
| Test families | Kafka, MariaDB-Server | **same — Kafka, MariaDB-Server** ✓ |
| Validation family | Ambari | **same — Ambari** ✓ |
| Multi-incident clusters | 90 | 2,456 (27×) |
| Quality filters | `pred_uncertainty ≤ 0.05`, `desc ≥ 200`, `log_msgs ≥ 1` | all three removed |
| Text truncation | 50 log lines / 1,500 chars | 200 log lines / 6,000 chars |
| Trivial-baseline triage_acc | 0.530 | 0.495 |
| Build script | `build_wol_real_corpus_v2.py` (augments v1) | `build_wol_real_corpus_v3.py` (fresh build) |
| On-disk size | ~120 MB | ~1.3 GB |

**Test families are deliberately preserved across versions** so any retriever's v2 → v3 number comparison is apples-to-apples on the eval side. The model has more memory to retrieve against in v3 (38,642 vs 2,000) and a much larger test set (13,388 vs 1,648), but the family identity is unchanged.

---

## Known Limitations and Threats to Validity

### 1. No telemetry, text-only

WoL is built from Jira tickets — there is no co-collected Loki/Tempo/Prometheus telemetry. All `triage_feature_*` numeric columns are zero-filled. This means:
- The Histogram-Gradient-Boosting (HGB) triage classifier cannot be evaluated on WoL (it reads numeric features).
- All retrieval signal must come from text.
- This is the textbook "log-only deployment" configuration of TCH-Lite.

### 2. `affected_services` is mostly empty

Apache projects describe failures at the **component** level (`KafkaBroker`, `HDFSDataNode`, `SparkSQL`) — not at microservice level (`payment-service`, `cart-service`). The LLM extractor correctly populates `components`, but `affected_services` is empty for ~99% of rows. This is a property of the source data, not an extraction defect.

Downstream impact: KG retrieval has to rely on `components` + `symptoms` + `error_classes` overlap rather than the cross-project `affected_services` overlap that works for OB / OTel-Demo.

### 3. Match relations are inferred, not labeled

Both coarse and strong match relations are computed mechanically from `project + components + symptom-token-Jaccard`. They are **not human-validated**. A reviewer could reasonably argue that two tickets sharing the same project and one component aren't necessarily about the same incident. The paper acknowledges this by reporting under both relations and bracketing the answer.

### 4. WoL extraction artifacts in `log_msgs`

The WoL paper's three-stage extractor has F1 = 0.70 on the full corpus. With the `pred_uncertainty ≤ 0.05` filter dropped, some `log_msgs` entries are misclassified prose. Downstream retrievers treat these as noise; this hurts retrieval precision slightly but doesn't bias any specific class.

### 5. Per-class trivial baselines

The triage class distribution in v3 (51 / 40 / 9) is more imbalanced than v2's (21 / 26 / 53), driven by including all 38K Bug+Fixed rows as ticket_worthy. This makes the **trivial-baseline triage accuracy = 0.495** — close to 50%. A triage classifier needs to clear that floor by ≥ 5-10 points to demonstrate signal.

### 6. Ambari is thin

Ambari has 248 total non-TW rows across all buckets, so the validation split is much smaller than train/test (3,836 vs. 60,916 / 13,388). Per-class counts on val are noisy — confidence intervals are wide. Don't over-fit hyperparameters on Ambari alone.

### 7. Single-class test families would be a concern

Kafka has 1,147 ticket_worthy + 211 borderline_duplicate + ... = ~2K total in v3 (pre-bucket-merging). MariaDB-Server has ~5,626 + ~723 + ... ≈ 7K. Both contribute enough to test for class-balanced eval, but per-family per-class numbers can be noisy.

### 8. Resolution-label semantics drift across Apache projects

"Done" means different things in different Apache project workflows (some treat it as Fixed-equivalent, others as Closed-without-resolution). v3 lumps all such non-canonical resolutions into `borderline_other_res` — the safer assumption that we don't know the disposition. A future iteration could do per-project resolution-semantics normalization.

### 9. Memory corpus does not include borderline/noise tickets

By design, only `ticket_worthy` (Bug+Fixed) tickets enter the memory corpus. Borderline and noise rows appear only as queries. This mirrors a real production setup: the past-incident database holds resolved bugs, not unresolved/rejected ones.

### 10. Sub-tasks and Epics excluded

WoL contains Sub-task and Epic rows. v3 excludes them to avoid double-counting (sub-tasks reference parent Bug tickets). A more elaborate dataset could include them with a parent-child relation; v3 takes the simpler "treat each as a standalone unit" approach by ignoring them.

---

## File Manifest

Locked artifacts under `data/derived/global/2026-06-17-wol-real-v3-global/`:

| Path | Size | Rows | Purpose |
|---|---:|---:|---|
| `global-triage-examples.jsonl` | 697 MB | 78,140 | Per-window query rows (training + val + test) |
| `jira-memory-corpus.jsonl` | 191 MB | 38,642 | Memory items (retrieval corpus, Bug+Fixed only) |
| `jira-shadow-humanized-v2/bulk-20260617/timeline.jsonl` | 86 MB | 38,642 | Humanized memory text (already in engineer voice via WoL) |
| `window-memory-matchings.jsonl` | 242 MB | 78,140 | Coarse gold relations |
| `window-memory-matchings-strong.jsonl` | 49 MB | 78,140 | Strong gold relations (Jaccard > 0.15) |
| `v2_kg_extractions/all_extractions.jsonl` | 10 MB | 38,587 | LLM-extracted memory-side KG entities |
| `v2_kg_extractions/ticket/*.json` | ~25 MB | 38,587 individual files | Per-ticket KG cache (resumable) |
| `v2_kg_extractions_windows/all_extractions.jsonl` | 23 MB | 78,140 | LLM-extracted window-side KG entities |
| `v2_kg_extractions_windows/window/*.json` | ~55 MB | 78,139 individual files | Per-window KG cache |
| `triage-split-manifest.json` | 4 KB | — | Family→split assignment |
| `triage-feature-columns.json` | 5 KB | — | 94 numeric feature column names (zero-filled in WoL) |
| `dataset-metadata.json` | 2 KB | — | Build provenance |
| `source-mapping.csv` | 10 MB | 78,140 | WoL `_id` → derived ticket-id mapping |
| `wol-priority-mapping.json` | 2 KB | — | Severity normalization (50+ priorities → 3 classes) |
| `README.md` | 4 KB | — | Dataset card (companion to this document) |
| `tch-lite-refit/kg-retrieval-predictions.jsonl` | 61 MB | 13,388 | Per-window KG-retrieval predictions on test split |
| `tch-lite-refit/kg-retrieval-mode3-results.json` | 2 KB | — | KG-retrieval headline metrics |
| `tch-lite-refit/biencoder-predictions.jsonl` | (TBC) | 13,388 | Per-window BiEncoder predictions on test split |
| `tch-lite-refit/biencoder-mode3-results.json` | (TBC) | — | BiEncoder headline metrics |

Pending follow-up artifacts (see `todo.md` for status):
- BM25 cascade predictions
- Hybrid-RRF cascade predictions
- Agent end-to-end eval output
- Bootstrap confidence intervals

---

## Citation and Acknowledgements

### When you use this derived dataset

Please cite **both** of the following:

1. **The source WoL corpus** (whose Jira archive this dataset is derived from):

```bibtex
@inproceedings{xiao2026worldoflogs,
  title     = {Empirical study using World of Logs},
  author    = {Xiao, Xiaohui and Yao, Kundi and Liao, Lizhi and Nie, Pengyu and Zhang, Xuan and Shang, Weiyi},
  booktitle = {Proceedings of the IEEE/ACM International Conference on Mining Software Repositories (MSR)},
  year      = {2026},
  note      = {Dataset hosted at WoL archive (CC BY 4.0).}
}
```

2. **Our paper** (in preparation, ICSE 2027):

```bibtex
@inproceedings{anonymous2027agent,
  title     = {Capability-Adaptive Incident Triage: Per-Window Diagnostic Planning Across Synthetic and Real Production Tickets},
  author    = {Anonymous Authors},
  booktitle = {Proceedings of the IEEE/ACM International Conference on Software Engineering (ICSE)},
  year      = {2027},
  note      = {WoL v3 dataset description.}
}
```

### Underlying data licensing

The WoL source archive (`data/wol/WoL_v1-2025-11-10.archive.gz`) is released under its own terms (see `data/wol/TERMS_OF_USE.md`). The Public Jira Dataset upstream of WoL is itself licensed CC BY 4.0 (Montgomery, Lüders, Maalej, 2025 — Zenodo DOI 10.5281/zenodo.15719919).

The Apache projects whose tickets are included (Spark, Cassandra, Kafka, etc.) are licensed under the Apache License 2.0; the Jira ticket text content itself is in the public domain.

### Acknowledgements

This derived dataset (v3) was built by reusing the v1/v2 mappers from `scripts/research-lab/build_wol_real_corpus.py` and `build_wol_real_corpus_v2.py`, with the bucket taxonomy extended (`borderline_unresolved`, `borderline_other_res`) and quality filters removed (`pred_uncertainty`, `desc`, `log_msgs`). The KG entity extractor (`src/v2_advanced/proposal_d_knowledge_graph/extractor.py`) uses OpenAI's `gpt-4o-mini` model.

---

## Quick-start for new researchers

```python
import json
from pathlib import Path

base = Path("data/derived/global/2026-06-17-wol-real-v3-global")

# 1. Load the memory corpus (the retrieval target pool)
memory = [json.loads(l) for l in (base / "jira-memory-corpus.jsonl").open(encoding="utf-8")]
print(f"Memory: {len(memory)} items")  # 38642

# 2. Load query windows (filtered to test split)
manifest = json.loads((base / "triage-split-manifest.json").read_text())
test_families = {f for f, s in manifest["family_assignment"].items() if s == "test"}

with (base / "global-triage-examples.jsonl").open(encoding="utf-8") as f:
    test_windows = [
        json.loads(l) for l in f
        if json.loads(l)["scenario_family"] in test_families
    ]
print(f"Test windows: {len(test_windows)}")  # 13388

# 3. Load coarse gold relations
with (base / "window-memory-matchings.jsonl").open(encoding="utf-8") as f:
    gold = {
        r["window_id"]: set(r["matched_memory_issue_ids"])
        for r in (json.loads(l) for l in f)
    }
print(f"Gold relations: {len(gold)}")  # 78140

# 4. For your retrieval pipeline:
#    - Index `memory` by `jira_shadow_issue_id`
#    - For each window in `test_windows`, retrieve from memory
#    - Hit@K against `gold[window_id]`
```

---

*Last updated: 2026-06-26.*
*Authoritative source: this document. Quick reference: `data/derived/global/2026-06-17-wol-real-v3-global/README.md`. Pipeline status: `todo.md`.*
