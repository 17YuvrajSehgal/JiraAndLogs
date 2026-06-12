# Data layout

This directory holds **three datasets** used across the research. Everything under `data/` is gitignored — the raw bytes live only on disk, not in git.

```
data/
├── derived/                         # processed / featurised outputs (all datasets share this root)
│   ├── 2026-05-25-dataset-v5-large-<scenario>-r<NN>/      # per-run derivations (Online Boutique, ~80 runs)
│   ├── 2026-06-09-otel-demo-v1-<scenario>-r<NN>/          # per-run derivations (OTel Demo, 22 runs)
│   ├── corpora/
│   │   ├── 2026-05-25-dataset-v5-large/                   # OB humanized corpora
│   │   └── 2026-06-09-otel-demo-v1/                       # OTel Demo humanized corpora
│   ├── otel-demo-gcp-pilot-001/                           # one-off GCP OTel Demo pilot
│   └── global/
│       ├── 2026-05-25-dataset-v5-large-global/            # **Online Boutique** locked global dataset
│       ├── 2026-06-09-otel-demo-v1-global/                # **OTel Demo** global (1,643 windows × 147 memory)
│       ├── 2026-06-11-wol-real-global/                    # **WoL** Mode 3 derived global (2,000 Apache Jira)
│       └── smoke-otel-pilot-global/                       # OB smoke-test global
│
├── runs/                            # **Online Boutique** raw collection runs (~80 GB)
│   └── 2026-05-25-dataset-v5-large-<scenario>-r<NN>/      # Loki + Tempo + Prometheus + k8s dumps per run
│
├── otel-demo-runs/                  # **OTel Demo** raw collection runs (~19 GB, 22 runs)
│   └── 2026-06-09-otel-demo-v1-<scenario>-r<NN>/
│
└── wol/                             # **WoL** source archive (~18 GB)
    ├── README.md
    ├── TERMS_OF_USE.md
    ├── WoL_v1-2025-11-10.archive
    ├── WoL_v1-2025-11-10.archive.gz
    └── Xiaohui_MSR_2026.pdf          # original WoL paper (MSR 2026)
```

## The three datasets in one paragraph

- **Online Boutique (OB).** Synthetic microservices benchmark. Locked global at `data/derived/global/2026-05-25-dataset-v5-large-global/` — 2,796 train / 984 val / 2,940 test windows + 347 V2-humanized Jira tickets. Full telemetry (Loki logs + Tempo traces + Prometheus metrics + k8s events). The headline cascade was developed and evaluated on this dataset.

- **OTel Demo.** Synthetic but realistic deployment of the OpenTelemetry demo application. Global at `data/derived/global/2026-06-09-otel-demo-v1-global/` — 1,643 windows × 147 memory tickets across 8 scenario classes (Kafka outage, network partition, payment outage, cart-redis degradation, cascading-Kafka-checkout, multi-fault, network-latency, l1-compact). Full telemetry. Used as a cross-application generalization test: does the OB-trained system transfer to a different microservices app with the same telemetry modality?

- **WoL (World of Logs).** Real Apache Jira data (MSR 2026 dataset). Source archive at `data/wol/`, derived global at `data/derived/global/2026-06-11-wol-real-global/` — 2,000 real Jira tickets from 7 Apache projects (Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server). **No telemetry** — only log lines that engineers pasted into the Jira ticket. Used for the WoL Mode 1 (distractor), Mode 2 (novelty), Mode 3 (self-contained retrieval) evaluations. See [`DOCS/docs7/REAL-DATA-WoL-PLAN.md`](../DOCS/docs7/REAL-DATA-WoL-PLAN.md).

## Cross-references

- **Locked OB charter:** [`RESEARCH-CHARTER.md`](../RESEARCH-CHARTER.md) §7 (datasets), §8 (pipelines).
- **WoL plan:** [`DOCS/docs7/REAL-DATA-WoL-PLAN.md`](../DOCS/docs7/REAL-DATA-WoL-PLAN.md).
- **OTel Demo cross-app evaluation:** scheduled per [`DOCS/docs7/RESEARCH-QUESTIONS.md`](../DOCS/docs7/RESEARCH-QUESTIONS.md) RQ-B1.
- **WoL source URL + license:** [`data/wol/TERMS_OF_USE.md`](wol/TERMS_OF_USE.md).
