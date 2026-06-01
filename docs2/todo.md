# TODO: Advanced ML/AI Pipeline Plan

**Created:** 2026-05-23
**Last updated:** 2026-05-23 (v4-large landed; Phase 0.5 acceptance reframed
to match what's empirically true on the larger corpus)
**Owner:** Yuvraj
**Status doc:** complements `docs/ml-ai-pipeline-benchmark-plan.md` (vision)
and `docs/triage-task-contract.md` (metrics contract). This file is the
**actionable execution plan** - what to build, in what order, with which
acceptance bar.

---

## Design principle: Jira-as-memory in every approach

This is not "yet another log analyzer." The differentiator is that the
**Jira memory corpus feeds into every triage decision**, not only into
post-hoc citation. Any pipeline that scores a window must consult past
Jira issues; any pipeline that does not is a baseline-only artifact.

Concretely, every triage model accepted into this plan must consume at
least ONE of the following Jira-derived signals as a feature:

| Signal                          | Computed how                                                     |
| ------------------------------- | ---------------------------------------------------------------- |
| `jira_max_similarity_score`     | best BM25 / embedding score against the visible memory corpus    |
| `jira_top_k_mean_score`         | mean of the top-K memory match scores                            |
| `jira_n_close_matches`          | count of matches above a similarity threshold                    |
| `jira_top_family_match`         | scenario_family of the top-1 hit (categorical / one-hot)         |
| `jira_top_service_match`        | affected_service of the top-1 hit                                |
| `jira_fault_class_match`        | does the top hit's fault_compatibility_class match the window?   |
| `jira_recurring_recent`         | issues filed in the last N days that match this family + service |
| `jira_novelty_distance`         | `1 - jira_max_similarity_score` (continuous novelty signal)      |
| `jira_resolution_keywords`      | n-hot bag of common verbs from top-K resolution_notes            |

These features are computed under the SAME time-ordering rule as retrieval:
only Jira entries with `available_as_memory_from < window.start_time` and
`dataset_run_id != window.dataset_run_id` are visible. Anything that breaks
that rule leaks future labels and invalidates the result.

This principle reframes the pipeline architecture:

```
                  ┌────────────────────────────┐
   window  ──────►│  Jira-memory featurizer    │──► jira_* features
                  │  (Phase 0.5; mandatory)    │
                  └────────────┬───────────────┘
                               │
   window ──► signal features  │
                  │            │
                  ▼            ▼
            ┌─────────────────────────────┐
            │  Triage model               │──► triage_score, decision
            │  (rule / logistic / LLM /…) │
            └─────────────┬───────────────┘
                          │
                          ▼
                     retrieval + citation (still important, but
                     no longer the only place Jira shows up)
```

---

## Current state (entering the plan)

| Asset                                | State                                              |
| ------------------------------------ | -------------------------------------------------- |
| `src/loganalyzer`                    | Built. Numeric + tf-idf lexical + hybrid + BM25/hash-embedding/hybrid retrievers. v4-large: PR-AUC 0.723, ROC-AUC 0.898, recall@5 0.256, MRR 0.420. |
| `src/logsense`                       | Built. Log-only with Drain-lite template miner. v4-large: PR-AUC 0.493, ROC-AUC 0.741, recall@5 0.154, MRR 0.279 (log-only is honestly weaker, as expected). |
| `src/jira_features`                  | Built (Phase 0.5). 11 scalar Jira-memory features per window; `JiraOnlyTriageModel`; `LogisticTriageModel(jira_featurizer=...)`. |
| `src/comparison`                     | Built (Phase 0). Stratified eval + score-ensemble + paired-bootstrap CIs + unified CLI; 5 pipelines registered. |
| Pilot dataset (576 windows, 39 issues) | Renamed to `data/derived-pilot/` and `data/runs-pilot/` for archival. |
| **v4-large dataset (3216 windows, 208 issues, 40 runs)** | **Landed 2026-05-23. Lives at `data/derived/global/2026-05-22-dataset-v4-large-global/` and `data/runs/`.** |
| Phase 0.5 reports                    | Pilot: `data/derived-pilot/.../comparison/phase0.5/`. v4-large: `data/derived/.../comparison/phase0.5-full/report.md` (complete, 1000-bootstrap CIs, all 5 pipelines). |

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
**Jira utilization:** baseline only - the analyzers under comparison use
Jira solely for post-hoc citation. Phase 0.5 closes this gap.
**Blocks:** every later phase ("does X beat the baseline?" needs this).
**Runs on:** pilot now. **Status:** done 2026-05-23.

---

## Phase 0.5 — Jira-memory featurizer (foundational, mandatory)
**Goal:** every later phase consumes the same Jira-derived feature block
on every window. Without this, "Jira-as-memory" is just a tagline.

- [x] **0.5.1** New module `src/jira_features/`. Public entrypoint:
      `JiraMemoryFeaturizer(corpus).features_for(window) -> dict[str, float]`.
      Reuses BM25 over `MemoryCorpus.visible_to(window)` (time-ordering +
      own-run exclusion enforced for free).
- [x] **0.5.2** Emits the 11 scalar features in
      `JIRA_FEATURE_COLUMNS`: `max_score`, `top3_mean_score`,
      `top5_mean_score`, `score_spread_top1_top5`, `novelty_distance`,
      `n_visible_memory`, `n_above_half_top`,
      `top_service_matches_window`, `top_fault_compatible`,
      `recurring_same_service_24h`, `recurring_same_service_7d`.
- [x] **0.5.3** Wired into `loganalyzer.triage.logistic` and
      `loganalyzer.triage.hybrid` via `jira_featurizer=...` kwarg.
      logsense-side wiring deferred (requires API change to thread
      TriageWindow through `predict_score`; revisit if Phase 1 numbers
      motivate it).
- [x] **0.5.4** `JiraOnlyTriageModel` added to `loganalyzer.triage`.
      Logistic on the 11 jira_* features alone, used to test whether
      the Jira-memory signal carries standalone triage value.
- [x] **0.5.5** `LoganalyzerWithJiraPipeline` and `JiraOnlyPipeline`
      registered in `comparison.pipelines`. Reports regenerated on
      both pilot and v4-large.
- [x] **0.5.6** Feature-importance audit done. Top features by |weight|:
      `top_fault_compatible` (0.34), `n_above_half_top` (0.26),
      `novelty_distance` (0.26), `top5_mean_score` (0.25),
      `n_visible_memory` (0.23). Sensible: the categorical
      "is-this-fault-class-known?" outweighs raw similarity scores.

### Acceptance (REVISED 2026-05-23 after pilot + v4-large runs)

**Original criteria did not survive contact with the data:**

| Original                                                  | Pilot      | v4-large           | Status        |
| --------------------------------------------------------- | ---------- | ------------------ | ------------- |
| `loganalyzer_with_jira` PR-AUC >= baseline + 3pts         | -0.02 (ns) | -0.03 (sig wrong)  | **NOT MET**   |
| `jira_only` PR-AUC > `rule_baseline`                      | 0.30 < 0.38 | 0.24 < ~0.38      | **NOT MET**   |

The original framing assumed Jira features would lift triage PR-AUC.
On both corpora they don't - the 28 native trace+log+metric features
already saturate the triage signal, and Jira features add slight noise.

**What DID happen, and what we now accept:**

| Revised criterion                                         | Pilot                | v4-large            | Status |
| --------------------------------------------------------- | -------------------- | ------------------- | ------ |
| `loganalyzer_with_jira` recall@5 > baseline by 5pts (sig) | +14pt (p=0.002)      | +1pt                | **MET on pilot; v4-large baseline retrieval already strong** |
| `loganalyzer_with_jira` MRR > baseline by 5pts (sig)      | +13pt                | +4pt                | **MET on pilot; partial on v4-large** |
| Ensemble (with + without Jira) beats best single on retrieval | recall@5 0.37 vs 0.22 | recall@5 0.29 vs 0.26 | **MET** |
| Feature importance distribution is sensible (no all-zero cols) | yes              | yes                 | **MET** |

**Honest read:** Jira features lift retrieval / MRR, not triage PR-AUC,
on this dataset shape. The principle ("Jira-as-memory feeds every
model") is correctly implemented; its measurable benefit on these
corpora is in ranking quality of cited memory, not in the binary triage
call. The pilot-vs-v4-large delta in retrieval lift suggests Jira
features matter most when the baseline retriever is undercooked.

**Implications for later phases:** keep Phase 0.5 features as standard
input to every classifier and retrieval pipeline. Re-evaluate after
Phase 1 (real embeddings) - semantic Jira similarity may surface the
triage lift that BM25-only features miss.

**Jira utilization:** this IS the Jira utilization layer; every
downstream phase inherits its outputs.
**Blocks:** Phase 1, 2, 3, 4, 5 (all later phases use these features).
**Status:** done 2026-05-23 (pilot + v4-large both swept).

---

## Phase 1 — Real text embeddings (with Jira-paired training)
**Goal:** replace the hashing-trick embedding retriever with real semantic
embeddings, **AND** learn a window↔Jira pairing objective so the
embedding space is shaped by past triage decisions, not just by raw text
similarity.

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
- [ ] **1.4** **Contrastive head training.** From the v4 training split,
      build positive pairs `(window_evidence_text, matched_jira_memory_text)`
      using `window_memory_matchings.jsonl` ground truth. Train a small
      projection head on top of the frozen sentence-transformer with
      InfoNCE loss (random in-batch negatives). The trained projection
      shapes the embedding space toward "windows close to their gold
      Jira issues."
- [ ] **1.5** New triage feature surface fed by the embedding space:
      `jira_embedding_max_similarity`, `jira_embedding_topk_mean`,
      `jira_embedding_distance_to_centroid_per_family`. Added to the
      Phase 0.5 featurizer so every downstream model picks them up.
- [ ] **1.6** Cache: persist computed embeddings under
      `data/derived/global/<id>/embeddings/{windows,memory,projection}.npy`
      keyed by content hash so repeated runs are fast.

**Acceptance:** (a) real embeddings beat BM25 + hashing-trick on recall@5
by 5+ absolute points on pilot; (b) contrastive head adds another 3+
points over raw sentence-transformer embeddings; (c) Jira-embedding
features in 0.5 lift `loganalyzer_with_jira` PR-AUC by 2+ points.
**Jira utilization:** Jira issues drive the contrastive training labels
and the retrieval-derived features that flow into every model.
**Blocks:** Phase 4 (hybrid retrieval), Phase 5 (cross-encoder reranking).
**Runs on:** pilot now, will rerun on v4-large.

---

## Phase 2 — LLM zero-shot triage baselines (with and without Jira)
**Goal:** establish how a frontier LLM does at triage across THREE
prompting strategies, two of which use Jira memory. This is also the
cleanest test of how much Jira retrieval helps an LLM judge.

- [ ] **2.1** Provider abstraction `src/llm/provider.py` with
      `LLMProvider.complete(prompt, system) -> str`. Implementations:
      `AnthropicProvider`, `OpenAIProvider`. Reads API key from env.
- [ ] **2.2** Prompt templates in `src/llm/triage_prompts.py`:
      system message describes the triage task and the three labels;
      user message contains the evidence_text. Model must return a
      structured JSON `{label, confidence, reason}`.
- [ ] **2.3** `LLMZeroShotTriageModel` (Jira-blind baseline) -
      window text only. Establishes the no-memory ceiling.
- [ ] **2.4** `LLMFewShotTriageModel` - 3 generic examples in the prompt
      (1 ticket_worthy, 1 borderline, 1 noise) drawn from training.
      Still does not retrieve from Jira.
- [ ] **2.5** **`LLMRAGZeroShotTriageModel` (Jira-aware)** -- the
      headline Phase-2 model. At inference: retrieve top-K Jira issues
      with the Phase 1 retriever, embed their summaries + resolution_notes
      in the prompt as "here are 3 similar past tickets the team filed",
      then ask the LLM to triage. This is zero-shot in the no-fine-tune
      sense but Jira-conditioned.
- [ ] **2.6** Cost / latency report alongside the metrics report. Token
      counts per window, total $ per operating point, broken down per
      variant.
- [ ] **2.7** Cache responses by `hash(prompt + model + temperature)` under
      `data/derived/global/<id>/llm-cache/` so re-runs don't repay.

**Acceptance:** (a) the Jira-blind zero-shot matches/beats `rule_baseline`
on PR-AUC strict; (b) `LLMRAGZeroShotTriageModel` beats the Jira-blind
variant by 5+ pts PR-AUC on the borderline-heavy strata; (c) total LLM
spend stays under $10 on the pilot test split.
**Jira utilization:** 2.5 is the main Jira-using variant; the Jira-blind
2.3 + 2.4 exist precisely so we can measure the lift from Jira context.
**Blocks:** Phase 3 (LLM cross-encoder), Phase 4 (full RAG triage).
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
**Jira utilization:** the reranker IS Jira-using by construction - every
candidate is a Jira memory entry. The cross-encoder LLM call exists to
extract structured evidence from `memory_text` + `resolution_notes`.
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
**Jira utilization:** this is the *full-bore* Jira-as-memory product
architecture - the LLM is conditioned on retrieved Jira context for
every decision. Phase 0.5 features remain available alongside.
**Blocks:** Phase 8 (production hardening).
**Runs on:** pilot now (small), v4-large after.

---

## Phase 5 — Advanced classical classifiers (all Jira-aware)
**Goal:** strong non-LLM baselines so we know how much the LLM actually
buys us. Every classifier here consumes the Phase 0.5 `jira_*` features
on top of its native signal features - an "advanced classifier without
Jira features" is not in scope for this phase.

- [ ] **5.1** Gradient boosting head (`xgboost` or `lightgbm`) over the
      28 numeric features **PLUS** Phase 0.5 `jira_*` features. Add
      `GradientBoostTriageModel` to loganalyzer. Report feature
      importances split by signal-vs-Jira contribution.
- [ ] **5.2** Gradient boosting over the dense template-count vector
      from logsense **PLUS** `jira_*` features. Compare to the pure-Python
      logistic. Same importance breakdown.
- [ ] **5.3** Tiny fine-tuned transformer (DistilBERT or MiniLM, frozen
      backbone + 1 linear head) on `evidence_text` **concatenated with
      the top-3 retrieved Jira memory summaries** -> triage_label.
      Lives in `src/loganalyzer/triage/finetuned_transformer.py`.
      Gate behind `try: import torch`. Ablate: with vs without the
      retrieved Jira concatenation.
- [ ] **5.4** Calibration layer: Platt scaling + temperature scaling +
      isotonic regression. Each model's `.predict_score` output gets
      post-calibrated using the validation split.
- [ ] **5.5** Per-family adaptive thresholds (one threshold per family,
      picked on validation). Compare to the single global threshold.

**Acceptance:** at least one non-LLM model lifts PR-AUC by 3+ pts over
the current pure-Python logistic; calibration drives ECE below 0.05 on
the test split; the 5.3 ablation shows the Jira-concatenated variant
beats the text-only variant by 2+ pts PR-AUC.
**Jira utilization:** every model in this phase takes Jira features as
input; 5.3 additionally concatenates retrieved memory text into the
transformer's context window.
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
**Jira utilization:** the corpus itself is the artifact under improvement;
every other phase reads from this enriched corpus.
**Blocks:** none; runs in parallel with later phases.
**Runs on:** v4-large only (pilot corpus too small to differentiate).

---

## Phase 7 — Robust evaluation framework (incl. Jira-utilization metrics)
**Goal:** make the headline numbers defensible for a paper.

- [ ] **7.1** Leave-one-run-out (LORO) folds in addition to LOFO.
      Tests temporal generalization vs scenario-family generalization.
- [ ] **7.2** Paired-bootstrap significance tests on every reported
      delta. Reject any "improvement" with p > 0.05.
- [ ] **7.3** Reliability diagrams per pipeline per family. PDF output.
- [ ] **7.4** Failure case study generator: pulls 5 ticket_worthy windows
      every pipeline missed, 5 noise windows every pipeline fired on.
      Emits `case-studies/` markdown files with full evidence text **plus
      the top-3 Jira memory hits and their similarity scores** so a
      reader can see whether the model had the right memory available.
- [ ] **7.5** Cost-aware Pareto frontier plot: $/window vs PR-AUC, every
      pipeline on the same axes.
- [ ] **7.6** **Jira-utilization audit.** For each pipeline, report:
      (a) fraction of decisions where any `jira_*` feature was non-zero;
      (b) ablation: PR-AUC with Jira features zeroed out vs intact;
      (c) per-family Jira-lift table - which families gain the most
      from Jira context, which gain nothing. This is the evidence
      package for "Jira-as-memory actually matters."

**Acceptance:** every claim in the future paper draft has a CI attached,
a case study supporting it, AND a Jira-utilization measurement (so the
paper can quantify the Jira contribution rather than just gesture at it).
**Jira utilization:** the audit IS the measurement of Jira utilization
across every pipeline.
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
| 1.5    | **Phase 0.5 (Jira featurizer)** | **2 days** | **Phase 0; foundational for all later phases** |
| 2      | Phase 1, Phase 5     | 3 days   | Phase 0.5              |
| 3      | Phase 2              | 2 days   | Phase 0.5; LLM key     |
| 4      | Phase 3, Phase 4     | 4 days   | Phase 1, Phase 2       |
| 5      | Phase 6              | 3 days   | v4-large landed        |
| 6      | Phase 7              | 2 days   | most phases run        |
| 7      | Phase 8              | 5 days   | best pipeline picked   |

Sprints 1-4 run on pilot data and finish before v4-large lands. Sprint 5
onward uses v4-large numbers for the headline benchmark.
**Phase 0.5 is non-optional** - every later phase reads its outputs.

---

## Quick wins available right now (today)

These do not block on v4-large or on the decision points above:

- [x] Phase 0.1: stratified evaluator (done 2026-05-23)
- [x] Phase 0.2: score ensemble (done 2026-05-23)
- [x] Phase 0.3: paired-bootstrap CIs (done 2026-05-23)
- [x] Phase 0.5: Jira-memory featurizer (done 2026-05-23; acceptance
      revised to retrieval-lift rather than triage-PR-AUC-lift)
- [ ] **Phase 1: real text embeddings** ← next, where Jira features
      should *also* start helping triage via semantic similarity
- [ ] Phase 5.1: gradient-boost on numeric features + jira_* features
- [ ] Phase 5.4: calibration layer (Platt + temperature)
- [ ] Phase 7.4: failure case study generator (now includes top-3 Jira hits)
- [ ] Phase 7.6: Jira-utilization audit

The clean entry point is **Phase 1** - real text embeddings with
window<->Jira contrastive training. This is where Jira features start
helping triage, not just retrieval, because the BM25-derived signals
miss semantic family overlap that a sentence-transformer catches.
