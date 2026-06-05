# Experimental Protocol — Phase G

This document is the single-source-of-truth for the Phase G experiment design. It is pre-registered in the sense that the parameters were locked in code before the final results were generated.

## Experiment ID

- **Phase:** G (neural model addition to the panel)
- **Date:** 2026-06-02
- **Code revision:** see `data/derived/global/<id>/training_runs/<pipeline>__<UTC>__<sha8>/config.json` for the exact git SHA per pipeline
- **Charter section:** Phase G is an addition to the original charter, not a replacement. The original five sub-claims and Hit@K methodological correction stand.

## Hypotheses

H1. Replacing the gradient-boosted triage head with a tabular Transformer does NOT close the gap between memory-augmented and telemetry-only systems on triage AUC. (Predicts: TabTransformer PR-AUC ≈ HGB PR-AUC ≈ 0.77, both >> memory-augmented PR-AUC ≈ 0.62.)

H2. A contrastively fine-tuned bi-encoder retriever (MultipleNegativesRankingLoss with BM25-mined hard negatives) outperforms the off-the-shelf cross-encoder reranker on Hit@K and MRR for the V2-humanized memory.

H3. Both neural pipelines preserve the deployment-history-depth-scaling result reported in Phase A.

H4. The BiEncoder retrieval head's triage AUC is BELOW the numeric-only baselines, because the logistic-on-similarity head sees no numeric telemetry. This is acceptable: the BiEncoder is positioned as a retrieval contribution, not a triage contribution.

## Pipelines under test

| ID | Pipeline | Role |
|---|---|---|
| 1 | `hist_gradient_boosting_numeric` (HGB) | Triage baseline (classical) |
| 2 | `tab_transformer` | Triage baseline (neural) |
| 3 | `memorygraph_v2_sota_nw080` (SOTA) | Memory baseline (cross-encoder reranker) |
| 4 | `bi_encoder_retrieval` (BiE) | Memory + fine-tuned dense retrieval |

## Metrics measured

| Metric | Where reported |
|---|---|
| PR-AUC, ROC-AUC (test split, full 2940 windows) | Headline table, §5.1 |
| Hit@1, Hit@5 (retrievable subset, 317 windows) | Anchor depth-curve figure, §5.1 |
| MRR (retrievable subset) | Headline table |
| Recall@5 (canonical, capped — for comparison only) | Appendix |
| Recall@5_norm = hits / min(5, |gold|) | Appendix |
| Time-to-diagnose simulation | §5.6 |

## Statistical envelope

- 95% paired bootstrap CIs
- 1000 resamples
- seed = 42
- Strict-label binarization (`triage_label == "ticket_worthy"` only)
- Per-pipeline scoring on the same shared `window_id` set

## Stratification axes

Inherited from Phase A:
- Overall
- `scenario_family` (7 test families)
- `service_name` (10 services)
- `window_type`
- `is_hard_case`
- `triage_reason_class`
- `is_novel`
- **`n_prior_family_tickets`** — the anchor depth axis, bucketed {0, 1-2, 3-5, 6-20, 21+}

## Pipeline ablations NOT in Phase G

Phase G focuses on the headline retrieval comparison. The following ablations are in the paper but not re-run in Phase G:

- Channel ablation (Phase C, §5.4) — derivative of SOTA, uninformative on V2 corpus for traces/k8s
- Distractor robustness (Phase D, §5.5) — derivative of SOTA, would also be done with BiE in future work
- Per-numeric-weight sweep (Phase A retune) — settled at 0.80

## Why these four pipelines and not more

Adding pipelines costs comparison-runner time AND reviewer cognitive load. We picked the minimum set that lets us:

1. Defend the triage-orthogonality claim (HGB vs. TabTransformer vs. SOTA)
2. Make the retrieval claim (SOTA vs. BiE — apples-to-apples on the same MiniLM backbone)
3. Provide the depth-scaling characterization that anchors the paper (every retrieval pipeline traced across `n_prior_family_tickets` buckets)

Adding LSTM-over-time-series, multi-modal text+numeric fusion, or larger backbones (mpnet-base, e5-large) are reasonable next experiments but they don't change the paper's contribution structure. They are future work.

## Threats to validity (Phase G specific)

- **TabTransformer hyperparameters not exhaustively tuned.** We used reasonable defaults (`d_model=64`, `n_layers=4`, `lr=1e-3`) without grid search. A wider sweep MIGHT close the gap with HGB but unlikely by 15 points.

- **BiEncoder fine-tune uses train+val pairs.** Same convention as the Phase B cross-encoder fine-tune (and most retrieval-task fine-tunes in the literature). This is potentially a slight leak into the val-based triage threshold; the absolute test numbers are still valid (test pairs are never seen during fine-tuning). We disclose this in §6.

- **CUDA non-determinism.** With CUDA enabled, kernel-launch order can shift floating-point results bitwise across runs. We accept this; the bootstrap CI width is much larger than the run-to-run variance. Reviewers wanting strict determinism can set `torch.use_deterministic_algorithms(True)` at small speed cost.

- **Single seed.** We run with seed=42 throughout. Multi-seed averaging would tighten CIs but is computationally expensive given the comparison-runner cost. Future work.
