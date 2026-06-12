# `docs3/` — Phase G Neural Models Documentation

Comprehensive documentation for Phase G of the ICSE 2027 submission. Phase G adds two deep-learning pipelines to the existing four-phase analysis (A: anchor, B: cross-encoder fine-tune, C: channels, D: distractors).

## Documents in this directory

| # | File | Purpose |
|---|---|---|
| 01 | [`01-MODELS.md`](01-MODELS.md) | Per-pipeline architectures, parameter counts, hyperparameters, role in the paper. |
| 02 | [`02-DATA-FLOW.md`](02-DATA-FLOW.md) | What data feeds what model. Apples-to-apples guarantees. What we do *not* use. |
| 03 | [`03-TRAINING-RECIPE.md`](03-TRAINING-RECIPE.md) | Optimizer, loss, regularization, seeds. Convergence traces. |
| 04 | [`04-GPU-USAGE.md`](04-GPU-USAGE.md) | RTX 5060 utilization audit. Per-pipeline GPU/VRAM/power/temp traces. Energy estimate. |
| 05 | [`05-EXPERIMENTAL-PROTOCOL.md`](05-EXPERIMENTAL-PROTOCOL.md) | Hypotheses, metrics, statistical envelope, stratification axes. Threats to validity. |
| 06 | [`06-REPRODUCIBILITY.md`](06-REPRODUCIBILITY.md) | Hardware / software requirements. Exact CLI commands. How to trace any number to a git SHA. |
| 07 | [`07-FINAL-RESULTS.md`](07-FINAL-RESULTS.md) | Locked headline numbers. Triage + retrieval tables. Significance tests. Failure analysis. |

## Quick read order for reviewers

For a reviewer evaluating the paper:

1. Start with `07-FINAL-RESULTS.md` for the headline numbers and significance tests.
2. If a number looks surprising, drill down to `01-MODELS.md` for architecture details or `02-DATA-FLOW.md` for the inputs that produced it.
3. For reproduction, follow `06-REPRODUCIBILITY.md`.
4. For training-time decisions, see `03-TRAINING-RECIPE.md`.
5. For GPU efficiency / carbon-footprint audit, see `04-GPU-USAGE.md`.
6. For experimental design + threats to validity, see `05-EXPERIMENTAL-PROTOCOL.md`.

## Summary of the Phase G contribution

Two pipelines added:

- **TabTransformer** (`src/neural_models/tab_transformer.py`) — FT-Transformer-style tabular Transformer over the 94 production-safe numeric features. Confirms triage is settled: $\mathrm{PR\text{-}AUC}_{\text{HGB}} = 0.7718$ vs $\mathrm{PR\text{-}AUC}_{\text{TabT}} = 0.7687$, paired-bootstrap $p = 0.83$.

- **BiEncoder** (`src/neural_models/bi_encoder.py`) — Contrastively fine-tuned MiniLM-L6-v2 over `(window, gold-ticket)` pairs with BM25-mined hard negatives. Beats the off-the-shelf cross-encoder reranker on all three retrieval metrics by 12–15\% relative, at $7.6\times$ predict-time speedup. Headline numbers: $\mathrm{Hit}@5 = 0.233 \uparrow$ from $0.202$; $\mathrm{MRR} = 0.196 \uparrow$ from $0.172$; diagnosis time $-0.9$ min/incident.

**One honest negative:** BiEncoder collapses to Hit@5 = 0.000 on the 21+ depth bucket (entirely `cart-redis` test windows with `redis-cart-intermittent-failure-major` sub-scenarios). This is overfit to BM25 hard negatives; future work should mix BM25-mined and random hard negatives.

## Paper section pointers

| docs3 file | Paper section |
|---|---|
| 01-MODELS.md | §3.1 system architecture, §3.3 cross-encoder fine-tuning, §5b.1 TabTransformer, §5b.2 BiEncoder |
| 02-DATA-FLOW.md | §4.1 dataset, §4.2 pipelines compared |
| 03-TRAINING-RECIPE.md | §3.3, §5b training recipes |
| 04-GPU-USAGE.md | §5b.5 energy and GPU efficiency |
| 05-EXPERIMENTAL-PROTOCOL.md | §4 methodology |
| 06-REPRODUCIBILITY.md | Appendix A |
| 07-FINAL-RESULTS.md | §5b headline neural comparison |
