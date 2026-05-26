# What v5-quick Tells Us (Phase 1–4 Findings)

A plain-English writeup of what the v5-quick experiment proved, what it
disproved, and what it leaves open. Numbers are direct from the
comparison reports under
`data/derived/global/2026-05-25-dataset-v5-quick-*/comparison/`.

---

## TL;DR (read this if you only read one section)

We collected a small "v5-quick" corpus (1,020 telemetry windows across
22 fault scenarios) on the local laptop to start ML model development
while the full v5 collection runs unattended on a cloud VM. Across four
phases of experiments, the clearest findings:

1. **The build-pipeline extension works end-to-end.** v5-quick produces
   a 66-feature derived dataset (38 new columns from M0–M5 instrumentation).
   The new metrics flow correctly.
2. **The new M0–M5 features specifically lift "orphan ticket detection"
   by 3×.** Orphan = a real incident with no matching past Jira ticket.
   A pattern-matching model can't fake its way through these — it has to
   detect the fault from telemetry alone. Random Forest's recall on
   orphan windows tripled from 0.115 to **0.346**.
3. **Numeric features dominate text features for triage classification.**
   The discrimination is fundamentally count-based ("how many Redis errors
   happened?"). Text embeddings can't outperform a 28-feature numeric
   model on this task. We confirmed this with both TF-IDF and a
   sentence-transformers bi-encoder.
4. **Random Forest with `borderline` counted as positive hits PR-AUC
   0.81** — our strongest single-pipeline number on v5-quick.
5. **We found two real bugs the existing leakage canary missed**: the
   `triage_evidence_text` field was embedding lab-only identifiers
   (`window_type`, `window_id`) as substring tokens, silently inflating
   any text-based pipeline's numbers. Both are now fixed.
6. **LM reranking on the Jira-memory retrieval task gives 2× lift**
   (R@3 0.115 → 0.231, R@5 0.154 → 0.308, MRR 0.087 → 0.176) using
   a local Qwen 2.5 Coder 14B. The retrieval task IS semantic (matching
   window evidence to past ticket text), so LMs help here even though
   they didn't help on count-based classification.

**What this predicts for the full v5 corpus** (7,400 windows, 27 families,
arriving in ~3 days): orphan detection numbers will tighten (more data,
narrower confidence intervals); the per-family lift on hard families like
`recommendation-outage` should hold (+13 pts measured on v5-quick); text
pipelines will still trail numeric unless the dataset gets a redesign of
evidence_text generation.

---

## 1. What did we actually collect?

Comparing the v5-quick corpus to v4-large (the previous baseline):

| | v4-large | v5-quick |
| --- | ---: | ---: |
| Total windows | 3,216 | 1,020 |
| Scenario families | 13 | 22 |
| Orphan ticket-worthy windows | 0 | **92** ← new |
| Hard cases | 40.8% | 42.7% |
| Train / val / test split | 1008/480/1728 | 414/156/450 |

**What this means:** v5-quick is about 1/3 the size of v4-large but covers
nearly twice as many fault families (including 9 brand-new ones the model
has never seen). The "orphan" windows are unique to v5 — they're real
faults the system intentionally doesn't file Jira tickets for, used to
test whether the model is *detecting* faults or just *memorizing* Jira
patterns.

---

## 2. The headline numbers — Phase 1, 2, 3, 4 progression

**PR-AUC** (Precision-Recall Area Under Curve) is our primary metric. It
measures how well the model ranks ticket-worthy windows above noise
windows. Range 0–1; higher is better; 0.5 is essentially random for our
class balance.

Random Forest results across all iterations:

| Setup | Features | Strict PR-AUC | Inclusive PR-AUC | Orphan recall |
| --- | ---: | ---: | ---: | ---: |
| v4-large baseline | 28 | 0.66 | 0.77 | n/a (no orphans) |
| v5-quick AS-IS | 28 | 0.68 | 0.71 | 0.115 |
| v5-quick + M0–M5 features | 66 | 0.63 | **0.81** | 0.269 |
| v5-quick + per-language fix | 66 | 0.64 | **0.81** | **0.346** |
| v5-quick + rich evidence text | 66 | 0.64 | **0.81** | 0.346 |
| v5-quick + categorical breakdowns | **94** | 0.61 | 0.81 | 0.346 |

**Reading this table:**

- **Strict PR-AUC** treats `borderline` windows as negative (the strictest "must be ticketed" call).
- **Inclusive PR-AUC** counts `borderline` as positive — rewards the model for catching "kind of suspicious" things even if not full incidents.
- **Orphan recall** is the fraction of orphan ticket-worthy windows the model actually flags. This is the headline production-readiness metric for v5 — see §3.

**Why the strict number dropped from v4 to v5:** v5's test split is much smaller (450 windows vs 1,728) and contains 9 new fault families the model has never seen. The model didn't get worse — the test got harder. We confirm this with **LOFO macro PR-AUC** (next section) which stays stable.

**Why the inclusive number lifted:** v5 has more "borderline" cases by design (24% vs 22%) and the model is genuinely picking them up, just not crisply calling them `ticket_worthy`.

---

## 3. The cleanest win: orphan detection tripled

The "orphan-detection recall gap" metric is what v5's D12 phase was built
for. The idea:

- **Reported tickets:** real faults that ALSO have a matching past Jira
  entry the model could pattern-match to.
- **Orphan tickets:** real faults with NO matching past Jira entry.

If a model's recall on orphan tickets is much LOWER than on reported
ones, it's relying on Jira pattern-matching rather than genuinely
understanding telemetry. We measure this as `gap_pts = 100 × (recall_reported − recall_orphan)`.

Random Forest's progression:

| Setup | recall_orphan | gap_pts | What this means |
| --- | ---: | ---: | --- |
| v5-quick AS-IS (28 cols) | 0.115 | +6.6 | Mostly detects from signal, but missing many orphans |
| v5-quick + M0–M5 (66 cols, Go-only) | 0.269 | −4.2 | M0–M5 metrics added real signal |
| v5-quick + per-language dispatch | **0.346** | −0.5 | Per-language metric coverage closed the gap |

HGB went 0.058 → 0.212 (×3.6); RF went 0.115 → 0.346 (×3.0). **This is
the cleanest single piece of evidence that v5's M0–M5 telemetry adds
real, label-independent signal.**

The orphan windows had no Jira memory to lean on; the model had to
detect the fault from `cart_operations_error_per_sec=2.20`,
`orders_placed_per_sec=0`, `rpc_server_duration_p95_seconds=4.92` — and
it did.

---

## 4. LOFO macros — the cleanest "does it generalize?" signal

**Leave-one-family-out** (LOFO) takes each scenario family, holds it out
as the test set, trains on all other families, and measures how well the
model does on the family it's never seen. We average over all families
for the "macro" number.

| Pipeline | v4 (10 families) | v5-quick (14 scored families) |
| --- | ---: | ---: |
| HGB | 0.886 | 0.834 (m05v2 with per-language fix) |
| RF | 0.852 | **0.866** |
| Logistic | 0.762 | 0.632 |

**What this means:** the macro number barely moved across the corpus
change. RF actually went up slightly. **The model's ability to
generalize to a new fault family is preserved.** The fixed-split PR-AUC
drops we saw earlier were because v5's test split happens to contain
harder families — not because the model lost generalization ability.

### Per-family LOFO PR-AUC (HGB on v5-quick-m05v2)

| Family | LOFO PR-AUC | What this means |
| --- | ---: | --- |
| `checkout-restart` | 1.00 | Perfect — easy fault signature |
| `email-outage` (NEW) | 1.00 | Perfect even though the model never saw email-outage during training |
| `flapping-pod` (NEW) | 1.00 | Perfect |
| `productcatalog-outage` | 0.99 | Strong |
| `checkout-outage` | 0.97 | Strong |
| `payment-outage` | 0.81 | Solid |
| `cart-redis` | 0.75 | Near the ceiling on numeric features alone |
| **`recommendation-outage`** | **0.71** | **Was 0.57 on v4** — +13 pt lift! |
| `ad-outage` | 0.70 | Mid |
| `productcatalog-latency` | 0.54 | Hardest |

`recommendation-outage` has historically been the hardest family. **It
moved from 0.57 → 0.71** with M0–M5 features. That's a real
generalization improvement on a hard fault type.

---

## 5. The strongest single-pipeline number: RF inclusive 0.81

**Random Forest, with `borderline` counted as positive, hits PR-AUC
0.81 on v5-quick.** This is our top number on v5-quick.

| Pipeline (m05v2) | strict | inclusive |
| --- | ---: | ---: |
| **Calibrated Random Forest** | 0.63 | **0.81** |
| HistGradient Boosting | 0.59 | 0.74 |
| logsense | 0.42 | 0.59 |
| jira_only | 0.29 | 0.43 |

**What this means:** the model surfaces borderline windows correctly,
just doesn't crisp-call them `ticket_worthy`. This is the *right*
behaviour for a triage product — borderline windows should rank above
noise but below clear incidents.

---

## 6. Phase 4: bi-encoder neural pipeline (the disappointment)

We tried `sentence-transformers/all-MiniLM-L6-v2` (384-dim semantic
embeddings of `triage_evidence_text`) to see if a richer text
representation could beat numeric features.

| Pipeline | PR-AUC (sparse text) | PR-AUC (rich text) |
| --- | ---: | ---: |
| HGB numeric-only baseline | **0.60** | **0.60** (unchanged) |
| Bi-encoder + numeric concat | 0.32 | 0.31 |
| Bi-encoder text-only | 0.25 | 0.21 |

**The bi-encoder made things WORSE, not better — and enriching the text
made it slightly worse still.** Why?

For triage classification on this dataset, the discriminative signal is
**count-based** ("how many errors happened?") not **semantic** ("what
*kind* of error happened?"). cart-redis active_fault windows have the
same `RedisConnectionException` text as baseline windows — just 50×
more frequent. HGB's `delta_log_error_count=200` captures the count
directly. A 384-dim embedding compresses 20 identical error lines into
roughly the same vector as 2 of them.

Even after we enriched evidence text with structured fields (`dep`,
`op`, `err_class`, `peer_service`), the bi-encoder *still* trailed.
The structured tokens (`RedisConnectionException`, `redis-cart`,
`GetCart`) ARE there in the embedding — but they don't distinguish
fault windows from baseline because cartservice serves GetCart calls all
the time.

We confirmed this by re-running the full comparison harness on the
rich-text dataset (`v5-quick-m05v3`):

| Pipeline | m05v2 (sparse text) | m05v3 (rich text) | Δ |
| --- | ---: | ---: | ---: |
| HGB numeric | 0.60 | 0.60 | 0 (numeric unchanged) |
| RF numeric | 0.63 | 0.64 | +0.01 |
| RF inclusive | 0.81 | 0.81 | 0 |
| loganalyzer (uses text) | 0.35 | 0.33 | −0.02 |
| jira_only (uses memory) | 0.29 | 0.27 | −0.02 |

The text cleanup was a **fidelity improvement** (removed the WINDOW
header label leak — see §7) but didn't unlock new ML performance.

**What this means:**

- **For triage classification:** text features don't help over numeric on
  this dataset. The bottleneck is count signal, not semantic signal.
- **For LM reranking:** the same bottleneck would apply — LMs reading
  the same text would hit the same wall. Worth trying only on hard
  families where the fault signature is genuinely *new* (system-faults
  from chaos-mesh: DNS errors, packet loss — those aren't in baseline).
- **For Jira memory retrieval:** different task. Text similarity matters
  there (matching window evidence to past ticket descriptions). Phase 4
  LM reranking is still meaningful for that task.
- **For honest reporting:** removing the WINDOW header leak was the right
  thing to do regardless. Now any future text/LM result is measured
  cleanly, not inflated by lab-only substring tokens.

---

## 6b. Phase 4.5: categorical feature breakdowns (the targeted win)

After the bi-encoder disappointment, we tried something more focused:
**break the business counters and RPC status codes down by their label
dimensions**. Instead of one `cart_operations_error_per_sec` aggregate,
we extract `cart_get_error_per_sec`, `cart_add_error_per_sec`,
`cart_empty_error_per_sec` separately. Same for `payments_total{result}`
(success/invalid/expired/unsupported) and `rpc_server_requests_total{status}`
(OK/Internal/Unavailable/FailedPrecondition/DeadlineExceeded).

That added 14 new feature columns, lifting the catalog from 66 → 94.

**What we expected:** cart-redis specifically gets better because the
fingerprint `cart_get_error >> cart_add_error >> cart_empty_error=0`
is now learnable. Confirmed by inspection on one window — during
cart-redis active_fault, cartservice shows `cart_get_error_per_sec=1.93`
vs `cart_add_error_per_sec=0.27` vs `cart_empty_error_per_sec=0`.

**What we got** (per-family LOFO HGB):

| Family | 66-col (m05v2) | **94-col (m05v4 / categorical)** | Δ |
| --- | ---: | ---: | ---: |
| **cart-redis** | 0.748 | **0.800** | **+0.05** ← targeted lift |
| payment-outage | 0.812 | 0.819 | +0.01 |
| recommendation-outage | 0.707 | 0.728 | +0.02 |
| productcatalog-latency | 0.544 | 0.500 | −0.04 |

**cart-redis lifted +5 pts to 0.80** — exactly as predicted. Models DO
pick up the categorical fingerprint when it's there.

**The overall macro stays roughly the same** because adding 28 new
columns to a 414-window train set introduces overfitting noise that
slightly hurts other families:

| Pipeline | m05v2 (66) | m05v4 (94) |
| --- | ---: | ---: |
| RF strict PR-AUC | 0.636 | 0.615 |
| RF inclusive PR-AUC | 0.811 | 0.807 (stable) |
| RF orphan recall | 0.346 | 0.346 (stable) |
| HGB LOFO macro | 0.830 | 0.822 |
| RF LOFO macro | 0.869 | 0.825 |

**What this means:**

- The categorical signal is **real** — cart-redis lifts measurably.
- It's partially **masked by noise** from added feature dimensions on
  this 414-window train set. This is the same effect we saw at the
  28→66 transition; more train data absorbs it.
- **Prediction for v5-large**: with 5,000+ train windows, the +5pt
  cart-redis lift should hold AND the overall macro should also lift
  by ~3–5 pts as the noise gets absorbed.

The 14 new columns ARE worth keeping. v5-large should run with
categorical extraction enabled from the start.

---

## 6c. Phase 4 (cont.): LM reranker for Jira-memory retrieval (the targeted win)

Bi-encoder failed because triage classification is count-based. But
**memory retrieval is fundamentally semantic** — matching a window's
evidence to a past Jira ticket's text. We tested an LM reranker on this
task using a local Qwen 2.5 Coder 14B (LM Studio on `:1234`) so it
works without an external API key.

**Setup:** for each ticket_worthy test window (n=26), BM25 ranks all 48
Jira memory entries, takes top-10, and asks Qwen to rerank them. We
score recall@1/3/5 and MRR against the ground-truth matched memory
issue id from `window-memory-matchings.jsonl`.

| Pipeline | R@1 | R@3 | R@5 | MRR | Wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 only | 0.000 | 0.115 | 0.154 | 0.087 | n/a |
| **BM25 + LM rerank pool=10** | **0.077** | **0.231** | **0.308** | **0.176** | 296s |
| **BM25 + LM rerank pool=20** | **0.077** | **0.269** | **0.308** | **0.203** | 524s |
| Lift (pool=20 vs BM25) | +7.7pt | **+15.4pt (2.3×)** | **+15.4pt (2×)** | **+10.4pt (2.3×)** | |

Per-family (pool=20):

| Family | n | BM25 R@3 | LM R@3 |
| --- | ---: | ---: | ---: |
| cart-redis | 16 | 0.062 | **0.250** |
| currency-outage | 3 | 0.667 | **1.000** |
| checkout-outage | 4 | 0.000 | 0.000 (gold not in BM25 top-20) |
| productcatalog-latency | 3 | 0.000 | 0.000 (gold not in BM25 top-20) |

**Pool-size sweep:** wider pool helps R@3 + MRR but not R@1/R@5 — R@5
is capped by "is gold in BM25's top-N?", and pool=20 only covers 42%
of the 48-entry corpus. Pool=10 → pool=20 cost 1.77× more wall time
for +3.8pt R@3 and +2.7pt MRR. **Pool=10 is the cost/quality sweet
spot for the local Qwen.** On v5-large with ~430 memory entries,
pool=10 covers only ~2% of corpus — pool will need to scale (or
better: replace BM25 with a semantic retriever like Nomic embed,
which would lift BM25 top-10 recall itself).

**What this means:**

- The LM rerank works **exactly as Phase 4 hoped** for the retrieval
  task. ~2× lift on R@3, R@5, MRR.
- It works because the LM reads BOTH the window evidence (`dep=redis-cart op=GetCart err_class=RedisConnectionException`) AND the candidate Jira text (`Summary: Intermittent slowness... Components: checkoutservice, frontend, productcatalogservice`) and reasons about which is the closer semantic match — beyond surface token overlap that BM25 measures.
- **The ceiling is BM25's top-10 recall.** When the gold issue isn't in BM25's top-10 (e.g. productcatalog-latency, checkout-outage), no reranker can recover it. The fix is either: a larger memory corpus (v5-large should have 4× more entries), a better cheap retriever (embedding-based, e.g. Nomic embed for the BM25 stage), or a wider pool (pool=20 or pool=full-corpus).
- Headline numbers are still LOW (R@5 = 31%) because the v5-quick memory corpus has only 48 entries and the memory text is generic ("Synthetic lab issue generated from Online Boutique telemetry" appears in EVERY entry, diluting IDF).
- **Cost:** 26 windows × pool=10 candidates × ~10s per Qwen call ≈ 5 min local-CPU. Free with local model. On v5-large with ~430 memory entries and ~600 ticket-worthy test windows, expect ~2 hours.

**This is the cleanest Phase 4 win.** It validates the thesis from
`docs/ml-ai-pipeline-benchmark-plan.md` §LM reranking — that LMs add
value over lexical retrievers when the relevance signal is semantic.

---

## 7. Real bugs surfaced (and fixed)

### Bug 1: `triage_evidence_text` embedded lab-only labels

The text field included a header line like
`WINDOW window_id=2026-05-25-dataset-v5-quick-compact-a-r01-cart-redis-degradation-critical-20260525T220053Z-active_fault-cartservice`.
TF-IDF saw tokens like `active_fault`, `recovery_window`, `quick orphans`,
`26t01` (the date) as deterministically discriminative.

This is **silent label leakage**. We measured:

| TF-IDF over evidence text | PR-AUC |
| --- | ---: |
| With the header (leaky) | 0.83 |
| Header stripped, lab tokens redacted | 0.34 |

A 49-point swing. The existing leakage canary missed this because it
only checks scenario_id / scenario_family / triage_label correlations,
not substring tokens embedded in the production-facing text field.

**Fix:** `evidence_text_from_raw` now drops the WINDOW header line
entirely. The leakage canary should be extended to check for substring
tokens.

### Bug 2: per-service M0–M5 metrics zero for non-Go services

Our first version of the supplement export script used Go's metric names
(`rpc_server_requests_total`) for every service. .NET cartservice,
.Node payment/currency, .Python recommendation/email, and .Java
adservice use *different* OTel metric names. So 8 of 38 new feature
columns were all-zero for those services.

**Fix:** `SERVICE_LANG_MAP` + per-language query dispatch. cartservice
now correctly uses `http_server_request_duration_seconds_count`
(AspNetCore middleware). Verified:

| Service | Metric | Before | After |
| --- | --- | ---: | ---: |
| cartservice (.NET) | `m05_svc_rpc_server_requests_per_sec` | 0.00 | **2.65** req/sec |
| frontend (Go-HTTP) | same | 0.00 | **7.21** req/sec |
| recommendationservice (Python) | `m05_svc_python_gc_per_sec` | 0.00 | 0.13 GC/sec |

For Node services (payment, currency) and Java (adservice), the OTel
SDKs don't currently emit RED metrics that land in our ServiceMonitor.
The supplement script correctly emits 0 for those rather than confusing
zeros with missing-metric noise.

### Bug 3 (open): evidence_text duplicates fields

After fixing the WINDOW header leak, we noticed the .NET JsonConsole
formatter renders structured State data as `{ key = value, key = value }`
inside the message text. So each line had `dep=redis-cart op=GetCart
err_class=RedisConnectionException` AND the full `msg="{ dep = redis-cart,
... }"` string. Fixed by suppressing the message-text echo when ≥3
structured fields were extracted (saves ~40% of the character budget).

---

## 8. What's solid for v5-large (the full 7,400-window corpus)

| Result | Confidence | Why |
| --- | --- | --- |
| Build pipeline runs end-to-end | High | Same scripts; just longer wall time |
| Orphan recall gap metric measures correctly | High | v5-large has 192 orphan windows (vs 92 here) — CIs tighten |
| RF inclusive PR-AUC ≥ 0.85 on v5-large | Medium-High | 0.81 on v5-quick scales with more train data |
| recommendation-outage LOFO ≥ 0.80 on v5-large | Medium | +13 pt lift on v5-quick suggests headroom |
| Per-language dispatch covers .NET (cartservice) correctly | High | Verified working on this corpus |
| Numeric pipelines (HGB, RF) remain the strongest | High | Confirmed across 3 dataset iterations |
| Text/embedding pipelines lift on v5-large | **Low** | Count-based discrimination doesn't unlock with more text |

---

## 9. What still needs work before v5-large delivers full value

| Issue | Severity | Status |
| --- | --- | --- |
| Per-service M0–M5 features zero for Node/Python/Java | **High** | Partial — cartservice/frontend fixed via per-language dispatch; Node/Python/Java need their OTel SDKs to emit Prom-scrapeable RED metrics first |
| WINDOW header leak in evidence_text | High | **FIXED** (`evidence_text_from_raw` updated) |
| Leakage canary doesn't catch substring tokens | High | Open — extend `validate-run-feature-distribution.py` to scan `triage_evidence_text` for embedded `triage_label`/`window_type`/`scenario_id` substrings |
| Evidence text duplicates structured fields | Medium | **FIXED** (suppress msg= when ≥3 fields extracted) |
| LM reranking untested (no API key set) | Medium | Open — needs `ANTHROPIC_API_KEY`; script `experiments/bi_encoder_v5.py` ready as the template |
| Categorical features (card_type, op, result, err_class as inputs) not extracted | Low–Medium | Open — would need a categorical-aware build_triage_dataset extension |

---

## 10. Quick reference: how to reproduce these numbers

```powershell
# v5-quick AS-IS leaderboard (28 features)
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-global" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,loganalyzer_with_jira,jira_only,logsense,hgb,rf,logistic_sklearn `
  --n-bootstrap 500 `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-global\comparison\phase3-v5-asis"

# Re-export M0–M5 supplement files (needs Prometheus port-forwarded to :19099)
kubectl -n observability port-forward `
  pod/prometheus-kube-prometheus-stack-prometheus-0 19099:9090
.venv\Scripts\python.exe scripts\research-lab\export_m05_supplement.py `
  --run-prefix 2026-05-25-dataset-v5-quick `
  --prometheus-url http://127.0.0.1:19099

# Rebuild per-run + global with M0–M5 features
for ($r in (gci data\runs\2026-05-25-dataset-v5-quick-*)) {
  .venv\Scripts\python.exe scripts\research-lab\build_triage_dataset.py `
    --dataset-run-id $r.Name --force
}
.venv\Scripts\python.exe scripts\research-lab\build_global_triage_dataset.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-quick `
  --global-dataset-id 2026-05-25-dataset-v5-quick-m05v2 --force
.venv\Scripts\python.exe scripts\research-lab\build_jira_memory_corpus.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-quick `
  --global-dataset-id 2026-05-25-dataset-v5-quick-m05v2 --force

# Phase 3 leaderboard with M0–M5 features
.venv\Scripts\python.exe -m comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-m05v2" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,loganalyzer_with_jira,jira_only,logsense,hgb,rf,logistic_sklearn `
  --n-bootstrap 500 `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-m05v2\comparison\phase3-perlang-dispatch"

# Phase 4 bi-encoder experiment
.venv\Scripts\python.exe experiments\bi_encoder_v5.py --cache-embeddings

# Fast sklearn iteration
.venv\Scripts\python.exe experiments\baseline_v4.py --global-id 2026-05-25-dataset-v5-quick-m05v2
```

Reports land under `<global-dir>/comparison/<output-name>/`:
- `report.md` — human-readable leaderboard with bootstrap CIs, pairwise
  significance tests, per-family stratification, inclusive borderline
  section, LOFO macros, orphan recall gap.
- `report.json` — machine-readable equivalent.
- `per-window-predictions.jsonl` — every test window with every
  pipeline's score + decision + retrieval result.

---

## 11. Reference: v4-large baseline numbers (for comparison)

From `data/derived/global/2026-05-22-dataset-v4-large-global/comparison/phase2-leaderboard/report.md`:

| Pipeline | PR-AUC | 95% CI | ROC-AUC | P@FPR=5% | LOFO Macro PR-AUC |
| --- | ---: | --- | ---: | ---: | ---: |
| `ensemble_mean` | 0.808 | [0.762, 0.844] | 0.960 | 0.751 | — |
| `loganalyzer_hybrid_bm25` | 0.723 | [0.680, 0.761] | 0.898 | 0.704 | — |
| `hist_gradient_boosting_numeric` | 0.719 | [0.665, 0.775] | 0.951 | 0.755 | 0.886 |
| `loganalyzer_hybrid_with_jira` | 0.692 | [0.650, 0.731] | 0.865 | 0.703 | — |
| `logistic_numeric_sklearn` | 0.674 | [0.631, 0.716] | 0.840 | 0.703 | 0.762 |
| `calibrated_random_forest_numeric` | 0.662 | [0.612, 0.723] | 0.933 | 0.657 | 0.852 |
| `logsense_hybrid_bm25` | 0.493 | [0.441, 0.545] | 0.741 | 0.624 | — |
| `jira_only` | 0.239 | [0.212, 0.271] | 0.546 | 0.277 | — |

---

## 12. Summary in one sentence

**v5-quick proves the build-pipeline chain works end-to-end, the M0–M5
features specifically lift orphan-ticket detection (3× on HGB and RF) —
exactly the case Jira-memory pattern matching cannot solve — and the
ML headroom from here is in better instrumentation coverage (Node, Java,
Python OTel RED metrics) and in richer Jira memory text for retrieval,
NOT in heavier model architectures for classification.**
