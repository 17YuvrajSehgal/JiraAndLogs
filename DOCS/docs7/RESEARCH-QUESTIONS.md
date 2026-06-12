# Research Questions Catalogue

**Status.** Draft 2026-06-12. Inventory of every research question this project either *can* answer with results we already have, *partially* answers and needs a small follow-up, or *should* answer for ICSE robustness but currently has no evidence for. Used to plan the paper's narrative and the remaining experiment queue.

**Scope.** Three datasets:

| Dataset | Type | Telemetry | Memory tickets | Test windows |
|---|---|---|---|---|
| **Online Boutique (OB)** | synthetic microservices | logs, traces, metrics, k8s events | 347 V2-humanized | 1,008 (locked split) |
| **OTel Demo** | synthetic-but-real-deployment | logs, traces, metrics | 147 V2-humanized | 1,643 (needs split) |
| **WoL (World of Logs)** | real Apache Jira | none (log lines pasted into tickets only) | 2,000 across 7 projects | 450 (Kafka + MariaDB, family-stratified holdout) |

The "system" referenced below is the agentic system that's the paper's contribution (skill registry + controller + loop). Internally it draws on the seven-pipeline TCH cascade as its skill set; externally the paper presents only the agentic framing.

---

## Table of contents

1. [Bucket A — Answered with results in hand](#1-bucket-a--answered-with-results-in-hand)
2. [Bucket B — Partially answered, small follow-up needed](#2-bucket-b--partially-answered-small-follow-up-needed)
3. [Bucket C — Likely needed for ICSE robustness, no evidence yet](#3-bucket-c--likely-needed-for-icse-robustness-no-evidence-yet)
4. [Summary table — RQ × evidence × status](#4-summary-table--rq--evidence--status)
5. [What this list deliberately excludes](#5-what-this-list-deliberately-excludes)

---

## 1. Bucket A — Answered with results in hand

These are research questions for which we have numerical evidence in committed artifacts. They are *ready to write* with the data on disk; no new compute is required.

### RQ-A1. Does a retrieval-augmented system find the right past Jira ticket for an incident window?

- **Numbers (OB synthetic, locked 1,008-window test split):** Hit@1 = 0.722, Hit@5 = 0.912, MRR = 0.794.
- **Evidence:** `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl`; headline tables in `docs6/X_FINAL_TCH_CASCADE.md` §12 and `technical-paper/sections/07-results.tex`.
- **Status:** Answered. Forms the baseline narrative for the agentic system to inherit.

### RQ-A2. Does retrieval Hit@5 scale with the depth of deployment history (more past tickets in the same scenario family → better Hit@5)?

- **Numbers:** Monotonic increase across 5 buckets of `n_prior_family_tickets` (0 / 1–2 / 3–5 / 6–20 / 21+); the anchor figure of the paper.
- **Evidence:** `technical-paper/figures/anchor_combined.pdf`; depth-curve analysis in `technical-paper/sections/07-results.tex`.
- **Dataset:** OB synthetic only (the only one with curated depth labels).
- **Status:** Answered. This is the locked charter's sub-claim 1.

### RQ-A3. Which input modalities (logs, traces, k8s events, metrics) actually carry the retrieval signal?

- **Finding:** Logs change retrieval substantially when removed (44 % Hit@5 change); trace-line and k8s-line channels contribute 0/2,940 to retrieval (zero windows where logs alone vs logs+others differed). Numeric features dominate triage but contribute nothing to retrieval.
- **Evidence:** `docs7/CHANNEL-ABLATION.md` and `docs7/channel-ablation-data.json`.
- **Dataset:** OB synthetic.
- **Status:** Answered. Justifies the system's input contract.

### RQ-A4. Does the system degrade gracefully under noise from unrelated past tickets in the memory corpus (real-world memory contamination)?

- **Numbers (OB):** Hit@5 drops 8.3 % rel (from 0.912 to 0.837) at 50 % distractor ratio (p_per_slot = 0.302); Hit@1 drops 29 % rel.
- **Evidence:** `docs7/MODE1-DISTRACTOR-RESULTS.md` (uses WoL distractors from 6 off-topic projects: Qt, Minecraft, Confluence, Sakai, JBoss EAP, JBoss Tools).
- **Dataset:** OB cascade predictions + WoL distractor pool.
- **Caveat:** The simulation is identity-agnostic (per-slot displacement is random); it tests *quantity* of noise, not *content* overlap. See §5 of MODE1 doc.
- **Status:** Answered (lower-bound robustness).

### RQ-A5. Can the system detect novel incidents — windows with no past analog — without false positives on out-of-distribution queries?

- **Numbers:** 100 % novel-precision (800/800) on WoL out-of-distribution queries from 8 unrelated projects, at the cascade's canonical novelty threshold. Max cosine similarity any WoL query achieves against OB memory is 0.4722 (well below the 0.5 threshold).
- **Evidence:** `docs7/MODE2-NOVELTY-RESULTS.md`; `data/derived/global/2026-06-11-wol-real-global/mode2_novelty_lowerbound.json`.
- **Dataset:** OB memory + WoL OOD queries.
- **Caveat:** Lower bound — uses only the "free signal" (max-similarity threshold), not the full three-disjunct L3. Adding the LLM-agent and learned-classifier signals can only increase novelty recall, never decrease precision.
- **Status:** Answered (lower bound).

### RQ-A6. Does the retrieval signal trained on synthetic data generalize to real Apache Jira tickets the system never saw during training?

- **Numbers (WoL Mode 3, test = Kafka + MariaDB, never seen during fine-tune):** BiEncoder coarse Hit@5 = **0.959** (Excellent band, ~15.7× random); Hybrid-RRF strong Hit@5 = **0.787** (Excellent band, ~119× random).
- **Evidence:** `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §§2–3, 3.6, 3.8; predictions in `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/`.
- **Dataset:** WoL real (2,000 Apache Jira tickets, family-stratified split).
- **Status:** Answered. This is the strongest external-validity result we have.

### RQ-A7. Which skill types are complementary on real data — i.e., does combining heterogeneous retrievers beat the best single retriever?

- **Numbers:** On WoL strong-match, Hybrid-RRF (BiEncoder + SPLADE + KG fusion) gets Hit@5 = 0.787 vs BiEncoder alone at 0.663 — **+0.124 absolute**. Per-project: Kafka strong-match Hit@5 lifts from 0.571 (BiEncoder) to 0.791 (Hybrid-RRF), **+0.220 absolute**. Coarse-match: BiEncoder saturates at 0.959 and adding lexical/graph signals slightly underperforms (0.901 fused), so fusion's benefit is *relation-dependent*.
- **Evidence:** `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §3.8 consolidated table.
- **Dataset:** WoL real.
- **Status:** Answered. Directly justifies the agent's multi-skill design vs a single-retriever baseline.

### RQ-A8. Does an LLM-as-verifier — taking top-K retrieval candidates and re-ranking via reasoning — transfer cross-domain?

- **Finding (negative, intentional):** No. DiagnosisAgent re-ranking the Hybrid-RRF top-10 on WoL degrades Hit@5 by **−0.272 absolute on coarse / −0.225 absolute on strong** vs the input pool. Strong-match Hit@1 improves by only +0.030. Three structural reasons (false novelty calls 15.6 %, OOD verify-prompt distribution, top-10 → top-5 compression dropping golds).
- **Evidence:** `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §3.9.
- **Dataset:** WoL real.
- **Status:** Answered. This is a *useful* negative result — it bounds when an LLM verifier helps vs hurts and motivates the agent's *adaptive* tool-selection design (don't blindly call the verifier on every window).

### RQ-A9. What is the cost of running the system end-to-end?

- **Numbers:** OB synthetic, cascade composition after upstream cached predictions: **16 µs/window**. Upstream per-window cost is dominated by the LLM agent (~30 sec/window); other pipelines combine to ≤ 1 sec/window. On WoL Mode 3: BiEncoder fit 25 min, LogSeq2Vec fit 80 min, Hybrid-RRF (incl. KG extraction) 9 h, DiagnosisAgent on 450 windows 4 h.
- **Evidence:** `docs6/X_FINAL_TCH_CASCADE.md` §12; wall-times logged in `logs/wol-*.log`.
- **Status:** Answered (descriptive, not yet a paper claim). Useful when arguing the agent's adaptive tool-selection cuts cost without accuracy loss.

---

## 2. Bucket B — Partially answered, small follow-up needed

These have *some* evidence but not enough to be a defensible paper claim. Each needs a bounded experiment (hours to a day) to close.

### RQ-B1. Does the system trained on synthetic OB transfer zero-shot to a different microservices application of the same kind (OTel Demo)?

- **What we have:** OTel Demo dataset on disk under `data/` — derived global at `data/derived/global/2026-06-09-otel-demo-v1-global/` (1,643 windows × 147 memory tickets), raw runs at `data/otel-demo-runs/` (22 runs, full telemetry: logs, traces, metrics, k8s), across 8 scenario classes including Kafka, network partition, payment outage, cart-redis degradation, cascading-Kafka-checkout. **No pipelines have been run on it yet.**
- **What's needed:** (a) Generate a proper family-stratified train/val/test split (currently all in train). (b) Run the synthetic-OB-trained pipelines unmodified against the OTel Demo windows, measure zero-shot Hit@K. (c) Optionally retrain only the L1 triage stacker on the OTel Demo train split (the "L1-retrained" claim).
- **Estimated cost:** ~4–8 hours of compute (one BiEncoder fine-tune on OTel Demo train, plus inference). KG extraction on the 147 OTel Demo tickets would add ~30 min more.
- **Status:** Highest-ROI follow-up. Strongest possible external-validity claim — *"system trained on app A works on app B, same modality."*

### RQ-B2. Does retrieval Hit@5 scale with deployment history on *real* Jira (not just synthetic)?

- **What we have:** Mode 3 results across 7 WoL projects with varying ticket counts in memory; depth is implicit but not explicitly stratified.
- **What's needed:** Re-bucket Mode 3 test queries by `n_prior_same_project_tickets` (1–10 / 11–50 / 51–200 / 201+), compute Hit@5 per bucket. Pure analysis pass — predictions are already in `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/biencoder-predictions.jsonl`. No new compute.
- **Estimated cost:** ~1 hour analysis script.
- **Status:** Closes the depth-scaling story across both synthetic and real corpora. Direct extension of RQ-A2.

### RQ-B3. Does an adaptive tool-selection controller (cheap-first, escalate on uncertainty) cut LLM inference cost without losing accuracy?

- **What we have:** Evidence on OB synthetic that ~75 % of windows have HGB triage > 0.9 AND BiEncoder consensus (back-of-envelope claim in `docs6/XX_AGENTIC_IDEA.md` §4.1). Cascade currently runs DiagnosisAgent on every window. Mode 3 DiagnosisAgent results on WoL show the agent often *hurts* the cascade, reinforcing the case for selective invocation.
- **What's needed:** Implement the controller (rule-based first, per `XX_AGENTIC_IDEA.md` §6.3 open question 1) and measure (a) LLM-call rate, (b) Hit@5 / Hit@1 / novel-recall vs the all-windows-cascade baseline. Run on OB and OTel Demo (telemetry-rich) and on WoL (text-only path).
- **Estimated cost:** ~1–2 weeks engineering (this is one of the system contributions, not just an experiment).
- **Status:** This is the *headline* claim of the agentic system. Needs the system itself to be implemented.

### RQ-B4. Does query reformulation on retrieval disagreement recover Hit@1 misses?

- **What we have:** Failure analysis on OB cart-redis sub-family suggests 15 of 29 misses are *retrievable* but the BiEncoder embeds the query in a region where a distractor outranks gold (per `docs6/XX_AGENTIC_IDEA.md` §4.2).
- **What's needed:** Implement the reformulator (constrained action space — drop_token, add_service, substitute_synonym), retry L2, measure Hit@1 deltas.
- **Estimated cost:** ~2–3 weeks engineering.
- **Status:** Second headline mechanism of the agent. Conditional on B3 being built first.

### RQ-B5. Does cross-app retrieval work when the memory is *real* tickets from one project and the queries are *live* telemetry from a related-but-different application (Mode 4: WoL Kafka × OTel Demo Kafka)?

- **What we have:** WoL has 350 Apache Kafka tickets. OTel Demo has 147 Kafka-scenario telemetry windows (across kafka-broker-outage, kafka-consumer-lag, cascade-kafka-broker-checkout). No cross-corpus matching has been done yet.
- **What's needed:** Build a cross-corpus gold relation (project=kafka + symptom-token Jaccard or component overlap), run retrieval, report Hit@K.
- **Estimated cost:** ~2–4 hours (most of it is gold-relation engineering; retrieval itself is fast).
- **Status:** The most "exotic" external-validity claim — explicitly bookmarked as Mode 4 in `docs7/REAL-DATA-WoL-PLAN.md` v3 §8.

### RQ-B6. Does the system's full TCH cascade composition (vs the best single retriever) improve Hit@K on real Apache Jira?

- **What we have:** All 5 retriever predictions cached on WoL Mode 3 (`tch-lite-refit/{biencoder,logseq2vec,hybrid-rrf,kg-retrieval,diagnosis-agent}-predictions.jsonl`). The composition step has not been run.
- **What's needed:** Run the L1 stacker refit on WoL train + L3 novelty refit + L2 RRF + overlap-rerank composition. Bookwork (the inputs are all cached).
- **Estimated cost:** ~2–4 hours scripting.
- **Status:** Closes the "is the cascade more than the sum of its parts on real data?" question. Useful even though the cascade is hidden in the paper — gives us the upper bound the agentic system is benchmarked against.

---

## 3. Bucket C — Likely needed for ICSE robustness, no evidence yet

These are anticipated reviewer concerns. Not having evidence here is a rejection risk. Ordered by likely reviewer-weight.

### RQ-C1. What is the statistical envelope (paired-bootstrap CIs) around the headline numbers?

- **Why ICSE cares:** Hit@5 = 0.912 means nothing without a CI. Section-3 paper review standard is 1,000-resample paired bootstrap on seed=42.
- **What's needed:** Re-run the metric computation with bootstrap resampling on the cached prediction JSONLs for every headline number (OB cascade, WoL 5 retrievers, OTel Demo when B1 is done).
- **Estimated cost:** ~2 hours scripting (one bootstrap utility, then iterate over predictions).
- **Status:** Mandatory.

### RQ-C2. How sensitive are the results to hyperparameter choices (L1 threshold = 0.5, L3 novelty threshold = 0.5, RRF k = 60, BiEncoder fine-tune epochs = 5)?

- **Why ICSE cares:** Without a sensitivity sweep, "the threshold happens to be 0.5" looks cherry-picked.
- **What's needed:** Small grid sweep per parameter, report robust regions.
- **Estimated cost:** ~1 day, mostly bookkeeping.
- **Status:** Strongly recommended for OB headline; lower priority for WoL Mode 3 since the rankings (not the scores) drive Hit@K.

### RQ-C3. What is the latency / cost per window of the agentic system vs the cascade vs a single-retriever baseline?

- **Why ICSE cares:** Deployment claim weight. Cascade's "16 µs cached" is meaningless without the upstream pipeline cost. The agent's adaptive-tool-selection RQ (B3) needs a cost baseline.
- **What's needed:** Per-skill latency measurement (already partially recorded in logs); compose into per-window cost distributions for the cascade and the agent.
- **Estimated cost:** ~half day.
- **Status:** Required for the B3 claim to be defensible.

### RQ-C4. How does the system compare to a strong published retrieval baseline (BM25 alone, or a single-vector dense baseline)?

- **Why ICSE cares:** Any paper claiming improvements over fusion needs a "naive baseline" comparison. We have BiEncoder-alone but BM25-alone has not been run as a standalone pipeline.
- **What's needed:** Run plain BM25 retrieval against memory on all three datasets, measure Hit@K.
- **Estimated cost:** ~half day (BM25 is fast; the work is wiring it as a pipeline runner).
- **Status:** Strongly recommended.

### RQ-C5. Skill-ablation: removing one skill at a time from the agent, which contributes the most to performance?

- **Why ICSE cares:** Validates the skill registry. Justifies inclusion / exclusion of each component.
- **What's needed:** N skill-removal runs of the agentic system; report Hit@K delta per removal. Mirrors the cascade's drop-one sweep but on the new architecture.
- **Estimated cost:** depends on agent fit time × N (≈ 4–8 hours total once the agent is built).
- **Status:** Required once the agentic system exists.

### RQ-C6. Failure analysis: when does the agentic system make a wrong call, and what's the categorical distribution of failures?

- **Why ICSE cares:** Honest reporting; matches what reviewers ask for. The cascade has this in `docs3/14-FAILURE-ANALYSIS.md`.
- **What's needed:** Pull the misses from the test split, manually code into categories (wrong-family, right-family-wrong-ticket, true-novel-not-flagged, false-novel, etc.), report distribution per dataset.
- **Estimated cost:** ~half day per dataset.
- **Status:** Strongly recommended.

### RQ-C7. Page-suppression and cross-window state: does maintaining a rolling memory of recent windows reduce duplicate paging during long incidents?

- **Why ICSE cares:** This is the §4.3 idea in `XX_AGENTIC_IDEA.md`; if it's not measured, reviewers will ask "what about repeated-window noise?".
- **What's needed:** Implement rolling state in the agent; measure pages-per-incident on OB synthetic (the only dataset with multi-window outages well-labeled). Target ≤ 1.5 pages-per-incident (currently ~6).
- **Estimated cost:** ~2–3 weeks engineering (system feature, not just experiment).
- **Status:** Stretch goal — could be future work depending on ICSE-deadline pressure.

---

## 4. Summary table — RQ × evidence × status

Quick-lookup. "Cost" = approximate engineering + compute time, not wall-time across humans.

| ID | Question (single sentence) | Bucket | Evidence on disk? | Cost to close |
|---|---|---|---|---|
| A1 | Retrieval system finds right past Jira ticket on OB | A | ✓ TCH headline numbers | — |
| A2 | Hit@5 scales with deployment-history depth (OB) | A | ✓ anchor figure | — |
| A3 | Which channels carry retrieval signal (logs critical) | A | ✓ CHANNEL-ABLATION.md | — |
| A4 | Distractor-noise graceful degradation | A | ✓ MODE1-DISTRACTOR-RESULTS.md | — |
| A5 | Cross-domain novelty detection precision | A | ✓ MODE2-NOVELTY-RESULTS.md | — |
| A6 | Retrieval transfers to real Apache Jira (cross-project) | A | ✓ MODE3-TCH-LITE-WoL-RESULTS.md | — |
| A7 | Multi-retriever fusion beats best single retriever | A | ✓ MODE3 §3.8 | — |
| A8 | LLM-verifier degrades cross-domain (negative finding) | A | ✓ MODE3 §3.9 | — |
| A9 | System cost / latency end-to-end | A | partial — logs | — |
| B1 | Zero-shot transfer to OTel Demo | B | data only, no run | ~6 h |
| B2 | Depth-scaling on real Apache Jira | B | predictions on disk | ~1 h analysis |
| B3 | Adaptive tool-selection cuts cost without accuracy loss | B | needs agent system | ~1–2 weeks |
| B4 | Query reformulation recovers Hit@1 misses | B | failure analysis only | ~2–3 weeks |
| B5 | Mode 4 cross-corpus (WoL Kafka × OTel Demo Kafka) | B | both datasets on disk | ~3 h |
| B6 | Cascade composition vs best-single on WoL | B | 5 prediction JSONLs cached | ~3 h |
| C1 | Statistical envelope (bootstrap CIs) on headline | C | none | ~2 h |
| C2 | Hyperparameter sensitivity sweep | C | none | ~1 day |
| C3 | Latency / cost-per-window quantified | C | partial in logs | ~half day |
| C4 | Comparison to BM25-only baseline | C | none | ~half day |
| C5 | Skill-ablation under the agentic system | C | needs agent | ~½ day post-agent |
| C6 | Failure-mode categorical distribution | C | predictions on disk | ~half day per dataset |
| C7 | Cross-window state reduces pages-per-incident | C | needs agent state | stretch goal |

---

## 5. What this list deliberately excludes

To keep the list tight:

- **Non-claims from the locked charter** stay non-claims: memory improving anomaly detection (refuted), production-readiness, outperforming commercial observability tools, solving cold-start (vs *characterizing* it), "humanized Jira is indistinguishable from real Jira".
- **Mode 4 expansion beyond Kafka** is bookmarked as future work — the WoL plan §8 framed Kafka as the natural anchor; expanding to Cassandra × Cassandra OTel etc. is its own research arc.
- **Comparison to commercial AIOps tools** is explicitly out of scope (RESEARCH-CHARTER non-claims).
- **LLM cost analysis at scale** beyond per-window latency is not in scope here — would need a separate observability-cost study.

---

## 6. Cross-references

- **Locked charter (binding):** `RESEARCH-CHARTER.md` (repo root); summary in `[[project-research-charter-locked]]` memory.
- **Cascade end-state spec (internal-only for the paper):** `docs6/X_FINAL_TCH_CASCADE.md`.
- **Agentic system design proposal:** `docs6/XX_AGENTIC_IDEA.md`; the agentic redesign that will replace the cascade in the paper narrative is being written next at `docs7/AGENTIC-SYSTEM.md` (to follow this catalogue).
- **WoL plan (modes 1/2/3 done, Mode 4 bookmarked):** `docs7/REAL-DATA-WoL-PLAN.md`.
- **Mode results (Bucket A evidence):** `docs7/MODE1-DISTRACTOR-RESULTS.md`, `docs7/MODE2-NOVELTY-RESULTS.md`, `docs7/MODE3-TCH-LITE-WoL-RESULTS.md`, `docs7/CHANNEL-ABLATION.md`.
- **Paper draft headline structure:** `technical-paper/sections/` and `[[reference-technical-paper-structure]]` memory.

---

*Generated 2026-06-12 as the planning input for the agentic-system redesign. Bucket A is the floor we can defend immediately; Bucket B is what closes naturally once the OTel Demo + agentic system are built; Bucket C is what protects the paper against reviewer pushback.*
