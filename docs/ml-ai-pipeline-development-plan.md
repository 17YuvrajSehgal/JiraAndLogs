# ML/AI Pipeline Development Plan

**Created:** 2026-05-25
**Companion to:** `docs/ml-ai-pipeline-benchmark-plan.md` (the contract),
`docs/triage-task-contract.md` (the task), `docs/dataset-v4-plan.md` (the
data schema). This file is the **actionable iteration plan** for model
development between v4-large (collected, available now) and v5-large
(collecting on GCP VM, ~5 days out) plus v5-quick (collecting on this
laptop, ~10 hours out).

The goal is to **start training today** against v4-large while designing
every component so that v5's richer telemetry plugs in **without code
changes** — only column-list updates and Prometheus-query mappings.

---

## 1. Audit: what exists today

### Data on disk (ready to use right now)

| Asset | Path | State |
| --- | --- | --- |
| v4-large global triage | `data/derived/global/2026-05-22-dataset-v4-large-global/global-triage-examples.jsonl` | **3,216 windows, 13 families, 40.8% hard cases** |
| v4-large Jira memory | `.../jira-memory-corpus.jsonl` | **208 entries, time-ordered** |
| v4-large memory matchings | `.../window-memory-matchings.jsonl` | 1,358 matched / 41 novel |
| v4-large feature column contract | `.../triage-feature-columns.json` | **28 columns** (14 base × pre+delta) |
| v4-large split manifest | `.../triage-split-manifest.json` | 1,008 train / 480 val / 1,728 test (split by scenario family) |
| Existing v4 baseline | `.../comparison/phase0.5-full/report.md` | `loganalyzer_hybrid_bm25` **PR-AUC 0.72**, `logsense_hybrid_bm25` 0.49 |
| v5-quick (collecting) | `data/derived/2026-05-25-dataset-v5-quick-control-r01/triage_examples.jsonl` (etc.) | Per-run files land as collection progresses |

Class distribution (v4-large): 55% noise / 22% borderline / 22% ticket_worthy.
Source: 100% `scenario_authored` — no human adjudication yet.

### Code on disk (model library)

| Module | Purpose | v5-readiness |
| --- | --- | --- |
| `src/loganalyzer/data/` | jsonl loaders + schema + family-split iterator | feature-list-agnostic ✓ |
| `src/loganalyzer/features/numeric.py` | `NumericFeaturizer(feature_columns)` + `StandardScaler` | **already reads column list from constructor — feature-list-agnostic ✓** |
| `src/loganalyzer/features/text.py` | text featurizer for evidence text | text-only — unaffected by v5 ✓ |
| `src/loganalyzer/triage/` | 5 model classes (rule, logistic, lexical, jira_only, hybrid) — all inherit `TriageModel` ABC | feature-list-agnostic (delegates to NumericFeaturizer) ✓ |
| `src/loganalyzer/memory/` | time-ordered corpus + retriever (BM25-able) | unaffected by v5 telemetry ✓ |
| `src/loganalyzer/product/analyzer.py` | `SmartLogAnalyzer` end-to-end (triage + retrieval + novelty + citations) | unaffected by v5 telemetry ✓ |
| `src/loganalyzer/eval/` | metrics + retrieval_metrics + runner | unaffected ✓ |
| `src/logsense/templates/` | Drain-lite log template miner + per-window fingerprints + anomalous-template surfacing | **directly benefits from v5 L1/L2/L3** ⬆ |
| `src/logsense/memory/`, `eval/`, `triage/` | logsense's own triage stack | feature-list-agnostic ✓ |
| `src/jira_features/featurizer.py` | BM25 + time-ordered memory wrapper | unaffected ✓ |
| `src/comparison/` | multi-pipeline harness with bootstrap, stratified, significance, ensemble | already generates `phase0.5-full/report.md` ✓ |
| `src/adjudication/adjudicate.py` | D0.2 borderline/hard-case review CLI | unaffected ✓ |

### Code that BLOCKS v5 richness (must be fixed before v5 features land in models)

| File | Issue | v5 impact | Fix |
| --- | --- | --- | --- |
| `scripts/research-lab/run_triage_benchmark.py` | imports `FEATURE_COLUMNS` from `triage_labels.py` (hardcoded 28 cols) and uses it directly | **Silently ignores all v5 RED / business / runtime columns** | Read from `triage-feature-columns.json` instead. ~10 line change. |
| `scripts/research-lab/build_triage_dataset.py` | uses hardcoded `_BASE_FEATURE_COLUMNS` (line 31) to know which Prometheus queries to fire | Per-run `triage_examples.jsonl` will NOT contain v5's new RED/business/runtime features even though they exist in raw exports | Add a Prometheus-query mapping for the new metrics. Bigger change — see Phase 3 below. |
| `scripts/research-lab/triage_labels.py` | `_BASE_FEATURE_COLUMNS` tuple is the source of truth | Adding features means editing this tuple; risk of forgetting downstream changes | Long-term: switch to a YAML-driven feature catalog. Short-term: extend the tuple and add the queries. |

Note: `build_global_triage_dataset.py` is **already** feature-list-agnostic
(line 100 scans `key.startswith("triage_feature_")` dynamically), so the
global aggregator will pick up whatever per-run builders emit. The chain is
strong everywhere except the two endpoints above.

---

## 2. What v5 will deliver that v4 cannot

When v5-large (or v5-quick) lands, the dataset will gain the following
production-grade signals that v4 entirely lacks. These are exactly what M0–M5
landed in `microservices-demo-google`:

### New numeric features (Prometheus side)

| Family | Examples | What it enables |
| --- | --- | --- |
| **RED metrics per RPC** | `rpc_server_duration_seconds_p50/p95`, `rpc_server_requests_total` per `{method, status}` | Direct latency + error rate features that don't have to be derived from spans. Triple the trace coverage. |
| **Per-dependency client metrics** | `rpc_client_duration_seconds`, `rpc_client_errors_total` per `{peer_service, operation}` | Direct measurement of cart→Redis, checkout→payment, etc. The cart-redis family becomes much more separable. |
| **Business counters** | `payments_total{card_type, result}`, `cart_operations_total{op, result}`, `orders_placed_total`, `recommendations_served_total`, `catalog_lookups_total{result}` | **Drop in `orders_placed_total` during active_fault is a strong, label-free ticket-worthiness signal.** Carries semantic meaning a model can learn. |
| **Runtime gauges** | `go_goroutines`, `process_runtime_dotnet_gc_*`, `python_gc_*`, `nodejs heap`, `jvm gc/threads/classes` | Saturation features. `slow-leak-saturation` (D1.8) becomes visible in process_memory_resident_bytes; today it's invisible. |

### New log diversity (logsense beneficiary)

| Layer | New content | logsense impact |
| --- | --- | --- |
| **L1 per-RPC** | One JSON log per RPC with `{trace_id, span_id, method, peer_service, latency_ms, status_code, err_class}` — every single request | **Template space explodes** — Drain-lite goes from ~50 templates per service to several hundred. PR-AUC 0.49 → likely 0.65+ on cart-redis. |
| **L2 dep-error** | `{dep, op, err_class, retry_attempt}` on every failure | Discriminative templates aligned with fault *shape*, not fault *name*. Reduces lab-bias risk. |
| **L3 business events** | `cart_size_changed`, `order_placed`, `payment_charged`, `recommendation_returned` | Baseline shape for "what should be happening" — anomalies are then defined as "this drop is unusual", not "this string matches an error pattern". |

### New trace signal

- `RecordError` + `SetStatus(Error)` on every error-returning handler across 5 languages → measured **3.0× lift in `trace_error_count`** on cart-redis active_fault windows. The existing `triage_feature_trace_error_count` becomes far more discriminative without any code change.

### New categorical signal (NEW for v5 — not currently handled anywhere)

The new business/RED metrics carry bounded enum labels:

- `card_type` ∈ {visa, mastercard, other}
- `result` ∈ {success, invalid, expired, unsupported}
- `op` ∈ {add, get, empty}
- `err_class` (per language: `ConnectTimeoutException`, `CartNotFound`, etc.)
- `peer_service`, `operation`, `status`, `method`

**Today, none of the numeric feature columns are split by these dimensions.** Adding them is the v5 architectural decision — see Phase 3.

### New benchmark tracks

- **`orphan_fault_detection`** (D12): 192 ticket_worthy windows in v5 with NO paired Jira shadow row, with `expected_in_memory=false + is_novel=true`. Enables the **orphan-detection recall gap** metric: how much does a pipeline's recall drop when it can no longer rely on a memory match? Verdict bucketing: `signal_learning` (gap < 10pts), `borderline` (10–20), `pattern_matching` (> 20).
- **System-faults from chaos-mesh** (D11): 50 active_fault windows with shapes that have no application exceptions (packet loss, DNS, partition, memory pressure). The pure logs/metrics signal has to carry the decision. **v5-quick excludes this; v5-large includes it.**

---

## 3. Development roadmap (4 phases)

### Phase 1 — Start training TODAY on v4-large (~2 hours)

**Goal:** have a working end-to-end model iteration loop against the
already-collected v4-large global dataset. Establishes the floor and
the iteration UX before v5 data arrives.

**Tasks:**

1. **Fix `run_triage_benchmark.py` to read from `triage-feature-columns.json`** instead of importing `FEATURE_COLUMNS`. ~10 line change; preserves backward compatibility because v4-large's contract file lists the same 28 columns.
2. **Re-run the existing comparison harness** on v4-large to confirm a reproducible baseline:
   ```powershell
   Set-Location C:\workplace\JiraAndLogs
   & .venv\Scripts\python.exe -m src.comparison.cli `
     --global-dir "data\derived\global\2026-05-22-dataset-v4-large-global" `
     --runs-root "data\runs" `
     --pipelines loganalyzer,logsense `
     --output-dir "data\derived\global\2026-05-22-dataset-v4-large-global\comparison\phase1-baseline"
   ```
   Expected: `loganalyzer_hybrid_bm25` PR-AUC ~0.72, `logsense_hybrid_bm25` ~0.49 (matching `phase0.5-full`).
3. **Author `notebooks/` (or a `experiments/` Python script)** for fast iteration:
   - Load global-triage-examples.jsonl + split manifest
   - Read feature columns from contract file
   - Train a sklearn `GradientBoostingClassifier` or `RandomForestClassifier` (NOT yet in the existing pipelines)
   - Score on test, report PR-AUC / ROC-AUC / Precision@FPR=1%
   - Side-by-side vs the rule + logistic baselines
4. **Confirm the orphan-detection recall gap metric is wired** (it's in
   `comparison/runner.py` per the source; v4 has only 1.3% novel windows so
   the metric will be noisy, but the code path must work).

**Acceptance:** developer can edit a model in `experiments/baseline_v4.py`,
re-run, and see new metrics in under 30 seconds. Three model variants
tried (existing rule, existing logistic, new gradient boosting) and ranked
on PR-AUC on the test split.

### Phase 2 — Strengthen the v4 baselines (~1 week)

**Goal:** push the v4 leaderboard before v5 arrives, so we know what
real headroom v5 gives us (not just "we trained a bigger model").

**Tasks:**

1. **Add classical-ML pipelines as `PipelineRunner` subclasses** in
   `src/comparison/pipelines.py`:
   - `GradientBoostingPipeline` — sklearn HistGradientBoosting over the numeric features. Should beat logistic on tree-friendly features like `delta_trace_error_count`.
   - `CalibratedRandomForestPipeline` — RF + isotonic calibration on val. Calibrated probabilities matter for the Precision@FPR=1% headline.
   - Both must implement `fit`, `predict`, expose `feature_columns` dynamically, and respect the family-holdout split.
2. **Add the strict / inclusive borderline reporting** — borderline counted as negative (headline) AND positive (inclusive). The contract requires both; `comparison/runner.py` may already support this — confirm before re-implementing.
3. **Wire up Expected Calibration Error and reliability curves** end-to-end. Required by the contract.
4. **Add leave-one-family-out (LOFO) macro metrics**. The split manifest declares them; the runner needs to iterate and aggregate. This is the primary generalization signal — a model that wins on the default test split but loses on LOFO has memorized the test family.
5. **Quick lexical featurization experiment**: BM25 over the `triage_evidence_text` field against a small set of ticket-worthy and noise reference texts (per `ml-ai-pipeline-benchmark-plan.md` Triage / Lexical). Will be MUCH stronger on v5 once L1/L2/L3 logs lift template diversity.

**Acceptance:** comparison harness emits a v4 leaderboard with at least 6
pipelines, all with PR-AUC + ROC-AUC + Precision@FPR=1% + ECE + LOFO macros,
borderline strict + inclusive both reported. New strong baseline numbers
recorded in `data/derived/global/2026-05-22-dataset-v4-large-global/comparison/phase2-leaderboard/report.md`.

### Phase 3 — v5-quick lands; design for richer features (~1 week from corpus end)

**Goal:** when v5-quick's ~470 windows land, immediately measure the
**richness ablation** — does the same model architecture pick up real lift
from the new RED / business / runtime / template signals?

**Tasks:**

1. **Extend `_BASE_FEATURE_COLUMNS`** in `triage_labels.py` to declare the
   new v5 metric columns. Group them so the catalog is readable:
   ```python
   _RED_METRIC_COLUMNS = (
       "triage_feature_rpc_server_requests_total",
       "triage_feature_rpc_server_duration_seconds_p50",
       "triage_feature_rpc_server_duration_seconds_p95",
       "triage_feature_rpc_server_error_rate",
       # ... per service-method-status bucket
   )
   _BUSINESS_COUNTER_COLUMNS = (
       "triage_feature_orders_placed_total",
       "triage_feature_payments_total_success",
       "triage_feature_payments_total_error",
       "triage_feature_cart_operations_total_add",
       "triage_feature_cart_operations_total_empty",
       "triage_feature_recommendations_served_total",
       "triage_feature_catalog_lookups_total_hit",
       "triage_feature_catalog_lookups_total_miss",
   )
   _RUNTIME_COLUMNS = (
       "triage_feature_process_memory_rss_bytes",
       "triage_feature_process_cpu_seconds_total_rate",
       "triage_feature_go_goroutines",
       "triage_feature_dotnet_gc_collections_per_sec",
       "triage_feature_python_gc_collected_per_sec",
       "triage_feature_nodejs_heap_used_bytes",
       "triage_feature_jvm_gc_collections_per_sec",
   )
   _BASE_FEATURE_COLUMNS = _LEGACY_BASE_COLUMNS + _RED_METRIC_COLUMNS + _BUSINESS_COUNTER_COLUMNS + _RUNTIME_COLUMNS
   ```
2. **Extend `build_triage_dataset.py`** with the Prometheus queries that
   populate each new feature from the per-window raw export. The existing
   per-window extractor already opens `raw/prometheus/*.json`; new
   PromQL queries should be one-liner additions per feature.
3. **Add a `v4-vs-v5 richness ablation`** to the comparison harness — train
   the same pipeline twice, once with only `_LEGACY_BASE_COLUMNS` (the v4
   feature subset) and once with the full v5 feature catalog. Report the
   lift per pipeline. Should be **largest on the families v5 specifically
   targets** (slow-leak via runtime gauges, payment scenarios via
   `payments_total`, productcatalog via `catalog_lookups_total`).
4. **Activate logsense's template-diversity benefit** — re-run logsense on
   v5-quick data. Expected lift: PR-AUC 0.49 → ~0.65 because L1 logs add
   per-request template diversity Drain-lite can mine.
5. **Add the orphan-detection recall gap headline** to the comparison
   report — v5-quick gives 32 orphan ticket-worthy windows, enough for the
   metric to be computable with usable variance.

**Acceptance:** comparison report on v5-quick global derived shows (a) the
richness ablation lift, (b) logsense lift vs v4, (c) orphan recall gap per
pipeline with verdict bucket.

### Phase 4 — Categorical features + LM reranking (~2 weeks after v5-large lands)

**Goal:** unlock the new categorical signal v5 adds (card_type / op / result
/ err_class) and start the language-model reranking track per the benchmark
plan.

**Tasks:**

1. **Add categorical feature handling** to `NumericFeaturizer` (or a new
   `MixedFeaturizer`). The bounded enums in v5 should be one-hot at first
   (the cardinality is small: ≤4 values per dimension). Future: embedding
   tables when card_type × result × op × err_class cross-product grows.
2. **Implement language-model reranking over top-k** per
   `ml-ai-pipeline-benchmark-plan.md` §Language Models. Start with:
   - Top-k retrieval from `loganalyzer_hybrid_bm25` (k=10)
   - Claude API call per query with bounded prompt (window evidence text + 10 candidate Jira issue texts)
   - Rationale-then-score rerank
   - **Temperature-scale** on val split before scoring on test (LMs are poorly calibrated by default — required by contract)
3. **Add bi-encoder neural pipeline** — `sentence-transformers/all-MiniLM-L6-v2` over `triage_evidence_text` (already wired into `run-global-embedding-pipeline-benchmark.ps1`, but the triage variant doesn't exist yet).
4. **Cross-encoder for hard cases only** — re-rank only the windows where (a) PR-AUC < threshold OR (b) `is_hard_case=true`. Saves cost vs running cross-encoder on every window.
5. **Stacking / hybrid blend** — weighted log-odds combination of: classical features, lexical BM25, embedding cosine, LM score. Reciprocal-rank fusion doesn't apply directly to classification — use stacking.

**Acceptance:** v5-large leaderboard with ≥10 pipelines, neural + LM
included, headline PR-AUC moved by ≥5pts vs the best v5 classical pipeline.
**Honest reporting required:** if LM doesn't beat tuned classical features,
say so.

---

## 4. Iteration loop — what to actually do this afternoon

### Step 0: confirm v4 baseline is reproducible

```powershell
Set-Location C:\workplace\JiraAndLogs
& .venv\Scripts\python.exe -m src.comparison.cli `
  --global-dir "data\derived\global\2026-05-22-dataset-v4-large-global" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,logsense `
  --output-dir "data\derived\global\2026-05-22-dataset-v4-large-global\comparison\phase1-baseline"
```

Expected (matching the committed phase0.5-full report):

| Pipeline | PR-AUC | ROC-AUC | Precision@FPR=5% |
| --- | ---: | ---: | ---: |
| `loganalyzer_hybrid_bm25` | ~0.72 | ~0.90 | ~0.70 |
| `loganalyzer_hybrid_with_jira` | ~0.69 | ~0.86 | ~0.70 |
| `jira_only` | ~0.24 | ~0.55 | ~0.28 |
| `logsense_hybrid_bm25` | ~0.49 | ~0.74 | ~0.62 |
| `ensemble_mean` | ~0.69 | ~0.89 | ~0.70 |

If the numbers reproduce within ~1pt, the harness is healthy and the v4
baseline is locked.

### Step 1: stand up a fast iteration script

Create `experiments/baseline_v4.py` — minimal, no comparison-harness
overhead — that loads the global derived data, trains a gradient-boosting
classifier, and reports headline metrics in under 30 seconds. This is for
the "I want to try one feature engineering idea" loop.

### Step 2: try one new model — gradient boosting

`HistGradientBoostingClassifier` over the 28 v4 features. Should beat
logistic regression on tree-friendly features like `delta_trace_error_count`,
but probably loses to `loganalyzer_hybrid_bm25` because it has no text
signal. Headline measurement: where does it sit on the v4 leaderboard?

### Step 3: try one richness experiment WITHOUT v5

While we wait for v5-quick: the v4 dataset has `triage_evidence_text` per
window. Run BM25 over it against a small reference set of ticket-worthy and
noise window summaries. Compute the lift vs the no-text logistic baseline.
This is a dress rehearsal for v5's much-richer logsense — the architecture
should work today, just with weaker signal.

### Step 4: monitor v5-quick progress

The launcher is task `bao50470l`; the progress monitor is `b8iqd8qt5`. Each
run completion emits a notification. After ~3–4 hours (when ~5 runs are
done), build a partial global dataset and run the comparison harness against
it — that's the first real measurement of the v4→v5 lift on the same code.

---

## 5. Design principles (apply to every new file under `src/` or `experiments/`)

### Feature-list-agnostic — always

- **Never** import `FEATURE_COLUMNS` from `scripts/research-lab/triage_labels.py` in model code.
- **Always** read the feature list from `data/derived/global/<id>/triage-feature-columns.json` at fit time.
- Validate at fit time that all expected `triage_feature_*` columns are present in the training data; warn on missing columns rather than silently zero-filling.

### Production-realism discipline — non-negotiable

From `microservice-changes.md`, applied to model inputs too:

- **Don't** use `scenario_id`, `scenario_family`, `triage_label`, `triage_severity`, `triage_components`, `triage_reason_class`, `is_hard_case`, or any field listed as "eval-only" in `triage-feature-columns.json` as a model input.
- **Do** use only `triage_feature_*` and `triage_evidence_text` as inputs.
- The `feature_columns` key in the contract file is the authoritative input set; the `eval_only_fields` key is the authoritative ban list.
- A pipeline that violates this is **rejected**, even if it scores higher.

### Split discipline — required by the contract

- Always train on `split=train`, threshold-tune on `split=validation`, score on `split=test`.
- For LOFO macros, hold out one family at a time from the union and average.
- Never split rows randomly — always by `scenario_family`.

### Calibration — required for the headline metric

- Models that output probabilities for the Precision@FPR=1% operating point **must** be calibrated on the validation split (Platt or isotonic). Uncalibrated LMs are explicitly called out in the contract.

### Reproducibility — every benchmark report

- Record the `triage-feature-columns.json` SHA, `triage-split-manifest.json` SHA, model code SHA, and Python version in the benchmark report. The comparison harness already does this for `loganalyzer` + `logsense`; new pipelines must match.

---

## 6. What's intentionally NOT in this plan

- **Real Jira-Cloud integration** — Phase 2 of the product roadmap, not a model-development concern.
- **Active learning / human-in-the-loop** — depends on D0.4 human adjudication landing.
- **Cross-app generalization** (Sock Shop, TrainTicket) — Phase D6 in `dataset-todo.md`; current pipelines should work as-is when those corpora land.
- **Online inference latency optimization** — research first, productize later.
- **Distributed training** — datasets are small enough (≤10,000 windows) that single-laptop sklearn fits in seconds.

---

## 7. Reference: known v4-large headroom (from `phase0.5-full/report.md`)

| Pipeline | PR-AUC | ROC-AUC | Precision@FPR=5% | Recall@5 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loganalyzer_hybrid_bm25` | 0.7230 | 0.8975 | 0.7043 | 0.2557 | 0.4197 |
| `loganalyzer_hybrid_with_jira` | 0.6924 | 0.8648 | 0.7031 | 0.2628 | 0.4555 |
| `ensemble_mean` | 0.6918 | 0.8876 | 0.7004 | 0.2853 | 0.5514 |
| `logsense_hybrid_bm25` | 0.4928 | 0.7407 | 0.6243 | 0.1541 | 0.2794 |
| `jira_only` | 0.2385 | 0.5460 | 0.2766 | 0.0672 | 0.1742 |

Phase 2 target: any new pipeline must beat `loganalyzer_hybrid_bm25` PR-AUC
0.72 on v4 OR justify its inclusion via a different headline (calibration,
latency, interpretability).

Phase 3 target: same pipelines on v5-quick should show **≥5pt PR-AUC lift**
on the cart-redis family (the M5.1 gate's 3× trace_error_count lift should
flow through), AND **≥10pt PR-AUC lift on the slow-leak-saturation family**
(where v4 has zero runtime-gauge signal). If the lifts don't materialize,
either the build pipeline isn't actually populating new columns, or the
model isn't using them — both are bugs, not "v5 was overhyped".
