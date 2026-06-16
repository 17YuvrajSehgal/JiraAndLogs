# Q&A — Understanding the Agentic Triage System

Running log of questions and plain-English answers. Each entry cites the source-of-truth file/line so claims can be re-verified.

---

## Q1. What does the agent take as input?

**Short answer.** One **`InputBundle`** per window (one "incident-shaped snapshot"), plus a shared **`MemoryView`** over the full Jira corpus.

### The `InputBundle` (defined at `src/agent/types.py:109`)

Think of a bundle as "everything we know about a 5-minute window in production." Only two fields are required — `window_id` and `dataset` — every other field is optional. The agent's whole point is that it handles whatever evidence is available, gracefully.

| Field | Type | What it is | Required? |
|---|---|---|:---:|
| `window_id` | str | Unique ID for this window (e.g. `2026-05-25-...-cart-redis-degradation-critical-...-active_fault-cartservice`) | ✓ |
| `dataset` | str | Which dataset this comes from: `"online_boutique"`, `"otel_demo"`, or `"wol"` | ✓ |
| `text_evidence` | str \| None | A short natural-language summary of the window (the headline + key log lines) | optional |
| `numeric_features` | dict[str, float] \| None | 94 pre-computed features (CPU/mem deltas, alert counts, trace error rates…) — the input to the HGB triage classifier | optional |
| `log_lines` | tuple[LogLine, ...] \| None | Raw log lines (ts, service, severity, line text) | optional |
| `log_lines_ordered` | bool | True if the lines are in temporal order (OB/OTel), False if they're an unordered bag (WoL) | flag |
| `trace_summary` | TraceSummary \| None | Tempo summary: `n_spans`, `error_spans`, etc. | optional |
| `k8s_events` | tuple[K8sEvent, ...] \| None | Kubernetes events (OOMKilled, CrashLoopBackOff…) | optional |
| `metric_snapshots` | dict[str, tuple[float, ...]] \| None | Prometheus time-series | optional |
| `scenario_family` | str \| None | Coarse incident family (e.g. `cart-redis`) — used for state binding + peer lookup | optional |
| `service_name` | str \| None | Which service the alert is about — used by the StateLayer's per-service ring buffer | optional |
| `window_type` | str \| None | `"active_fault"` / `"pre_fault_baseline"` / `"recovery_window"` / `"observation_window"` — drives controller branching | optional |
| `extra` | dict[str, Any] | Forward-compatible slot — carries `*_fetchable` markers (see below) | optional |

### The `extra` dict — the Phase-2 plumbing trick

This is subtle but important. The loader sets markers like:

```python
bundle.extra = {
    "k8s_events_fetchable": True,
    "trace_summary_fetchable": True,
    "metric_snapshots_fetchable": True,
}
```

These tell the capabilities observer "there's no in-memory telemetry, but the data lake has the raw JSON on disk." The observer then **still surfaces** `K8S_EVENTS` / `TRACE_SUMMARY` / `METRIC_SNAPSHOTS` capability flags, and the ReAct tools fetch from disk on demand. This keeps bundles small while still letting the agent reason about evidence it can pull when needed.

On **WoL** the loader deliberately sets `extra={}` — there's no telemetry to fetch, so the 3 telemetry tools auto-drop on missing flags. Only the text-based peer-lookup tool applies.

### The `MemoryView` — the Jira corpus

Alongside the bundle, the agent gets a `MemoryView` — an in-memory handle over the full Jira ticket corpus the agent retrieves against (e.g. 347 tickets on OB, 147 on OTel, 304 on WoL). This is **shared** across windows, not per-bundle.

### How a bundle is built

The **data loaders** at `src/agent/data_loaders/` are responsible for reading per-dataset raw data and producing `InputBundle`s:

- `ob_loader.py` → reads `global-triage-examples.jsonl`; populates all telemetry + sets all `*_fetchable` markers.
- `otel_demo_loader.py:278` → similar; populates fetchable markers so all 4 ReAct tools can fire.
- `wol_loader.py:256` → text-only; sets `extra={}` deliberately; verifier structurally skipped.

The loader's one job: produce the right bundle shape so the capabilities observer can fire the right flags downstream.

### Per-dataset evidence picture

| Evidence | OB | OTel | WoL |
|:---|:---:|:---:|:---:|
| Numeric features (94 cols) | ✓ | ✓ | ✗ |
| Text evidence | ✓ | ✓ | ✓ |
| Ordered logs | ✓ | ✓ | ✗ (unordered) |
| Trace summary | ✓ | ✓ | ✗ |
| K8s events | ✓ | ✓ | ✗ |
| Metric snapshots | ✓ | ✓ | ✗ |
| Memory text (Jira corpus) | ✓ | ✓ | ✓ |

WoL is "text-only" — that's why it's the strongest test of the agent's generalization: it has the **least** evidence and still hits the highest retrieval numbers — WoL v2: Hit@1 = 0.958, Hit@5 = 1.000. Triage accuracy is the honest negative: 0.164 baseline (below the 0.496 majority-class floor), reflecting the text-only limitation; the `dense_only` configuration recovers triage to 0.921. See `PAPER-FINDINGS.md` for the WoL v2 numbers and `RQ-CLOSURE-TABLE.md` row C1 for cross-dataset Hit@5.

**Citations.**
- `InputBundle` definition: `src/agent/types.py:109`
- Per-dataset wiring + fetchable markers: `DOCS/docs8/AGENTIC-SYSTEM-V3.md` §5.1 + §18
- Loader files: `src/agent/data_loaders/{ob,otel_demo,wol}_loader.py`

---

## Q2. Show me real examples — what does the actual input look like from OB / OTel / WoL? Where do `text_evidence` and the metadata come from? And concretely, what's in `extra`?

The whole input pipeline for each dataset is:

```
<raw collection scripts>                       # OB simulator / OTel demo runs / WoL Jira dump
        │
        ▼
data/runs/<run_id>/  +  data/otel-demo-runs/<run_id>/    # raw per-window k8s/loki/tempo/prom JSONs
data/wol/WoL_v1-2025-11-10.archive                       # WoL raw Jira archive
        │
        ▼ (cascade-era dataset build scripts: triage feature engineering, text synthesis)
        │
data/derived/global/<dataset>/global-triage-examples.jsonl   # ← THE LOADER INPUT
        │
        ▼ (src/agent/data_loaders/{ob,otel_demo,wol}_loader.py — `_build_bundle()`)
        │
InputBundle                                                  # ← THE AGENT'S INPUT
```

So the **agent never reads raw telemetry directly**. The loader reads one JSONL row → builds an `InputBundle`. The raw k8s/tempo/prom JSONs are only fetched on demand by the ReAct tools through the `RawRunDataLake`.

### 2.1 Example: OB row → InputBundle

Source file (real path):
```
data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl
```

A real first row (trimmed for display — the actual row is one line with all 94 numeric features):

```json
{
  "window_id": "2026-05-25-dataset-v5-large-compact-a-r01-baseline-normal-traffic-20260525T132459Z-observation_window-checkoutservice",
  "dataset_run_id": "2026-05-25-dataset-v5-large-compact-a-r01",
  "incident_episode_id": "2026-05-25-dataset-v5-large-compact-a-r01-baseline-normal-traffic-20260525T132459Z",
  "scenario_family": "baseline-normal",
  "scenario_id": "baseline-normal-traffic",
  "service_name": "checkoutservice",
  "window_type": "observation_window",
  "start_time": "2026-05-25T13:24:59.27+00:00",
  "end_time":   "2026-05-25T13:26:14.30+00:00",
  "split": "test",
  "is_hard_case": false,
  "source": "scenario_authored",

  "triage_evidence_text": "SERVICE checkoutservice\nTRACES total_spans=3242 error_spans=0 p50_ms=1.0 p95_ms=19.2\n  root=grpc.hipstershop.CurrencyService/Convert count=269\n  root=frontend count=123\n  root=grpc.hipstershop.CurrencyService/GetSupportedCurrencies count=107\n  root=/grpc.health.v1.Health/Check count=22\n  root=grpc.health.v1.Health/Check count=16",

  "triage_label": "noise",
  "triage_severity": null,
  "triage_components": null,
  "triage_reason_class": null,

  "triage_feature_metric_cpu_pct": 70.05,
  "triage_feature_metric_memory_pct": 22498645.33,
  "triage_feature_trace_count": 500.0,
  "triage_feature_trace_error_count": 0.0,
  "triage_feature_trace_error_rate": 0.0,
  "triage_feature_trace_latency_p50_ms": 1.04,
  "triage_feature_trace_latency_p95_ms": 19.16,
  "triage_feature_log_total_count": 195.0,
  "triage_feature_k8s_restart_count": 2.0,
  "triage_feature_m05_rpc_server_requests_per_sec": 35.42,
  "triage_feature_delta_metric_cpu_pct": 0.0,
  "...90 more triage_feature_* columns...": "..."
}
```

What the `_build_bundle()` at `ob_loader.py:225` actually maps to:

```python
InputBundle(
    window_id     = "2026-05-25-...-observation_window-checkoutservice",
    dataset       = "online_boutique",
    text_evidence = "SERVICE checkoutservice\nTRACES total_spans=3242 ...",   # ← from triage_evidence_text
    numeric_features = {
        "triage_feature_metric_cpu_pct": 70.05,
        "triage_feature_trace_count": 500.0,
        ... # 94 entries
    },
    log_lines       = None,             # not threaded — cascade consumed at build time
    trace_summary   = None,             # same
    k8s_events      = None,             # same
    metric_snapshots= None,             # same
    scenario_family = "baseline-normal",
    service_name    = "checkoutservice",
    window_type     = "observation_window",
    extra = {
        "k8s_events_fetchable":     True,    # ← raw json exists at data/runs/<run_id>/raw/kubernetes/<window_id>.json
        "trace_summary_fetchable":  True,    # ← raw json exists at data/runs/<run_id>/raw/tempo/<window_id>.json
        "metric_snapshots_fetchable": True,  # ← raw json exists at data/runs/<run_id>/raw/prometheus/<window_id>.json
    },
)
```

### 2.2 Example: OTel Demo row → InputBundle

Source file:
```
data/derived/global/2026-06-09-otel-demo-v1-global/global-triage-examples.jsonl
```

A real first row (trimmed):

```json
{
  "window_id": "2026-06-09-otel-demo-v1-baseline-r01-otel-demo-baseline-normal-traffic-20260609T174313Z-...",
  "dataset_run_id": "2026-06-09-otel-demo-v1-baseline-r01",
  "scenario_family": "baseline-normal-traffic",
  "service_name": "frontend",
  "split": "train",
  "triage_evidence_text": "SERVICE frontend\nTRACES total_spans=2301 error_spans=35 p50_ms=4.4 p95_ms=15002.5\n  root=user_browse_product count=43\n  root=image-provider count=23\n  root=POST count=22\n  root=user_view_cart count=15\n  root=user_add_to_cart count=14",
  "...94 triage_feature_* columns..."
}
```

Note `error_spans=35` and `p95_ms=15002.5` — already a real fault signature in the text. Maps to the same InputBundle shape as OB; only difference is `dataset="otel_demo"` and the data lake's `runs_root` flips from `data/runs/` to `data/otel-demo-runs/`.

### 2.3 Example: WoL row → InputBundle (text-only)

Source file:
```
data/derived/global/2026-06-11-wol-real-global/global-triage-examples.jsonl
```

A real first row (the text is a literal Apache Spark stack trace from a real Jira issue):

```json
{
  "window_id": "wol-q-3589f4c00c9af528",
  "dataset_run_id": "wol-self-contained-2026-06-11-3589f4c00c9af528",
  "scenario_family": "wol-spark",
  "service_name": "SQL",
  "window_type": "active_fault",
  "split": "train",
  "triage_label": "ticket_worthy",
  "triage_severity": "minor",
  "triage_components": ["SQL"],

  "wol_source_id": "3589f4c00c9af528...",
  "wol_project": "Spark",
  "wol_issue_key": "SPARK-13326",       // ← REAL Apache Jira issue

  "triage_evidence_text": "org.apache.spark.sql.AnalysisException: cannot resolve 'value' given input columns: []; \n   at org.apache.spark.sql.catalyst.analysis.package$AnalysisErrorAt.failAnalysis(package.scala:42) \n   at org.apache.spark.sql.catalyst.analysis.CheckAnalysis$$anonfun$checkAnalysis$1$$anonfun$apply$2.applyOrElse(CheckAnalysis.scala:60)\n   ...43 more stack frames...",

  "triage_feature_metric_cpu_pct": 0.0,    // ← ALL 94 numeric cols are 0 — telemetry doesn't apply
  "triage_feature_trace_count":    0.0,
  "...all zeros..."
}
```

WoL's `_build_bundle()` at `wol_loader.py:225` deliberately throws away the all-zero numeric features and emits an empty `extra`:

```python
InputBundle(
    window_id        = "wol-q-3589f4c00c9af528",
    dataset          = "wol",
    text_evidence    = "org.apache.spark.sql.AnalysisException: cannot resolve 'value' ...",
    numeric_features = None,         # ← deliberately dropped (all-zero garbage)
    log_lines        = None,         # WoL has unordered log_quotes; UNORDERED_LOGS not yet wired
    scenario_family  = "wol-spark",
    service_name     = "SQL",
    window_type      = "active_fault",
    extra            = {},           # ← EMPTY — no fetchable markers, no telemetry on disk
)
```

The empty `extra` is the key correctness gate — the 3 telemetry ReAct tools (`request_pod_events`, `request_extended_trace_window`, `request_pod_metrics`) auto-drop because their `required_flags` (`K8S_EVENTS`, `TRACE_SUMMARY`, `METRIC_SNAPSHOTS`) never surface. Only the 4th tool, `request_similar_incident_window` (no required flags, just needs the Jira corpus), fires on WoL.

### 2.4 Where each field comes from — sources by dataset

| Field | OB (synthetic) | OTel Demo | WoL (real) |
|---|---|---|---|
| `window_id` | built from `{run}-{scenario}-{timestamp}-{window_type}-{service}` | same pattern | hash-based: `wol-q-<hex>` |
| `text_evidence` (`triage_evidence_text`) | **auto-generated** during dataset build: "SERVICE X\nTRACES total_spans=N error_spans=M ..." — a templated summary of the trace shape | same auto-generation as OB | **literal Jira issue text** (description + stack trace) pulled from `WoL_v1-2025-11-10.archive` |
| `numeric_features` | 94 `triage_feature_*` cols computed from raw loki/tempo/prom captures at dataset-build time | same 94 cols | none (set to None — columns are present in JSONL but all zero, loader drops) |
| `scenario_family`, `service_name`, `window_type` | authored in the fault-injection scenario script (e.g. `cart-redis-degradation`, `active_fault`) | same | from WoL mapping: project → family (e.g. `wol-spark`), component → service (e.g. `SQL`); `window_type` is always `"active_fault"` because each WoL row IS a real reported issue |
| `incident_episode_id` | groups multi-window incidents into one logical incident; used by StateLayer suppression rule | same | one-window-per-incident (text-only data has no temporal sequence) |

### 2.5 What the `extra` dict actually unlocks — concrete chain

When `bundle.extra["k8s_events_fetchable"] = True`:

1. `CapabilitiesObserver.observe(bundle, ctx)` checks `bundle.extra.get("k8s_events_fetchable")` → adds `K8S_EVENTS` to the capability flag set.
2. The capability gate on `RequestPodEventsSkill.required_flags = {"K8S_EVENTS"}` opens → the skill can be invoked.
3. When invoked, the skill calls `RawRunDataLake.get_pod_events(window_id)`.
4. The data lake reads:
   ```
   data/runs/<run_id_extracted_from_window_id>/raw/kubernetes/<window_id>.json
   ```
5. That file is a real captured k8s output (here's a real header I just read):
   ```json
   {
     "fetched_at": "2026-05-25T13:27:17.39Z",
     "window": { "start_time": "...", "end_time": "...", "padded_start_time": "...", "padded_end_time": "..." },
     "namespace": "online-boutique-research",
     "service_name": "checkoutservice",
     "deployment_name": "checkoutservice",
     "events": { "ok": true, "response": { "items": [...] } },
     "pods":   { "ok": true, "response": { "items": [ {pod manifest with restartCount, annotations, status...} ] } }
   }
   ```
6. The skill summarises it → emits a `ToolResult` with fields like `events`, `warning_count`. The reranker uses these tokens to score candidate Jira tickets.

The whole point of the `*_fetchable` design is **bundles stay small, evidence stays available**. Loading every window with full k8s+tempo+prom inline would explode memory; the marker pattern delays the disk read until the controller actually decides the tool is worth firing (i.e. only on the low-consensus gate).

### 2.6 Summary table — `extra` per dataset

| Dataset | `extra` shape | Why |
|---|---|---|
| OB | `{"k8s_events_fetchable": True, "trace_summary_fetchable": True, "metric_snapshots_fetchable": True}` | Full telemetry captured at simulation time; all 4 ReAct tools can fire. |
| OTel Demo | same as OB | Same — full telemetry captured during demo runs. |
| WoL | `{}` (empty) | No on-disk telemetry; the 3 telemetry tools auto-drop on missing capability flags. Only `request_similar_incident_window` (no required flags) applies. |

### 2.7 What the agent sees vs what the loader hides

Looking at the OB row, you can see the agent's input is a *small subset* of what's in the JSONL — many fields are loader-internal (gold labels, splits, hard-case flags). The strict separation matters: gold labels (`triage_label`, etc.) are kept out of the bundle to prevent leakage. The eval harness consumes them separately.

| In JSONL | In `InputBundle`? | Why |
|---|---|---|
| `window_id`, `dataset_run_id` | ✓ window_id | id propagation |
| `triage_evidence_text` | ✓ text_evidence | input |
| `triage_feature_*` (94 cols) | ✓ numeric_features | input |
| `scenario_family`, `service_name`, `window_type` | ✓ metadata | controller branching + state binding |
| `incident_episode_id` | partially — used downstream by StateLayer | groups multi-window incidents |
| `triage_label`, `triage_severity`, `triage_components`, `triage_reason_class` | ✗ — **kept out** | gold labels; flow to `EvaluationCase.gold_*` instead |
| `split`, `is_hard_case`, `source`, `dataset_run_id`, `start_time`, `end_time` | ✗ — loader-internal | filtering / sorting only |

**Citations.**
- OB loader: `src/agent/data_loaders/ob_loader.py:225` (`_build_bundle`)
- OTel loader: `src/agent/data_loaders/otel_demo_loader.py:255`
- WoL loader: `src/agent/data_loaders/wol_loader.py:225`
- OB sample JSONL row: `data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl` line 1
- OTel sample JSONL row: `data/derived/global/2026-06-09-otel-demo-v1-global/global-triage-examples.jsonl` line 1
- WoL sample JSONL row: `data/derived/global/2026-06-11-wol-real-global/global-triage-examples.jsonl` line 1
- Raw k8s evidence example: `data/runs/2026-05-25-dataset-v5-large-compact-a-r01/raw/kubernetes/<window_id>.json`
- Data lake fetcher: `src/agent/data_lake/raw_run.py`

---

## Q3. What is `MemoryView` and why is it useful? When does the agent use it?

**Short answer.** `MemoryView` is a thin, **read-only, signature-stamped iterable** over the list of past Jira tickets the agent can retrieve against. It's the "memory" half of "Jira-as-memory" — every skill that wants to look at past tickets reaches through this object.

### 3.1 What's in it — one `JiraMemoryIssue` per ticket

`MemoryView` wraps a list of `JiraMemoryIssue` (defined at `src/core/data/schema.py:78`). One issue object per past ticket in the corpus.

Real row from `data/derived/global/2026-05-25-dataset-v5-large-global/jira-memory-corpus.jsonl`:

```json
{
  "jira_shadow_issue_id": "shadow-2026-05-25-...-productcatalog-latency-major-...",
  "jira_issue_key": "OBSRV-1001",
  "dataset_run_id": "2026-05-25-dataset-v5-large-compact-a-r01",
  "incident_episode_id": "2026-05-25-...-productcatalog-latency-major-20260525T132741Z",
  "available_as_memory_from": "2026-05-25T13:38:41+00:00",
  "scenario_id": "productcatalog-latency-major",
  "scenario_family": "productcatalog-latency",
  "affected_service": "productcatalogservice",
  "fault_type": "application_latency",
  "fault_compatibility_class": "latency",
  "severity": "major",
  "memory_text": "<the humanised Jira issue: title + description + comments>",
  "resolution_notes": "...",
  "linked_window_ids": [...],
  "linked_trace_ids": [...],
  "linked_alert_fingerprints": [...]
}
```

Field-by-field purpose:

| Field | Used by |
|---|---|
| `jira_shadow_issue_id` | the ID space the agent retrieves over — every `matched_issue_ids` tuple in a `SkillOutput` contains these |
| `jira_issue_key` | human-readable key (e.g. `OBSRV-1001`, `SPARK-13326`) — for display only |
| `memory_text` | the searchable text — title + description + comments, in engineer voice (TAWOS-realistic on OB/OTel; real Jira text on WoL). Consumed by the rerank skill for token-overlap scoring. |
| `scenario_family` | used by `request_similar_incident_window` to find peer tickets |
| `affected_service` | enables service-scoped retrieval |
| `available_as_memory_from` | **time-ordering key** — the issue is invisible to a window whose `start_time` is before this |
| `linked_*` | for cross-validation, not for retrieval |

WoL's corpus has the same shape but `memory_text` is the literal Apache Jira ticket text (304 issues across Kafka + MariaDB + Spark etc.).

### 3.2 What the class actually does — `src/agent/skills/base.py:88`

```python
class MemoryView:
    """Iterable view of the memory tickets visible to a bundle."""

    def __init__(self, issues, *, signature_override=None):
        self._issues = list(issues)
        # SHA-1 hash of issue IDs in iteration order — stable identity of "this corpus"
        self._signature = hashlib.sha1("|".join(...).encode()).hexdigest()[:16]

    def __iter__(self):          return iter(self._issues)
    def __len__(self):           return len(self._issues)
    def issues(self) -> list:    return list(self._issues)        # copy — callers can't mutate
    def signature(self) -> str:  return self._signature           # part of every SkillCache key
```

That's it — three small things wrapped together:

1. **An iterable** over `JiraMemoryIssue` objects.
2. **A signature** (`sha1(issue_ids)[:16]`) that uniquely identifies the *composition* of the view.
3. **A copy-safe accessor** (`.issues()`) so consuming skills can't mutate it.

### 3.3 Three reasons it exists

**(1) Encapsulation — the agent never reaches into the global corpus directly.**
Different bundles might in principle see different memory subsets:
- Time-ordering: a window from 2026-05-25T13:24 shouldn't see issues created at 2026-05-25T13:38.
- Same-run exclusion: prevents trivial wins where a window matches the Jira issue spawned by its own run.
- Distractor injection: RQ-D1's distractor-noise sweep adds unrelated tickets to memory — the view holds the modified corpus.

In v1, all of these filters are pre-applied upstream (in the cascade prediction step), so the loader ships a single shared MemoryView containing the full corpus. But the **abstraction is in place** — future versions can swap in a per-bundle filter without touching any skill code.

**(2) Cache correctness — `signature()` is part of every SkillCache key.**

From `src/agent/skills/base.py:283`:

```python
def cache_key(self, bundle, memory, *, extra_inputs=None) -> str:
    return sha256(
        name, version,
        bundle.cache_key(),
        memory.signature(),        # ← here
        extra_inputs
    )[:24]
```

The signature changes the moment any issue is added or removed from the corpus → every dependent cache entry naturally invalidates. This is critical for ablations like distractor sweeps that re-run the same windows against different memory compositions — without the signature, the cache would silently serve stale results.

**(3) Sharing — one view, used across every window.**

In `ob_loader.py:100–115`, the corpus is loaded **once** and the same `MemoryView` object is attached to every `EvaluationCase`:

```python
memory_corpus_path = global_dir / "jira-memory-corpus.jsonl"
memory_issues = [JiraMemoryIssue.from_row(row) for row in _iter_jsonl(memory_corpus_path)]
shared_memory_view = MemoryView(memory_issues)
log.info("OB loader: memory corpus loaded n=%d", len(memory_issues))
# ...
for window in ...:
    case = EvaluationCase(bundle=bundle, memory=shared_memory_view, ...)
```

One ~hundreds-of-KB list, shared by reference across 1008 windows. The signature is computed once at construction so per-window cache-key building is just a string lookup.

### 3.4 When the agent uses it — every skill receives it

Every `Skill.invoke()` has this signature (`src/agent/skills/base.py:253`):

```python
def invoke(
    self,
    bundle: InputBundle,
    memory: MemoryView,         # ← here
    ctx: AgentContext,
) -> SkillOutput: ...
```

So the controller passes `memory` to **every** skill call. Different skills do different things with it:

| Skill | What it does with `memory` |
|---|---|
| **`triage_numeric`** (HGB classifier) | Ignores content. Uses `memory.signature()` only — for cache-key correctness. The triage decision depends on `bundle.numeric_features`, not memory. |
| **`retrieve_dense`** (BiEncoder) | In v1, results are pre-computed at cascade time and pulled from the predictions JSONL — `memory` content is **not** re-read at inference. But `memory.signature()` is still in the cache key, so if you swap corpora, the cache invalidates. |
| **`retrieve_log_sequence`, `retrieve_hybrid_fusion`, `retrieve_hybrid_fusion_llm`, `retrieve_knowledge_graph`** | Same v1 pattern — predictions-backed; `memory` is signature-only. |
| **`compose_l2`, `compose_triage`, `compose_novelty`** | Pure trace-readers — combine prior skill outputs. Don't touch `memory` content; signature-only for caching. |
| **`rerank_with_evidence`** (Phase 2) | **Actually iterates the view.** Builds a `{issue_id → memory_text}` dict (`rerank_with_evidence.py:236`), then scores each L2-top-K candidate by token-overlap between ReAct evidence tokens and the candidate's `memory_text`. This is the one v1 skill that reads `memory.issues()` directly. |
| **`verify_with_llm`** | Reads memory_text of candidates to feed into the LLM prompt (when verifier is enabled — i.e. NOT on WoL). |
| **`reformulate_query`** | Doesn't read memory; rewrites the query text only. |
| **`request_similar_incident_window`** | Goes through `RawRunDataLake.get_similar_incidents` (which reads `<global_dir>/jira-memory-corpus.jsonl` independently) — bypasses MemoryView so it can apply its own family-scoped + exclude-own-incident filter. |

### 3.5 The `MEMORY_TEXT` capability flag and the WoL fail-fast result

The `CapabilitiesObserver` flips on `MEMORY_TEXT` whenever the bundle ships with a non-empty view (`ObservationContext.has_memory_text`). This is the **structural gate** that prevents the retrievers from being invoked on empty corpora.

Phase 3 §4.14 (paired-delta on WoL) closed RQ-C4 by masking `MEMORY_TEXT`:

| Mask | Hit@1 delta on WoL | p |
|---|---|---|
| Strip `MEMORY_TEXT` | **−0.78** | **<0.0001** |
| Strip `TEXT_EVIDENCE` | **−0.78** | **<0.0001** |

A clean fail-fast: without the corpus, the agent can't retrieve, and Hit@1 collapses to ~0. The capability-gate is doing real work.

### 3.6 Per-dataset MemoryView sizes

| Dataset | Tickets in `jira-memory-corpus.jsonl` | Notes |
|---|---:|---|
| OB | 347 | Auto-generated humanised synthetic Jira (Phase 6 humaniser, TAWOS-realistic) |
| OTel Demo | 147 | Same pipeline, smaller corpus |
| WoL | 304 | Real Apache Jira issues (Kafka + MariaDB + Spark + …) |

Small enough that the in-memory list is fine; large enough that the signature + cache-key story actually saves real work during ablations.

### 3.7 Mental model

Think of `MemoryView` as the agent's **library card**:
- Identifies *which* library catalogue you're allowed to browse (the signature).
- Hands you an iterator over the visible books.
- Doesn't let you scribble in them (copy-safe).
- Every skill gets the same card per bundle — they choose whether to actually walk the stacks (`rerank_with_evidence` does) or just note the catalogue ID (most cascade skills do, for caching).

**Citations.**
- Class definition: `src/agent/skills/base.py:88–142`
- Used in cache key: `src/agent/skills/base.py:283`
- Loaded once per dataset: `src/agent/data_loaders/ob_loader.py:100–115` (analogous in `wol_loader.py`, `otel_demo_loader.py`)
- `JiraMemoryIssue` schema: `src/core/data/schema.py:78–124`
- Real corpus row: `data/derived/global/2026-05-25-dataset-v5-large-global/jira-memory-corpus.jsonl` line 1
- Iteration in rerank: `src/agent/skills/rerank_with_evidence.py:236–249`
- Capability-mask paired delta: `DOCS/docs8/PAPER-FINDINGS.md` §RQ-B3 (WoL `MEMORY_TEXT` mask)

---

## Q4. On WoL we have no telemetry. So what does the agent *triage* on? What is it actually doing?

You've spotted the most important structural difference between OB/OTel and WoL. The agent runs the **same code** on all three datasets, but the **task type flips**:

| Dataset | What the bundle carries (the "query") | What memory carries (the "candidates") | Task in plain English |
|---|---|---|---|
| OB / OTel | Telemetry summary + 94 numeric features | Past humanised Jira tickets | "Given this incident's telemetry, which past Jira ticket describes the same problem?" |
| **WoL** | **A raw Jira issue's text itself** (stack trace / error report) | **Other past Jira tickets** | **"Given this newly-reported Jira issue, which past resolved Jira ticket is most similar?"** |

So on WoL the agent is doing **Jira-text-to-Jira-text retrieval** with the framework around it (capability gating, branch selection, state suppression, novelty detection) still intact. That's the whole point — to prove the *same agent* can do the *same job* when the modality of evidence changes.

### 4.1 What the SPARK-13326 row from `temp/delete.jsonl` actually is

This row from `data/derived/global/2026-06-11-wol-real-global/global-triage-examples.jsonl` is **one real Apache Jira issue**, treated as if it were a freshly-arrived incident report:

```
wol_issue_key      = "SPARK-13326"
wol_project        = "Spark"
scenario_family    = "wol-spark"
service_name       = "SQL"               # from Jira's "Component" field
window_type        = "active_fault"      # all WoL rows are active_faults — every row is a real reported bug
triage_label       = "ticket_worthy"     # gold label — this IS a real ticket
triage_components  = ["SQL"]
triage_evidence_text = "org.apache.spark.sql.AnalysisException: cannot resolve 'value' given input columns: []; \n   at org.apache.spark...\n   ...43 more frames"
```

The `triage_evidence_text` IS the issue's body (stack trace + AnalysisException). That's what the agent sees as the "query." The 94 `triage_feature_*` numeric columns are all zero — WoL has no telemetry.

### 4.2 What the agent is asked to do, step by step

Concretely, against SPARK-13326's stack trace, the agent must:

1. **Classify** — is this even worth a ticket? (`triage_decision`)
2. **Retrieve** — which 5 past tickets (out of 304 in the WoL corpus, spanning Kafka, MariaDB, Spark, …) are most similar to this one?
3. **Detect novelty** — is this a problem we've never seen before? (`is_novel`)
4. **Suppress duplicates** — has this service / family already been paged in recent windows?
5. **Emit a confidence + a full Trace** — for replay and audit.

The gold answer (used only for scoring, not given to the agent) says: SPARK-13326 should retrieve some related Spark SQL AnalysisException tickets, classify as `ticket_worthy`, severity `minor`, component `SQL`.

### 4.3 Which skills actually fire on WoL — the capability-gating chain

Because WoL's bundle has `numeric_features=None`, `log_lines=None`, `extra={}`, the `CapabilitiesObserver` only surfaces three flags: `TEXT_EVIDENCE`, `MEMORY_TEXT`, optionally `KG_GRAPH_MEMORY`. Most cascade skills auto-drop:

| Skill | Fires on WoL? | Why / why not |
|---|:---:|---|
| `triage_numeric` (HGB on 94 features) | ✗ | Needs `NUMERIC_FEATURES` — absent. WoL has no telemetry, so the numeric triage classifier can't fire. Triage decision comes from retrieval-driven `compose_triage` instead. |
| `retrieve_dense` (BiEncoder) | ✓ | Embeds the stack trace into a vector, dense-retrieves from past Jira tickets. **Workhorse** — coarse Hit@5 = 0.7553 on WoL test split. |
| `retrieve_log_sequence` (LogSeq2Vec) | ✗ | Needs `ORDERED_LOGS` — WoL has unordered text fragments at best, so the sequential model auto-skips. |
| `retrieve_hybrid_fusion` (Hybrid-RRF) | ✓ | BM25 + BiEncoder fusion — works on text. |
| `retrieve_hybrid_fusion_llm` | ✓ | Augmented with LLM-extracted entities (when KG available). |
| `retrieve_knowledge_graph` | gated | Fires if KG ingestion ran for WoL. |
| `verify_with_llm` (DiagnosisAgent) | ✗ structurally | The `VerifierCalibration.known_harmful_distributions` config marks WoL as `verifier_policy="harmful"` (per Mode 3 §3.9: −0.272 Hit@5 if verifier ran on WoL). The `VERIFIER_KNOWN_HELPFUL` flag never surfaces → the skill literally can't be invoked. RQ-D3 closure. |
| `compose_l2` | ✓ | RRF-fuses whatever retrievers ran. |
| `compose_triage` | ✓ | Class-balanced stacker. On WoL, derives triage from BiEncoder's max similarity score (no `triage_numeric` to lean on). |
| `compose_novelty` | ✓ | L3 disjunction — but the LLM verifier signal is missing, which is exactly why WoL's false_novel rate **collapses from ~40% (OB) to 0.7%** (the 60× collapse, RQ-D5). |
| **ReAct tools** | | |
| `request_pod_events` | ✗ | No `K8S_EVENTS` flag (no fetchable marker). |
| `request_extended_trace_window` | ✗ | No `TRACE_SUMMARY`. |
| `request_pod_metrics` | ✗ | No `METRIC_SNAPSHOTS`. |
| **`request_similar_incident_window`** | ✓ | No required flags — just needs the Jira corpus. Fetches 3 peer tickets from the same `scenario_family="wol-spark"`. **This is the only ReAct tool that fires on WoL.** |
| `rerank_with_evidence` | ✓ | Re-ranks L2's top-K candidates using tokens from the peer tool's `memory_text` summaries. |

So on WoL the active pipeline is roughly:

```
text_evidence + memory
       │
       ├─→ retrieve_dense (BiEncoder)        ─┐
       ├─→ retrieve_hybrid_fusion (RRF)      ─┤
       ├─→ retrieve_hybrid_fusion_llm (KG)   ─┤
       └─→ retrieve_knowledge_graph (gated)  ─┘
                       │
                       ▼
                   compose_l2  (fuse + rerank)
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
  compose_triage  request_similar_   compose_novelty
       │          incident_window         │
       │               │                  │
       │               ▼                  │
       │          rerank_with_evidence    │
       │               │                  │
       └───────────────┼──────────────────┘
                       ▼
                 AgentDecision
                 (triage + top-5 matches +
                  novelty + confidence + Trace)
```

### 4.4 What "triage" means when there's no telemetry

In OB/OTel, **triage answers** "is this telemetry window worth paging an engineer?" — distinguishing real faults from baseline noise (50%+ of OB windows are `observation_window` baselines that should be classified as `noise`).

In WoL, **triage answers** "is this a real, actionable ticket?" — distinguishing genuine bug reports from low-signal items. Every WoL row in the test split actually IS `ticket_worthy` (they're real Apache Jira issues that humans filed), so triage accuracy on WoL is naturally high: **0.9342** — the agent's strongest triage accuracy across the three datasets.

The composition is different but the *output schema* is identical — that's the design property. The eval harness uses `evaluation_mode` to enforce apples-to-apples:

| `AgentDecision.evaluation_mode` | Set for | What it gates |
|---|---|---|
| `"telemetry_diagnosis"` | OB, OTel | Compared against telemetry-derived gold |
| `"text_retrieval_generalisation"` | WoL | Compared against text-retrieval gold (a different scoring contract) |

`EvaluationModeMismatch` is raised if you try to compare an OB decision against a WoL contract. That's the structural firewall.

### 4.5 Why this is a useful research design

It's the **strongest external-validity claim the paper has** (RQ-C1):

> The agent trained on synthetic OB generalises to real Apache Jira: WoL Hit@1 = 0.7818, MRR = 0.8045, triage = 0.9342 — the **highest** values across the three datasets.

If the agent only worked on the rich telemetry of OB/OTel, reviewers would say "it's a microservices-only toy." The fact that the **same skill registry, same controller, same runner** also tops out on real Apache Jira text — by simply *not firing* the telemetry-dependent skills — is the cleanest "capability-driven, not dataset-driven" evidence in the paper.

### 4.6 Why this is useful in real life

Imagine an on-call engineer who copies a raw stack trace from Slack or a log line from Grafana into the system. There's no perfectly-shaped telemetry window — there's just a blob of text. The agent should still:

1. Decide "yes, this looks ticket-worthy" (vs noise / known-flake).
2. Retrieve the 5 most similar past tickets ("we've seen this before — look at OBSRV-1001, SPARK-13326, …").
3. Flag it as novel if nothing matches well.
4. Not page again if a duplicate has already been raised in the last few windows.

WoL is the proxy for that "engineer pastes text into search" scenario. OB/OTel are the proxy for "alert system fires automatically with full telemetry attached." The framework supports both because **what changes between them is the capability set, not the code path**.

### 4.7 What WoL also proves the framework still does

Even with the cheap text-retrieval-only configuration, WoL still demonstrates that the framework's *non-retrieval* features keep working:

- **Page suppression** — pages_per_incident = 1.000 on WoL, 18 suppressions fired (RQ-A4). The StateLayer ring buffer works even when input is text-only.
- **Verifier OOD-refusal** — `_assert_verifier_structurally_skipped` post-condition in `smoke_wol.py` proves the structural gate (RQ-D3). The expensive-and-known-harmful skill literally cannot be invoked.
- **Capability fail-fast** — masking `MEMORY_TEXT` or `TEXT_EVIDENCE` collapses Hit@1 by 0.78 (p<0.0001, §4.14). The gates aren't decorative; remove the modality, the system fails cleanly rather than producing garbage.

### 4.8 Mental model

Think of WoL as the agent doing **"smart Stack Overflow search"** instead of **"smart alert triage"**:
- Same retrieval substrate (BiEncoder + Hybrid-RRF + KG fusion).
- Same decision shape (`triage / matched_issue_ids / is_novel / confidence`).
- Same audit trail (full Trace, replayable).
- Different modality of input — and the agent doesn't care, because the controller gates skills on capabilities, not on dataset names.

The contribution isn't "best on telemetry" or "best on text" — it's "**one capability-adaptive policy** that handles both, with the cost and risk profile to match each."

**Citations.**
- WoL row schema + sample: `data/derived/global/2026-06-11-wol-real-global/global-triage-examples.jsonl`
- WoL loader skill gating + comment about deliberately-empty `extra`: `src/agent/data_loaders/wol_loader.py:225–257`
- Verifier OOD-refusal calibration: `src/agent/capabilities_observer.py:56` + `agent-config.yaml > verifier_calibration`
- Apples-to-apples evaluation modes: `DOCS/docs8/AGENTIC-SYSTEM-V3.md` §5.8 + §14.1
- WoL headline numbers + framing: `DOCS/docs8/PAPER-FINDINGS.md` §"World of Logs" + RQ-C1
- WoL false_novel collapse (60×): RQ-D5 in `PAPER-FINDINGS.md`

---

## Q5. WoL is all-positive (every row is a real reported issue). What is the model actually being evaluated on? Are we raising red flags?

You spotted a serious methodological issue. **I'm going to be straight with you: yes, there are red flags. Some are real and need disclosure in the paper; some we can legitimately defend; one or two we should consider dropping or reframing entirely.**

### 5.1 The smoking gun — measured label distributions across 3 datasets

I ran `grep -c` on the actual `global-triage-examples.jsonl` files. Here is the **measured** label distribution:

| Dataset | rows | `noise` | `borderline` | `ticket_worthy` | trivial-baseline triage acc | reported agent triage acc | actual lift |
|---|---:|---:|---:|---:|---:|---:|---:|
| OB   | 6720 | 3639 (54.2%) | 1666 (24.8%) | 1415 (21.1%) | 0.542 (predict `noise` always) | 0.8343 | **+0.293** ✓ |
| OTel | 1643 |  631 (38.4%) |  506 (30.8%) |  506 (30.8%) | 0.384 (predict `noise` always) | 0.8421 | **+0.458** ✓ |
| **WoL**  | **2000** | **0 (0%)** | **0 (0%)** | **2000 (100%)** | **1.000 (predict `ticket_worthy` always)** | **0.9342** | **−0.066** ✗ |

Confirmed against `triage-split-manifest.json`:
```
"label_counts_by_split": {
    "train":      {"ticket_worthy": 1398},
    "validation": {"ticket_worthy": 298},
    "test":       {"ticket_worthy": 304}
}
```

**Every single row in WoL — train, val, test — is labeled `ticket_worthy`. Zero noise. Zero borderline.**

### 5.2 Red flag #1 — WoL triage accuracy is mathematically misleading 🚨

**The most serious issue.** `PAPER-FINDINGS.md` reports `Triage accuracy: 0.9342` and frames it as "**(highest of 3 datasets)**". This claim is mathematically misleading:

- WoL is single-class → a model that **always** predicts `ticket_worthy` scores **1.000**.
- The agent's 0.9342 means it is **incorrectly predicting non-ticket-worthy in ~6.6% of cases** that are by construction ticket-worthy.
- The agent is **worse than the trivial baseline** by −0.0658 absolute.

This is the inverse of the OB/OTel finding. On OB the agent's 0.8343 is a genuine +0.293 lift over the majority-class baseline. On WoL the same number-shape (0.9342) is actually a negative lift.

**Why the reported number is what it is.** The agent's triage signal on WoL comes from `compose_triage` reading retrieval scores. When retrieval is highly confident (a strong match exists in memory), `triage_decision = ticket_worthy`. When retrieval confidence is low, the agent emits `borderline` or `noise` — even though the gold is always `ticket_worthy`. That fraction of low-confidence retrievals IS the 6.6% gap.

**Recommended action:**
- **Drop** `triage_accuracy` from WoL headline tables, OR
- **Disclose** the single-class structure and explicitly note that the trivial baseline scores 1.000.
- Reframe as: "WoL is a retrieval-only generalisation test. Triage classification is not meaningfully evaluable because every test row is by construction `ticket_worthy`."

### 5.3 Red flag #2 — pages-per-incident = 1.000 on WoL is structural, not earned 🚨

The PAPER-FINDINGS table reports "Pages per incident = 1.000 universal across 3 datasets" as a strong cross-dataset claim. On WoL this is also structurally trivial:

- Every WoL row has `incident_episode_id == window_id` (1:1) — each Jira ticket IS its own incident.
- There are **no multi-window incident sequences** in WoL test split. The StateLayer's suppression rule needs multiple windows in the same `scenario_family` with the same `top1_match` and no recovery to fire.
- The "18 suppressions fired on WoL" can only happen via family-level same-top1 — which means two MariaDB or two Kafka queries in a row that happened to retrieve the same top-1 ticket. That's a structural duplication artifact of having 200 Kafka queries in test, not a meaningful incident-correlation result.

**Recommended action:**
- Disclose: "WoL test split has 1 incident per window by construction. Pages-per-incident = 1.000 on WoL is structurally trivial; the 18 suppressions fired are family-co-located retrieval duplicates, not multi-window incident correlations. OB and OTel results carry the load-bearing evidence for this metric."

### 5.4 Red flag #3 — plan diversity = 1 on WoL was already disclosed (good)

The docs already disclose this honestly: "WoL: 1 plan ID across 304 windows (no fault-window taxonomy on real Jira). The branching mechanism is operational but not exercised." This is fine as-written — no further action needed beyond keeping the disclosure prominent.

### 5.5 Red flag #4 — Mode 3 self-contained retrieval has caveats 🟡

The retrieval evaluation is the **stronger** part of WoL, but it has its own caveats worth disclosing:

1. **Query and memory share the same 2000-ticket pool.** Mode 3 is "self-contained" — the candidate corpus IS the query corpus. The same-window exclusion prevents trivial Hit@1, but the task is structurally easier than "given query from project A, retrieve from a separate memory corpus."

2. **Family-held-out split is genuinely a leave-domain-out test.** Train = Spark+Cassandra+HBase+Flink, val = Ambari, test = MariaDB-Server + Kafka. So the BiEncoder fine-tune doesn't see Kafka or MariaDB tickets during training. This is a real generalisation signal — defensible.

3. **Gold is project-id-conditioned with broad positives.** From the README:
   - `window-memory-matchings.jsonl` (coarse): same `wol_project` + non-trivial token overlap
   - `window-memory-matchings-strong.jsonl` (strong): same project + ≥50% Jaccard symptom overlap

   A real sample gold row I just inspected has **20+ matched_memory_issue_ids** — Hit@5 only needs one of those 20+ in the top 5. That's a wide net. Hit@K mostly measures "BiEncoder embeds Kafka-stuff close to other Kafka-stuff" — which is a fair retrieval signal but a weaker claim than "agent recognises the same incident."

4. **The "55 evaluable" figure deserves explanation.** Reported headline n=55 / 304 = 18% coverage. The other 82% are excluded by some filter (likely empty gold or strong-relation mismatch). Need to verify what gates this — a small evaluable sample is a real CI-width concern. Worth disclosing the filter explicitly.

**Recommended action:**
- Specify in the paper: "WoL retrieval is Mode 3 self-contained (query pool = memory pool), family-held-out test split, with project-conditioned coarse gold and Jaccard-symptom-overlap strong gold. Report both relations. Disclose the n_eval = 55 / 304 effective sample size and the filter that produced it."

### 5.6 What IS legitimately defensible on WoL ✓

Despite the above, WoL still carries **real research weight**. These claims hold up:

1. **Retrieval generalises from synthetic to real Apache Jira.** BiEncoder fine-tuned on synthetic OB humanised Jira retrieves real Apache Jira tickets at Hit@5 = 0.8364 (n=55 evaluable). The family-held-out split and ≥50% Jaccard strong-gold relation make this a non-trivial test.

2. **Capability fail-fast works as advertised.** RQ-C4's measured −0.78 Hit@1 collapse when `MEMORY_TEXT` is masked (p<0.0001) IS a real systems-level demonstration. The capability gate isn't decorative.

3. **Verifier OOD-refusal is structural.** `_assert_verifier_structurally_skipped` proves the calibration mechanism (RQ-D3). This is real.

4. **The 60× false_novel collapse is a real LLM-induced finding (RQ-D5).** Without the LLM verifier, false_novel rate drops from ~40% (OB+OTel) to 0.7% (WoL). This is a mechanism finding, not a metric, and it doesn't depend on the all-positive label structure.

5. **BM25 baseline comparison stands.** Agent Hit@5 = 0.8364 vs BM25 Hit@5 = 0.6000 = 1.39× lift. Both measured against the same gold, on the same n=55 evaluable subset.

### 5.7 Recommended reframing for the paper

**Current framing (problematic):**
> "On real Apache Jira (World of Logs, 55 evaluable), it achieves Hit@5 = 0.8364, Hit@1 = 0.7818, and **triage accuracy = 0.9342 — its strongest dataset**."

**Honest framing:**
> "On real Apache Jira (World of Logs, 55 evaluable out of 304 test windows), the same agent — trained on synthetic OB — achieves Hit@5 = 0.8364 and Hit@1 = 0.7818 under a family-held-out split (train: Spark/Cassandra/HBase/Flink; test: Kafka/MariaDB-Server). The triage and page-suppression metrics are not meaningfully evaluable on WoL: all test rows are by construction `ticket_worthy`, and each ticket is a one-window incident. The retrieval generalisation result is the load-bearing claim for this dataset."

**Specific edits to PAPER-FINDINGS.md and AGENTIC-SYSTEM-V3.md:**

| File / section | Current | Recommended |
|---|---|---|
| `PAPER-FINDINGS.md` §"World of Logs" — Triage accuracy row | `0.9342 (highest of 3 datasets)` | **Drop the row** OR add `[N/A — single-class dataset; trivial baseline = 1.000]` |
| `PAPER-FINDINGS.md` §Abstract paragraph | "triage accuracy = 0.9342 — its strongest dataset" | Remove the triage clause; lead with the retrieval generalisation claim |
| `PAPER-FINDINGS.md` §RQ-A4 (page suppression) | "1.000 universal across 3 datasets" | "1.000 on OB+OTel (load-bearing); WoL=1.000 is structurally trivial (1:1 ticket-to-incident mapping)" |
| `RQ-CLOSURE-TABLE.md` Bucket A row "A4" | "1.000 (✓ 3/3 universal)" | "1.000 OB+OTel (real); WoL=1.000 trivial (1:1 mapping)" |
| Anywhere "highest of 3 datasets" appears | implies WoL is a strong result | reframe as "retrieval-only generalisation evidence" |

### 5.8 Bottom line — what to tell reviewers up-front

Three honest framings for the paper, in order of importance:

1. **"WoL is a retrieval-only test."** Triage classification and page suppression are structurally trivial on this dataset and we don't claim lift on them. The retrieval result IS the contribution.

2. **"WoL retrieval is family-held-out leave-one-domain-out with synthetic gold."** Gold is project-id + Jaccard symptom overlap. Hit@5 = 0.8364 with n=55 evaluable, 1.39× BM25. The BiEncoder fine-tune (trained on synthetic) generalising to real Apache Jira is the headline.

3. **"WoL does NOT exercise the controller's branching."** The capability-adaptive policy claim rests on OB+OTel (4 plan IDs each). WoL's single plan ID demonstrates *graceful collapse*, not *active selection*.

Reviewers will find #1–#3 themselves; the paper is stronger if it surfaces them first.

### 5.9 What this DOESN'T change

The agent's headline claims on OB and OTel are unaffected:
- Cost savings 64.1% / 65.3% on OB / OTel — real, measured, with CIs.
- ReAct lift NS finding is real (and was already an honest negative).
- `request_extended_trace_window` harmful finding (p=0.002) is real.
- Capability-mask collapse on OB/OTel — real.
- Plan diversity (4 plan IDs on OB and on OTel) — real.

WoL is one leg of a three-leg stool. Trimming the over-claims on WoL doesn't weaken the other two; it makes the three-leg claim believable.

**Citations.**
- WoL label measurements: `grep -c` on `data/derived/global/2026-06-11-wol-real-global/global-triage-examples.jsonl` (this conversation).
- Split manifest with single-class confirmation: `data/derived/global/2026-06-11-wol-real-global/triage-split-manifest.json`.
- WoL build script (Mode 3 self-contained design): `scripts/research-lab/build_wol_real_corpus.py:69–94`.
- README's explicit "no telemetry" + "by family" disclosure: `data/derived/global/2026-06-11-wol-real-global/README.md`.
- Gold relation construction (coarse vs strong): same README §"Gold relations: coarse vs strong".
- Mode 3 self-contained design + per-project counts: `dataset-metadata.json` + README §"At a glance".

---

## Q6. Can we inject real distractors / non-ticket-worthy windows into WoL so it's comparable to OB/OTel — without synthetic data?

**Short answer:** yes — we already have most of the raw material on disk; the rest is a Mongo extraction we already know how to do. Here's a concrete plan ranked by realism and cost.

### 6.1 What we'd be trying to achieve

To make WoL triage-evaluable in the same spirit as OB/OTel, we need a **multi-class label distribution** — not just `ticket_worthy`. Approximate targets to match the OB/OTel shape:

| Class | OB share | OTel share | WoL target |
|---|---:|---:|---:|
| `ticket_worthy` | 21% | 31% | ~25–35% |
| `borderline` | 25% | 31% | ~25–35% |
| `noise` | 54% | 38% | ~35–50% |

For a 2,000-row WoL pool, that's roughly **500–700 ticket-worthy + 500–700 borderline + 700–1,000 noise**. Crucially, the *interpretation* of `noise` has to be reframed for a text-only setting — there's no telemetry "baseline window." So `noise` becomes "**this Jira-shaped text is NOT an actionable infrastructure incident**" — which is itself a real operational question.

### 6.2 Five real-data sources we can use, ranked

#### Tier 1 — already on disk, ready today (zero new collection)

**Source A: The 300 off-topic distractors we already extracted.**
- File: `data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl` (300 rows from Qt, Minecraft, Confluence, Sakai, JBoss EAP, JBoss Tools).
- These are real Jira tickets that are CORRECT in their own projects but **out-of-distribution** for the Apache-infrastructure agent. Currently only used for RQ-D1 distractor robustness.
- Relabel them as `noise` for triage purposes — "agent's memory doesn't contain anything actionable about Minecraft mob spawning."
- ✓ Already extracted, real, sourced, citable.

**Source B: The 800 OOD novelty queries we already extracted.**
- File: `data/derived/global/2026-06-11-wol-real-global/novelty-queries/windows.jsonl` (800 rows: half adjacent Apache + half unrelated).
- The "adjacent Apache" half could be labeled `borderline` (real Apache tickets, but in projects the agent doesn't have memory for).
- The "unrelated" half could be labeled `noise`.
- ✓ Already extracted, real, sourced, citable.

**Combined Tier 1 yield:** ~300 `noise` + ~400 `borderline` + ~400 `noise` = **~1,100 non-ticket-worthy rows added** for $0 of new collection. Mostly closes the gap by itself.

#### Tier 2 — real WoL Mongo harvest (1–2 days of engineering)

**Source C: Jira `resolution` field — "Won't Fix" / "Invalid" / "Cannot Reproduce" / "Duplicate" / "Incomplete".**
- The WoL Mongo source has 2.7M Jira issues. The current 2,000 selection in Mode 3 only kept `resolution=Fixed`-style tickets (real actionable bugs).
- Harvesting tickets with `resolution ∈ {"Won't Fix", "Invalid", "Cannot Reproduce", "Duplicate", "Incomplete"}` from the SAME 7 Apache projects gives us **real in-distribution tickets that engineers explicitly closed as non-actionable**.
- This is the **most defensible** signal — it's literal operational reality: human engineers, looking at this ticket, decided not to act.
- Mapping: `Won't Fix` / `Invalid` / `Cannot Reproduce` → `noise`; `Duplicate` / `Incomplete` → `borderline` (need-more-info).
- ✓ Source script already exists (`scripts/research-lab/build_wol_real_corpus.py`) — add a `resolution` filter branch.

**Source D: Jira `priority` field — `Trivial` / `Minor` / `Lowest` as `borderline`/`noise`.**
- We already have `wol-priority-mapping.json` normalising 50+ priority strings to {critical, major, minor, fallback}.
- Extend: `minor` + `fallback` priority → `borderline`; `Trivial` / `Lowest` / `Optional` → `noise`.
- Caveat: priority is an author judgement, not always a reliable signal. Some "Minor" Spark bugs are still worth a real fix. Use this only in combination with Source C, not standalone.

#### Tier 3 — non-Jira sources from the same WoL archive (defensible but harder to argue)

**Source E: WoL Stack Overflow questions (2.7M available).**
- WoL ships SO questions with `log_msgs` for the same 7 Apache projects (e.g. `[apache-spark]` tag).
- An SO question like "How do I configure Kafka SASL?" is NOT an incident report — it's a user question. Honest `noise` label for an incident triage system.
- ⚠️ Reviewer pushback risk: "SO questions aren't comparable to Jira tickets." Use sparingly (e.g. only a small fraction of the noise pool) and disclose explicitly.

**Source F: WoL GitHub issues — documentation/feature requests.**
- Filterable by `type=feature` or label `documentation`. Real, in-domain, but non-actionable as infrastructure incidents.
- Same reviewer-pushback risk as Source E.

### 6.3 Recommended composition for a v2 WoL dataset

Sized to match OB's label distribution within 5 percentage points:

| Class | Count | Source |
|---|---:|---|
| `ticket_worthy` | 2,000 | The current Mode-3 pool (real Apache bugs, `resolution=Fixed`). **Unchanged.** |
| `borderline` | 1,000 | Source B (adjacent Apache OOD, ~400) + Source C (Duplicate/Incomplete, ~600) |
| `noise` | 1,500 | Source A (off-topic distractors, ~300) + Source B (unrelated, ~400) + Source C (Won't Fix/Invalid, ~800) |
| **Total** | **4,500** | — |

Effective ratios: 44% ticket_worthy / 22% borderline / 33% noise — close to OB's 21/25/54 and OTel's 31/31/38. The trivial baseline collapses from 1.000 to ≤0.44 on triage accuracy, so the agent's measured triage score becomes meaningful again.

### 6.4 What this fixes — and what it does NOT fix

**Fixes (✓):**

1. **Triage accuracy becomes a real signal.** Trivial baseline drops from 1.000 to ~0.44. Any observed agent triage accuracy >0.44 is genuine lift. Headline becomes defensible.
2. **Distractor robustness (RQ-D1)** gets a built-in test: agent should NOT match `wol-spark` distractors to its Apache memory.
3. **Capability fail-fast** stays valid (and gets stress-tested by off-topic distractors).
4. **BM25 baseline comparison** stays valid and probably *strengthens* — BM25 will struggle with off-topic distractors that have token overlap but no semantic match.

**Does NOT fix (✗) — these need separate disclosure:**

1. **Pages-per-incident = 1.000 will STILL be structurally trivial.** All these tickets are still one-window incidents. Multi-window incident sequences would require clustering related tickets into shared `incident_episode_id`s — that's a separate dataset-engineering decision (see §6.6 below).
2. **Plan diversity = 1 will STILL hold.** No fault-window taxonomy → controller still picks the same branch. This needs to be disclosed honestly as before.
3. **Retrieval gold structure unchanged.** Same coarse/strong gold construction; still project-id-conditioned. The Hit@K interpretation doesn't get any easier or harder.

### 6.5 Cost estimate

| Tier | Engineering work | Time |
|---|---|---|
| Tier 1 (re-label existing distractors+novelty) | Add a relabel pass in `build_wol_real_corpus.py`; update split manifest | ~½ day |
| Tier 2 Source C (resolution harvest) | Extend Mongo aggregation pipeline; ~50 lines | ~1 day |
| Tier 2 Source D (priority remap) | Use existing `wol-priority-mapping.json`; trivial | ~2 hours |
| Tier 3 Sources E/F | Mongo collection switch JIRA → SO/GitHub; new schema mapping | ~2 days (if pursued) |
| Re-run cascade + agent on v2 WoL | Existing scripts; deterministic | ~6–8 wall hours |
| **Total (Tiers 1 + 2)** | — | **~2 days of work + 1 night for cascade re-run** |

Doable inside one Phase-3 sprint. No new external data, no synthetic generation, no LLM augmentation.

### 6.6 Bonus consideration — fixing pages-per-incident at the same time

If we're touching the WoL build, we should also consider fixing the **1:1 ticket-to-incident structural problem** so pages-per-incident becomes a real signal too. Real Apache Jira already has the relations to do this:

- **`is duplicate of`** / **`duplicates`** Jira links → cluster the source + target into one `incident_episode_id`.
- **`relates to`** / **`depends on`** with same root cause → optionally cluster.
- **Temporal clustering**: tickets in the same project filed within a 24-hour window with high symptom-token overlap → cluster.

This would turn ~10–15% of the corpus into multi-ticket incident sequences (some Spark / Kafka bugs are notoriously re-filed multiple times). Then pages-per-incident becomes a real metric: did the agent recognise that this Kafka KAFKA-9999 follow-up is the same as last week's KAFKA-9876?

Engineering cost: another ~1 day to harvest the Jira link graph from Mongo and cluster.

### 6.7 What I'd recommend, concretely

A **two-phase upgrade** to WoL, both using real-not-synthetic data:

**Phase A (1 day) — fixes triage trivially.** Repurpose the existing 300 distractors + 800 novelty queries with the `triage_label` reframing. Re-run cascade + agent. Re-write the WoL claims in PAPER-FINDINGS as a real triage result. This alone is enough to remove Red Flag #1 from Q5.

**Phase B (3–4 days) — full v2 dataset.** Add Source C (Mongo resolution harvest) and Source D (priority remap). Optionally add the duplicate-link clustering for pages-per-incident. Re-run everything. Update RQ-CLOSURE-TABLE.

**Phase A first, Phase B if there's time before the paper deadline.** Phase A alone closes the most damaging red flag with a single day of engineering. Phase B is a stronger story but takes a week including the cascade re-run wait.

### 6.8 The narrative this enables

With the v2 WoL dataset, the paper's WoL section can claim something genuinely defensible:

> "We construct a real-Jira evaluation dataset (WoL-v2) with a triage-realistic label distribution by combining `resolution=Fixed` Apache infrastructure tickets (ticket-worthy), `resolution=Won't Fix / Invalid / Duplicate` tickets from the same projects (noise / borderline), and out-of-distribution off-topic tickets (noise). All data is real Apache Jira; no LLM augmentation. The agent's measured triage accuracy of X over a trivial-baseline of 0.44 demonstrates that text-modality triage decisions generalise from synthetic to real data."

Same retrieval claim as before, but now joined by a defensible triage claim — and the trivial baselines actually mean something.

### 6.9 What I would NOT recommend

- **Don't** synthesize fake telemetry to match OB's shape. Would break the "real Apache Jira" purity and gain nothing reviewers respect.
- **Don't** use LLM-generated `noise` examples. Defeats the purpose of using real data.
- **Don't** label real Jira `Fixed`-status tickets as `noise` post-hoc just to balance classes. That's editorialising the ground truth.
- **Don't** try to fix the pages-per-incident structural issue with synthetic clustering. Use the real Jira `is duplicate of` graph or disclose the structural limitation; don't manufacture incidents.

**Citations.**
- Existing distractor pool: `data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl` (300 rows).
- Existing novelty queries: `data/derived/global/2026-06-11-wol-real-global/novelty-queries/windows.jsonl` (800 rows).
- Priority mapping (already covers 50+ strings): `wol-priority-mapping.json`.
- WoL build script — add a `resolution` filter here: `scripts/research-lab/build_wol_real_corpus.py:46–94`.
- Source archive (2.7M Jira issues + 800K GitHub + 2.7M SO): `data/wol/WoL_v1-2025-11-10.archive.gz` per `data/wol/README.md`.
- Mode 3 design rationale: `data/derived/global/2026-06-11-wol-real-global/README.md` §"Splits" + §"Known limitations".

---

## Q6 — LOCKED PLAN (2026-06-15)

After verifying Mongo capacity per bucket per project, §6.1–§6.9 is now **locked** with these specifics. Build script: `scripts/research-lab/build_wol_real_corpus_v2.py`.

### Decisions made via AskUserQuestion

| Question | Decision |
|---|---|
| What is "regular data"? | **In-domain non-bug Jira** — same 7 Apache projects, issuetype ∈ {Improvement, New Feature, Question, Documentation, Wish}. Labeled `noise`. |
| Target ratio | **Match OB** (21 : 25 : 54). Keep 2000 ticket_worthy; add ~2400 borderline + ~5100 noise → ~9500 total. |
| Family scope | **Same 7 Apache only** — Spark, Cassandra, HBase, Flink, Ambari, Kafka, MariaDB-Server. |
| Duplicate-link clustering (§6.6) | **YES, in-scope** — Jira `is duplicate of` / `Cloners` / `Cause` link types collapse multi-ticket clusters under a shared `incident_episode_id`. |

### Measured Mongo capacity (real counts, 2026-06-15)

Per-project capacity with existing quality filters (`pred_uncertainty ≤ 0.05`, `desc ≥ 200 chars`, `log_msgs ≥ 1` for Bug rows; logs filter dropped for non-Bug rows since regular Improvement/Question/Documentation tickets often have no logs):

```
BUCKET                              Spark Cassan  HBase  Flink Ambari  Kafka MariaDB  TOTAL
-------------------------------------------------------------------------------------------
borderline_duplicate                  453    402    236    363     78    159    318   2009
borderline_incomplete                 527      8     16      4      2      3    150    710
borderline_cantrepro                  204    213    124    189     31     60    145    966
noise_wontfix                         128     88     88    101     16     50    141    612
noise_invalid                         215    130    170     58     33     40      0    646
noise_notabug                          23     13      6     56      2     27    293    420
noise_notaproblem                     441    206     91    164     31     73      0   1006
regular_improvement                   688    435    317    409     51    183      0   2083
regular_newfeature                     38     14     14     24      1      5      0     96
regular_question                      111      0      0      0      0      0      0    111
regular_docs                           24      0      0      0      2      0      0     26
regular_wish                           11      0      1      0      1      6      0     19
-------------------------------------------------------------------------------------------
BORDERLINE TOTAL: 3,685   (target 2,400 — 1.5x headroom)
NOISE + REGULAR : 5,019   (target 5,100 — essentially at ceiling)
```

**Two capacity gotchas the build script handles:**

1. **MariaDB-Server has zero non-Bug issuetypes.** It doesn't use the Improvement / Question / Documentation / Wish workflow in its Jira project. The build script's `_distribute_quota()` redistributes MariaDB's regular-data quota to projects with headroom (mostly Spark + Cassandra + Flink + HBase).
2. **Ambari is thin everywhere.** 248 total capacity vs an OB-ratio target of ~938. The script caps at availability; expect the val split to be slightly lighter on Ambari than strict-stratification would predict.

### What the build script does, end-to-end

`scripts/research-lab/build_wol_real_corpus_v2.py augment --source-global-dir <v1> --out-global-dir <v2>`:

1. **Copy v1 invariants** — `jira-memory-corpus.jsonl` (unchanged), `jira-shadow-humanized-v2/`, `distractors/`, `novelty-queries/`, `v2_kg_extractions/` (memory-side), `triage-feature-columns.json`, priority mapping.
2. **Harvest Mongo** — 12 bucket types × 7 projects = 84 pool extractions. Each cached at `<out>/.pool_cache/<bucket>/<project>.jsonl`. Subsequent runs reuse the cache.
3. **Distribute quotas** — borderline target split across the 3 resolution sub-buckets proportional to capacity; noise budget split 55/45 between resolution-noise (4 sub-buckets) and regular-noise (5 sub-buckets). Within each sub-bucket, projects get their OB-ratio share, with deficit redistribution.
4. **Sample + field-map** — `random.Random(seed=42)` for determinism. Each sampled doc passes through `map_to_triagewindow_v2()` which mirrors v1's `map_to_triagewindow` but accepts `triage_label` as a parameter and falls back to `summary + description` when `log_msgs` is empty (regular non-Bug data).
5. **Cluster duplicate-links** — union-find over **Jira `key`** (e.g. `SPARK-13326`). Edges come from `fields.issuelinks` with link type ∈ {Duplicate, Cloners, Cause, Caused, Caused by}. Only edges where both endpoints survived sampling produce a merged cluster.
6. **Concatenate JSONL** — v1's 2000 rows verbatim + ~7500 new rows → `global-triage-examples.jsonl` (~9500 rows total).
7. **Update split manifest** — family assignment unchanged (Spark/Cassandra/HBase/Flink → train, Ambari → val, Kafka/MariaDB-Server → test); `label_counts_by_split` regenerated per the new label distribution.
8. **Regenerate gold matchings** — v1 ticket_worthy rows keep their gold; new borderline/noise rows get **empty `matched_memory_issue_ids`**. Eval harness treats empty gold as "this window doesn't contribute to Hit@K aggregation" (mean-with-filter); triage and novelty metrics still apply normally.
9. **Write metadata + README** — full provenance, label-counts table, list of deferred follow-up work.

### What stays unchanged in v2 — by design

- **Memory corpus** (`jira-memory-corpus.jsonl`) — still 2000 ticket_worthy past tickets. Noise/borderline/regular queries are NOT in memory (mirrors OB: `noise` and `observation_window` queries don't generate Jira tickets to retrieve against). The agent's job on a noise query is to fail-fast: low retrieval confidence → emit `triage = noise`.
- **Family assignment** — Spark/Cassandra/HBase/Flink → train, Ambari → val, Kafka/MariaDB-Server → test. Same leave-one-domain-out structure.
- **Memory-side artifacts** — `jira-shadow-humanized-v2/`, `v2_kg_extractions/`, `triage-feature-columns.json`, `wol-priority-mapping.json`.
- **Distractor pool** (300 off-topic) and **novelty queries** (800 OOD) — independent of Mode 3 augmentation; copied as-is.

### Deferred work (run separately after build completes)

| Step | Why deferred | How long | Command |
|---|---|---|---|
| Re-extract KG entities over new ~7500 rows | LLM pass is multi-hour; not blocking smoke test | ~3 hours | `python scripts/agent/extract_window_entities.py --global-dir <v2>` |
| Re-run cascade predictions on new test split | Required for BiEncoder/Hybrid-RRF/KG/LogSeq2Vec headline numbers | ~6 wall hours | `python scripts/research-lab/run_{biencoder,hybrid_rrf,kg_retrieval,logseq2vec,bm25}_wol_mode3.py --global-dir <v2>` |
| Re-run agent smoke + bootstrap CIs | Headline numbers regenerate | ~30 min after cascade | `python scripts/agent/smoke_wol.py --global-dir <v2>` then `bootstrap_predictions.py` |

### Execution checklist

```bash
# 1. Verify wol-mongo container is up
docker ps --filter "name=wol-mongo"

# 2. Run the augment (Mongo harvest + sample + field-map + cluster + write)
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python scripts/research-lab/build_wol_real_corpus_v2.py augment \
    --source-global-dir data/derived/global/2026-06-11-wol-real-global \
    --out-global-dir    data/derived/global/2026-06-15-wol-real-v2-global

# 3. Sanity-check the output dataset (label distribution)
python -c "import json,collections; \
c=collections.Counter(json.loads(l)['triage_label'] \
  for l in open('data/derived/global/2026-06-15-wol-real-v2-global/global-triage-examples.jsonl')); \
print(dict(c))"
# Expected: {'ticket_worthy': 2000, 'borderline': ~2400, 'noise': ~5100}

# 4. (Deferred ~3hr) Re-run KG extraction over new rows
python scripts/agent/extract_window_entities.py \
    --global-dir data/derived/global/2026-06-15-wol-real-v2-global

# 5. (Deferred ~6hr — can run overnight) Re-run cascade
for pipe in biencoder hybrid_rrf kg_retrieval logseq2vec bm25; do
    python scripts/research-lab/run_${pipe}_wol_mode3.py \
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global
done

# 6. Re-run agent smoke + headline numbers
python scripts/agent/smoke_wol.py \
    --global-dir data/derived/global/2026-06-15-wol-real-v2-global \
    --experiment smoke-wol-v2-2026-06-15

# 7. Re-run bootstrap CIs on new predictions
python scripts/agent/bootstrap_predictions.py \
    --predictions-dir data/agent_runs/smoke-wol-v2-2026-06-15
```

### After the v2 dataset lands

The §5.7 reframing recommendations get **replaced** because the dataset itself becomes triage-evaluable:

| Doc | Old wording | New wording (post-v2) |
|---|---|---|
| PAPER-FINDINGS.md §"World of Logs" | "n=55 evaluable; triage_acc=0.9342 highest of 3 datasets" | "n_eval = 304 + ~7500 evaluable across 3 classes; trivial baseline triage_acc = 0.54 (OB-matched); agent triage_acc = X" |
| PAPER-FINDINGS.md §A4 page suppression | "1.000 universal across 3 datasets" | "1.000 OB / 1.000 OTel / X.XXX WoL-v2 (Y multi-ticket clusters)" |
| RQ-CLOSURE-TABLE.md row A4 | "1.000 ✓ 3/3 universal" | "1.000 OB/OTel; WoL-v2 measured non-trivially via Jira link clustering" |

When the v2 numbers come in, the WoL section becomes a **load-bearing** triage + suppression result, not just a retrieval result. Both red flags from §5 close.

**Citations.**
- Build script: `scripts/research-lab/build_wol_real_corpus_v2.py`
- Measured Mongo counts (this section): live Mongo query 2026-06-15.
- Existing v1 build patterns reused: `scripts/research-lab/build_wol_real_corpus.py:179–504` (aggregation pipeline, `sample_per_project`, field mappers).
- Triage decision enum: `src/agent/types.py` — confirms `noise` and `borderline` are existing labels, no schema change needed.

---

## Q5 — OUTCOME (2026-06-16, post-v2)

Phase B v2 ran end-to-end. Real outcomes against the Q5 red flags:

### Red flag #1 — single-class triage / trivial baseline = 1.000 → RESOLVED, with a new honest finding

**Resolved:** v2's class distribution is now ticket_worthy / borderline / noise = 21.4% / 25.7% / 52.9% — near-perfect match for OB ratio. Trivial single-class baseline drops to 0.214 on the full dataset (was 1.000 on v1) and **0.496 on the test split majority class** (always-predict-noise).

**But v2 surfaced a new honest finding** the v1 single-class dataset could not have shown:

- **Agent triage accuracy = 0.164**, BELOW all three trivial single-class baselines (0.496 noise, 0.320 borderline, 0.184 ticket_worthy).
- Mechanism: WoL has no telemetry → `triage_numeric` doesn't fire → `compose_triage` falls back to retrieval-confidence → rich 2000-ticket memory yields high-confidence matches for borderline / noise queries too → 901/1648 cases (54.7%) get paged as ticket_worthy.
- This is a **measured weakness of the text-only triage path** — not a dataset artefact. The agent's retrieval lane is operating at Hit@5 = 1.000; the failure is purely in the triage composition.
- Goes into the paper's "Discussion / honest framing" section, not the headline. Future work: learned text-classifier head OR memory-novelty-aware threshold on retrieval confidence.

### Red flag #2 — pages/incident = 1.000 structurally trivial → RESOLVED substantively

- v1: 18 suppressions over 304 windows (each its own 1-window incident). 1.000 pages/incident was structurally trivial.
- **v2: 510 suppressions over 1648 windows; 901 distinct incidents.** Pages/incident = 1.000 is now substantive — the StateLayer suppression rule operates over real multi-window incident sequences produced by the Jira `is duplicate of` link union-find (90 multi-ticket clusters at build time, expanded via state-layer tracking to 510 actual suppression events).
- The "1.000 universal across 3 datasets" claim is now genuinely load-bearing on all three.

### Red flag #3 — plan diversity = 1 → MITIGATED (1 → 2)

- v1: 1 plan ID across 304 windows.
- v2: **2 plan IDs** across 1648 windows (`plan_dc3eb48e98f8`, `plan_baf2a91d0f2e`). The state_suppress branch now fires alongside active_fault, exercising the controller branching mechanism on WoL for the first time.
- Still below OB/OTel's 4 plans (those have a 4-way `window_type` taxonomy WoL lacks), but the branching IS now operational on WoL. Disclose honestly.

### Red flag #4 — Mode 3 self-contained retrieval caveats → unchanged

The Mode 3 self-contained design (query pool = memory pool with same-window exclusion), project-conditioned gold, and small n_eval are unchanged in v2 — but:

- n_eval went from 55 → 48 at the agent level (because agent uses stricter "has retrieval gold" criterion than the cascade scripts) and 55 → 276 at the cascade level (5× larger evaluable sample).
- Family-held-out split (train: Spark/Cassandra/HBase/Flink → test: Kafka/MariaDB-Server) unchanged.
- Strong-gold relation (≥50% Jaccard symptom overlap) unchanged.

### Measured headline numbers (replace v1 everywhere)

| Metric | v1 | **v2** |
|---|---:|---:|
| n test rows | 304 | **1648** |
| n_eval (cascade) | 55 | **276** |
| n_eval (agent) | 55 | 48 |
| Agent Hit@1 | 0.7818 | **0.958** |
| Agent Hit@5 | 0.8364 | **1.000** |
| Agent MRR | 0.8045 | 0.976 |
| Agent triage acc | 0.9342 | **0.164** (HONEST: below 0.496 majority baseline) |
| Pages/incident | 1.000 (structural) | **1.000 (substantive)** |
| Suppressions fired | 18 | **510** (28×) |
| Distinct plan IDs | 1 | **2** |
| Cascade BiEncoder Hit@5 coarse | 0.7553 | **0.971** [0.949, 0.989] |
| Cascade Hybrid-RRF Hit@5 strong | 0.787 | **0.814** (+0.135 over BiEncoder strong) |
| Cascade BM25 Hit@5 | 0.6000 | 0.609 (clean replication) |
| RQ-D5 false_novel | 0.7% | 0.0% |
| Verifier structural-skip | ✓ | ✓ |

### Documentation already updated (2026-06-16)

- `DOCS/docs8/PAPER-FINDINGS.md` — abstract paragraph, WoL headline table, RQ-A1, RQ-A4, RQ-B3, RQ-C1, RQ-D5, and a new "honest negative #4" in the Discussion section.
- `DOCS/docs8/RQ-CLOSURE-TABLE.md` — all WoL cells, status banner, Cross-dataset findings, WoL v2 closure summary, reproduction one-liner.
- `memory/project-wol-methodology-redflags.md` — v2 status block at top.

### Still to do (mechanical, non-blocking)

1. ~~Re-run RQ-A5 skill-disable ablations on v2~~ ✓ **DONE 2026-06-16**: `no_hybrid` lifts triage by +0.7462 [+0.7230, +0.7700] p<0.001\*\*\* — paper-quotable headline finding ([4.1 SUMMARY](../../results/wol-v2/4.1-skill-ablation/SUMMARY.md))
2. ~~Re-run RQ-C4 capability-mask paired-delta on v2~~ ✓ **DONE**: −0.958 Hit@1 [−1.000, −0.896] p<0.001\*\*\* (sharpens v1's −0.78) ([4.4 SUMMARY](../../results/wol-v2/4.4-capability-mask/SUMMARY.md))
3. ~~Measure WoL v2 cost-vs-cascade savings (RQ-A2 WoL)~~ ✓ **DONE**: 98.9% wall / 100% USD savings (highest of 3 datasets) ([4.5 SUMMARY](../../results/wol-v2/4.5-cost-vs-cascade/SUMMARY.md))
4. ~~Re-run RQ-D6 tool-use failure-mode catalog on v2 traces~~ ✓ **DONE**: 0 invocations across 1641 traces (framework correctly skips tools when retrieval confident) ([3.6 SUMMARY](../../results/wol-v2/3.6-failure-mode-catalog/SUMMARY.md))
5. Plus: RQ-A6 tool ablation, RQ-A7 budget curve, RQ-B2 Pareto sweep all measured ✓
6. Plus: paired-delta CIs computed for skill-ablation, tool-ablation, and capability-mask cells ✓

**All measurable analyses complete.** Outstanding items are architectural-change deferrals (RQ-A3 reformulation Hit@K requires live-retrieval mode; RQ-D1 agent-level distractor needs cascade re-train with poisoned memory). Both disclosed in `PAPER-FINDINGS.md` §v1 deferrals.

Final consolidated artifacts:
- `results/wol-v2/PHASE3-WOL-V2-SUMMARY.md` — master per-RQ summary
- `results/wol-v2/{3.6..4.14}/SUMMARY.md` — per-section finding details
- `DOCS/docs8/PAPER-FINDINGS.md` — updated with v2 numbers in every relevant RQ section
- `DOCS/docs8/RQ-CLOSURE-TABLE.md` — all WoL cells filled with measured v2 numbers

None of these change the headline; they fill in the remaining "v2 pending" cells in the closure table.

---


