# TODO: Advanced ML/AI Pipeline Plan

**Created:** 2026-05-23
**Owner:** Yuvraj
**Status doc:** complements `docs/ml-ai-pipeline-benchmark-plan.md` (vision)
and `docs/triage-task-contract.md` (metrics contract). This file is the
**actionable execution plan** - what to build, in what order, with which
acceptance bar.

---

## Current state (entering the plan)

| Asset                                | State                                              |
| ------------------------------------ | -------------------------------------------------- |
| `src/loganalyzer`                    | Built. Numeric + tf-idf lexical + hybrid + BM25/hash-embedding/hybrid retrievers. Pilot: PR-AUC strict 0.658, ROC-AUC 0.900, recall@5 0.061, novelty F1 0.857. |
| `src/logsense`                       | Built. Log-only with Drain-lite template miner. Pilot: PR-AUC strict 0.344, ROC-AUC 0.681, recall@5 0.046, novelty F1 0.667. |
| Pilot dataset (576 windows, 39 issues) | On disk: `data/derived/global/2026-05-21-dataset-v4-pilot-global/` |
| v4-large collection (40 runs, ~3700 windows, ~400 memory entries) | In progress on GCP VM; expected ETA 2026-05-24. |
| Existing benchmarks                  | `triage-baseline-v1` / `-v2-lofo` / `-v3-postfix` under pilot's `benchmarks/`. |

---

## Phase 0 — Comparison + ensemble foundation
**Goal:** put the two existing analyzers head-to-head on the pilot, so the
later advanced models have a real baseline table to beat. No new ML.

- [ ] **0.1** Stratified evaluator in `src/comparison/stratified.py`.
      Joins predictions from each pipeline by `window_id`, breaks metrics
      down per `scenario_family`, `service_name`, and `window_type`.
      Output: `data/derived/global/<id>/comparison/stratified-metrics.md`
      table - one row per family, one column per pipeline.
- [ ] **0.2** Score-level ensemble in `src/comparison/ensemble.py`.
      `mean`, `max`, `weighted` blends of any subset of pipelines.
      Adds an `EnsembleAnalyzer` so an ensemble can run in the same CLI shape.
- [ ] **0.3** Significance harness in `src/comparison/significance.py`.
      Paired bootstrap on per-window scores; emits 95% CIs and p-values
      for PR-AUC / recall@5 / novelty F1.
- [ ] **0.4** `python -m comparison.run --pipelines loganalyzer,logsense,ensemble`
      writes one unified report.

**Acceptance:** A single report shows loganalyzer vs logsense vs simple mean
ensemble on the pilot, with CIs and per-family stratification.
**Blocks:** every later phase ("does X beat the baseline?" needs this).
**Runs on:** pilot now.

---

## Phase 1 — Real text embeddings
**Goal:** replace the hashing-trick embedding retriever with real semantic
embeddings, for both window evidence and Jira memory text.

- [ ] **1.1** Add optional dependency: `sentence-transformers` (model:
      `all-MiniLM-L6-v2`, 22MB, runs on CPU in seconds). Gate behind
      `try: import sentence_transformers` so the package still works
      without it.
- [ ] **1.2** New file `src/loganalyzer/memory/sentence_embedding.py` with
      `SentenceEmbeddingRetriever` implementing the same Retriever
      protocol. Embed memory at fit time; embed query at retrieval time.
- [ ] **1.3** New file `src/logsense/memory/sentence_embedding.py` -
      query text is the concatenation of top-5 anomalous templates plus
      service name (matches the BM25 query shape).
- [ ] **1.4** New triage feature: per-window evidence text embedding fed
      into a logistic head. Add `EmbeddingTriageModel` to both packages.
- [ ] **1.5** Cache: persist computed embeddings under
      `data/derived/global/<id>/embeddings/{windows,memory}.npy` keyed by
      content hash so repeated runs are fast.

**Acceptance:** real embeddings beat both BM25 and hashing-trick on
recall@5 by 5+ absolute points on pilot.
**Blocks:** Phase 4 (hybrid retrieval), Phase 5 (cross-encoder reranking).
**Runs on:** pilot now, will rerun on v4-large.

---

## Phase 2 — LLM zero-shot triage baseline
**Goal:** establish how a frontier LLM does at triage without any training
data, given just a prompt and the window's evidence text. Required by
`docs/dataset-v4-plan.md` Phase D.

- [ ] **2.1** Provider abstraction `src/llm/provider.py` with
      `LLMProvider.complete(prompt, system) -> str`. Implementations:
      `AnthropicProvider`, `OpenAIProvider`. Reads API key from env.
- [ ] **2.2** Prompt template in `src/llm/triage_prompts.py`:
      system message describes the triage task and the three labels;
      user message contains the evidence_text. Model must return a
      structured JSON `{label, confidence, reason}`.
- [ ] **2.3** `LLMZeroShotTriageModel` in `src/loganalyzer/triage/llm_zero_shot.py`.
      Implements the TriageModel protocol - fit is no-op, predict_score
      calls the LLM and parses the JSON.
- [ ] **2.4** Few-shot variant `LLMFewShotTriageModel` that includes K
      diverse training-set examples (1 ticket_worthy, 1 borderline,
      1 noise per family) in the prompt.
- [ ] **2.5** Cost / latency report alongside the metrics report. Token
      counts per window, total $ at headline operating point.
- [ ] **2.6** Cache responses by `hash(prompt + model + temperature)` under
      `data/derived/global/<id>/llm-cache/` so re-runs don't repay.

**Acceptance:** LLM zero-shot matches or beats `rule_baseline` on PR-AUC
strict; LLM few-shot reaches within 5pts of `logistic_numeric` while
spending <= $5 on the pilot test split.
**Blocks:** Phase 3 (LLM cross-encoder), Phase 5 (RAG triage).
**Runs on:** pilot now (small split), v4-large after.

---

## Phase 3 — LLM cross-encoder reranker
**Goal:** use an LLM as a second-stage scorer over BM25/embedding's top-K
candidates - the textbook RAG reranking move.

- [ ] **3.1** `LLMCrossEncoderReranker` in `src/loganalyzer/memory/rerank.py`.
      Takes top-K from a base retriever, asks the LLM "rate similarity
      0-10" for each (window, memory) pair, sorts by LLM score.
- [ ] **3.2** Batched scoring (one prompt scores all K candidates at once
      to cut latency / cost).
- [ ] **3.3** Wire into the analyzer as a wrapper retriever:
      `RerankingRetriever(base=EmbeddingRetriever(), reranker=LLMCrossEncoder(), first_stage_k=20)`.
- [ ] **3.4** Add a "novelty-aware" prompt variant that explicitly returns
      `is_novel=true` when no candidate looks close. Compare to the
      existing distance-threshold novelty.

**Acceptance:** reranking lifts recall@5 by 5+ absolute points over the
embedding retriever alone, novelty F1 stays >= 0.85.
**Blocks:** Phase 4 (hybrid pipelines).
**Runs on:** pilot now, v4-large after.

---

## Phase 4 — Hybrid retrieval-augmented triage
**Goal:** flip the pipeline - retrieve memory FIRST, then condition triage
on the retrieved memories. This is the canonical RAG-for-classification
pattern and ought to help borderline calls.

- [ ] **4.1** `RAGTriageModel` in `src/loganalyzer/triage/rag.py`.
      At inference: retrieve top-K Jira memories for the window, build
      a prompt that includes their summaries + resolution_notes, ask
      LLM "given these prior incidents, is this window ticket-worthy?".
- [ ] **4.2** Compare RAG triage vs. triage-then-retrieve on
      novelty F1 and on borderline-bucket performance.
- [ ] **4.3** **Ablation:** swap retrieved memory for randomly sampled
      memory - if RAG still wins, the gain is from the LLM, not memory.
      If it loses, memory is genuinely informative.
- [ ] **4.4** **Two-stage ensemble:** numeric logistic produces a coarse
      score; RAG only fires for windows in the [0.3, 0.7] uncertainty
      band. Cheap + accurate.

**Acceptance:** RAG-triage beats the best non-RAG triage by 5+ pts PR-AUC
on the borderline-heavy strata; ablation shows memory contributes (not
just LLM).
**Blocks:** Phase 8 (production hardening).
**Runs on:** pilot now (small), v4-large after.

---

## Phase 5 — Advanced classical classifiers
**Goal:** strong non-LLM baselines so we know how much the LLM actually
buys us.

- [ ] **5.1** Gradient boosting head (`xgboost` or `lightgbm`) over the
      28 numeric features. Add `GradientBoostTriageModel` to loganalyzer.
- [ ] **5.2** Gradient boosting over the dense template-count vector
      from logsense. Compare to the pure-Python logistic.
- [ ] **5.3** Tiny fine-tuned transformer (DistilBERT or MiniLM, frozen
      backbone + 1 linear head) on `evidence_text` -> triage_label.
      Lives in `src/loganalyzer/triage/finetuned_transformer.py`.
      Gate behind `try: import torch`.
- [ ] **5.4** Calibration layer: Platt scaling + temperature scaling +
      isotonic regression. Each model's `.predict_score` output gets
      post-calibrated using the validation split.
- [ ] **5.5** Per-family adaptive thresholds (one threshold per family,
      picked on validation). Compare to the single global threshold.

**Acceptance:** at least one non-LLM model lifts PR-AUC by 3+ pts over the
current pure-Python logistic; calibration drives ECE below 0.05 on the
test split.
**Runs on:** pilot now.

---

## Phase 6 — Memory enhancement
**Goal:** improve recall@k by enriching the Jira memory corpus itself.
Retrieval recall on pilot is bottlenecked partly by sparse memory_text.

- [ ] **6.1** LLM-generated summary field: for each memory entry, ask LLM
      to produce a one-paragraph incident summary. Store as
      `memory_text_summary` alongside the existing `memory_text`.
- [ ] **6.2** Hypothetical-window generation: for each memory entry,
      ask LLM to synthesize the kind of telemetry window that would
      trigger it. Index those synthetic windows alongside real ones (HyDE).
- [ ] **6.3** Hard-negative mining: from the v4-large training set,
      collect windows whose top retrieval hit is wrong; use these to
      contrast-train an embedding head.
- [ ] **6.4** Memory cluster index: cluster memory entries with the
      embedding retriever; surface cluster centroid as the citation
      when individual hits are weak.

**Acceptance:** recall@5 lifts 5+ pts on v4-large over the Phase 1
embedding retriever alone.
**Blocks:** none; runs in parallel with later phases.
**Runs on:** v4-large only (pilot corpus too small to differentiate).

---

## Phase 7 — Robust evaluation framework
**Goal:** make the headline numbers defensible for a paper.

- [ ] **7.1** Leave-one-run-out (LORO) folds in addition to LOFO.
      Tests temporal generalization vs scenario-family generalization.
- [ ] **7.2** Paired-bootstrap significance tests on every reported
      delta. Reject any "improvement" with p > 0.05.
- [ ] **7.3** Reliability diagrams per pipeline per family. PDF output.
- [ ] **7.4** Failure case study generator: pulls 5 ticket_worthy windows
      every pipeline missed, 5 noise windows every pipeline fired on.
      Emits `case-studies/` markdown files with full evidence text.
- [ ] **7.5** Cost-aware Pareto frontier plot: $/window vs PR-AUC, every
      pipeline on the same axes.

**Acceptance:** every claim in the future paper draft has a CI attached
and a case study supporting it.
**Runs on:** pilot now; final numbers on v4-large.

---

## Phase 8 — Product hardening
**Goal:** the SmartLogAnalyzer becomes something a real on-call team can
plug into their Loki / OTel pipe.

- [ ] **8.1** Streaming inference path: `LogSenseAnalyzer.analyze_stream(iter[LogLine])`
      that bucketizes lines into sliding windows and emits triage decisions
      online.
- [ ] **8.2** Confidence-aware abstention: any score in [t-margin, t+margin]
      returns label `escalate_to_human` instead of forcing a binary.
- [ ] **8.3** Active learning loop: track production windows where the
      analyzer abstained; feed back into the training set on a schedule.
- [ ] **8.4** Online retrieval index: appending a new Jira memory entry
      should not require a full re-fit. Lazy incremental indexing for both
      BM25 and the embedding retriever.
- [ ] **8.5** Dockerfile + sample compose under `deploy/loganalyzer/`.

**Acceptance:** the analyzer can be deployed as a service that accepts
windows on HTTP and returns AnalysisResults, with the memory corpus loaded
once at boot.
**Runs on:** v4-large.

---

## Cross-cutting deliverables

- [ ] **C1** Single comparison dashboard at
      `data/derived/global/<id>/comparison/dashboard.md` that aggregates
      every phase's headline numbers into one table.
- [ ] **C2** `examples/run_full_benchmark.py` - one-shot script that fits
      every pipeline, runs every retrieval backend, writes the dashboard.
      Used by CI / paper-experiment reproducibility.
- [ ] **C3** Per-phase results frozen as `benchmarks/<phase>-<date>/` so
      progress is auditable.

---

## Decision points

These are explicit forks that need user input before locking the plan.

1. **LLM provider.** Anthropic Claude (default - team has access) or
   OpenAI GPT (familiar to most researchers)? Both supported in Phase 2;
   pick one for headline numbers.
2. **Embedding model.** `all-MiniLM-L6-v2` (cheap, CPU, 384-dim) or
   `bge-small-en-v1.5` (slightly better, same footprint)? Default: MiniLM.
3. **Fine-tuned transformer scope** (Phase 5.3). Frozen-backbone linear
   head only, or full fine-tune? Default: frozen.
4. **Cost ceiling.** What's the budget for LLM phases on v4-large? Rough
   estimate: $20-50 for zero-shot, $50-150 for cross-encoder, $50-100 for
   RAG triage. Total likely under $300 across all phases.

---

## Suggested execution order (sprints)

| Sprint | Phases               | Duration | Depends on             |
| ------ | -------------------- | -------- | ---------------------- |
| 1      | Phase 0              | 1 day    | nothing                |
| 2      | Phase 1, Phase 5     | 3 days   | Phase 0                |
| 3      | Phase 2              | 2 days   | Phase 0; LLM key       |
| 4      | Phase 3, Phase 4     | 4 days   | Phase 1, Phase 2       |
| 5      | Phase 6              | 3 days   | v4-large landed        |
| 6      | Phase 7              | 2 days   | most phases run        |
| 7      | Phase 8              | 5 days   | best pipeline picked   |

Sprints 1-4 run on pilot data and finish before v4-large lands. Sprint 5
onward uses v4-large numbers for the headline benchmark.

---

## Quick wins available right now (today)

These do not block on v4-large or on the decision points above:

- [ ] Phase 0.1: stratified evaluator
- [ ] Phase 0.2: score ensemble
- [ ] Phase 5.1: gradient-boost on numeric features
- [ ] Phase 5.4: calibration layer (Platt + temperature)
- [ ] Phase 7.4: failure case study generator

Pick any of those to start.
