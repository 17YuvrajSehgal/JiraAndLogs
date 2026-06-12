# v2_advanced Pipeline Matrix

The complete set of pipelines now registered in `comparison.runner.KNOWN_PIPELINES`, with what each does, what they share, and what they uniquely contribute.

## At a glance

| Pipeline | Family | Triage signal | Retrieval signal | LLM needed? | GPU needed? |
|---|---|---|---|---|---|
| `hist_gradient_boosting_numeric` (HGB) | v1 baseline | 94 numeric features → HGB | none | no | no |
| `tab_transformer` | v1 baseline | 94 numeric features → 4L Transformer | none | no | yes (light) |
| `memorygraph_v2_sota_nw080` | v1 SOTA | numeric blend + similarity max | BM25 + log-sig + cross-encoder rerank | no | yes |
| `bi_encoder_retrieval` | v1 Phase G | similarity features → logistic | fine-tuned MiniLM dense | no | yes |
| `kg_retrieval_rulebased` | **v2 Phase D** | graph entity overlap → logistic | rule-based extraction + Cypher graph traversal | no | no |
| `kg_retrieval` | **v2 Phase D** | graph entity overlap → logistic | LLM extraction + Cypher graph traversal | **yes** | no |
| `hybrid_rrf_no_graph` | **v2 Phase C** | hybrid features → logistic | SPLADE + BiEncoder fused via RRF | no | yes |
| `hybrid_rrf_retrieval` | **v2 Phase C** | hybrid features → logistic | SPLADE + BiEncoder + Graph via RRF | depends on Graph | yes |
| `logseq2vec_retrieval` | **v2 Phase B** | similarity features → logistic | LogSeq2Vec encoder over raw log lines | no | yes |
| `diagnosis_agent` | **v2 Phase E** | agent confidence | LLM-verified ranking on hybrid_rrf top-10 | **yes** | yes |

## Apples-to-apples comparison guarantees

All pipelines share:
- Same test split (1008 windows under v2 resplit, 2940 under v1 family-disjoint)
- Same V2 humanized memory (347 tickets, time-ordered visibility)
- Same metric definitions (PR-AUC, Hit@K, MRR with paired bootstrap CIs)
- Same comparison harness (`comparison.cli` + the v2 resplit driver)

What changes between pipelines is purely the SIGNAL FLOW. We can measure each pipeline's contribution exactly because nothing else moves.

## How each pipeline answers the research questions

| RQ | Question | Which pipelines answer it |
|---|---|---|
| RQ-A | Does in-distribution evaluation give a fairer picture? | Compare any v1 pipeline's result on v1 split (family-disjoint) vs v2 split (window-stratified). Run `run_v2_comparison.py`. |
| RQ-B | Does using raw log sequences beat the "characteristic line"? | Compare `logseq2vec_retrieval` to `memorygraph_v2_sota_nw080`. |
| RQ-C | Does hybrid retrieval beat BM25 alone? | `hybrid_rrf_retrieval` vs `memorygraph_v2_sota_nw080`. |
| RQ-D | Does an LLM-built knowledge graph add retrieval signal? | `kg_retrieval` vs `kg_retrieval_rulebased`. |
| RQ-D' | Is the graph alone competitive with embedding retrieval? | `kg_retrieval_rulebased` vs `bi_encoder_retrieval`. |
| RQ-E | Does an agentic reasoning loop fix the cold-start novelty problem? | `diagnosis_agent` novelty-detection rate on n_prior=0 windows vs `memorygraph_v2_sota_nw080`'s. |

## What outputs each pipeline produces

Every pipeline produces a uniform `PipelineResult` containing:

| Field | Definition |
|---|---|
| `pipeline_name` | The registered name above |
| `predictions: list[PipelinePrediction]` | One per test window, schema in `src/comparison/schema.py` |
| `triage_threshold` | Tuned on val for FPR=5% |
| `fit_seconds`, `predict_seconds` | Per-pipeline timing |
| `metadata` | Free-form dict; we standardize keys for `retrieval` ("none", "bm25", "bi_encoder_dense", "kg_cypher", "hybrid_rrf", "logseq2vec", "diagnosis_agent") |

Inside `PipelinePrediction`:

| Field | Definition |
|---|---|
| `window_id` | Stable per-window ID |
| `triage_score` | Float in [0, 1] |
| `triage_decision` | "ticket_worthy" or "noise" |
| `is_novel` | Pipeline's novelty flag; None when not computed |
| `matched_issue_ids` | Top-K ticket IDs, ranked highest similarity first |
| `gold_*` fields | Joined from `window-memory-matchings.jsonl` at scoring time |
| `scenario_family`, `service_name`, etc. | Stratification keys |

This uniform schema means the comparison harness can compute Hit@K, MRR, PR-AUC, and bootstrap CIs the same way for every pipeline — no per-pipeline metric customization needed.
