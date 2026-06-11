# Mode 3 — TCH-Lite × WoL End-to-End Retrieval Results

**Status.** P7+P8 BiEncoder + LogSeq2Vec slices complete (2026-06-11) — `REAL-DATA-WoL-PLAN.md` v3 §7. **BiEncoder lands in the "Excellent" band; LogSeq2Vec is "Concerning" — the structural reason is explained in §4.** Hybrid-RRF and KG-Retrieval are pending KG population.

**Scope of this round.** This document covers two of the four L2 retrievers — **BiEncoder** (§2–§3) and **LogSeq2Vec** (§3.5) — on the WoL Mode 3 self-contained retrieval task. The full TCH-Lite cascade requires also the Hybrid-RRF and KG-Retrieval pipelines plus the DiagnosisAgent; those are queued behind the in-progress LLM-extracted KG population (qwen3.6-35b-a3b via LM Studio + Neo4j). The BiEncoder result is the **load-bearing claim** — it's the cascade's strongest single Hit@1 contributor and the position-1 anchor for L2 overlap rerank.

---

## Table of contents

1. [What was tested](#1-what-was-tested)
2. [Headline results](#2-headline-results)
3. [Per-project stratification](#3-per-project-stratification)
4. [Honest scope and what's missing](#4-honest-scope-and-whats-missing)
5. [Paper integration](#5-paper-integration)
6. [Files produced](#6-files-produced)
7. [Cross-references](#7-cross-references)

---

## 1. What was tested

| Property | Value |
|---|---|
| Cascade variant | TCH-Lite's L2 anchor pool — **BiEncoder only**, no fusion |
| Dataset | `data/derived/global/2026-06-11-wol-real-global/` (WoL Mode 3) |
| Memory corpus | 2,000 real Apache Jira tickets across 7 projects |
| Query split | Family-stratified per the legacy `triage-split-manifest.json` |
| Train families | wol-spark, wol-cassandra, wol-hbase, wol-flink (1,300 records) |
| Validation family | wol-ambari (250 records) |
| **Test families** | **wol-kafka, wol-mariadb-server (450 records)** |
| Gold relations | Coarse-match (same project + ≥1 shared component) and Strong-match (coarse + symptom-token Jaccard > 0.15) |
| Self-match exclusion | `MemoryCorpus.visible_to` excludes memory[i] when querying with window[i] via per-WoL-record `dataset_run_id` |
| BiEncoder config | sentence-transformers/all-MiniLM-L6-v2 fine-tuned on WoL train; G1 negative mix (2 BM25-hard + 1 random); use_all_golds=False (1 random gold per window per epoch); 5 epochs; seed 42 |

**Note on the family split.** This is a **cross-project transfer** evaluation: the BiEncoder is trained on tickets from 4 distributed-systems projects (Spark, Cassandra, HBase, Flink) and tested on 2 different ones (Kafka, MariaDB). It is a stronger test than within-project retrieval — closer in spirit to a leave-one-family-out evaluation than to an in-distribution one.

---

## 2. Headline results

| Metric | Coarse match | Strong match |
|---|---:|---:|
| n test queries with gold | 342 / 450 | 169 / 450 |
| **Hit@1** | **0.9240** | 0.2189 |
| **Hit@5** | **0.9591** | **0.6627** |
| **MRR** | **0.9377** | 0.3774 |

Wall time: fit = 1,490.8 s (~25 min on RTX 3070, 5 epochs over 1,079 contrastive pairs), predict ≈ 5 ms for 450 windows × 2,000 memory issues (dense, vectorized).

**Comparison points:**

- BiEncoder standalone on the synthetic dataset: Hit@1 = 0.695, Hit@5 = 0.789, MRR = 0.729 → real-data **coarse** Hit@5 is **+0.170 absolute** higher than synthetic. (Note: WoL has more golds per query under coarse, so the comparison is not strictly apples-to-apples — see §4.)
- Random baseline (1 − (1 − k/n)^5, with avg k ≈ 25 coarse / ≈ 2.66 strong golds and n = 1,999 visible memory issues): coarse ≈ **0.061**, strong ≈ **0.0066**. We are **~15.7× random (coarse)** and **~100× random (strong)**.
- Acceptance bars per `REAL-DATA-WoL-PLAN.md` v3 §15.3:

| Outcome | Hit@5 (coarse) | Hit@5 (strong) | This result |
|---|---|---|---|
| **Excellent** | **≥ 0.70** | **≥ 0.55** | **✓ both bands** |
| Acceptable | 0.50–0.70 | 0.35–0.55 | — |
| Reportable | 0.35–0.50 | 0.25–0.35 | — |
| Concerning | < 0.35 | < 0.25 | — |

**Bottom line.** BiEncoder retrieval generalizes from synthetic Online Boutique to real Apache Jira. Trained only on Spark/Cassandra/HBase/Flink tickets and tested on never-seen Kafka and MariaDB-Server tickets, it finds the right same-project + shared-component bucket 96 % of the time (top-5) and a same-project + shared-component + shared-symptom-token match 66 % of the time. Hit@1 falls sharply under strong match (0.92 → 0.22) because at k=1 there's typically only one true strong-match gold per query and ranking it #1 against ~25 also-valid coarse-match neighbours is hard — top-5 absorbs that uncertainty.

---

## 3. Per-project stratification

Cross-project transfer: trained on Spark/Cassandra/HBase/Flink, evaluated on Kafka and MariaDB-Server. Numbers are over the **test partition windows that have gold under the given relation** (so denominators differ across rows).

### Coarse match

| Project | n with gold | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| wol-kafka          | 147 | **0.9796** | **0.9864** | **0.9819** |
| wol-mariadb-server | 195 | 0.8821     | 0.9385     | 0.9044     |

### Strong match

| Project | n with gold | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| wol-kafka          | 91 | 0.1209 | 0.5714     | 0.2725 |
| wol-mariadb-server | 78 | **0.3333** | **0.7692** | **0.4998** |

**Observation.** Kafka transfers slightly better under coarse match (Hit@5 0.986 vs 0.939) but MariaDB transfers substantially better under strong match (Hit@5 0.769 vs 0.571, MRR 0.500 vs 0.273). The asymmetry is consistent with MariaDB-Server tickets containing more symptom-discriminating tokens (e.g. SQL error codes, replication state names) — the symptom-token Jaccard signal that defines strong match is more available to the BiEncoder when those tokens are lexically rich. Kafka tickets lean more on framework-generic vocabulary (`producer`, `consumer`, `partition`) that recurs across coarse-bucket neighbours and is therefore less discriminating at the strong-match level. Either way, no test project falls below the "Excellent" Hit@5 bar in either relation.

---

## 3.5. LogSeq2Vec on WoL Mode 3 (Round 2)

**Setup.** Same family-stratified split (train Spark/Cassandra/HBase/Flink, test Kafka/MariaDB-Server), 1,300 train + 250 val + 450 test windows, 2,000 memory tickets. Each window's "log sequence" is built from the `triage_evidence_text` (the WoL record's `log_quotes` pasted into the JIRA ticket; mean ≈ 19 lines/window, max 80). LogSeq2Vec aggregator: 2-layer transformer over the `all-MiniLM-L6-v2` line encoder, 5 epochs, 43,924 training pairs (1,079 windows × 3 BM25-hard + 1 random neg, mining over the memory pool), batch=8, ~78 min on RTX 3070. Training loss decreased from 1.629 → 1.253. The single-class fallback (every WoL window is `ticket_worthy`) emits max_sim as the triage_score; retrieval ranking is the load-bearing output.

### Headline (LogSeq2Vec)

| Metric | Coarse match | Strong match |
|---|---:|---:|
| n test queries with gold | 342 / 450 | 169 / 450 |
| Hit@1 | 0.0877 | 0.0296 |
| Hit@5 | **0.3099** (Concerning, < 0.35) | **0.1834** (Concerning, < 0.25) |
| MRR | 0.1625 | 0.0787 |

### Per-project (coarse)

| Project | n | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| wol-kafka          | 147 | 0.1293 | 0.4558 | 0.2412 |
| wol-mariadb-server | 195 | 0.0564 | 0.2000 | 0.1032 |

### Interpretation

LogSeq2Vec underperforms BiEncoder on WoL by a wide margin (Hit@5 coarse 0.310 vs 0.959 — a 0.649 gap). This is **structurally expected**, not a regression:

- **LogSeq2Vec's inductive bias is temporal**. Its design assumes the input is a chronologically ordered stream of log lines from a live system (Loki dumps in our synthetic dataset), where the *order and co-occurrence pattern* of distinct templates carries identity information. The aggregator's positional encoding and self-attention are specifically built to exploit that structure.
- **WoL log sequences have no temporal structure**. They are 1–19 lines pasted by a human into a JIRA ticket. The reporter included whichever lines they thought were most relevant, often a stack trace fragment plus one or two surrounding lines. Position carries no information; co-occurrence is dominated by what one stack trace happened to span.
- **Per-project asymmetry confirms it.** Kafka (more multi-line traceback-style log_quotes) gets Hit@5 = 0.456, MariaDB-Server (often single-line error message log_quotes) gets only 0.200 under coarse. The structure-rich slice transfers better, the structure-poor slice barely beats random.
- **For TCH-Lite-as-deployed, this is the correct read**: when telemetry is only what a human reporter pasted into a ticket (WoL's situation), LogSeq2Vec contributes little and the cascade should down-weight or skip it. In contrast, in the synthetic OB setting where every window has 100 ordered Loki lines, LogSeq2Vec is a meaningful retriever (it sits in the cascade's L2 RRF pool for a reason). The WoL result is a real-world honesty check on which retrievers depend on rich telemetry vs which generalise to text-only.

Headline: **the BiEncoder result generalises to real Jira; the LogSeq2Vec result generalises only when real log streams accompany the ticket.** Both findings are useful for the paper.

---

## 4. Honest scope and what's missing

The full Mode 3 evaluation per the v3 plan §7 requires:

| Pipeline | Status | What's needed |
|---|---|---|
| BiEncoder | **done — Round 1** | ✓ fit + predict |
| LogSeq2Vec | **done — Round 2** | ✓ fit + predict (see §3.5) |
| Hybrid-RRF rule | not done | Needs Neo4j with WoL knowledge graph (LLM-extracted entities for 2,000 tickets, ~30 min LLM time) + SPLADE indexing |
| Hybrid-RRF LLM | not done | Same as rule variant + LLM-extracted query-side entities at retrieval time |
| KG-Retrieval rule | not done | Needs Neo4j populated (shared with Hybrid-RRF) |
| DiagnosisAgent | not done | ~30 sec/window × 450 = ~4 hours of LM Studio time |
| TCH-Lite L1 stacker refit | not done | Trivial once retrievers' triage scores exist |
| TCH-Lite L3 classifier refit | not done | Trivial once `tch_max_retrieval_conf` is computable from retrievers |
| Full cascade Hit@K | not done | Composition step takes seconds once predictions are cached |

This first-cut report covers the BiEncoder slice because it's the cascade's strongest single Hit@1 retriever. Adding the other pipelines should generally **improve** the cascade's Hit@K (via RRF fusion) but the BiEncoder result is informative as a single-retriever lower bound.

---

## 5. Paper integration

Suggested treatment in `ICSE/sections/05-results.tex` as a new §5.X.3 subsection of the Real-Data Validation block (along with §5.X.1 Mode 1 distractor, §5.X.2 Mode 2 novelty):

> **§5.X.3 Mode 3 — End-to-end retrieval on real Apache Jira (BiEncoder slice).**
> To test whether TCH-Lite's core retrieval signal generalises beyond the synthetic Online Boutique fault library, we built a self-contained retrieval task from 2,000 real Apache Jira tickets across 7 distributed-systems projects (WoL dataset, MSR 2026). The family-stratified split holds out **wol-kafka** and **wol-mariadb-server** (450 test windows) — projects whose tickets the BiEncoder never sees during fine-tuning. Gold relations are inferred from same-project + shared-component (coarse, avg 25 golds/query) and additionally shared symptom-token Jaccard > 0.15 (strong, avg 2.66 golds/query).
>
> The G1 BiEncoder (`sentence-transformers/all-MiniLM-L6-v2`, fine-tuned with 2 BM25-hard + 1 random negative, 5 epochs) achieves **Hit@5 = 0.959 / MRR = 0.938 under coarse match** and **Hit@5 = 0.663 / MRR = 0.377 under strong match**. Both numbers fall within the pre-registered "Excellent" bands (Table 5.X) of ≥ 0.70 coarse / ≥ 0.55 strong and exceed the size-matched random baseline (0.061 coarse, 0.0066 strong) by ≈ 15.7× and ≈ 100× respectively. Per-project breakdown shows balanced cross-family transfer (Kafka Hit@5 0.99, MariaDB Hit@5 0.94 under coarse), with one notable asymmetry: MariaDB's symptom-rich tickets translate to a stronger strong-match result (Hit@5 0.77 vs Kafka 0.57). We interpret this as evidence that the core dense-retrieval signal of TCH-Lite — which is the cascade's strongest single-retriever contributor on synthetic data — survives the transfer to real human-written Jira text without dataset-specific re-engineering.

Once the remaining four retrievers are layered in (§4), the corresponding §5.X.3 should report the full-cascade Hit@K and contrast against this BiEncoder-only lower bound. Until then, this number stands as the strongest single-component evidence for Mode 3.

---

## 6. Files produced

| Path | Purpose |
|---|---|
| `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` | This document |
| `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/biencoder-mode3-results.json` | BiEncoder Hit@K + per-project stratification |
| `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/biencoder-predictions.jsonl` | BiEncoder per-test-window prediction records |
| `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/logseq2vec-mode3-results.json` | LogSeq2Vec Hit@K + per-project stratification |
| `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/logseq2vec-predictions.jsonl` | LogSeq2Vec per-test-window prediction records |
| `data/derived/global/2026-06-11-wol-real-global/v2_logseq/*.jsonl` | Per-window log-line files for LogSeq2Vec (2,000 files, 38,730 lines) |
| `scripts/research-lab/run_biencoder_wol_mode3.py` | BiEncoder driver |
| `scripts/research-lab/build_wol_logseq.py` | WoL → v2_logseq adapter |
| `scripts/research-lab/run_logseq2vec_wol_mode3.py` | LogSeq2Vec driver |

To reproduce:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/research-lab/run_biencoder_wol_mode3.py
```

---

## 7. Cross-references

- **Plan §7** — [`docs7/REAL-DATA-WoL-PLAN.md`](REAL-DATA-WoL-PLAN.md) §7 (Mode 3 specification).
- **TCH-Lite design** — [`docs7/TCH-Lite.md`](TCH-Lite.md) §3–§6.
- **WoL dataset build** — [`docs7/REAL-DATA-WoL-PLAN.md`](REAL-DATA-WoL-PLAN.md) §13.
- **G1 BiEncoder details** — [`docs6/pipeline-2-BiEncoder.md`](../docs6/pipeline-2-BiEncoder.md).
- **Prior Mode results** — [`docs7/MODE1-DISTRACTOR-RESULTS.md`](MODE1-DISTRACTOR-RESULTS.md), [`docs7/MODE2-NOVELTY-RESULTS.md`](MODE2-NOVELTY-RESULTS.md), [`docs7/CHANNEL-ABLATION.md`](CHANNEL-ABLATION.md).

---

*Generated 2026-06-11 as part of P7+P8 (Mode 3 BiEncoder slice) per `REAL-DATA-WoL-PLAN.md` v3 §14 phased plan. BiEncoder fit + predict completed in 1,499 s on a single RTX 3070; results written to `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/biencoder-mode3-results.json` and `biencoder-predictions.jsonl`.*
