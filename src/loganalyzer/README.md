# loganalyzer

Smart log analysis system that decides, for every telemetry window:

1. **is this worth a Jira ticket?** (triage)
2. **which past issues does it look like?** (memory retrieval)
3. **is this a novel incident?** (no close match in memory)

Trained and evaluated on the v4 dataset described in `docs/dataset-v4-plan.md`;
contract in `docs/triage-task-contract.md`.

---

## 1. The big picture

```
                       ┌─────────────────────────────────────────────────┐
                       │  Jira memory corpus  (jira-memory-corpus.jsonl) │
                       │  -- past tickets, time-ordered, used as memory  │
                       └────────────────────┬────────────────────────────┘
                                            │ fit (index once)
                                            ▼
   ┌────────────────────┐         ┌─────────────────────┐        ┌────────────────────┐
   │ Telemetry window   │ ──────► │  SmartLogAnalyzer   │ ─────► │  AnalysisResult    │
   │ (one row from      │ analyze │  triage + retrieval │        │  triage_decision   │
   │  global-triage-    │         │                     │        │  is_novel          │
   │  examples.jsonl)   │         │                     │        │  matched_issues[]  │
   └────────────────────┘         └─────────────────────┘        └────────────────────┘
```

Inside `SmartLogAnalyzer.analyze(window)`:

```
   window ──► NumericFeaturizer ──► 28-dim vector ──► LogisticTriageModel ─┐
              (triage_feature_*)                                            │
                                                                            ▼
   window ──► tokenize(evidence_text) ──► tf-idf ──► LexicalTriageModel ──► blend ──► triage_score
                                                                                          │
                                                                                          ▼
                                                                            ┌─── if >= threshold ──┐
                                                                            │                      │
                                                                            ▼                      ▼
                                                                       decision="noise"     decision="ticket_worthy"
                                                                                                   │
                                                                                                   ▼
                                                                       BM25Retriever / Embedding / Hybrid
                                                                       over visible-to-window memory
                                                                                                   │
                                                                                                   ▼
                                                                       top-k Jira citations + is_novel flag
```

The retriever respects two visibility rules at query time:

- only memory entries created **before** the window's `start_time` are visible
- entries from the window's **own dataset_run_id** are excluded (no leakage)

---

## 2. What the model takes as input

The unit of inference is a `TriageWindow` - one row from
`global-triage-examples.jsonl`. Each window has two parallel views:

### 2a. Structured numeric view (what `LogisticTriageModel` sees)

A flat 28-feature vector pulled from columns prefixed `triage_feature_*`.
Half are the raw signal, half are the delta vs the pre-fault baseline window
for the same service.

| Group     | Feature                                | Why it matters                                       |
|-----------|----------------------------------------|------------------------------------------------------|
| Traces    | `trace_error_rate`                     | gRPC/HTTP error rate from Tempo span bodies          |
| Traces    | `trace_error_count`                    | absolute error count, useful when traffic is low     |
| Traces    | `trace_latency_p50_ms`, `_p95_ms`      | latency degradation signal                           |
| Traces    | `trace_span_count`, `trace_count`      | traffic volume - distinguishes outage vs quiet hour  |
| Logs      | `log_error_count`, `_warning_count`    | Loki body severity, JSON-aware                       |
| Logs      | `log_total_count`                      | volume baseline                                      |
| Metrics   | `metric_cpu_pct`, `metric_memory_pct`  | cAdvisor resource usage                              |
| K8s       | `k8s_pod_unavailable_count`            | desired vs ready replicas - catches scale-downs      |
| K8s       | `k8s_restart_count`, `_warning_event_count` | restart loops and warning events filtered to service |
| Delta\*   | every feature above with `delta_` prefix | active vs pre_fault_baseline difference - the key learnable signal |

### 2b. Free-text view (what `LexicalTriageModel` and the retrievers see)

The `triage_evidence_text` field is a structured snapshot of the window:

```
WINDOW window_id=...  service=frontend  start=2026-05-22T00:57:48Z  end=...
LOG-ERRORS
[error] request error
[error] request error
...
TRACES total_spans=80 error_spans=24 p50_ms=0.5 p95_ms=5882.3
  root=frontend count=13
  root=grpc.hipstershop.CurrencyService/Convert count=5
  ...
```

The lexical model and BM25 retriever tokenize this text (lowercase,
alphanumeric, len>=2) and treat it as a bag-of-tokens query against the Jira
memory corpus.

---

## 3. Real input example (from the pilot dataset)

Window `2026-05-21-dataset-v4-pilot-compact-a-r02-cart-redis-degradation-critical-20260522T005748Z-active_fault-frontend`:

```
scenario_id:   cart-redis-degradation-critical
service:       frontend
window_type:   active_fault
gold label:    ticket_worthy
gold is_novel: false  (a similar issue already exists in memory)
```

**Numeric view (showing the 5 features that fired):**

| Feature                              | Value  |
|--------------------------------------|-------:|
| `trace_error_rate`                   |  0.300 |
| `trace_error_count`                  | 24.0   |
| `delta_trace_error_count`            | 18.0   |
| `log_error_count`                    | 183.0  |
| `trace_latency_p95_ms`               | 5882.3 |

(other 23 features are 0 or near-baseline)

**Text view (first 400 chars of `evidence_text`):**

```
WINDOW window_id=...cart-redis-degradation-critical...active_fault-frontend
       service=frontend  start=...00:57:48Z  end=...00:59:05Z
LOG-ERRORS
[error] request error
[error] request error
[error] request error
... (183 lines of [error] request error)
TRACES total_spans=80 error_spans=24 p50_ms=0.5 p95_ms=5882.3
  root=frontend count=13
  root=grpc.hipstershop.CurrencyService/Convert count=5
  ...
```

---

## 4. Real output example

After `analyzer.analyze(window)` on the input above:

```text
AnalysisResult
  window_id        : ...active_fault-frontend
  triage_score     : 0.6636                          # P(ticket-worthy)
  triage_decision  : ticket_worthy
  is_novel         : False
  matched_issues   :
    [rank 1] OBSRV-1004   score=15.83   family=cart-redis              service=cartservice
    [rank 2] OBSRV-1001   score=13.22   family=productcatalog-latency  service=checkoutservice
    [rank 3] OBSRV-1002   score=11.70   family=payment-outage          service=checkoutservice
  citation_summary : Likely matches OBSRV-1004 (cart-redis / cartservice). ...
```

And `render_explanation(result)` produces the human-facing string:

```
Window: ...cart-redis-degradation-critical-...active_fault-frontend
Triage: ticket_worthy (score=0.664)
Novelty: matches an existing pattern in Jira memory.
Recommendation: link to the top match before filing a new ticket.

Top matches:
  #1 OBSRV-1004 score=15.826 family=cart-redis        service=cartservice
        "Summary: Customer checkout path seeing elevated failures ..."
  #2 OBSRV-1001 score=13.225 family=productcatalog-latency service=checkoutservice
        "Summary: Intermittent slowness reported around checkoutservice ..."
  #3 OBSRV-1002 score=11.699 family=payment-outage    service=checkoutservice
        "Summary: Customer checkout path seeing elevated failures ..."

Summary: Likely matches OBSRV-1004 (cart-redis / cartservice). ...
```

The product behaviour summarised:

| Gold label      | Analyzer says           | Action surfaced to engineer                              |
|-----------------|-------------------------|----------------------------------------------------------|
| `noise`         | score < threshold       | "do not file a ticket"                                   |
| `ticket_worthy` | score >= threshold, match found | "link to OBSRV-1004 before filing a new ticket"   |
| `ticket_worthy` | score >= threshold, no match    | "NOVEL - file a new ticket; this looks unfamiliar"|

---

## 5. Package layout

```
src/loganalyzer/
  data/        TriageWindow, JiraMemoryIssue dataclasses
               load_dataset() reads global-triage-examples.jsonl,
               jira-memory-corpus.jsonl, window-memory-matchings.jsonl,
               triage-split-manifest.json, triage-feature-columns.json
  features/    NumericFeaturizer (column -> float vector)
               build_window_query_text() / build_memory_doc_text() / tokenize()
  triage/      RuleTriageModel        - hardcoded thresholds on 5 columns
               LogisticTriageModel    - L2 logistic on 28-dim numeric vector
               LexicalTriageModel     - tf-idf centroid (pos vs neg evidence text)
               HybridTriageModel      - weighted blend of numeric + lexical
  memory/      MemoryCorpus           - time-ordered, own-run exclusion
               BM25Retriever          - Okapi BM25 over memory_text tokens
               EmbeddingHashingRetriever - sha1 hashing-trick dense vectors
               HybridRetriever        - normalize + blend BM25 + embedding
  product/     SmartLogAnalyzer       - .fit(train_windows), .analyze(window)
               render_explanation()   - plain-text formatter for chatops
  eval/        pr_auc, roc_auc, ECE, precision@FPR, F-beta
               recall@k, MRR, novelty F1
               run_full_evaluation()  - train -> threshold-tune -> test
  cli/         python -m loganalyzer.cli.analyze
```

---

## 6. Quick start

```python
from loganalyzer.data import load_dataset, iter_split
from loganalyzer.memory.corpus import MemoryCorpus
from loganalyzer.memory.retrieval import BM25Retriever
from loganalyzer.product.analyzer import SmartLogAnalyzer
from loganalyzer.product.formatter import render_explanation
from loganalyzer.triage.hybrid import HybridTriageModel

ds = load_dataset("data/derived/global/2026-05-21-dataset-v4-pilot-global")
train = list(iter_split(ds.windows, ds.split_manifest, "train"))

analyzer = SmartLogAnalyzer(
    triage_model   = HybridTriageModel(ds.feature_columns),
    retriever      = BM25Retriever(),
    memory_corpus  = MemoryCorpus(issues=ds.memory_corpus),
)
analyzer.fit(train)

for window in ds.windows[:5]:
    result = analyzer.analyze(window)
    print(render_explanation(result))
```

---

## 7. CLI

```
python -m loganalyzer.cli.analyze \
    --global-dir data/derived/global/2026-05-21-dataset-v4-pilot-global \
    --triage-model hybrid \
    --retriever bm25
```

Choices:

| Flag             | Values                              | Effect                                         |
|------------------|-------------------------------------|------------------------------------------------|
| `--triage-model` | `rule`, `logistic`, `lexical`, `hybrid` | which classifier to fit                    |
| `--retriever`    | `bm25`, `embedding`, `hybrid`        | which memory retriever to index                |
| `--top-k`        | int (default 5)                      | how many Jira matches to surface               |
| `--target-fpr`   | float (default 0.05)                 | operating point picked on validation split     |

Writes under `<global-dir>/loganalyzer/<triage>-<retriever>/`:

- `report.md` — headline triage + retrieval + novelty metrics
- `report.json` — machine-readable copy
- `per-window-predictions.jsonl` — every test window's prediction trail

---

## 8. Demo

```
python examples/run_loganalyzer_demo.py
```

Fits a hybrid+BM25 analyzer on the pilot train split and prints one rendered
explanation per gold label (`ticket_worthy`, `borderline`, `noise`).

---

## 9. Pilot benchmark (576 windows, 39 memory issues)

| Pipeline          | PR-AUC strict | ROC-AUC | p@FPR=5% | recall@5 | novelty F1 |
| ----------------- | ------------: | ------: | -------: | -------: | ---------: |
| rule + embedding  |         0.380 |   0.644 |    0.522 |    0.045 |      0.500 |
| logistic + hybrid |         0.642 |   0.885 |    0.732 |    0.045 |      0.857 |
| lexical + bm25    |         0.653 |   0.912 |    0.542 |    0.106 |      0.571 |
| hybrid + bm25     |         0.658 |   0.900 |    0.744 |    0.061 |      0.857 |

Retrieval recall is low because the pilot corpus has only 39 issues and the
test split holds out 6 of 13 families. With the v4-large run (40 dataset
runs, ~400 memory entries spanning 20+ families) these numbers should climb.

---

## 10. Dependencies

Stdlib only - no numpy, scikit-learn, or torch required. The embedding
retriever uses Python's `hashlib` for deterministic dense vectors. A future
iteration will gate sentence-transformers behind an optional install for
companies that want stronger semantic recall.
