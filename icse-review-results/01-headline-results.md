# Headline results — what we can claim

All numbers verified against their source file. Re-check with
`python scripts/v2/verify_claims.py` (19/19 passing as of 2026-10-27).

---

## 1. Fusion margin — seed-matched, 5 seeds each

The single most important result. Replaces the published "+0.065 Hit@5,
95% CI [+0.058,+0.073]", which compared one run to one run with a
query-bootstrap CI that ignored training-seed variance.

`paper-results-v2/multiseed{,-hybrid}/wol-v3/` · `scripts/v2/fusion_margin_seedmatched.py`
n = 5,150 queries, seeds 42/1/2/3/4

| Metric | Bi-encoder | Hybrid | Paired margin | 95% CI (t, df=4) | Ranges |
|---|---|---|---|---|---|
| coarse Hit@5 | 0.9190 | 0.9742 | **+0.0553** | [+0.0353, +0.0752] | **separated** +0.0245 |
| strict Hit@5 | 0.4907 | 0.7646 | **+0.2739** | [+0.2485, +0.2993] | **separated** +0.2212 |
| coarse Hit@1 | 0.8757 | 0.8350 | **−0.0408** | [−0.0685, −0.0130] | overlap |
| coarse MRR | 0.8905 | 0.8991 | +0.0087 | [−0.0149, +0.0322] | overlap |

Per-seed coarse Hit@5:

| seed | bi-enc | hybrid | delta |
|---|---|---|---|
| 42 | 0.8981 | 0.9701 | +0.0720 |
| 1 | 0.9014 | 0.9711 | +0.0697 |
| 2 | 0.9456 | 0.9788 | +0.0332 |
| 3 | 0.9229 | 0.9763 | +0.0534 |
| 4 | 0.9268 | 0.9748 | +0.0480 |

**Claimable:**
- Fusion significantly improves top-5 retrieval under both relations.
- *Every* hybrid seed beats *every* bi-encoder seed on both Hit@5 relations —
  a distribution-free statement, stronger than the mean difference.
- Fusion **significantly hurts Hit@1** (−0.041, CI excludes 0). This is a
  trade-off, not a clean win. The submission showed 0.839 vs 0.856 and passed
  over it; five seeds make it a real finding.
- Hybrid is **5.4× more seed-stable** than the bi-encoder (sd 0.0036 vs 0.0196).
  Fusing three retrievers damps the trained component's noise.

**Suggested framing:** fusion buys recall and stability at the cost of top-1
precision. Which matters depends on whether the consumer is a human scanning
five candidates (Hit@5) or an automated handoff (Hit@1).

---

## 2. Strict-relation leaderboard — full 9-system panel

`paper-results-v2/strict-leaderboard.json` · `scripts/v2/strict_leaderboard_full.py`
n = 4,362 queries scored by all nine systems.

| Method | Hit@1 | Hit@5 | MRR@5 |
|---|---|---|---|
| **Hybrid fusion (ours)** | **0.511** | **0.744** | **0.602** |
| BM25 (raw corpus) | 0.015 | 0.740 | 0.332 |
| TF-IDF | 0.445 | 0.715 | 0.549 |
| BGE (zero-shot) | 0.474 | 0.706 | 0.564 |
| E5 (zero-shot) | 0.450 | 0.698 | 0.544 |
| Cross-encoder rerank | 0.418 | 0.694 | 0.523 |
| MPNet (zero-shot) | 0.444 | 0.667 | 0.530 |
| Dense bi-encoder (ours) | 0.260 | 0.523 | 0.356 |
| Knowledge graph (ours) | 0.016 | 0.036 | 0.023 |

**23 of 24 paired comparisons significant** after Benjamini–Hochberg. Sole
exception: Hit@5 vs raw-corpus BM25 (+0.004, CI [−0.011,+0.019], q=0.54) — a
method with Hit@1 0.015, i.e. a degenerate top-rank ordering, beaten on MRR by
+0.271.

Calibration reference points (quote these so readers can judge the scores):
random ranker expected Hit@5 = **0.036 coarse**, **0.0044 strict**.

---

## 3. Triage on real incidents — text, not zero-filled features

`paper-results-v2/triage-text/wol-v3/` · `scripts/v2/wol_text_triage_panel.py`
Leave-domain-out (train 21 projects / test Kafka+MariaDB), 5 seeds.

| Input | Model | ROC-AUC | PR-AUC | Accuracy |
|---|---|---|---|---|
| zero-filled numeric *(as published)* | HGB/RF/LogReg | 0.500 | 0.506 | 0.506 |
| ticket text | LogReg | 0.572 | 0.564 | 0.528 |
| ticket text | **Linear SVM** | **0.601** [0.592, 0.611] | 0.584 | 0.523 |
| ticket text | HGB + SVD | 0.583 | 0.569 | 0.552 |
| telemetry (OB / OTel) | HGB | 1.000 | 1.000 | — |

Strict binarization (TW vs noise, borderline dropped, n=8,024): best ROC-AUC
**0.704** [0.688, 0.721], majority accuracy 0.844.

**Claimable:** real-incident triage from text is weakly learnable (ROC 0.57–0.70
depending on binarization, CI excludes 0.500) but retains little of the signal
injected telemetry provides (1.000), and does not beat majority at the operating
threshold. Robust to the binarization choice.

---

## 4. LLM-as-judge with hard negatives

`paper-results-v2/gold-validation/wol-v3/judge-v2-results.json` ·
`scripts/v2/llm_judge_hard_negatives.py`
300 queries × 3 conditions = 900 single-blind calls, shuffled order,
Qwen2.5-7B-Instruct, greedy, seed 42.

| Candidate | Mean | ≥4 | ≥3 |
|---|---|---|---|
| System top-1 | **3.65** | **39.0%** | **94.0%** |
| Hard negative (same project, most lexically similar non-gold) | 3.10 | 25.3% | 79.3% |
| Uniform control *(old protocol)* | 1.32 | 0.0% | 15.7% |

System vs hard negative: **+0.55**, 95% bootstrap CI [+0.36, +0.73]; paired sign
test 121 W / 47 L / 132 T, **p ≈ 1e-8**.

**Claimable:** the system's actual top-1 beats a confusable same-project
alternative, which is the comparison R2 asked for. Contrast with the old
protocol: only **6.3%** of coarse-*gold* pairs rated ≥4, but **39.0%** of the
system's actual top-1 — a gold match is an arbitrary member of a large relevant
set; the system returns the one it ranks highest.

**Must report alongside:** the hard negative scores 3.10 itself (same-project
tickets are often somewhat related, so the achievable gap is narrow), and the
judge's effective scale is coarse — on system output it emits only 1/3/5
(6.0% / 55.0% / 38.3%), using 4 twice. "Rated ≥4" means "rated 5".

---

## 5. Seed variance and reproducibility

`paper-results-v2/multiseed/` · `scripts/v2/seed_variance_decomposition.py`

| Dataset | Hit@5 mean ± sd (5 seeds) | Range | Seed share of variance |
|---|---|---|---|
| Online Boutique | 0.6356 ± 0.0161 | 0.0393 | **28%** |
| OTel Demo | 0.6756 ± 0.0046 | 0.0084 | 1% |
| World of Logs (bi-encoder) | 0.9190 ± 0.0196 | 0.0476 | — |
| World of Logs (hybrid) | 0.9742 ± 0.0036 | 0.0087 | — |

Also: Hit@1 is less stable than Hit@5 on Online Boutique (range 0.051 vs
0.039), so single-seed top-1 comparisons on the small corpora need caution.

**Reproduction:** all five zero-shot baselines reproduced their published
coarse numbers **exactly** on different hardware months later — tfidf
0.5212/0.7662/0.6262, mpnet 0.6437/0.8340/0.7254, bge 0.6229/0.8287/0.7099,
e5 0.6394/0.8381/0.7250, ce 0.6858/0.8740/0.7663. Three pre-existing telemetry
seeds also reproduced exactly.

---

## 6. Cost

`paper-results-v2/cost/` · `scripts/v2/cost_measured_vs_modelled.py`

Reported saving 40% / 63% / 78% is **counts × a modelled per-skill cost table**,
not a wall-clock measurement. Measured: 75,334 skill invocations and 31,734 gate
skips on WoL. Modelled: the per-call costs.

Robustness: recomputing with each skill's **measured** mean duration as its unit
cost gives **79.0%** vs the modelled **77.9%** — 1.1 points apart, despite the
table misstating `reformulate_query` by ~8,700× and understating
`request_similar_incident_window` (the only real-I/O step) by 68× (204 ms
measured vs 3 ms modelled). Reason: every gated skill sits behind the *same*
gate, so the saving tracks that gate's closure rate nearly independently of unit
costs.

**Do not** replace it with the harness's measured wall-clock (43 ms/window):
the harness replays cached predictions, so that is the cost of replaying a
decision, not making one.
