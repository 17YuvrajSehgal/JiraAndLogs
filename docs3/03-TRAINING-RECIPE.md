# Training Recipe — Reproducibility document

This document lists every training-time decision in enough detail that an independent reviewer can re-run our experiments. All seeds are fixed; all hyperparameters are pinned.

## TabTransformer training recipe

### Optimizer
```
AdamW(
    lr = 1e-3,
    weight_decay = 1e-4,
    betas = (0.9, 0.999)   # defaults
)
scheduler = CosineAnnealingLR(T_max = epochs)
```

### Loss
```
BCEWithLogitsLoss(pos_weight = n_neg / n_pos)
```
On the train split, `n_pos = 622, n_neg = 2174` → `pos_weight ≈ 3.49`. This handles the ~22% positive rate without resampling.

### Regularization
- Dropout 0.1 in attention and FFN
- Gradient clipping at norm 1.0
- Weight decay 1e-4 (AdamW)
- Patience-5 early stopping on val_loss

### Data preprocessing
- `StandardScaler` fit on train split. Applied identically at predict time. We store the fitted scaler inside the model wrapper so the comparison harness uses the same transform throughout.
- Internal 90/10 split of train: `X_train_arr[idx[:cut]]` for fit, `X_train_arr[idx[cut:]]` for early-stop validation. Seed = 42.

### Forward pass
1. `x: (B, 94)` → `tokenizer(x): (B, 94, 64)` (per-feature linear embedding).
2. Prepend learned [CLS]: → `(B, 95, 64)`.
3. 4 × pre-LN Transformer encoder blocks, 4 heads, FFN expansion 4.
4. LayerNorm + linear over [CLS] → scalar logit.
5. Sigmoid at predict time only.

### Convergence behavior (typical)
```
ep 01: train_loss=0.78  val_loss=0.45  val_AUC=0.93
ep 05: train_loss=0.33  val_loss=0.26  val_AUC=0.97
ep 10: train_loss=0.23  val_loss=0.20  val_AUC=0.985
ep 15: train_loss=0.18  val_loss=0.19  val_AUC=0.989
ep 20: train_loss=0.12  val_loss=0.20  val_AUC=0.992
ep 21: early stopping (no val_loss improvement for 5 epochs)
```

Total training time: ~10-25 seconds on RTX 5060.

---

## BiEncoder fine-tuning recipe

### Optimizer (from sentence-transformers defaults)
```
AdamW(
    lr = 2e-5,
    weight_decay = 0.01,   # transformers default
)
warmup_steps = 0.1 × epochs × (n_pairs / batch_size)
```

### Loss
```
MultipleNegativesRankingLoss(
    similarity_fct = cos_sim,
    scale = 20.0          # default
)
```
Each `InputExample(texts=[anchor, positive, hard_neg_1, hard_neg_2, hard_neg_3])` contributes 1 positive + 3 explicit hard negatives + (batch_size−1) × 4 in-batch negatives per gradient step. Loss is symmetric cross-entropy: anchor should rank positive above all negatives.

### Pair construction
- Source windows: `train ∪ val` from `triage-split-manifest.json` (2796 + 984 = 3780 windows).
- Filter: keep windows where `matched_memory_issue_ids` is non-empty AND at least one gold ticket is visible (time-ordered).
- For each surviving window: emit ONE example per (window, gold-ticket) pair (~12K positives total).
- For each positive: BM25 top-20 candidates excluding gold → sample 3 hard negatives.

### Encoder
- Backbone: `sentence-transformers/all-MiniLM-L6-v2`
- 6 Transformer layers, hidden 384, 12 attention heads, intermediate 1536
- Mean pooling + L2 normalization output
- All ~22M params are unfrozen during fine-tuning

### Training loop (sentence-transformers `model.fit`)
```
model.fit(
    train_objectives = [(train_dl, MultipleNegativesRankingLoss(model))],
    epochs = 5,
    warmup_steps = 10% of total steps,
    optimizer_params = {"lr": 2e-5},
    show_progress_bar = False,
)
```
Internally: standard sentence-transformers training loop with smart-batching collator, FP16 disabled on RTX 5060 by default (model.fit doesn't auto-enable AMP).

### Memory + speed
- Batch size 32 with ~6-7 tokens per anchor → fits in 8GB VRAM with headroom
- ~3-5 minutes for 5 epochs on RTX 5060
- Encoder is then frozen for inference

### Triage head training
After fine-tuning the encoder:
```
sim_features = [max_sim_over_visible, mean_top5_sim, n_above_0.5]
logistic = LogisticRegression(class_weight="balanced", max_iter=2000, solver="lbfgs")
logistic.fit(sim_features_train, y_train)
```
Threshold tuned on val (precision-at-FPR=5%) per the comparison harness convention.

---

## Reproducibility commands

To re-run the full Phase G comparison:

```powershell
cd C:\workplace\JiraAndLogs
$env:PYTHONPATH = "src"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:TRANSFORMERS_VERBOSITY = "error"
python -W ignore -m comparison.cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --pipelines hgb,tab_transformer,memorygraph_v2_sota_nw080,bi_encoder_retrieval `
    --no-ensemble `
    --n-bootstrap 1000 `
    --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\phase-g-neural
```

All pipeline-side seeds are fixed at 42. The bootstrap CI seed is 42. The HGB and TabTransformer random-state are 42. The BiEncoder pair-builder rng is 42. Reproducibility is end-to-end determinism modulo CUDA non-determinism, which we accept (well below the bootstrap CI width).

## Training-run artifacts (per pipeline, per fit)

Every `pipeline.train_and_predict(...)` call is wrapped in `open_training_run(...)` and writes:

```
data/derived/global/<global_id>/training_runs/<pipeline>__<UTC>__<sha8>/
    config.json          # pipeline class, hyperparams, target_fpr, git SHA, Python version, paths
    metrics.json         # threshold, fit/predict timing, sample count, custom metadata
    predictions.jsonl    # 2940 lines (per-window predictions, schema = PipelinePrediction)
    train.log            # human-readable UTC-timestamped log lines
    model/               # opt-in pickle of the fitted estimator (empty by default)
    artifacts/           # opt-in side artifacts (empty by default)
```

The git SHA stamped in `config.json` lets reviewers trace any reported number back to the exact code revision that produced it.
