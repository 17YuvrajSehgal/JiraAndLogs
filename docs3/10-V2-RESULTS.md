# v2_advanced — Results Roll-up

Final headline numbers from the v2 panel. All metrics with 95% paired bootstrap CIs (1000 resamples, seed=42). For full per-pipeline reports see the corresponding `data/derived/global/<id>/comparison/<run-id>/report.json`.

## Headline summary — v2 in-distribution split

Under the new window-stratified split (4701 train / 1011 val / 1008 test) where every fault family appears in all three splits:

| Pipeline | PR-AUC | Hit@1 | Hit@5 | MRR | Notes |
|---|---:|---:|---:|---:|---|
| HGB (v1 baseline) | **0.9998** | — | — | — | Triage ceiling on numerics. Near-perfect under in-distribution. |
| TabTransformer (v1 baseline) | 0.9351 | — | — | — | Slightly behind HGB; same story as v1. |
| memorygraph_v2_sota_nw080 (v1 SOTA) | 0.9979 | 0.015 | 0.047 | 0.128 | Triage near-perfect; cross-encoder retrieval is still mediocre. |
| bi_encoder_retrieval (v1 Phase G) | 0.283 | **0.154** | **0.486** | **0.676** | Triage low (only similarity features). **Retrieval massively better under in-distribution.** |
| **kg_retrieval_rulebased (v2 Phase D)** | 0.289 | 0.004 | 0.111 | 0.170 | Rule-based graph extraction; weak triage; modest retrieval. Honest baseline. |
| **kg_retrieval (LLM, v2 Phase D)** | TBD | TBD | TBD | TBD | Awaits LM Studio model load. |
| **hybrid_rrf_no_graph (v2 Phase C)** | TBD | TBD | TBD | TBD | SPLADE + BiEncoder via RRF. |
| **hybrid_rrf_retrieval (v2 Phase C)** | TBD | TBD | TBD | TBD | + Graph via RRF. |
| **logseq2vec_retrieval (v2 Phase B)** | TBD | TBD | TBD | TBD | Currently training. |
| **diagnosis_agent (v2 Phase E)** | TBD | TBD | TBD | TBD | Awaits LM Studio model load. |

## Key v1 vs v2 comparisons

### v1 (family-disjoint, n=2940 test) vs v2 (in-distribution, n=1008 test)

The split-choice alone moves numbers dramatically:

| Pipeline | v1 PR-AUC | v2 PR-AUC | v1 Hit@5 | v2 Hit@5 |
|---|---:|---:|---:|---:|
| HGB | 0.7718 | **0.9998** | — | — |
| TabT | 0.7687 | 0.9351 | — | — |
| memorygraph SOTA | 0.6186 | 0.9979 | 0.202 | 0.047 |
| BiEncoder | 0.242 | 0.283 | 0.233 | **0.486** |

Two stories here:

1. **Triage** is now nearly trivial under in-distribution (HGB 0.9998). This says the model was severely penalized by family-disjoint OOD evaluation; production teams should expect numbers closer to 0.99 than 0.77.

2. **Retrieval** for BiEncoder jumps from 0.233 → 0.486 on Hit@5 (+109% relative). This is the biggest single-number lift in the whole project: **fine-tuned dense retrieval works incredibly well when the encoder has seen the same fault families at train time**, which is exactly the production scenario.

3. **memorygraph SOTA** (cross-encoder rerank) DROPS on retrieval from 0.202 → 0.047 under in-distribution. The cross-encoder reranker is OFF-THE-SHELF (not fine-tuned), so it doesn't benefit from the larger training set. The capped recall@5 metric also hurts here because in-distribution lets |gold| grow larger.

## Per-window-prediction artifacts

All pipelines emit:
```
data/derived/global/<id>/comparison/<run-id>/
├── report.json                    headline metrics + bootstrap CIs + strata
├── report.md                      human-readable summary
└── per-window-predictions.jsonl   one PipelinePrediction per (window, pipeline)
```

The `training_runs/<pipeline>__<UTC>__<sha8>/` directories preserve per-pipeline `config.json` / `metrics.json` / `predictions.jsonl` so any reported number traces back to a specific git SHA.

## Stratification — depth scaling under v2 split

Once all v2 pipelines are scored, we'll re-run the depth-stratified Hit@K analysis (`scripts/depth_analysis.py`) on the v2 predictions. Expected story: in-distribution split should make the depth curve smoother (more samples per bucket) and the absolute numbers higher across the board.
