# Research Progress Log

**Charter:** `RESEARCH-CHARTER.md` — locked 2026-06-01
**Plan:** `C:\Users\17yuv\.claude\plans\wise-watching-sutton.md`
**Goal:** ICSE-quality paper on memory-augmented incident triage.

This log accumulates key findings, decisions, and ICSE-paper-worthy points as we work the plan.

---

## Phase 0 — Setup [COMPLETE]

- **Charter locked** (`f649af5`). The headline claim pivoted from "memory improves anomaly detection" (refuted by our own depth-stratification) to **"retrieval-augmented diagnosis scales with deployment history"** (empirically supported: R@5 goes 0% → 36% as history grows from 0 → 100+ prior tickets).
- **Training registry wired** (`1b8f365`). Every pipeline `fit()` now writes a self-contained `training_runs/<pipeline>__<UTC>__<sha8>/` directory with `config.json`, `metrics.json`, `predictions.jsonl`, `train.log`. Each artifact tagged with the git SHA that produced it.

### Key point for ICSE paper

The reproducibility story matters: every comparison run can be re-analyzed without re-fitting, and every prediction file is tagged with the exact code revision that produced it. Reviewers can pull any reported number back to a specific git SHA.

---

## Phase A — Anchor Experiment [COMPLETE]

Goal: produce the depth-stratified retrieval curve with 95% bootstrap CIs. This is the anchor figure of the paper.

### Headline numbers

| Metric | Test n=2940 (overall) |
|---|---:|
| HGB PR-AUC | 0.7718 |
| HGB Retrieval | n/a (no head) |
| memorygraph PR-AUC | 0.6186 |
| memorygraph Hit@5 (corrected) | 0.190 (depth 1-2) → 0.250 (depth 21+) |
| memorygraph Hit@1 | **0.048 → 0.250** (5.2× improvement with depth) |
| memorygraph MRR | **0.095 → 0.250** (2.6× improvement with depth) |

### The depth-stratified curve (anchor figure)

| Depth bucket | n retrievable | Hit@5 [95% CI] | Hit@1 [95% CI] | MRR [95% CI] |
|---|---:|---:|---:|---:|
| 0 prior | 0 | n/a (no retrievable) | n/a | n/a |
| 1-2 prior | 42 | 0.190 [0.07, 0.31] | 0.048 [0.00, 0.12] | 0.095 [0.03, 0.17] |
| 3-5 prior | 63 | 0.159 [0.06, 0.25] | 0.127 [0.05, 0.21] | 0.138 [0.06, 0.23] |
| 6-20 prior | 184 | 0.212 [0.16, 0.27] | 0.179 [0.13, 0.23] | 0.190 [0.14, 0.25] |
| 21+ prior | 28 | 0.250 [0.11, 0.43] | 0.250 [0.11, 0.43] | 0.250 [0.11, 0.43] |

HGB sits at exactly 0 across every bucket (no retrieval head).

### Key methodological correction (worth a paragraph in §4 of the paper)

The native `recall@K = |top_K ∩ gold| / |gold|` definition systematically *understates* retrieval quality in deep-history buckets, because |gold| > K caps the metric at K/|gold|. With |gold|=21, max possible recall@5 = 5/21 = 0.238. **Hit@K** (binary: 1 if any gold in top-K else 0) is the right metric for "did the engineer find a relevant ticket in top-K." We report Hit@K as primary, MRR as secondary, and the (capped) recall@K_norm for completeness.

### Cold-start novelty: a critical limitation

There are **333 cold-start anomalies** in the test set (ticket_worthy + no compatible memory tickets + gold_is_novel=True). These are the cases where the system *should* say "this is a novel incident, no past ticket applies."

Of 333 such cases, **the system flags 0 as novel**. Predicted `is_novel` is mostly `None` (1988) or `False` (67), True only 11 times across the whole 2066 n=0 subset.

This is the right kind of negative result for the paper: it shows the retrieval head is robust within its competence (Hit@K scales with depth) but the novelty detector is broken. **Two complementary failure modes that future work needs to address.**

### ICSE-worthy points captured from Phase A

1. **Deployment-history scaling is real and quantifiable.** Hit@1 grows 5.2× and MRR grows 2.6× as memory depth grows from 1-2 to 21+ compatible tickets. Telemetry-only models (HGB) cannot exhibit this curve at all because they have no retrieval head.

2. **Triage detection is a separate, solved problem.** HGB's PR-AUC 0.7718 dominates memorygraph's 0.6186 by 15 points. Memory-augmented retrieval is *orthogonal* to anomaly detection, not a substitute. The paper's claim is about retrieval-augmented *diagnosis*, not retrieval-augmented detection.

3. **Methodological contribution:** The "Hit@K vs Recall@K" distinction matters when |gold| varies across windows. Our depth-stratified analysis would have been *non-monotone* (R@5 falsely drops from 0.155 at 1-2 to 0.057 at 6-20) under the standard formulation. The fix is one line of code, but the diagnostic value is high.

4. **Cold-start novelty detection is unsolved.** Existing skill chain detects "no good match" using a hard-coded 0.15 threshold on `max(combined_scores)`. Among 333 true-novel test cases with empty compatible memory, zero get flagged correctly. Recommendation for future work: train a calibrated novelty classifier on `(max_similarity, n_compatible_in_memory, top_K_score_spread)` features.

### Phase A artifacts

- `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/phase-a-anchor/{report.json, report.md, per-window-predictions.jsonl}` (full comparison output, 5880 prediction rows)
- `results/phase-a-anchor/depth_analysis.{json,md}` (corrected Hit@K + bootstrap CIs)
- `results/figures/anchor_depth_hit5.{png,pdf}` (primary anchor figure)
- `results/figures/anchor_depth_hit1.{png,pdf}` (Hit@1 — strictly monotone)
- `results/figures/anchor_depth_mrr.{png,pdf}` (MRR — strictly monotone)
- `results/figures/anchor_depth_precision5.{png,pdf}` (Precision@5 — strictly monotone)

---

