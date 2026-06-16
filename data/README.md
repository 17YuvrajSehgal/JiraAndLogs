# Data layout

This directory holds **three publishable datasets** plus their source / raw-collection roots. Everything under `data/` is gitignored — the raw bytes live only on disk, not in git.

```
data/
├── derived/                         # processed / featurised outputs
│   ├── 2026-05-25-dataset-v5-large-<scenario>-r<NN>/      # per-run derivations (OB, ~80 runs)
│   ├── 2026-06-09-otel-demo-v1-<scenario>-r<NN>/          # per-run derivations (OTel Demo, 22 runs)
│   ├── corpora/                                            # humanizer working dirs
│   └── global/
│       ├── 2026-05-25-dataset-v5-large-global/            # **Online Boutique** locked global dataset ← publishable
│       ├── 2026-06-09-otel-demo-v1-global/                # **OTel Demo** global ← publishable
│       └── 2026-06-15-wol-real-v2-global/                 # **WoL v2** Mode 1+2+3 global ← publishable (supersedes 2026-06-11 v1)
│
├── runs/                            # **OB** raw collection runs (~80 GB) — optional reference
├── otel-demo-runs/                  # **OTel Demo** raw collection runs (~19 GB) — optional reference
└── wol/                             # **WoL** source archive (~18 GB) + license / paper
```

The three `data/derived/global/<id>/` directories are the **publishable artifact sets**. Each is self-describing via its own README.

## The three datasets — headline figures

| Dataset | Windows | Memory tickets | Families | Telemetry | Split (v2-resplit) |
|---|---|---|---|---|---|
| **Online Boutique** (`2026-05-25-dataset-v5-large-global/`) | 6,720 | 347 | 27 | Loki + Tempo + Prometheus + k8s | 4701 / 1011 / 1008 |
| **OTel Demo** (`2026-06-09-otel-demo-v1-global/`) | 1,643 | 147 | 52 | Loki + Tempo + Prometheus + k8s | 1150 / 246 / 247 |
| **WoL v2** (`2026-06-15-wol-real-v2-global/`) | 9,341 | 2,000 | 7 | none (real Apache Jira text) | by-family: 7,147 / 546 / 1,648 |

**One paragraph each:**

- **Online Boutique (OB).** Synthetic microservices benchmark, locked global at `data/derived/global/2026-05-25-dataset-v5-large-global/` — 6,720 telemetry windows (4,701 train / 1,011 val / 1,008 test under the locked v2-resplit) × 347 V2-humanized Jira tickets across 27 scenario families. Full telemetry (Loki logs + Tempo traces + Prometheus metrics + k8s events). The headline cascade was developed and evaluated on this dataset.

- **OTel Demo.** Synthetic but realistic deployment of the OpenTelemetry demo application, global at `data/derived/global/2026-06-09-otel-demo-v1-global/` — 1,643 windows × 147 memory tickets across 52 scenario families (Kafka outage, network partition, payment outage, cart-redis degradation, cascading-Kafka-checkout, multi-fault, network-latency, l1-compact-*, etc.). Full telemetry. Used as a cross-application generalization test: does the OB-trained system transfer to a different microservices app with the same telemetry modality?

- **WoL (World of Logs) v2.** Real Apache Jira data (MSR 2026 source). Source archive at `data/wol/`; derived global at `data/derived/global/2026-06-15-wol-real-v2-global/` — **9,341 real Jira tickets** from 7 Apache projects (Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server): 2,000 `ticket_worthy` + 2,399 `borderline` + 4,942 `noise`. **No telemetry** — only log lines that engineers pasted into the Jira ticket. v2 (locked 2026-06-16) supersedes v1 (`2026-06-11-wol-real-global`, locked 2026-06-13) by adding the negative labels so triage accuracy becomes non-trivial, plus 90 multi-ticket incident clusters that exercise the `pages_per_incident` metric. See [`DOCS/docs7/REAL-DATA-WoL-PLAN.md`](../DOCS/docs7/REAL-DATA-WoL-PLAN.md).

## Publishable artifact set (per dataset)

Every `data/derived/global/<id>/` directory ships with the same core file set:

| File | Purpose |
|---|---|
| `global-triage-examples.jsonl` | Window-level rows: feature columns + `triage_evidence_text` + ground-truth labels |
| `jira-memory-corpus.jsonl` | Memory tickets used as the retrieval target |
| `jira-shadow-humanized-v2/bulk-*/timeline.jsonl` | Engineer-voice humanized memory tickets (OB + OTel synthesized; WoL is real text reformatted) |
| `v2_kg_extractions/all_extractions.jsonl` | LLM-extracted entities (services / components / errors / symptoms) per **memory ticket** |
| `v2_kg_extractions_windows/all_extractions.jsonl` | LLM-extracted entities per **test window** (symmetric-KG retrieval) |
| `window-memory-matchings.jsonl` | Coarse-relation gold mapping window → matched memory ticket ids |
| `window-memory-matchings-strong.jsonl` (WoL only) | Strong-relation gold for the strong-match paper claim |
| `triage-split-manifest.json` | Original split |
| `triage-split-manifest-v2-resplit.json` (OB + OTel) | 70/15/15 stratified resplit — recommended for cross-pipeline comparison |
| `triage-feature-columns.json` | Numeric feature-list contract for the classical-ML baselines |
| `global-triage-build-manifest.json` (OB + OTel) | Build provenance (seed, git SHA, run counts) |
| `README.md` | Per-dataset card with field schemas, ID linkage, citation |

WoL also has:

| File / dir | Purpose |
|---|---|
| `distractors/` | 300 off-topic tickets (Qt, Minecraft, etc.) for the RQ-A4 distractor sweep |
| `novelty-queries/` | 800 out-of-distribution queries for the RQ-A5 novelty layer |
| `self-contained/` | Mode-3 memory + queries + gold relations |
| `wol-priority-mapping.json` | Normalization of 50+ Jira priority strings to `{critical, major, minor}` |
| `wol-extraction-manifest.json` | Per-mode extraction provenance |

## ID linkage between files

- **OB + OTel humanized ↔ memory:** humanized `source_episode_id` == memory `incident_episode_id` (1:1)
- **WoL humanized ↔ memory:** humanized `ticket_id` == memory `jira_shadow_issue_id` (1:1)
- **Window ↔ memory matchings:** matchings `window_id` keys into both examples and matchings; `matched_memory_issue_ids` values are memory `jira_shadow_issue_id`s
- **Window-side KG ↔ memory-side KG:** both keyed by id (`window_id` / memory `jira_shadow_issue_id`); fields are identical schema (`affected_services`, `components`, `error_classes`, `symptoms`)

## How to load (Python)

```python
from core.data.loaders import load_dataset
from core.memory.corpus import MemoryCorpus

# coarse-relation gold (default)
ds = load_dataset("data/derived/global/2026-06-11-wol-real-global")
corpus = MemoryCorpus(issues=ds.memory_corpus)

# strong-relation gold (WoL only)
ds = load_dataset(
    "data/derived/global/2026-06-11-wol-real-global",
    matchings_file="window-memory-matchings-strong.jsonl",
)
```

The cascade scripts use these loaders via `--global-dir <path>` on every CLI; see `DOCS/docs7/REPRODUCE.md` for the full pipeline-by-pipeline reproduction recipe.

## Distribution packages

The publishable artifact is `data/published/` — see its [README](published/README.md) for the full layout. Each dataset is in its own subdirectory with a `simple_dataset.zip` (derived features only) and a `full_dataset.zip` (raw telemetry + derived + global):

```
data/published/
├── README.md                                  # landing page — start here
├── online-boutique/                           # Online Boutique (Google demo, full telemetry)
│   ├── README.md
│   ├── simple_dataset.zip   ~28 MB
│   └── full_dataset.zip      ~4.4 GB
├── otel-demo/                                 # OpenTelemetry Demo (cross-app generalization)
│   ├── README.md
│   ├── simple_dataset.zip   ~4 MB
│   └── full_dataset.zip      ~1.0 GB
└── world-of-logs/                             # Real Apache Jira (no telemetry)
    ├── README.md
    ├── simple_dataset.zip   ~7 MB
    └── full_dataset.zip      ~2.3 GB
```

Each zip is **self-contained** — it ships with a complete `README.md` (field schemas, ID linkage rules, example rows, splits, reproducibility provenance, citation) plus a `MANIFEST.sha256.json` for integrity verification. No external document references.

## What's NOT in the bundles

- Pilots / smoke runs (`data/otel-demo-runs/otel-demo-gcp-pilot-001/`, etc.) — one-off engineering tests, not part of the dataset.
- Working / scratch dirs (`data/derived/corpora/`, `data/derived/wol/extraction-cache/`) — humanizer / extractor intermediate state, regenerable.
- Tier-3 cascade outputs inside OB (`comparison/`, `training_runs/`, `text-leakage-report/`, `jira-shadow-humanized-v2-distractors/`) — these are pipeline results, not data, and are reproducible from the dataset + pipeline code.
- Pre-extracted agent results (`data/agent_runs/`) — also reproducible.
- The uncompressed `data/wol/WoL_v1-2025-11-10.archive` — bit-identical content to the included `.archive.gz` (just `gunzip` it).

## Cross-references

- **Locked OB charter:** [`RESEARCH-CHARTER.md`](../RESEARCH-CHARTER.md) §7 (datasets), §8 (pipelines).
- **WoL plan:** [`DOCS/docs7/REAL-DATA-WoL-PLAN.md`](../DOCS/docs7/REAL-DATA-WoL-PLAN.md).
- **OTel Demo cross-app evaluation:** [`DOCS/docs7/RESEARCH-QUESTIONS.md`](../DOCS/docs7/RESEARCH-QUESTIONS.md) RQ-B1.
- **WoL source URL + license:** [`data/wol/TERMS_OF_USE.md`](wol/TERMS_OF_USE.md).
