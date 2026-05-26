# Once v5-large is available — checklist

Captured 2026-05-26 while working on v5-quick (the laptop dry-run).
v5-large is the ~7,400-window corpus collecting unattended on the GCP
VM, expected ~3 days from now. This doc captures **everything from
this v5-quick session that needs to flow into v5-large** so we don't
lose it.

Three groupings: (1) verify code fixes already landed, (2) workflow to
run when v5-large lands, (3) open bugs to fix before / alongside
the v5-large derived build.

---

## 1. Fixes already in code (just verify they're still there)

These were all fixed during the v5-quick session and are committed to
`master-bigger-dataset`. When v5-large lands, the derived-build chain
will use them automatically. If anyone reverted them in the meantime,
**re-apply before re-deriving v5-large**.

| Fix | Commit | File | Quick check |
| --- | --- | --- | --- |
| `run_triage_benchmark.py` reads feature columns from `triage-feature-columns.json` (not hardcoded) | `6ea6e9e` | `scripts/research-lab/run_triage_benchmark.py` | `grep "_load_feature_columns" run_triage_benchmark.py` returns a hit |
| HGB / RF / Logistic sklearn pipelines registered in comparison harness | `6ea6e9e` | `src/comparison/pipelines.py`, `src/comparison/runner.py` | `grep "GradientBoostingPipeline\|hgb" src/comparison/runner.py` returns 2+ hits |
| LOFO macros + inclusive borderline + ECE in comparison report | `6ea6e9e` | `src/comparison/runner.py` | `grep "lofo_macros\|inclusive_strata" src/comparison/runner.py` returns 2+ hits |
| M0–M5 supplement export (cluster + per-service queries) | `6ea6e9e` | `scripts/research-lab/export_m05_supplement.py` | file exists, has `_CLUSTER_QUERIES` + `_PER_SERVICE_QUERIES` |
| Per-language metric dispatch (cartservice .NET → http_server_*, etc.) | `9bcc216` | `scripts/research-lab/export_m05_supplement.py` | `grep "SERVICE_LANG_MAP" export_m05_supplement.py` returns a hit |
| `numeric_features_from_raw` reads supplement files + emits m05 columns | `6ea6e9e` | `scripts/research-lab/triage_labels.py` | `grep "_M05_SUPPLEMENT_FEATURE_KEYS\|prometheus_supplement" triage_labels.py` returns 2+ hits |
| `evidence_text_from_raw` drops WINDOW header (label leak fix) | `fb94129` | `scripts/research-lab/triage_labels.py` | `grep -A 2 "No WINDOW header" triage_labels.py` returns a hit |
| `evidence_text_from_raw` strips per-request IDs (trace_id, span_id, EventId) | `fb94129` | `scripts/research-lab/triage_labels.py` | `grep "_PER_REQUEST_IDS_RE" triage_labels.py` returns a hit |
| `evidence_text_from_raw` extracts structured fields (dep, op, err_class, etc.) | `fb94129` | `scripts/research-lab/triage_labels.py` | `grep "_KEEP_KEYS" triage_labels.py` returns a hit |
| Categorical features (cart op×result, payment results, rpc statuses) — 14 new cols → 94 total features | `c50d163` | `scripts/research-lab/export_m05_supplement.py` + `triage_labels.py` | `grep "m05_cart_get_error_per_sec" triage_labels.py` returns a hit; cart-redis LOFO HGB lifted +5pt on v5-quick |

If any of these fail the quick check, restore from the listed commit.

---

## 2. Workflow when v5-large lands

Assume v5-large finishes collection on the GCP VM as
`2026-05-25-dataset-v5-large-*` (~100 runs / ~7,400 windows / 27
families). Do the following on a machine that can talk to the GCP VM's
Prometheus (port-forward over `gcloud compute ssh`, or run on the VM).

### Step 1 — pull the raw runs to wherever you'll do derivation

```powershell
# Example using rsync via gcloud — adjust to your setup
gcloud compute scp --recurse --zone=us-central1-a `
  jira-logs-dataset-v5-vm:~/workplace/JiraAndLogs/data/runs/2026-05-25-dataset-v5-large-* `
  ./data/runs/
```

Or just do the derivation directly on the VM if disk is plentiful.

### Step 2 — export M0–M5 supplements (needs live Prometheus)

The export script back-fills the new RED / business / runtime metrics
from Prom for every collected window. Prom retains data for 15 days by
default, so do this within ~2 weeks of v5-large collection ending.

```powershell
kubectl -n observability port-forward `
  pod/prometheus-kube-prometheus-stack-prometheus-0 19099:9090
.venv\Scripts\python.exe scripts\research-lab\export_m05_supplement.py `
  --run-prefix 2026-05-25-dataset-v5-large `
  --prometheus-url http://127.0.0.1:19099
```

Expected: ~7,400 windows × ~30 queries each ≈ ~30 min wall time (linear
scaling from v5-quick's 16s per 78-window run). The script is
resumable — it skips windows where the supplement file already exists
unless you pass `--overwrite`.

### Step 3 — rebuild per-run + global derived data

```powershell
for ($r in (gci data\runs\2026-05-25-dataset-v5-large-*)) {
  .venv\Scripts\python.exe scripts\research-lab\build_triage_dataset.py `
    --dataset-run-id $r.Name --force
}
.venv\Scripts\python.exe scripts\research-lab\build_global_triage_dataset.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-large `
  --global-dataset-id 2026-05-25-dataset-v5-large-m05 --force
.venv\Scripts\python.exe scripts\research-lab\build_jira_memory_corpus.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-large `
  --global-dataset-id 2026-05-25-dataset-v5-large-m05 --force
```

Expected runtime: ~25–35 min (per-run builds are seconds each; the
global aggregate scales linearly).

### Step 4 — run the comparison leaderboard

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-large-m05" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,loganalyzer_with_jira,jira_only,logsense,hgb,rf,logistic_sklearn `
  --n-bootstrap 1000 `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-large-m05\comparison\v5-large-leaderboard"
```

Expected runtime: ~15–25 min (logsense is the slow one).

### Step 5 — sanity-check against the predictions

Open `docs/results-v5-quick.md` §8 ("What's solid for v5-large") and
check whether each prediction held. The high-confidence ones:

- `RF inclusive PR-AUC ≥ 0.85` (v5-quick had 0.81)
- `recommendation-outage LOFO HGB ≥ 0.80` (v5-quick had 0.71)
- `RF orphan recall stays ≥ 0.30 with much tighter CI` (v5-quick had 0.346 on n=52; v5-large will have n≈192)
- Orphan recall gap ≤ 5 pts for HGB/RF (verdict: signal_learning)

If any prediction misses by more than ~10 pts, that's worth a deeper
investigation — likely candidates: missing supplement files, leakage
canary missed something, or v5-large collected with a different M0–M5
image set.

### Step 6 — fast iteration scripts (sanity loop)

```powershell
# Five-second sklearn smoke
.venv\Scripts\python.exe experiments\baseline_v4.py `
  --global-id 2026-05-25-dataset-v5-large-m05

# Confirm text-features-vs-numeric gap still holds (bi-encoder bottleneck)
.venv\Scripts\python.exe experiments\bi_encoder_v5.py `
  --global-id 2026-05-25-dataset-v5-large-m05 --cache-embeddings

# Confirm honest lexical baseline holds (no leakage)
.venv\Scripts\python.exe experiments\lexical_evidence_v4.py `
  --global-id 2026-05-25-dataset-v5-large-m05
```

These three should reproduce the v5-quick story: HGB numeric wins,
bi-encoder trails, lexical is weak after redaction.

---

## 3. Open bugs to fix BEFORE or DURING v5-large derived build

These are real issues surfaced during v5-quick that the v5-large work
will hit unless fixed first.

### 3.1 Leakage canary doesn't catch substring tokens (**high priority**)

`scripts/research-lab/validate-run-feature-distribution.py` currently
only checks that no NUMERIC feature column perfectly correlates with
`scenario_id` / `scenario_family` / `triage_label`. It misses substring
leaks in text fields like `triage_evidence_text`.

The v5-quick session caught two such leaks (WINDOW header containing
`window_type` + `window_id`; per-request `trace_id`/`span_id` dominating
embeddings). Both were silently inflating any text-based pipeline's PR-AUC.

**Fix:** extend the validator with a check that scans
`triage_evidence_text` for embedded substrings matching the lab-only
field values (`active_fault`, `pre_fault_baseline`, `recovery_window`,
`observation_window`, the run's `dataset_run_id` segments, etc.) and
fails the run if any such substring appears in >X% of the text.

**Risk if skipped:** new text fields added to evidence_text in
v5-large's evidence_text_from_raw could introduce fresh leaks that
silently inflate loganalyzer/logsense/LM-reranker numbers. The
existing fixes only catch the leaks we already know about.

### 3.2 Per-service M0–M5 features still zero for Node/Python/Java (medium priority)

Our per-language dispatch correctly handles Go (rpc_server_*),
.NET-cartservice (http_server_request_duration_*), and frontend
(http_server_request_duration_*). But Node services (paymentservice,
currencyservice) and Python services (recommendationservice,
emailservice) and Java (adservice) **don't emit any per-service RED
metrics** that Prometheus can scrape. The supplement script correctly
emits 0 for those, but the model has no per-service signal for them.

This is an **upstream issue in the service code**, not in the export
script:

- **Node**: paymentservice and currencyservice have `@opentelemetry/sdk-node` wired but the gRPC server-side metric exporter isn't producing data that lands in our ServiceMonitor scrape. Either the metric reader path is broken or the OTel SDK's Prom exporter wasn't registered.
- **Python**: recommendationservice and emailservice have `GrpcInstrumentorServer` wired (per M4.2a) but no `grpc_server_*` series appear in Prom. Same root cause as Node — the Prom exporter binding isn't producing scrape-friendly output.
- **Java**: adservice uses the OTel Java agent (M1.2) which is supposed to expose metrics on port 9464 via `OTEL_METRICS_EXPORTER=prometheus`, but `rpc_server_duration_*` series for adservice are absent from Prom.

**Fix (per service):** verify the OTel SDK Prom-exporter wiring in each
service's main file, confirm the metric reader actually emits on port
9100/9464, and confirm the ServiceMonitor endpoint covers those ports.
Probably ~1 day of work per language; could land in a `M4.6 — fleet
RED parity` follow-up phase to M0–M5.

**Risk if skipped:** v5-large's per-service features for Node/Python/Java
services will still be zero. The cart-redis family will continue to be
the only big family with full per-service coverage. Other families
will fall back to cluster-wide aggregates which work but are weaker
than per-service signal.

### 3.3 .NET cartservice has no `process_resident_memory_bytes` (low priority)

`process_resident_memory_bytes` is the standard Prom client default for
Go/Python; .NET doesn't emit it. We correctly skip the query for .NET
via the per-language dispatch (`dotnet` lang → None), so cartservice's
`m05_svc_process_memory_rss_max` is 0.

**Fix:** for .NET, query `process_runtime_dotnet_total_allocated_bytes`
(cumulative, take rate) or the .NET `kestrel_*` metrics that DO appear.
Not a perfect 1:1 to Go's RSS, but better than 0.

**Risk if skipped:** slow-leak-saturation on cartservice (.NET) wouldn't
show memory growth via `process_memory_rss_max`. Other languages still
get it.

### 3.4 Categorical labels we haven't seen yet (low priority, watch on v5-large)

The categorical extraction queries fire for all label values we've
seen, including some only seen during specific fault scenarios. v5-large
will exercise more fault scenarios so MORE label values will appear:

- `payments_total{result=invalid}` likely appears during payment-outage
- `payments_total{result=expired}` may not appear at all (loadgenerator doesn't generate expired cards)
- `catalog_lookups_total{result=miss}` may appear during productcatalog-outage
- `rpc_server_requests_total{status=DeadlineExceeded}` may appear during latency-injection scenarios
- `rpc_server_requests_total{status=Unavailable}` may appear during pod-restart scenarios

If a label value never appears in v5-large either, the corresponding
column stays zero — the model learns to ignore it. No harm done.

**Action:** after v5-large derived build, check per-column population
rate via the `feature-distribution.md` reports for each run, and
prune any features that are 100% zero across the whole corpus.

### 3.5 Evidence text could include L3 business events (low priority, future work)

`evidence_text_from_raw` currently includes structured L1/L2 log lines
+ TRACES summary. It does NOT yet include L3 business events
(`order_placed`, `payment_charged`, `cart_size_changed`,
`recommendation_returned`).

The numeric counterparts (`m05_orders_placed_per_sec`, etc.) already
flow as features. Adding the LOG-EVENTS lines for L3 would help only
text/LM pipelines, which we've shown are bottlenecked on the
count-vs-semantic problem anyway. So **low priority for v5-large** —
worth adding only if Phase 4 LM reranking shows promise on the
retrieval-quality task (where text similarity matters).

### 3.6 D11 system-fault scenarios may need fresh metric handling (medium, only if running them)

v5-large includes 10 system-faults runs (chaos-mesh: DNS / network
partition / packet loss / network latency / memory pressure). These
fault types don't generate gRPC errors — they manifest as latency,
timeouts, or DNS resolution failures. The current metric coverage:

- DNS failures → `dns_resolver_*` metrics aren't scraped today
- Network packet loss → only visible via latency_p95 in our trace metric, no dedicated packet-loss metric
- Memory pressure → visible via `m05_svc_process_memory_rss_max` for Go services but not .NET

**Action:** when running v5-large derived against system-faults runs,
look at the per-family LOFO PR-AUC for the 5 chaos-mesh families. If
any are < 0.50, the metric coverage for that fault type is the gap —
candidate for a `M6 — chaos-fault telemetry parity` future phase.

---

## 4. Phase 4 work NOT done in v5-quick (carry into v5-large)

These were on the v5-quick Phase 4 plan but skipped due to dependency
gaps. All apply equally to v5-large.

### 4.1 LM reranker for Jira memory retrieval

The bi-encoder finding (`docs/results-v5-quick.md` §6) shows text
features don't help classification on this dataset (count-based
discrimination). But Jira memory retrieval is a DIFFERENT task —
matching a window's evidence to a past Jira issue's text. Text
similarity is the right tool there.

**Action when v5-large + ANTHROPIC_API_KEY both available:**
1. Take top-k Jira memory candidates from a cheap retriever (BM25 over jira-memory-corpus)
2. Format as Claude prompt: "given this window evidence, which of these k Jira issues is the closest match, and why?"
3. Use rationale-then-score response format
4. Calibrate temperature on val split before scoring test (per ml-ai-pipeline-benchmark-plan.md)
5. Score against the `recall_at_k` / `mrr` metrics already in the comparison harness

Likely candidate model: claude-haiku-4-5 (fast, cheap, sufficient for this reasoning task).

**Cost estimate:** ~7,400 test windows × ~10 candidates each × ~500 tokens in + ~200 tokens out per call = ~52M tokens. At Haiku 4.5 pricing, ~$15–30 for a single benchmark pass. Reasonable.

### 4.2 Cross-encoder for hard cases only

Bi-encoder failed on count-based classification. A cross-encoder over
(window_evidence, candidate_jira_text) pairs might do better on the
RETRIEVAL task — for the same reason: comparing the TEXT of a window
to the TEXT of a Jira issue is naturally semantic.

**Action:** install `sentence-transformers` cross-encoder (e.g.
`cross-encoder/ms-marco-MiniLM-L-6-v2`), rerank the top-k from BM25,
measure recall@k lift vs BM25 alone.

### 4.3 Stacking / hybrid blend

Reciprocal-rank fusion doesn't apply to classification; the docs
suggest stacking (weighted log-odds blend of numeric features + lexical
score + LM score). On v5-quick this had no clear win because text
features were weak. On v5-large with LM reranker added, worth re-trying
to see if LM rationale adds anything HGB can't already extract.

---

## 5. Predictions to validate on v5-large

From `docs/results-v5-quick.md` §8, listed here in checkable form:

| Prediction | v5-quick number | v5-large target | If misses |
| --- | --- | --- | --- |
| RF inclusive PR-AUC | 0.81 | **≥ 0.85** | Investigate: probably feature-distribution shift |
| HGB LOFO macro PR-AUC | 0.82 (m05v4) | **≥ 0.85** | Investigate: smaller drops here would suggest dataset shift |
| RF orphan recall | 0.346 (n=52) | **0.30–0.50** (n≈192) | Investigate: probably the per-language dispatch broke for some service |
| RF orphan gap_pts | +1.7 (m05v4) | **−5 to +5** | If much more negative: pipeline relies on Jira memory; if much more positive: pattern_matching verdict |
| recommendation-outage LOFO HGB | 0.73 (m05v4) | **≥ 0.80** | Investigate: probably recommendationservice still doesn't emit usable RED metrics |
| **cart-redis LOFO HGB** | **0.80 (m05v4)** | **≥ 0.85** | The categorical features lifted this +5pt on v5-quick; v5-large should compound |
| `cart_get_error_per_sec` discriminates cart-redis from baseline | 1.93 vs 0 in cartservice fault | Same pattern v5-large | If 0 even during cart-redis fault: categorical query mis-configured |
| Categorical-feature noise penalty on small train | -2pt macro on v5-quick | Should be **POSITIVE** on v5-large | If macro drops further: the 94-col catalog is too many features for the data size |
| Bi-encoder text-only PR-AUC | 0.21 | Similar (≤ 0.30) | If much higher: residual text leak we didn't catch |

---

## 6. Things this session intentionally did NOT do

For clarity — these are "not bugs, just not in scope":

- **D11 system-faults scenario LOFO numbers** — v5-quick didn't include the system-faults plan (laptop too constrained). v5-large does. First numbers on system-faults arrive with v5-large.
- **Cross-app generalization (Sock Shop / TrainTicket)** — Phase D6, not part of v5-large either.
- **Real Jira Cloud integration** — Phase 2 of product roadmap; out of scope.
- **D11 chaos-fault-specific metric coverage** — see §3.6 above; needs a follow-up phase if numbers reveal coverage gaps.
- **Human adjudication of borderline windows (D0.4)** — separate manual task; tool already exists (`src/adjudication/adjudicate.py`).

---

## 7. Where to read more

- `docs/results-v5-quick.md` — the full v5-quick writeup with the headline findings + per-section context + reproduction commands
- `docs/ml-ai-pipeline-development-plan.md` — the 4-phase plan with design principles
- `docs/ml-ai-pipeline-benchmark-plan.md` — the contract for metrics, splits, pipeline tracks
- `docs/triage-task-contract.md` — label space, severity, components, hard-case flag
- `microservice-changes-todo.md` — the M0–M5 instrumentation implementation status

---

## 8. Commits from this session (for `git log` lookup)

```
c50d163 Phase 4.5: categorical feature breakdowns + cart-redis +5pt lift
7a1df0f todo: checklist for everything that needs to flow into v5-large
47e0571 docs: add Phase 4 rich-text leaderboard finding
fb94129 Phase 4: bi-encoder + evidence_text fix + simpler results doc
9bcc216 supplement: per-language metric dispatch for cartservice + frontend RED metrics
efc7c94 docs: v5-quick results writeup — Phase 1–3 findings
6ea6e9e ML dev plan + Phases 1-3: feature-list-agnostic pipelines, sklearn baselines, M0-M5 feature extraction
```

Pull these together into a single mental model: **all the v5-quick
fixes are in code; v5-large mostly just needs the workflow in §2 run
against it; the open items in §3 are real but not blocking — they're
the next round of work after v5-large gives us a wider data slice to
measure on.**
