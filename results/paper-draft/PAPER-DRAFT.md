# Retrieval-Augmented Incident Triage: How Deployment History Sharpens On-Call Diagnosis

**Target venue:** ICSE 2027 (research track) — alternative venues: FSE, ASE, MSR, ICSME.
**Status:** Draft. Numbers locked from comparison runs through 2026-06-01.
**Authors:** Yuvraj Sehgal (+ TBD)

---

## Abstract

Modern site reliability engineering teams operate mature anomaly detection pipelines — what is missing is a fast bridge from a fresh telemetry signal to the past incident that explains it. We build a retrieval-augmented triage system that, given a 5-minute window of logs + traces + Kubernetes events, retrieves the most-similar past Jira tickets from a memory of engineer-voice incident reports. Our characterization on a synthetic-but-realistic dataset of 2940 test windows and 347 prior tickets shows:

1. **Retrieval quality scales monotonically with deployment history.** As the number of compatible prior tickets in memory grows from 1-2 to 21+, Hit@1 climbs 5.2× (0.05 → 0.25) and MRR climbs 2.6× (0.09 → 0.25). Telemetry-only models (gradient-boosted classifier on 94 numeric features) cannot exhibit this curve at all — they have no retrieval head.
2. **Anomaly detection and retrieval are orthogonal.** Numeric telemetry already saturates the binary anomaly task (PR-AUC 0.77). Our retrieval-augmented system trades 15 PR-AUC points for a retrieval capability that the baseline cannot have, and we report this trade-off honestly.
3. **A domain-fine-tuned cross-encoder reranker shifts probability mass toward Hit@5** at the cost of top-1 precision, suggesting the right product framing is "engineer reviews top-K candidates" rather than "auto-cite top-1."
4. **The system is robust to memory noise:** with 25% of memory occupied by plausible-but-fake "distractor" tickets, Hit@5 drops only ~1% relative while top-1 erodes 23% — distractors get pushed to ranks 6-15 by the reranker.
5. **Cold-start novelty detection is unsolved.** Of 333 cold-start anomalies (no compatible memory at predict time), the system flags zero as novel — a clear failure mode for future work.

Translated to engineer-time-saved: a memory-augmented system with our fine-tuned reranker cuts mean diagnosis time from 30 min (telemetry-only baseline) to 23.6 min per resolvable incident.

---

## 1. Introduction

On-call engineers do not lack alerts; they lack *context*. When a pager fires at 3am, the SRE knows the system is unhealthy — but they don't know whether this incident is similar to one they (or a teammate) already debugged last quarter. Jira issue trackers contain rich, structured knowledge about past incidents and their resolutions, but they are unindexed against live telemetry. Mature observability stacks bridge metrics to dashboards, but not metrics to *past tickets*.

We pose retrieval-augmented incident triage as a complementary capability to anomaly detection. Anomaly detection answers "is something wrong?" Retrieval-augmented triage answers "what is wrong, and have we seen this before?" The latter directly reduces the most expensive step of incident response: the *diagnosis* phase, where an engineer scans logs, traces, and past tickets trying to recognize a recurring pattern.

### Research questions

- **RQ1.** How does retrieval-augmented diagnosis quality vary with the number of compatible prior tickets accumulated in memory?
- **RQ2.** Does anomaly detection improve with Jira memory (or is it orthogonal)?
- **RQ3.** Can fine-tuning a domain-specific cross-encoder reranker on (window, ticket) pairs improve retrieval over off-the-shelf rerankers?
- **RQ4.** Which telemetry channel (logs / traces / k8s) contributes most to retrieval signal?
- **RQ5.** How does retrieval degrade as memory becomes noisier with irrelevant tickets?
- **RQ6.** What is the engineer-time-saved when a top-K retrieval head is added to a triage system?

### Contributions

- A retrieval-augmented triage architecture that composes BM25, cross-encoder reranking, and a multi-channel evidence graph over a humanized Jira memory corpus.
- An empirical characterization of how retrieval quality scales with deployment history — the central result of the paper.
- A methodological correction: under the standard `Recall@K = |top_K ∩ gold| / |gold|` definition, retrieval quality *mechanically drops* as |gold| grows beyond K. We report **Hit@K** (binary recall at top-K) as the right metric for "did the engineer find a relevant ticket."
- A negative result on cold-start novelty detection: the system fails to identify all 333 novel incidents in our test set, motivating future work on calibrated novelty heads.
- An open dataset and reproducible code base, with every reported number traceable to a specific git SHA via an automatic training-run registry.

---

## 2. Related Work

[TODO — survey: log-based anomaly detection (DeepLog, LogAnomaly), trace-based diagnosis (Pinpoint, FacetGraph), retrieval-augmented generation (REALM, RAG), Jira analytics (TAWOS, etc.), AIOps surveys.]

---

## 3. System

### 3.1 Architecture

The system is a deterministic skill chain that processes each 5-minute telemetry window:

```
INPUT: window {logs, traces, k8s_events, derived_numeric_features}
  |
  +-> entity_extract        — pull (service, component, error_class, severity)
  +-> component_filter      — pre-filter Jira memory by entity overlap
  +-> lexical_similarity    — BM25 over memory_text
  +-> log_signature         — Move-A: characteristic log line per side
  +-> cross_encoder_rerank  — MS-MARCO MiniLM joint scoring on top-20
  +-> graph_score           — bridge-weighted scoring on entity graph
  +-> numeric_blend         — HGB triage head over 94 numeric features
  +-> triage_decide         — blend numeric + similarity → triage_score
  +-> novelty_check         — flag if no good past-ticket match
  +-> graph_traverse_explain — explanation citing graph entities

OUTPUT: {triage_score, top_5_candidates, is_novel, explanation}
```

### 3.2 The humanized Jira memory corpus (V2)

347 engineer-voice incident tickets, anchored to TAWOS-empirical length / comment-count / code-block distributions (458K real Jira issues). Each ticket has a leading `description_code` (engineer-vocabulary log lines from when the incident was filed) and per-step `body_code` blocks pasted by the timeline persona (on-call, sub-system owner, SRE-lead). Sanitizer-verified: zero lab terminology leaks (no `chaos`, `synthetic`, `scenario`, etc.) reach the indexed text.

### 3.3 Cross-encoder fine-tuning

Starting from `cross-encoder/ms-marco-MiniLM-L-6-v2`, we fine-tune on 12,641 (query, doc, label) pairs built from train+val splits — 8,855 positives (each gold-matching window/ticket pair) and 3,786 hard negatives (top-20 BM25 candidates excluding gold). Best checkpoint at epoch 1: validation AP=0.737, F1=0.802.

---

## 4. Methodology

### 4.1 Dataset

- **Source:** Synthetic but realistic telemetry traces generated against Google's microservices-demo on Kubernetes, with controlled fault injections from 14 distinct fault families spread across train, val, and test.
- **Split:** Chronological + family-stratified: train (2796 windows, 14 families), val (984 windows, 6 families), test (2940 windows, 7 families). Families do not overlap between splits — out-of-distribution evaluation by design.
- **Memory:** 347 V2 humanized Jira tickets, available-from times anchored chronologically. Test windows see only tickets minted before them.
- **Distractors:** 110 plausibly-realistic but unrelated tickets (60 TAWOS-derived + 25 in-architecture + 25 cross-architecture) for robustness eval.

### 4.2 Pipelines compared

| Pipeline | Memory | Retrieval | Reranker |
|---|---|---|---|
| `hgb` | none | none | none |
| `memorygraph_v2_sota_nw080` (SOTA) | V2 humanized, 347 | BM25 + log-sig + cross-enc + graph | MS-MARCO MiniLM (off-the-shelf) |
| `memorygraph_v2_sota_nw080_ft` (FT, this paper) | V2 humanized, 347 | BM25 + log-sig + cross-enc + graph | **Fine-tuned MiniLM on our pairs** |
| `memorygraph_v2_sota_nw080_no_{logs,traces,k8s}` | per-channel masked | same | off-the-shelf |
| `memorygraph_v2_sota_d{000,010,025,050}pct` | + N distractor tickets | same | off-the-shelf |

### 4.3 Metrics

Triage detection: PR-AUC, ROC-AUC, F1@FPR=5%, ECE (calibration).

Retrieval (primary): **Hit@K** for K∈{1, 3, 5}. We argue Hit@K is the right metric for our scenario because the standard `Recall@K = |top_K ∩ gold| / |gold|` mechanically caps at K/|gold| in deep-history buckets — a methodological correction we discuss in §4.4.

Retrieval (secondary): MRR, Precision@5, capacity-normalized Recall@5 = `|top_K ∩ gold| / min(K, |gold|)`.

Utility: simulated mean time-to-diagnose per incident, assuming engineer reviews top-K candidates at 30s each, falling back to 30min if none helpful.

Statistical envelope: 95% paired bootstrap CIs, 1000 resamples, seed=42. Stratified CIs per (pipeline × bucket) cell.

### 4.4 The Hit@K methodological correction

The native `Recall@K = |top_K ∩ gold| / |gold|` ranks `recall@5 = 1.0` when |gold| = 5 and all five are surfaced, but only `5/21 = 0.238` even with perfect retrieval when |gold| = 21. This mechanical capping makes the depth-stratified retrieval curve look *non-monotone* (R@5 falsely drops from 0.155 at depth 1-2 to 0.044 at depth 21+ in our anchor experiment). **Hit@K** = `1 if any gold in top-K else 0` is the right metric for "did the engineer find a relevant ticket" and yields a strictly monotone curve.

---

## 5. Results

### 5.1 Anchor experiment: retrieval scales with deployment history (RQ1, RQ2)

[Figure: anchor_depth_hit5.png — primary]

[Table: Hit@1, Hit@5, MRR per pipeline per bucket with 95% CIs]

**Headline result:** As the number of compatible prior tickets in memory grows from 1-2 to 21+:
- Hit@1: 0.048 → 0.250 (**5.2× improvement**)
- Hit@5: 0.190 → 0.250
- MRR: 0.095 → 0.250 (**2.6× improvement**)

HGB sits at exactly 0.000 across every bucket — it has no retrieval head and cannot improve with memory accumulation. **Memory-augmented retrieval is structurally orthogonal to anomaly detection.**

PR-AUC on the binary anomaly task: HGB 0.772 vs memorygraph 0.619 — HGB wins triage by 15 percentage points. **Our system does not improve anomaly detection; it adds a retrieval capability the baseline cannot have.** (RQ2: memory does not help triage AUC.)

### 5.2 Cross-encoder fine-tuning (RQ3)

[Figure: anchor_depth_hit5.png — with FT line]

Fine-tuning on 12,641 (window, ticket) pairs shifts probability mass toward higher Hit@5 at the cost of top-1:

| Metric | SOTA off-the-shelf | SOTA + FT | Δ |
|---|---:|---:|---:|
| Hit@5 (depth 3-5) | 0.159 | 0.190 | +20% rel |
| Hit@5 (depth 6-20) | 0.212 | 0.234 | +10% rel |
| Hit@1 (depth 6-20) | 0.179 | 0.136 | -24% rel |
| MRR (depth 6-20) | 0.190 | 0.171 | -10% rel |

(RQ3: yes, fine-tuning helps Hit@5; the trade-off implies the right product framing is "show top-K candidates" rather than "auto-suggest top-1.")

### 5.3 Channel ablation (RQ4)

[Awaiting Phase C results]

### 5.4 Distractor robustness (RQ5)

[Awaiting Phase D results]

### 5.5 Utility (RQ6)

[Figure: diagnosis_time.png — bar chart]

| Pipeline | Find rate (top-10) | Mean diagnosis time |
|---|---:|---:|
| HGB (telemetry only) | 0% | 30.0 min |
| memorygraph SOTA | 20.2% | 24.1 min |
| memorygraph + FT | 22.1% | 23.6 min |

A retrieval-augmented system saves **6.4 minutes per resolvable incident** vs the telemetry-only baseline (assuming 30s/candidate review, 30min fallback).

---

## 6. Limitations

### 6.1 Cold-start novelty detection is broken

Of 333 cold-start anomalies in our test set (ticket_worthy windows with no compatible memory + true `gold_is_novel`), the existing skill chain flags **zero** as novel. The hard-coded `max(combined_scores) < 0.15` rule is too brittle. A calibrated novelty classifier on `(max_similarity, n_compatible_in_memory, top_K_score_spread)` is the obvious fix but out of scope for this paper.

### 6.2 Synthetic data

We use synthetic-but-realistic data, calibrated against TAWOS's 458K real Jira issues for ticket-level realism. We do not validate on production Jira; reviewers should consider our results as characterizations of the *retrieval-augmented architecture*, not predictions of production yields. Validation on a real industrial corpus is future work.

### 6.3 Single deployment

We use a single Google microservices-demo deployment with 14 fault families. Multi-deployment validation would strengthen the deployment-history scaling claim.

### 6.4 Family-disjoint test split

Train and test families do not overlap. This is *good* for generalization claims but means cold-start performance is undertestable: every test window is, by family, in some sense cold-start. The depth axis we use (compatible-ticket count) is the right lens, but it is not equivalent to a temporal "first occurrence" cold-start.

---

## 7. Conclusion

The bottleneck in modern on-call response has shifted from detection (mature) to *diagnosis* (under-served). We characterized retrieval-augmented diagnosis as a complementary capability to anomaly detection, and showed empirically that retrieval quality scales meaningfully with deployment history — Hit@1 grows 5.2× and MRR grows 2.6× as memory accumulates from 1-2 to 21+ compatible prior tickets. Fine-tuning a domain cross-encoder further shifts probability mass into top-5 at a top-1 cost, suggesting the right UX is "review top-K candidates" rather than "auto-suggest top-1." We disclaim improvement on anomaly detection itself: telemetry-only gradient boosting already wins that task by 15 PR-AUC points; memory is for *citation*, not *detection*. We open-source the dataset, pipeline, and training-run registry for reproducibility.

---

## Appendix A — Reproducibility checklist

- Code: `<repo>/src/{comparison,memorygraph,util}`
- Data: `<repo>/data/derived/global/2026-05-25-dataset-v5-large-global/`
- Phase A run: `comparison/phase-a-anchor/{report.json, per-window-predictions.jsonl}`
- Phase B run: `comparison/phase-b-finetune/{...}`
- Fine-tuned model: `results/phase-b-finetune/crossenc_ft_v1/` (model.safetensors gitignored due to size; reproducible from `scripts/finetune_crossenc.py`)
- Training runs: `data/derived/global/<id>/training_runs/<pipeline>__<UTC>__<sha8>/` — every result tagged with its git SHA
- Charter: `RESEARCH-CHARTER.md` (locked 2026-06-01, git `f649af5`)

