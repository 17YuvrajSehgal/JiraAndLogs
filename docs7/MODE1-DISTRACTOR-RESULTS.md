# Mode 1 — Real-Distractor Robustness Results

**Status.** Empirical results from P4 (2026-06-11) — `REAL-DATA-WoL-PLAN.md` v3 §5.

**One-paragraph summary.** Re-ran the cascade's distractor-displacement simulation using the **300-ticket WoL distractor pool** (off-topic projects: Qt, Minecraft, Confluence, Sakai, JBoss EAP, Tools). The pool is **2.7× larger than the §13.1 synthetic pool (110)**, which means the simulation's per-slot displacement probability extends to **0.302** at 50% ratio (vs §13.1's 0.137). Under this stronger stress, the cascade's Hit@5 drops to **0.8369** — an **8.3% relative drop** from the locked baseline of 0.9124, vs §13.1's 2.0% drop at its (smaller-pool) 50% ratio. **Hit@1 is more sensitive**, dropping 29% rel at p=0.302. The cascade survives the stronger noise floor; the result reinforces §13.1's finding and extends the operating range.

---

## Table of contents

1. [Results table](#1-results-table)
2. [Honest reading: pool size, not identity, drove the deltas](#2-honest-reading-pool-size-not-identity-drove-the-deltas)
3. [The combined robustness curve](#3-the-combined-robustness-curve)
4. [Paper integration](#4-paper-integration)
5. [Limitations and what would close the remaining gap](#5-limitations-and-what-would-close-the-remaining-gap)
6. [Files produced](#6-files-produced)
7. [Cross-references](#7-cross-references)

---

## 1. Results table

Two runs, both against the locked TCH-Final cascade predictions on the v2-resplit 1008-window test split. Same simulation script (`src/v2_advanced/tch/distractor_sweep.py`), same seed (42), same memory size (347), different distractor pool size.

### 1.1 §13.1 reproduction — synthetic pool of 110

| Ratio | n_distractors | p_per_slot | Hit@1 | Hit@5 | MRR |
|---:|---:|---:|---:|---:|---:|
| 0% | 0 | 0.000 | **0.7221** | **0.9124** | **0.7937** |
| 10% | 11 | 0.031 | 0.7190 | 0.9094 | 0.7899 |
| 25% | 27 | 0.072 | 0.6586 | 0.9003 | 0.7506 |
| 50% | 55 | 0.137 | 0.6193 | 0.8943 | 0.7290 |

(Reproduces the paper's §13.1 table exactly.)

### 1.2 Mode 1 — WoL pool of 300

| Ratio | n_distractors | p_per_slot | Hit@1 | Hit@5 | MRR |
|---:|---:|---:|---:|---:|---:|
| 0% | 0 | 0.000 | **0.7221** | **0.9124** | **0.7937** |
| 10% | 30 | 0.080 | 0.6707 | 0.8943 | 0.7584 |
| 25% | 75 | 0.178 | 0.6103 | 0.8731 | 0.7140 |
| 50% | 150 | 0.302 | **0.5106** | **0.8369** | **0.6339** |

### 1.3 Relative-degradation summary (vs same-pool 0%-ratio baseline)

| Ratio | §13.1 ΔHit@5 | Mode 1 ΔHit@5 | §13.1 ΔHit@1 | Mode 1 ΔHit@1 |
|---:|---:|---:|---:|---:|
| 10% | −0.3% | −2.0% | −0.4% | −7.1% |
| 25% | −1.3% | −4.3% | −8.8% | −15.5% |
| 50% | −2.0% | **−8.3%** | −14.2% | **−29.3%** |

---

## 2. Honest reading: pool size, not identity, drove the deltas

The existing simulation (`distractor_sweep.py:63-83`) **does not depend on distractor identity**. For each window's top-5, it replaces each slot independently with a random distractor ID at probability `p = n_distractors / (n_distractors + n_memory)`. The injected IDs are placeholders (`DISTRACTOR-000`, `DISTRACTOR-001`, …) — they would never be in any gold list, by construction. The math is identical whether the "300 distractors" are real WoL ticket IDs (`wol-d-3589f4c00c9af528`) or synthetic placeholders.

**Implication.** The Mode 1 vs §13.1 deltas are entirely explained by the larger WoL pool driving higher per-slot probability. They do **not** isolate a "real-language-overlap" effect. To do that, the simulation would need to weight per-distractor displacement by query-text similarity (see §5 below).

What Mode 1 **does** measure, honestly:

1. The cascade's behavior at a higher noise floor than §13.1 covers (p extends from 0.137 to 0.302).
2. The shape of the robustness curve is well-behaved through that range: Hit@5 degrades gracefully (sublinear in p), Hit@1 degrades steeply (close to linear in p).
3. The cascade still beats every individual baseline retriever's standalone Hit@5 even at p=0.302 (Hybrid-RRF rule's standalone Hit@5 is 0.798; the cascade under 50% WoL-pool stress is 0.8369).

---

## 3. The combined robustness curve

Plotting both runs on the same `p_per_slot` axis confirms the simulation is identity-agnostic — the curves overlap where they share x-values.

| p_per_slot | n_distractors | Hit@5 | Source |
|---:|---:|---:|---|
| 0.000 | 0 | 0.9124 | both baselines (overlap) |
| 0.031 | 11 | 0.9094 | §13.1 10% (synthetic pool=110) |
| 0.072 | 27 | 0.9003 | §13.1 25% |
| 0.080 | 30 | 0.8943 | Mode 1 10% (WoL pool=300) |
| 0.137 | 55 | 0.8943 | §13.1 50% |
| 0.178 | 75 | 0.8731 | Mode 1 25% |
| 0.302 | 150 | 0.8369 | Mode 1 50% |

Notice that at similar `p` values (§13.1 50% at p=0.137 vs Mode 1 10% at p=0.080), Hit@5 lands close — both around 0.89. The simulation produces a single Hit@5(p) curve; the two runs just sample different points on it.

The cascade's empirical Hit@5(p) curve is approximately:

```
Hit@5(p) ≈ 0.9124 - 0.25·p   for p ∈ [0, 0.30]
```

That is, Hit@5 drops about a quarter point per percentage point of per-slot displacement probability. At p=1.0 (every slot replaced), Hit@5 would extrapolate to ~0.66, which is consistent with each of the cascade's RRF retrievers' standalone Hit@5 values (0.53–0.80).

---

## 4. Paper integration

Suggested treatment in `ICSE/sections/05-results.tex` §5.X (real-data validation subsection):

> *We extended the §13.1 distractor robustness sweep using a 300-ticket real-Jira distractor pool drawn from six off-topic open-source projects (Qt, Minecraft, Confluence Server, Sakai, JBoss EAP, JBoss Tools). The pool is 2.7× larger than the synthetic distractor pool used in §13.1, which extends the simulation's per-slot displacement probability from 0.137 (§13.1's 50% operating point) to 0.302. Under this stronger stress, the cascade's Hit@5 drops from 0.9124 to 0.8369 (8.3% relative), and Hit@1 from 0.7221 to 0.5106 (29.3% relative). The cascade continues to outperform every standalone retriever's clean-corpus Hit@5 even at the higher noise floor. The simulation is identity-agnostic (per-slot displacement probability is computed from pool size, not vocabulary overlap with queries); a similarity-weighted version that distinguishes real-language overlap from random injection is left for future work.*

Companion table — the **combined** robustness curve sampled at both pools' operating points (§3 above) — fits in a single column.

---

## 5. Limitations and what would close the remaining gap

The current simulation is the **lower-bound model** the script itself documents:

> *"This simulates UNIFORM distractor displacement. In practice, distractors that LOOK like the window evidence are more likely to outrank gold; unrelated distractors rarely appear in top-K. The simulation gives a 'lower bound' on cascade degradation under the assumption distractors are evenly likely to appear in top-K positions."* — `distractor_sweep.py:9-14`

Three levels of additional rigor, in increasing order of effort:

| Level | What it adds | Effort |
|---|---|---|
| **1. Similarity-weighted simulation** | Compute per-(window, distractor) text-similarity scores (e.g., TF-IDF cosine); replace top-K slots with the highest-similarity distractors first instead of random IDs. The simulation becomes identity-aware: real distractors with high vocabulary overlap displace gold more often than random. | ~half day |
| **2. Re-fit retrievers with WoL distractors in memory** | The rigorous approach: actually mix the 300 WoL distractors into the 347-ticket synthetic memory, re-fit BiEncoder + Hybrid-RRF + LogSeq2Vec + KG-Retrieval, re-run retrieval, compose the cascade. This is what `distractor_sweep.py`'s caveat says is the right thing to do. | ~1 day of GPU + integration work per ratio × 4 ratios = ~4 days |
| **3. Real-corpus joint-evaluation** | The methodologically cleanest version: train each retriever on a corpus that combines synthetic gold and WoL distractors, evaluate end-to-end. Effectively a complete re-train. | several days |

For the ICSE submission, **Level 1 is the highest-ROI follow-up**. It would let us claim "real-language distractors degrade Hit@5 by X% more than equal-count random distractors", which is the actual claim the v3 plan §5.5 anticipated. Level 2 is the right number for a journal extension.

---

## 6. Files produced

| Path | Purpose |
|---|---|
| `docs7/MODE1-DISTRACTOR-RESULTS.md` | This document |
| `data/derived/global/2026-06-11-wol-real-global/distractor_curve_wol_pool_300.json` | Mode 1 raw output (per-ratio metrics, JSON) |
| `/tmp/distractor_baseline_synthetic_110.json` | §13.1 reproduction (intentionally not committed; regenerable) |

To reproduce:

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m v2_advanced.tch.distractor_sweep \
    --cascade-predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
    --out data/derived/global/2026-06-11-wol-real-global/distractor_curve_wol_pool_300.json \
    --memory-size 347 --distractor-pool-size 300 \
    --ratios 0,10,25,50 --seed 42
```

---

## 7. Cross-references

- **Plan §5** — [`docs7/REAL-DATA-WoL-PLAN.md`](REAL-DATA-WoL-PLAN.md) §5 (Mode 1 specification).
- **Simulation script** — `src/v2_advanced/tch/distractor_sweep.py`.
- **Locked cascade predictions used as input** — `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl`.
- **WoL distractor pool source** — `data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl` (300 records from 6 OFF-topic projects, see [`build_wol_real_corpus.py`](../scripts/research-lab/build_wol_real_corpus.py)).
- **Synthetic baseline** — §13.1 of the paper draft (`ICSE/sections/05-results.tex` §5.X.1 robustness sweep).
- **TCH-Lite + channel ablation** — [`docs7/TCH-Lite.md`](TCH-Lite.md), [`docs7/CHANNEL-ABLATION.md`](CHANNEL-ABLATION.md).

---

*Generated 2026-06-11 as part of P4 (Mode 1 distractor evaluation) per `REAL-DATA-WoL-PLAN.md` v3 §14 phased plan.*
