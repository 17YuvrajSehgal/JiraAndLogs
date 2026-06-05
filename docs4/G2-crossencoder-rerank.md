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

_(To be filled in after run completes.)_

## 6. Advantages

_(To be filled in.)_

## 7. Disadvantages

_(To be filled in.)_

## 8. Decision

_(To be filled in.)_

## 9. Open questions

- Is the cross-encoder better as a 5th RRF voter, or as a final reranker over L2's top-5?
- Does the cross-encoder need a different training-data builder than the bi_encoder (e.g., different negative-sampling strategy)?
- Does it help only specific families (e.g., cart-redis), or across the board?

---

*Generated 2026-06-05 before G2 launch.*
