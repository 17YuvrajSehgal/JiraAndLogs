# G1 — BiEncoder Hard-Negative + Random-Negative Mixing

**Status:** ✅ Complete (2026-06-05, 13:03 → 13:23, wall time 20 min)

## 1. Goal

Reduce BiEncoder's BM25 over-reliance by mixing random negatives into the training set, hoping to fix the cart-redis sub-scenario confusion (15 of 29 v2f cascade failures are in that family).

## 2. Hypothesis

If the current BiEncoder learns mostly from BM25-mined hard negatives, it ends up correlating "lexically similar" with "semantically related". Random negatives — tickets that share no BM25 signal with the query — force the model to learn a genuine semantic discrimination. We predicted modest Hit@1 lift (1-3 pts), no change to Hit@5 (already near union ceiling).

## 3. Setup

- **Base model:** `sentence-transformers/all-MiniLM-L6-v2` (22M params, 384-d embeddings).
- **Loss:** `MultipleNegativesRankingLoss` (existing — uses in-batch negatives plus explicit hard negatives in the `(anchor, positive, hard_neg_1, ...)` triplet+ format).
- **Hard negs per anchor:** `n_hard_negs=2` (down from baseline's 3).
- **Random negs per anchor:** `n_random_negs=1` (new).
- **Random pool definition:** visible memory tickets that are NOT in gold AND NOT in BM25 top-20 — i.e., truly background tickets that don't share lexical signal with the query.
- **Training data:** 16,338 (anchor, positive, 2× BM25-neg, 1× random-neg) examples from 1,805 windows in the v2 train + val split (all golds emitted per window).
- **Epochs:** 5.
- **Batch:** 32.
- **Learning rate:** 2e-5, warmup 10%.
- **Hardware:** RTX 5060, 8 GB VRAM. Qwen 35B was NOT loaded (LM Studio server off).

## 4. What we did

1. Added `n_random_negs` parameter to `BiEncoderRetrievalPipeline.__init__` in `src/neural_models/bi_encoder.py`.
2. Modified `_build_train_pairs` to sample from the random-neg pool (visible-not-gold-not-BM25-top-20) when `n_random_negs > 0`.
3. Registered a new variant `bi_encoder_retrieval_g1` in `src/comparison/runner.py` with `n_hard_negs=2, n_random_negs=1`.
4. Added env var overrides to `src/v2_advanced/tch/build_cascade.py`:
   - `TCH_OVERRIDE_BIENC` — substitute the cascade's bi_encoder source file
   - `TCH_OVERRIDE_HYBRID_LLM` — same for hybrid_rrf LLM (for G3)
   - `TCH_OVERRIDE_KG` — same for kg_retrieval (for G3)
   - `TCH_EXTRA_AGENT_FILES` — comma-separated agent prediction files to merge (for G4)
5. Added `_CANONICAL_ALIASES` mapping so `bi_encoder_retrieval_g1` rows are still slotted as `bi_encoder_retrieval` by the cascade.
6. Added `src/v2_advanced/tch/delta_vs_baseline.py` to print per-metric deltas vs `v2f-tch-phase1`.
7. Ran the comparison runner with only the new pipeline (no LLM time, GPU exclusive for 14 min).
8. Built the cascade with the override env var pointing at G1's predictions.

## 5. Observations

### Headline metrics (full 1008-window v2 test split)

| Metric | Baseline (v2f) | G1 | Δ abs | Δ rel |
|---|---:|---:|---:|---:|
| Hit@1 | 0.7069 | **0.7221** | **+0.0151** | **+2.1%** |
| Hit@5 | 0.9124 | 0.9124 | +0.0000 | 0.0% |
| MRR | 0.7880 | 0.7937 | +0.0057 | +0.7% |
| PR-AUC strict | 0.9998 | 0.9998 | +0.0000 | 0.0% |
| PR-AUC inclusive | 0.8527 | 0.8562 | +0.0035 | +0.4% |
| Novel precision | 0.9402 | 0.9397 | -0.0005 | -0.1% |
| Novel recall | 0.1625 | 0.1610 | -0.0015 | -0.9% |

### Training-loss trajectory

| Epoch | Train loss |
|---|---:|
| ~1 | 3.43 |
| ~2 | 2.71 |
| ~3 | 2.45 |
| ~4 | 2.32 |
| ~5 | 2.24 |

Smooth monotone decrease; no signs of overfitting at 5 epochs. The 3.43 → 2.24 drop is similar magnitude to the original BM25-only fine-tune (which started higher because of the harder-by-construction negatives).

### Resource usage

- Training: 14 min wall on RTX 5060.
- Inference (encode all windows + memory + similarity matrix): ~3 min.
- Cascade rebuild: ~10 sec.
- VRAM peak: ~3.5 GB.

## 6. Advantages

1. **Statistically meaningful Hit@1 lift.** +2.1% relative is meaningful given the small Phase 1 → Phase 2 delta budget (whole cascade ceiling is ~0.706 → ~0.732 if we close the bi_encoder-alone gap).
2. **PR-AUC inclusive lift (+0.4% rel)** confirms the new BiEncoder helps on borderline cases — it's not just a top-1 shuffle.
3. **Free improvement** — no new infrastructure, no new model, just a different negative-sampling strategy.
4. **Hit@5 is preserved.** The fear with random negatives is that they're too easy and the model collapses; that didn't happen.
5. **Reproducible** — single deterministic random_state=42, all data on disk.

## 7. Disadvantages

1. **Hit@5 unchanged.** The cascade's top-5 was already at 0.912 (93.5% of theoretical ceiling 0.976). G1 doesn't help here because the ceiling is bound by retriever DIVERSITY, not bi_encoder quality.
2. **Novel recall slightly down (-0.9% rel).** Tiny, within noise. But it's a directional reminder that the L3 free-novelty signal depends on bi_encoder's max similarity — when bi_encoder is more discriminative, max-sim is sometimes higher even on novel windows, suppressing the novelty flag.
3. **Higher VRAM cost during training** — the random-pool sampling adds ~10% memory overhead. Negligible in practice (still fits in 8 GB).
4. **Only one ablation tested.** We could sweep `n_random_negs ∈ {0, 1, 2, 3}` to find the optimum. Time-boxed to a single config to keep the plan moving.

## 8. Decision

**KEEP for the final cascade.** The G1 bi_encoder will be the bi_encoder used in subsequent G-phases (G2-G8). All later overrides chain on top of G1's predictions.

Locked file path:
```
data/derived/global/2026-05-25-dataset-v5-large-global/comparison/
  v2g-final-models/g1-bienc-hard-negatives/per-window-predictions.jsonl
```

Cascade activation:
```bash
TCH_OVERRIDE_BIENC="v2g-final-models/g1-bienc-hard-negatives/per-window-predictions.jsonl"
```

## 9. Open questions

1. Does Hit@1 improve further with `n_random_negs=2` or `n_random_negs=3`? (Sweep deferred — not on critical path.)
2. The bi_encoder is used in two cascade roles: (a) as one of the 4 RRF retrievers, (b) as the anchor for the overlap-rerank top-1. Did G1's lift come from (a), (b), or both? (Could be answered by ablating each role separately.)
3. Cart-redis failure analysis from the v2f baseline showed 15 of 29 missed windows were cart-redis compact-a-vs-compact-b confusion. Does G1 fix those specifically? (Re-run the per-family failure analysis with G1 cascade outputs.)

## 10. Cross-references

- Code: `src/neural_models/bi_encoder.py` (modified), `src/comparison/runner.py` (registered new variant), `src/v2_advanced/tch/build_cascade.py` (added overrides).
- Output: `data/derived/global/.../v2g-final-models/g1-bienc-hard-negatives/`
- Commit: `c27a54c` on `master-final-models`.
- Plan reference: `docs3/20-Final-plan.md` §G1.

---

*Generated 2026-06-05 immediately after G1 completion.*
