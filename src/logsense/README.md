# logsense

Smart **log-only** analysis system. For every telemetry window it decides:

1. **is this worth a Jira ticket?** (triage)
2. **which past Jira issues do its logs look like?** (memory retrieval)
3. **is this a novel incident?** (no close match in memory)
4. **which specific log lines are the weirdest?** (anomalous-template surfacing)

Sibling of `loganalyzer`. Same Jira-as-memory contract, completely different
input plane: where `loganalyzer` consumes 28 pre-aggregated `triage_feature_*`
columns spanning traces+metrics+kubernetes+logs, `logsense` goes back to the
**raw Loki log lines** exported per window and mines templates from scratch.

---

## 1. The big picture

```
            ┌──────────────────────────────────────────────────────────────┐
            │  raw Loki logs per window  (data/runs/<run>/raw/loki/*.json) │
            │  service streams: (timestamp_ns, body)                       │
            └──────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
       ┌─────────────────┐  ┌─────────────────────────┐  ┌──────────────────┐
       │ LogLine parsing │─►│ Drain-lite template     │─►│ Per-window       │
       │  + severity     │  │ mining: mask <UUID> /   │  │ fingerprint:     │
       │  inference      │  │ <NUM> / <TS> / <EMAIL>  │  │ template counts  │
       │  (.NET fail:,   │  │ / "<STR>" / <PATH>      │  │ + aggregates     │
       │   stack frames) │  └─────────────────────────┘  └─────────┬────────┘
       └─────────────────┘                                          │
                                                                    ▼
                                  ┌────────────────────┐   ┌────────────────────┐
                                  │ baseline           │   │ LogTriageModel     │
                                  │ fingerprint        │   │ (rule / logistic / │
                                  │ (avg over          │   │  anomaly / hybrid) │
                                  │ pre_fault windows  │   │ → triage_score     │
                                  │ for same service)  │   └─────────┬──────────┘
                                  └─────────┬──────────┘             │
                                            │                        ▼
                                            ▼          ┌─── if >= threshold ──┐
                                  compare_to_baseline  │                      │
                                            │          ▼                      ▼
                                            ▼     decision=noise       decision=ticket_worthy
                                  AnomalousTemplate[5]                       │
                                            ▲                                ▼
                                            │           LogTemplateBM25Retriever  ◄── Jira memory corpus
                                            │           query = anomalous tokens   (time-ordered, own-run
                                            │                + top in-window         exclusion)
                                            │                  templates
                                            └─── (surfaced to user) ──► top-K Jira citations + is_novel
```

---

## 2. What the model takes as input

The unit of inference is a **`WindowLogs`** — a list of `LogLine`s parsed
from the raw Loki JSON for one (run, episode, service, window_type)
combination.

```text
data/runs/<dataset_run_id>/raw/loki/<window_id>.json
        ├── service_window     ──► loaded as labeled-service LogLines
        ├── service_context    (broader before/after padding)
        └── namespace_context  (every pod in namespace)
```

Each `LogLine` carries:

| Field          | Source                                             | Example                                                  |
|----------------|----------------------------------------------------|----------------------------------------------------------|
| `timestamp_ns` | Loki entry timestamp                               | `1779410029152011849`                                    |
| `body`         | raw line                                           | `at Microsoft.Extensions.Caching.StackExchangeRedis...`  |
| `severity`     | JSON `severity`/`level`, `.NET fail:` tag, stack-frame detection, exception keywords | `error` |
| `service`      | Loki label `service_name`                          | `cartservice`                                            |
| `pod`          | Loki label `pod`                                   | `cartservice-568cbf9f9b-vn55j`                           |
| `container`    | Loki label `container`                             | `server`                                                 |

---

## 3. The template miner (the key piece)

Each line is masked into a **template** by replacing variable tokens with
named slots:

| Pattern                                       | Replacement |
|-----------------------------------------------|-------------|
| `8-4-4-4-12` hex strings                      | `<UUID>`    |
| `0x...` or `≥16` hex chars                    | `<HEX>`     |
| email-like `local@domain.tld`                 | `<EMAIL>`   |
| `https?://...`                                | `<URL>`     |
| dotted-quad IPv4 + optional `:port`           | `<IP>`      |
| ISO-8601 timestamps                           | `<TS>`      |
| durations `123ms / 1.2s / 45h`                | `<DUR>`     |
| unix or windows file paths                    | `<PATH>`    |
| quoted string literals `"..."` / `'...'`      | `"<STR>"`   |
| standalone integers / decimals ≥2 digits      | `<NUM>`     |

Plus **JSON-aware extraction**: if a body is a JSON object, the miner
extracts the canonical `message` / `msg` field first instead of masking
the whole serialized object.

Example transformation:

```text
RAW:
  {"message":"order confirmation email sent to \"youngsean@example.com\"",
   "severity":"info","timestamp":"2026-05-22T00:21:03.148434848Z"}

TEMPLATE:
  order confirmation email sent to "<STR>"
```

```text
RAW:
        at Microsoft.Extensions.Caching.StackExchangeRedis.RedisCache.GetAsync(
        String key, CancellationToken token)

TEMPLATE:
  at Microsoft.Extensions.Caching.StackExchangeRedis.RedisCache.GetAsync(
  String key, CancellationToken token)
```

---

## 4. Real input example (pilot dataset)

Window `2026-05-21-dataset-v4-pilot-compact-a-r01-cart-redis-degradation-critical-...active_fault-cartservice`
— 1500+ log lines from `cartservice` during a Redis outage.

| Aggregate feature   | Value  |
|---------------------|-------:|
| `n_lines`           |  1511  |
| `error_count`       |   ~930 |
| `warning_count`     |     0  |
| `unique_templates`  |    18  |
| `max_burst_per_sec` |    ~40 |

Top-3 in-window templates by count (after masking):

```text
182x  info: Grpc.AspNetCore.Server.ServerCallHandler[<NUM>]
185x  at Microsoft.Extensions.Caching.StackExchangeRedis.RedisCache.GetAndRefreshAsync(
        String key, Boolean getData, CancellationToken token)
185x  --- End of inner exception stack trace ---
```

---

## 5. Real output example

`analyzer.analyze(window)` on the input above:

```text
Window: ...cart-redis-degradation-critical-...active_fault-cartservice
Triage: ticket_worthy (score=0.416)

Anomalous log templates (vs same-service baseline):
  - severity=error    active=185 baseline=0   novelty=370.00
    template: at Microsoft.Extensions.Caching.StackExchangeRedis.RedisCache.GetAndRefreshAsync(
              String key, Boolean getData, CancellationToken token)
  - severity=error    active=185 baseline=0   novelty=370.00
    template: --- End of inner exception stack trace ---
  - severity=error    active=179 baseline=0   novelty=358.00
    template: ---> StackExchange.Redis.RedisConnectionException: It was not possible to
              connect to the redis server(s). ConnectTimeout
  - severity=error    active=179 baseline=0   novelty=358.00
    template: Error status code '<STR>' with detail '<STR>'t access cart storage.
              StackExchange.Redis.RedisConnectionException: The message timed out in...

Novelty: NOVEL - no close log-template match in Jira memory.
Recommendation: file a new ticket; surface the anomalous lines above.

Summary: Likely novel log pattern. Top weird line: "at Microsoft.Extensions.
Caching.StackExchangeRedis.RedisCache.GetAndRefreshAsync(...)" (185x in
window, 0x in baseline).
```

The differentiator vs `loganalyzer`: companies see **specific log lines
ranked by novelty** alongside the triage decision, not just a score. That's
what an on-call engineer actually wants to copy into a ticket.

---

## 6. Package layout

```
src/logsense/
  data/        LogLine, WindowLogs dataclasses
               load_window_logs() reads data/runs/<run>/raw/loki/<window>.json
               load_logs_dataset() joins labels from loganalyzer's global dir
  templates/   mask_line() - the Drain-lite token masker
               TemplateMiner - global vocabulary builder
               fingerprint_window() - per-window template counts + aggregates
               compare_to_baseline() - top anomalous templates vs same-service
                                       baseline fingerprint
  triage/      ErrorBurstRuleModel       - rule on error/burst aggregates
               TemplateLogisticModel     - L2 logistic on top-K template counts
               AnomalyScoreModel         - per-template ticket-worthy frequency
               HybridLogModel            - weighted blend of the three
  memory/      LogTemplateBM25Retriever  - BM25 with anomalous-templates as query
                                          (reuses loganalyzer.memory.corpus
                                          MemoryCorpus for time-ordering)
  product/     LogSenseAnalyzer.fit(train)
               LogSenseAnalyzer.analyze(window) -> LogAnalysisResult
               render_log_explanation() - plain-text rendering for chatops
  eval/        run_log_evaluation() - train → threshold-tune → test
                                     (reuses loganalyzer.eval.metrics)
  cli/         python -m logsense.cli.analyze
```

---

## 7. What it reuses from loganalyzer

| Reused                                       | Why                                       |
|----------------------------------------------|-------------------------------------------|
| `loganalyzer.data.splits.iter_split / iter_lofo_folds` | Split logic is pipeline-agnostic. |
| `loganalyzer.data.loaders.load_split_manifest, load_memory_corpus, load_window_memory_matchings, load_global_triage_examples` | The dataset contract is shared. |
| `loganalyzer.memory.corpus.MemoryCorpus`     | Time-ordered visibility + own-run exclusion is in docs/dataset-v4-plan.md. |
| `loganalyzer.eval.metrics.*` and `retrieval_metrics.*` | PR-AUC / recall@k / novelty F1 don't care what produced the scores. |

Everything log-specific (template mining, fingerprinting, triage models,
log-tuned retriever, analyzer) is fresh.

---

## 8. Quick start

```python
from pathlib import Path
from loganalyzer.memory.corpus import MemoryCorpus
from logsense.data.dataset import load_logs_dataset
from logsense.memory.retrieval import LogTemplateBM25Retriever
from logsense.product.analyzer import LogSenseAnalyzer
from logsense.product.formatter import render_log_explanation
from logsense.triage.hybrid import HybridLogModel

ds = load_logs_dataset(
    "data/derived/global/2026-05-21-dataset-v4-pilot-global",
    "data/runs",
)
analyzer = LogSenseAnalyzer(
    triage_model  = HybridLogModel(),
    retriever     = LogTemplateBM25Retriever(),
    memory_corpus = MemoryCorpus(issues=ds.memory_corpus),
)
analyzer.fit(ds.by_split("train"))

for lw in ds.by_split("test")[:5]:
    result = analyzer.analyze_labeled(lw)
    print(render_log_explanation(result))
```

---

## 9. CLI

```
python -m logsense.cli.analyze \
    --global-dir data/derived/global/2026-05-21-dataset-v4-pilot-global \
    --runs-root  data/runs \
    --triage-model hybrid
```

| Flag             | Values                              | Effect                                     |
|------------------|-------------------------------------|--------------------------------------------|
| `--triage-model` | `rule`, `logistic`, `anomaly`, `hybrid` | which log triage model to fit        |
| `--top-k`        | int (default 5)                     | how many Jira matches to surface           |
| `--target-fpr`   | float (default 0.05)                | operating point picked on validation       |

Writes under `<global-dir>/logsense/<triage>-bm25/`:

- `report.md` — headline triage + retrieval + novelty metrics
- `report.json` — machine-readable copy
- `per-window-predictions.jsonl` — every test window's prediction trail, including its top-3 anomalous templates

---

## 10. Demo

```
python examples/run_logsense_demo.py
```

Fits a hybrid+BM25 analyzer on the pilot train split and prints one rendered
explanation per gold label, including the anomalous-template list.

---

## 11. Pilot benchmark (576 windows, 39 memory issues)

| Pipeline (signal source)      | PR-AUC strict | ROC-AUC | p@FPR=5% | recall@5 | novelty F1 |
| ----------------------------- | ------------: | ------: | -------: | -------: | ---------: |
| **logsense** (log-only)       |         0.344 |   0.681 |    0.353 |    0.046 |      0.667 |
| loganalyzer (full telemetry)  |         0.658 |   0.900 |    0.744 |    0.061 |      0.857 |

The logsense numbers are honestly weaker than loganalyzer's, which is the
expected outcome and a useful research finding: **log signal alone does not
catch latency-dominated faults** (productcatalog-latency, currency-outage,
etc. live in trace timing, not log bodies). Where logsense shines is on
exception-emitting faults like `cart-redis-degradation-critical` - those
are exactly the cases its anomalous-line surfacing nails.

For companies whose only observability source is logs (ELK, CloudWatch,
Loki), logsense gives them the best signal extractable from that input.
For companies running full OTel telemetry, the right move is to run both
and ensemble - which is what the next iteration will support.

---

## 12. Dependencies

Stdlib only - no numpy, sklearn, or torch.
