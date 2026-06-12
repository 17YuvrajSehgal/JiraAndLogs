# Model Architectures — ICSE 2027 Paper

This document specifies the four pipelines compared in the paper, with enough detail for reviewers to reproduce. All numbers are from the `comparison/phase-g-neural/` run (Phase G v2, 2026-06-02).

## Panel summary

| Pipeline | Role | Trainable params | Triage head | Retrieval head |
|---|---|---:|---|---|
| `hist_gradient_boosting_numeric` (HGB) | Triage baseline | ~10K (tree nodes) | sklearn HGB on 94 numeric features | none |
| `tab_transformer` | Triage neural baseline | ~285K | 4-layer Transformer over 94 features | none |
| `memorygraph_v2_sota_nw080` (SOTA) | Memory baseline | ~22M (frozen MiniLM) | HGB on memory features blended with similarity | BM25 + MiniLM-L6-v2 cross-encoder rerank |
| `bi_encoder_retrieval` (BiE, **this paper**) | Memory + neural retrieval | ~22M (fine-tuned) | logistic on similarity features | fine-tuned MiniLM-L6-v2 dense retrieval |

---

## 1. Histogram Gradient Boosting (HGB) — classical baseline

**Implementation:** `src/comparison/pipelines.py::GradientBoostingPipeline`

**Architecture:** sklearn `HistGradientBoostingClassifier`. Tree-based; no embedding layers; scale-invariant; tabular only.

**Hyperparameters (defaults from the existing codebase):**
- `max_iter = 300`
- `learning_rate = 0.05`
- `max_depth = 8`
- `l2_regularization = 0.1`
- `random_state = 42`

**Inputs:** the 94 derived numeric features per 5-minute window: latency p99, error rate, trace error count, k8s restart count, CPU%, memory%, plus 47 delta-from-baseline columns and 33 moving-5-minute-average columns. Schema: `data/derived/global/<id>/triage-feature-columns.json`.

**Output:** scalar P(ticket_worthy) ∈ [0, 1] per window.

**Role in the paper:** the strong triage baseline. We make no attempt to beat its PR-AUC; we report it honestly as the ceiling we acknowledge.

---

## 2. TabTransformer — neural triage on numeric features

**Implementation:** `src/neural_models/tab_transformer.py`

**Architecture (FT-Transformer-style, Gorishniy et al. NeurIPS 2021):**

```
numeric feature vector  x ∈ ℝ^94
        |
        +-- per-feature linear embedding:  e_i = W_i · x_i + b_i  ∈ ℝ^d
        +-- learned [CLS] token prepended
        |
        v
   sequence of 95 tokens, each d=64-dim
        |
        v
   4 × {Pre-LayerNorm → Multi-head Self-Attention (4 heads) → FFN (GELU, 4×expansion)}
        |
        v
   LayerNorm over [CLS] representation
        |
        v
   Linear head -> scalar logit -> sigmoid -> P(ticket_worthy)
```

**Trainable parameters:** ~285K. Calculation: 94 × 64 × 2 (tokenizer) + 64 (CLS) + 4 × (4 × 64×64 + 4 × 64×256 + 2 × 64) (transformer blocks) + 64 + 64 (head + final norm) ≈ 285K.

**Hyperparameters:**
- `d_model = 64`
- `n_heads = 4`
- `n_layers = 4`
- `dropout = 0.1`
- `epochs = 30` with patience-5 val-loss early stopping
- `batch_size = 128`
- `lr = 1e-3`, AdamW, cosine schedule, weight_decay = 1e-4
- Loss: BCEWithLogitsLoss with `pos_weight = n_neg / n_pos`
- Gradient clip at 1.0
- `seed = 42`

**Inputs:** the same 94 numeric features as HGB. Internally StandardScaled before being fed to the tokenizer.

**Training data:** the train split (2796 windows) with an internal 90/10 train/val carve-out for early stopping (the harness's val split is reserved for threshold tuning, not encoder selection).

**Training time:** ~10–25 seconds on RTX 5060 depending on early-stop convergence.

**Role in the paper:** confirms that the gap between memory-augmented and telemetry-only systems is not an artifact of using a tree learner. A modern neural tabular model achieves similar PR-AUC to HGB; both saturate the numeric-feature signal.

---

## 3. MemoryGraph SOTA — multi-channel skill-chain with cross-encoder rerank

**Implementation:** `src/memorygraph/pipeline.py::MemoryGraphPipeline` with `with_log_signatures=True, with_cross_encoder=True, numeric_weight=0.80`.

**Architecture (deterministic skill chain):**

```
INPUT: window {logs, traces, k8s_events, 94 numeric features}
  |
  +-> entity_extract                   parse (service, component, error_class, severity)
  +-> component_filter                 cheap pre-filter on entity-shared memory
  +-> lexical_similarity (BM25)        bag-of-words retrieval
  +-> log_signature_similarity         characteristic log line per side (Move-A)
  +-> cross_encoder_rerank             MS-MARCO MiniLM-L-6-v2 joint scoring on top-20
                                       blend = 0.6 · crossenc + 0.4 · bi-encoder
  +-> graph_score                      bridge-weighted scoring over entity graph
  +-> numeric_blend                    HGB on 94 numeric features -> P(triage)
  +-> triage_decide                    w_num=0.80 · numeric + 0.20 · max_combined
  +-> top-5 candidates
```

**Trainable parameters:** only the `numeric_blend` HGB head (~10K tree nodes). MiniLM cross-encoder is **frozen** (off-the-shelf).

**Hyperparameters:** numeric blend weight = 0.80 (tuned in Phase F numeric-weight sweep on the val split). Other parameters inherit from the cross-encoder reranker (top-20 candidates, blend=0.6).

**Inputs:** logs (Loki), traces (Tempo), k8s events, 94 numeric features, and the V2 humanized memory corpus (347 tickets).

**Training time:** ~5–10 seconds for the HGB head; cross-encoder is loaded from HF hub on first run (~80MB download).

**Test time:** ~230 seconds for the test split — cross-encoder joint scoring on top-20 candidates per window is the bottleneck (~80ms/window).

**Role in the paper:** the baseline memory-augmented system. Shows what off-the-shelf cross-encoder reranking achieves; serves as the natural "ablate the fine-tune" comparison point for the BiEncoder.

---

## 4. BiEncoder — fine-tuned dense retrieval (this paper's main retrieval contribution)

**Implementation:** `src/neural_models/bi_encoder.py::BiEncoderRetrievalPipeline`

**Architecture:**

```
Encoder: sentence-transformers/all-MiniLM-L6-v2 (22M params, 384-d output)
   - 6 Transformer layers, hidden 384, intermediate 1536
   - Mean-pooled token embeddings; L2-normalized

Training: MultipleNegativesRankingLoss
   - Each example: (anchor, positive, hard_neg_1, hard_neg_2, hard_neg_3)
   - Anchor   = window query text (build_window_query_text)
   - Positive = gold-matched ticket's memory_text
   - Hard negs= top-20 BM25 candidates NOT in gold (3 per example)
   - In-batch: every other example's positives + hard negs are also negs
   - Loss: cross-entropy where the positive's similarity must dominate

Triage head:
   features = [max_sim, mean_top5_sim, n_above_0.5]
   logistic_regression(class_weight="balanced", max_iter=2000)
```

**Trainable parameters:** ~22M (full MiniLM-L6-v2) fine-tuned for retrieval; ~4 (logistic head: 3 weights + bias) for triage.

**Hyperparameters:**
- `backbone = "sentence-transformers/all-MiniLM-L6-v2"`
- `finetune_epochs = 5`
- `finetune_batch_size = 32`
- `finetune_lr = 2e-5`
- `warmup_ratio = 0.1`
- Optimizer: AdamW (defaults from sentence-transformers)
- `n_hard_negs = 3` per positive
- `bm25_top_n = 20` (pool from which hard negs are sampled)
- `use_all_golds = True` (emit one example per (window, gold) pair, not 1-random)
- `max_chars = 512` (truncation on both anchor and document texts)
- `seed = 42`

**Inputs:**
- Window query text built by `loganalyzer.features.text.build_window_query_text` — same function the SOTA pipeline uses for BM25, so both retrievers see identical query content (apples-to-apples).
- Memory document text built by `build_memory_doc_text` — leads with `description_code`, then per-step prose + `body_code` blocks. From the V2 humanized corpus.
- For triage: only the similarity features above (no numeric telemetry).

**Training data:**
- (window, gold-ticket) positives: ~12K pairs from train (2796 windows) + val (984 windows) splits where the window has non-empty `matched_memory_issue_ids` and at least one gold is visible at the window's timestamp (time-ordered visibility respected).
- Hard negatives: 3 per positive, sampled from BM25 top-20 candidates that are NOT in gold.
- Total `InputExample` rows: ~12K × (1 anchor + 1 pos + 3 negs) = 60K text fragments fed through the encoder per epoch.

**Training time:** ~3–5 minutes on RTX 5060 for 5 epochs.

**Test time:** ~30 seconds — embed 347 memory docs once + 2940 test windows once + cosine matmul. No per-pair joint scoring.

**Role in the paper:** the headline retrieval contribution. Production-deployable (documents precomputed, queries embed in milliseconds) and substantially outperforms the cross-encoder reranker on retrieval metrics in our smoke tests.

---

## Why these four pipelines?

The four-pipeline panel maps cleanly to the paper's research-question structure:

| RQ | Comparison |
|---|---|
| RQ1 — depth scaling | HGB (flat at zero) vs SOTA vs BiE — all three plotted by `n_prior_family_tickets` bucket |
| RQ2 — orthogonality | HGB triage AUC > SOTA triage AUC, but only SOTA/BiE have retrieval heads |
| RQ3 — fine-tune | SOTA (off-the-shelf MiniLM reranker) vs BiE (fine-tuned MiniLM bi-encoder) |
| Triage neural baseline | HGB vs TabTransformer — confirms the gap is not tree-vs-NN |

The Phase C (channel ablation) and Phase D (distractor robustness) variants of memorygraph are NOT in Phase G because they are derivatives of SOTA and answer narrower questions; their results stay in Sections 5.4–5.5 of the paper.
