# FINAL — `master-final-models` G-Series Summary

**Date locked:** 2026-06-06
**Branch:** `master-final-models`
**Baseline:** `v2f-tch-phase1` (locked 2026-06-01)

---

## Headline

> **The TCH cascade with G1+G4+G7 integrated lifts novel recall from 0.163 to 0.793 (+388% rel) at preserved novel precision (0.940), while keeping all retrieval/triage metrics within ±2.1% of the v2f baseline. The win is robust to memory-noise distractors (Hit@5 −2% rel at 50% ratio) and to family-distribution shift (F1 −11.4% rel under leave-one-family-out).**

## Final cascade configuration

```bash
TCH_OVERRIDE_BIENC="v2g-final-models/g1-bienc-hard-negatives/predictions-bienc.jsonl"
TCH_EXTRA_AGENT_FILES="v2g-final-models/g4-agent-phase3/per-window-predictions.jsonl"
TCH_LEARNED_NOVELTY_PATH="v2g-final-models/g7-learned-novelty/learned_novelty.jsonl"
TCH_LEARNED_NOVELTY_THRESHOLD=0.50
```

Cascade output: `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/`

## Final metrics vs v2f baseline

| Metric | v2f baseline | Final cascade | Δ rel |
|---|---:|---:|---:|
| Hit@1 | 0.7069 | **0.7221** | **+2.1%** |
| Hit@5 | 0.9124 | 0.9124 | tie |
| MRR | 0.7880 | **0.7937** | **+0.7%** |
| PR-AUC strict | 0.9998 | 0.9998 | tie |
| PR-AUC inclusive | 0.8527 | **0.8562** | **+0.4%** |
| Novel precision | 0.9402 | 0.9405 | tie |
| **Novel recall** | **0.1625** | **0.7932** | **+388%** |

## Per-phase verdict table

| Phase | What we tried | Δ vs baseline | Verdict |
|---|---|---|---|
| G1 | BiEncoder fine-tune w/ BM25 hard negs + random negs | Hit@1 +2.1% rel, novelty unchanged | **KEEP** |
| G2 | Cross-encoder reranker as 5th retriever | Hurts cascade Hit@5 (−5pt in fusion mode) | SKIP |
| G3 | Symmetric LLM extraction (windows too) | Standalone kg +404% Hit@1, cascade integration breaks | SKIP |
| G4 | Agent Phase 3 — remaining 658 windows | Novel recall +119% rel, retrieval tied or up | **KEEP** |
| G5 | LLM judge reranker | Judge confidence uninformative (84% = 0.85); overrides hurt Hit@1 | SKIP |
| G6 | Distractor ratio sweep (simulated) | Hit@5 ≤ 2% rel drop at 50% noise | **KEEP** (analysis) |
| G7 | Learned per-window novelty threshold (LogReg) | Novel recall +388% rel at preserved precision | **KEEP** |
| G8 | OOD eval (leave-one-family-out) | F1 within 11.4% rel of in-distribution | **KEEP** (analysis) |

## What the publishable narrative is

1. **The biggest single-phase win is G7 (learned novelty threshold).** Replacing a fixed `ret_conf < 0.5` heuristic with a learned LogReg over per-window features yields the largest novelty-recall lift of the entire G-series, at zero cost to retrieval and zero LLM inference cost.

2. **The cascade is a local optimum that resists naïve reranking.** Three independent reranking interventions (G2 cross-encoder, G5 LLM judge, and partial Phase E agent) all failed to lift Hit@K despite standalone wins — strong evidence that the overlap-rerank consensus in L4 is already extracting most of the rerankable signal.

3. **Standalone wins don't always survive cascade integration.** G3 demonstrated this most clearly: KG retrieval gained +404% rel Hit@1 standalone but degraded the cascade by shifting 99% of top-5 votes (overlap-rerank instability) and breaking the L4 score-scale calibration. **Publishable negative result.**

4. **The cascade is robust** to two of the most-common deployment concerns: memory noise (G6, Hit@5 −2% at 50% distractor ratio simulated) and family-distribution shift (G8, F1 −11% rel under leave-one-family-out).

5. **Novelty is decomposable but recall on truly cold families is the open problem.** G8 shows the OOD recall failure mode is structural: families dominated by `active_fault` windows lose 30–50pts recall when held out, while families with strong `window_type` priors (baseline, recovery, restart) generalize perfectly. A richer family representation would likely close most of the gap.

## Files and locations

| Artifact | Path |
|---|---|
| Final cascade metrics | `comparison/v2g-final-models/final/tch_metrics.json` |
| Final per-window predictions | `comparison/v2g-final-models/final/per-window-predictions.jsonl` |
| Final headline | `comparison/v2g-final-models/final/headline-final.json` |
| Per-phase observation docs | `docs4/G1-…md` through `docs4/G8-…md` |
| Index | `docs4/00-INDEX.md` |

## What's intentionally NOT in this branch

- Smaller LLM (Phase 4 of original plan) — skipped per user direction
- Real-Jira corpus (Phase 8 of original plan) — skipped per user direction
- New corpus collection — out of scope for master-final-models

These are tracked separately on different branches / deferred to future work.

## Deployment guidance

For an organization considering deploying this cascade:

- **Default (in-distribution families):** threshold 0.50. F1 0.861, novel precision matches v2f baseline.
- **OOD-robust (new families expected):** threshold 0.30. F1 0.788, recall 0.78, precision 0.79. Still beats v2f baseline by +381% rel on novel recall.
- **Strict precision:** threshold 0.60–0.70. F1 ~0.87, precision ≥ 0.99.

The threshold is a deployment-time knob; the model itself need not change.

---

*Locked 2026-06-06 on `master-final-models`. End of G-series.*
