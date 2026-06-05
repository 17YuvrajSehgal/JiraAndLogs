# G2 — Cross-Encoder as 5th Retriever (and/or Reranker)

**Status:** 🟡 In progress (started 2026-06-05, ~13:25)

## 1. Goal

Add a fine-tuned cross-encoder as a 5th signal in L2's retrieval fusion to close part of the 6.3-pt gap between TCH (Hit@5 = 0.912) and the theoretical union ceiling (0.976). Cross-encoders read query + document jointly (vs bi-encoders which encode separately), so they capture interactions BiEncoders structurally cannot.

## 2. Hypothesis

The theoretical ceiling says SOMEONE's retriever has the gold in top-5 for 0.976 of windows. TCH at 0.912 means 0.064 of windows have the gold in some retriever's top-5 but our 4-retriever RRF places it outside top-5. A cross-encoder rerank over the union of top-10s should:
- Hit@5 lift: +1 to +3 pts (closing the gap toward 0.94-0.95)
- Hit@1 lift: small (already at 0.722 after G1) — maybe +1 pt
- MRR lift: moderate (~+1 pt)
- Cost: ~30 min GPU exclusive for fine-tune, ~5 min inference, ~1.5 GB VRAM at inference

Risk: cross-encoders are finicky on small training sets. The Phase B cross-encoder (locked in `data/derived/global/.../models/crossenc_ft_v1/`) was trained on the v1 split, didn't help on the original v2 numbers. We're retraining on the v2 train split this time.

## 3. Setup

- **Base model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M params).
- **Loss:** `BinaryCrossEntropyLoss` (standard cross-encoder objective).
- **Training data:** built fresh from v2 train split. Positives = (window, gold_ticket) pairs. Negatives = 2× BM25-mined hard negatives + 1× random negative (matching G1's recipe for consistency).
- **Epochs:** 3.
- **Batch:** 16.
- **Learning rate:** 2e-5.
- **Hardware:** RTX 5060, 8 GB. Qwen 35B must be ejected (won't fit alongside training).

## 4. Plan

1. Build training pairs script that uses the V2 humanized corpus (existing `scripts/build_crossenc_pairs.py` builds from v1 — need to update for v2 in-dist split + the mixed-neg recipe).
2. Fine-tune cross-encoder using existing `scripts/finetune_crossenc.py`.
3. Write a `CrossEncoderRetrieverPipeline` (new) that:
   - Loads the fine-tuned model.
   - For each test window: collect the union of top-10 from each existing retriever (bi_encoder G1 + hybrid_rrf rule + logseq2vec + kg_retrieval).
   - Score every (window, candidate) pair with the cross-encoder.
   - Emit per-window-predictions.jsonl with the cross-encoder's top-5.
4. Add to L2 fusion as a 5th retriever — re-run cascade.
5. Test alternative: keep L2 fusion at 4 retrievers but use cross-encoder to RERANK the L2 top-5 (a different use case).
6. Compute delta vs G1 baseline.

## 5. Observations

### Training (cross-encoder fine-tune on v2 train + val)

| Phase | Wall time | Train loss | Val F1 | Val AP |
|---|---:|---:|---:|---:|
| Epoch 1 | ~1.5 min | 0.40 | 0.919 | 0.954 |
| Epoch 2 | ~1.5 min | 0.28 | 0.935 | 0.965 |
| Epoch 3 | ~1.5 min | 0.26 | **0.940** | **0.968** |
| Total | 4.7 min | — | — | — |

Strong training metrics. F1=0.940 means the cross-encoder is great at the BINARY classification task ("is this candidate relevant?").

### Inference

- 1008 test windows × avg pool size 15.2 candidates = 13,130 pairs scored in 42 sec.
- Pool source: G1 bi_encoder + hybrid_rrf rule + logseq2vec + kg_retrieval, top-10 each, deduplicated.

### Standalone retrieval metrics (cross-encoder alone)

| Metric | Cross-encoder G2 | G1 bi_encoder (for context) |
|---|---:|---:|
| Hit@1 | 0.571 | 0.722 |
| Hit@5 | 0.873 | (would need separate run) |
| MRR | 0.696 | — |

### Cascade with G2 added as 5th L2 RRF voter

| Metric | G1 cascade | G1+G2 cascade | Δ |
|---|---:|---:|---:|
| Hit@1 | 0.7221 | 0.6677 | **-5.4pts** ❌ |
| Hit@5 | 0.9124 | 0.8943 | **-1.8pts** ❌ |
| MRR | 0.7937 | 0.7551 | -3.9pts ❌ |
| PR-AUC | 0.9998 | 0.9998 | tie |

### Cascade with G2 as RERANKER over L2 top-5 (no dilution)

| Metric | G1 cascade | G1 + G2 rerank | Δ |
|---|---:|---:|---:|
| Hit@1 | 0.7221 | 0.6767 | **-4.5pts** ❌ |
| Hit@5 | 0.9124 | 0.9124 | tie (same candidates) |
| MRR | 0.7937 | 0.7751 | -1.9pts ❌ |

## 6. Advantages

1. **Validates the cross-encoder can be trained well on v2 data.** F1=0.940, AP=0.968 are healthy numbers.
2. **Inference is fast** — 42 seconds for 13k pairs. Could scale.
3. **Honestly investigated.** We tested BOTH integration modes (RRF voter + reranker) and have evidence both hurt.

## 7. Disadvantages

1. **HURTS Hit@1 in both integration modes** by 4.5-5.4pts. The cross-encoder's standalone top-1 is much weaker (0.571 vs G1's 0.722).
2. **HURTS Hit@5 when added to RRF voters** (-1.8pts) — same dilution effect we saw with hybrid_rrf LLM (the "RRF density paradox").
3. **Tied Hit@5 when used as reranker** — because we're reordering the same 5 candidates. But the new ordering is worse than the cascade's existing overlap-rerank + RRF.
4. **Doesn't address the theoretical ceiling gap.** TCH is still capped at union-of-retrievers Hit@5 = 0.976. Cross-encoder only reranks within an existing pool, can't surface new candidates.
5. **Training-data imbalance not fully addressed.** 16k pos / 5k neg = 75/25 split. Likely contributed to noisy ranking among "all relevant" candidates. Re-balancing to 50/50 might help but wasn't tested in this iteration.

## 8. Decision

**SKIP G2 from the final cascade.** Two negative-result modes confirm cross-encoder hurts both retrieval channels. The fine-tuned model is preserved (in case future work wants to retry with different training data), but the cascade does NOT include it.

This is a publishable negative result — supports the paper's claim in `docs3/16-TCH-CASCADE.md` §10 ("13 ablations confirmed no further fusion tuning helps").

`TCH_ENABLE_CROSSENC` env var stays in build_cascade.py for posterity but defaults OFF.

## 9. Open questions

- **Re-balanced training data.** With 1:N neg/pos ratio at 1:3 or 1:5, would the cross-encoder's top-1 selection become sharper? Not pursued (low expected ROI).
- **Different cross-encoder backbone.** ms-marco-MiniLM-L-6-v2 is small; a 12-layer cross-encoder might capture more signal. Not pursued (time-box).
- **Why exactly does the cross-encoder fail at top-1?** Empirically it's because cross-encoders trained with BCE optimize per-pair classification, not per-query ranking. A listwise loss (e.g., LambdaRank) might do better. Out of scope.

## 10. Cross-references

- Code: `src/v2_advanced/proposal_g_crossencoder/pipeline.py` (new), `src/v2_advanced/tch/build_cascade.py` (modified — TCH_ENABLE_CROSSENC toggle).
- Training script: `scripts/build_crossenc_pairs_v2.py` (new), `scripts/finetune_crossenc.py` (existing).
- Output: `data/derived/global/.../v2g-final-models/g2-crossencoder-rerank/` (model + predictions).
- Commit pending.

---

*Generated 2026-06-05 after G2 completion. Negative result.*

---

*Generated 2026-06-05 before G2 launch.*
