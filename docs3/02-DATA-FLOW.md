# Data Flow — What feeds what

This document specifies, for every pipeline, the EXACT data each model sees at training and prediction time. Reviewers can audit this against the paper's claims about apples-to-apples comparison and out-of-distribution evaluation.

## Dataset summary

| Asset | Path | Size | Source |
|---|---|---:|---|
| Windows | `data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl` | 6720 rows | Synthetic from Google microservices-demo |
| Numeric features | embedded per window | 94 columns | Derived from logs/traces/metrics, per `triage-feature-columns.json` |
| Memory corpus (V2) | `jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl` | 347 tickets | Humanized from TAWOS-anchored synthetic episodes |
| Distractor pool | `jira-shadow-humanized-v2-distractors/mint-20260601/timeline.jsonl` | 110 tickets | LLM-generated plausibly-realistic but irrelevant |
| Train/val/test split | `triage-split-manifest.json` | 2796/984/2940 | Chronological + family-stratified |
| Per-window matchings | `window-memory-matchings.jsonl` | 6720 rows | Gold-truth (window → list of compatible memory tickets) |
| Raw Loki logs | `data/runs/.../raw/loki/<window_id>.json` | ~50M lines | Per-window log dumps |
| Raw Tempo traces | `data/runs/.../raw/tempo/<window_id>.json` | trace spans | Per-window trace dumps |

## Split visualization

```
                                      time →
Train:    [2796 windows | 14 families: deploy, dns, email, frontend, latency-near-miss,
                                       network-packet-loss, network-partition,
                                       payment, post-deploy, productcatalog-outage,
                                       recovered, scheduled-job, shipping, single-pod-restart]
Val:      [ 984 windows |  6 families: checkout-restart, flapping-pod,
                                       recommendation-outage, resource-saturation,
                                       slow-leak-saturation, third-party-blip]
Test:     [2940 windows |  7 families: ad-outage, baseline-normal, cart-redis,
                                       checkout-outage, currency-outage,
                                       network-latency, productcatalog-latency]
```

**Critical property:** test families do NOT appear in train. This is family-stratified out-of-distribution evaluation by design. The retrieval result we report is for families the encoder has never seen.

## Memory visibility

Each memory ticket has an `available_as_memory_from` timestamp. A window at time `t` is only allowed to see tickets minted before `t` — this is enforced by `loganalyzer.memory.corpus.MemoryCorpus.visible_to(window)`. Every pipeline respects this rule, so we never leak future tickets into past retrievals.

---

## Per-pipeline data flow

### Pipeline 1: HGB

```
Input:   window.derived_numeric_features  →  np.ndarray (94,)
Output:  P(ticket_worthy) ∈ [0, 1]
```

- Sees only the 94 columns. No text, no traces, no memory.
- Fit on the train split (2796 rows), evaluated on test (2940 rows).
- Class weight balanced (handles the ~22% positive rate).

### Pipeline 2: TabTransformer

```
Input:   window.derived_numeric_features  →  np.ndarray (94,)
         (StandardScaled internally)
Output:  P(ticket_worthy) ∈ [0, 1]
```

- Same 94 columns as HGB.
- Internal 90/10 split of the train set for validation-loss-based early stopping. The harness's `val` split is NOT used by the encoder — it's reserved for triage-threshold tuning.
- StandardScaler fit on train; applied identically at predict time.

### Pipeline 3: MemoryGraph SOTA

```
Inputs (per window):
  - 94 derived numeric features
  - window.evidence_text                      (build_window_query_text)
  - raw/loki/<window_id>.json                 (for log_signature_similarity)
  - entity extractions (service, component, error_class, severity)
  - V2 humanized memory corpus (347 tickets, time-ordered visibility)

Outputs:
  - triage_score
  - top-5 candidate Jira ticket IDs (matched_issue_ids)
  - is_novel flag (currently buggy — flagged as a limitation)
```

- The `numeric_blend` HGB head trains on the 94 features (same as Pipeline 1).
- The `cross_encoder_rerank` MiniLM model is OFF-THE-SHELF (frozen, not fine-tuned). It scores `(query, doc)` pairs jointly on the top-20 BM25 candidates.
- BM25 indexes the V2 memory corpus's `memory_text` (description_code + per-step body_code).

### Pipeline 4: BiEncoder Retrieval (this paper's main contribution)

```
Fine-tune phase (one-time, train+val):
  Build pairs from train_w + val_w where matched_memory_issue_ids is non-empty:
    For each (window, gold_ticket) pair:
      anchor   = build_window_query_text(window)[:512]
      positive = build_memory_doc_text(gold_ticket)[:512]
      hard_negs = sample 3 from BM25 top-20 NOT in gold
      → InputExample(texts=[anchor, positive, neg1, neg2, neg3])
  Total: ~12K examples × 5 epochs

Training: MultipleNegativesRankingLoss
  AdamW lr=2e-5, batch=32, warmup=10% of total steps
  In-batch negatives + explicit hard negatives

Inference phase (per test window):
  - Embed full V2 memory once (347 → matrix M of shape (347, 384))
  - Embed each window once
  - cosine_sim = window_embed @ M.T
  - Mask non-visible memory rows with -inf
  - top_k indices → matched_issue_ids
  - Triage features (max_sim, mean_top5_sim, n_above_0.5) → logistic head → triage_score
```

- The BiEncoder is fine-tuned on train+val pairs. This is consistent with the Phase B cross-encoder fine-tune (also used train+val). Test set windows are NEVER used during fine-tuning.
- The logistic triage head is fit ONLY on train similarities; val similarities are used for threshold tuning (FPR=5% target).
- All retrieval respects time-ordered visibility.

---

## What we DO NOT use

These data sources are available but NOT consumed by any reported pipeline:

| Source | Why omitted |
|---|---|
| Raw Loki logs (50M+ lines, per-window JSON dumps) | Used by `log_signature_similarity` skill inside SOTA pipeline (compresses each window to ONE characteristic log line). Not consumed directly by HGB, TabTransformer, or BiEncoder — paper limits log content to the engineer-readable "query text" representation. Direct ingestion of raw 50M-row corpus is future work (would require streaming embedding pipeline, which is out of scope for this paper). |
| Raw Tempo traces | Aggregated into derived numeric features. Not consumed directly. |
| TAWOS reference corpus | Used to calibrate V2 humanizer's empirical distributions (length, comment count, code-block ratio). NOT used at training time. |
| Distractor pool (110 tickets) | Used only in Phase D robustness sweep, not in Phase G. |
| Alarm-management metadata | Not part of the 94-column feature schema. |

---

## Apples-to-apples guarantees

For honest cross-pipeline comparison, the paper relies on these guarantees:

1. **Identical test set:** all four pipelines score on the same 2940 test windows. The `_NumericClassifierPipeline` scaffold and the `BiEncoderRetrievalPipeline` both call `iter_split(ds.windows, ds.split_manifest, "test")`.

2. **Identical memory corpus:** SOTA and BiEncoder both load the V2 humanized corpus (347 tickets) via `load_humanized_corpus`. No corpus drift between the two retrieval pipelines.

3. **Identical query text:** SOTA's BM25 layer and BiEncoder both build the query via `build_window_query_text`. Differences in retrieval outputs reflect the model, not the input.

4. **Identical visibility rule:** all retrieval pipelines use `MemoryCorpus(mode="time_ordered").visible_to(window)`. No future-ticket leakage.

5. **Identical scoring code:** Hit@K, MRR, PR-AUC are computed by the same `comparison/significance.py` and `comparison/stratified.py` functions for every pipeline. No per-pipeline metric customization.

6. **Identical bootstrap:** 1000 resamples, seed=42, paired bootstrap on shared window IDs. The `paired_bootstrap_ci` function in `significance.py` enforces window-id alignment.

These guarantees are checked by the comparison runner's `_headline_metrics` and `stratified_metrics` functions — both refuse to score predictions whose `window_id` is missing from the gold side.
