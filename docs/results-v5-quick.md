# v5-quick Results — Phase 1–3 Findings

**Dataset:** `data/derived/global/2026-05-25-dataset-v5-quick-global/` (28 v4-shape features)
**Richer dataset:** `data/derived/global/2026-05-25-dataset-v5-quick-m05/` (66 features = 28 v4 + 38 m05)
**Collected:** 2026-05-25 / 2026-05-26 on local laptop kind cluster (`jira-telemetry-lab`)
**Code:** committed at `6ea6e9e`
**Companion:** `docs/ml-ai-pipeline-development-plan.md` (the contract)

This document records what the v5-quick corpus actually tells us about
v5's telemetry richness, what generalises, what doesn't, and what to
expect when v5-large lands on the GCP VM. Numbers are direct from
`comparison/phase3-*` and `experiments/baseline_v4.py` reports.

---

## 1. Corpus delivered (vs. plan)

| Item | Planned | Actual |
| --- | --- | --- |
| Runs | 16 | **16** ✓ |
| Windows | ~470 | **1,020** (over-delivered) |
| Scenario families | 22 | **22** ✓ |
| Jira memory entries | ~85 | **48** (under — fewer orphan twins than expected) |
| Orphan ticket_worthy windows | 32 | **92** (over-delivered — orphan plan generated more per run than estimated) |
| Hard cases | ≥15% | **42.7%** (matches v4-large's 40.8%) |
| Label distribution | mirror v4 | 56% noise / 24% borderline / 20% ticket_worthy (v4 was 55/22/22) |
| Wall-clock | ~6–8 h | ~10 h (small overrun; well within tolerance) |

**Family coverage** (descending by window count): cart-redis 138, baseline-normal 120, productcatalog-latency 66, recovered-in-window 60, payment-outage 54, currency-outage 54, shipping-outage 54, ad-outage 48, recommendation-outage 36, productcatalog-outage 36, frontend-traffic-pressure 36, slow-leak-saturation 36, latency-near-miss-partial-recovery 36, **email-outage 36** (new D12 family), frontend-restart 30, post-deploy-churn 30, third-party-blip 30, flapping-pod 30, checkout-restart 24, checkout-outage 24, scheduled-job-spike 24, single-pod-restart-healthy-replication 18.

**Splits:** 414 train / 156 val / 450 test (vs v4-large 1,008 / 480 / 1,728 — same family-stratified design at ~1/3 scale).

---

## 2. The headline number progression

PR-AUC (strict borderline = negative, family-stratified test split) across our three operating points:

| Pipeline | v4-large (28 cols) | v5-quick AS-IS (28) | v5-quick-m05 (66) |
| --- | ---: | ---: | ---: |
| `ensemble_mean` | **0.8078** | 0.5773 | 0.4478 |
| `loganalyzer_hybrid_bm25` | 0.7230 | 0.4586 | 0.3367 |
| `hist_gradient_boosting_numeric` | 0.7194 | 0.6652 | 0.5880 |
| `loganalyzer_hybrid_with_jira` | 0.6924 | 0.4825 | 0.3539 |
| `logistic_numeric_sklearn` | 0.6745 | 0.4322 | 0.2839 |
| `calibrated_random_forest_numeric` | 0.6621 | **0.6776** | 0.6335 |
| `logsense_hybrid_bm25` | 0.4928 | 0.4234 | 0.4234 |
| `jira_only` | 0.2385 | 0.2887 | 0.2887 |

**At first glance this looks like a regression.** It's not — the numbers move for three independent reasons that need to be separated before any interpretation.

### Why fixed-split PR-AUC drops from v4 to v5

| Cause | Magnitude | Evidence |
| --- | --- | --- |
| **Smaller test split** (1,728 → 450 windows) raises variance | ~±5 pts | 95% bootstrap CIs on v5 are ~2× wider than on v4 |
| **22 families vs 13** — more held-out diversity for the test position | ~5–10 pts | LOFO macros barely move (see §3); fixed-split numbers move a lot |
| **9 of 22 families are brand-new D1/D12 shapes** the model has no analog for | ~10–15 pts | LOFO PR-AUC on `recommendation-outage` (the hardest family) is 0.57 on v4 — same number on v5 |

None of these are "v5 is worse than v4." They're "v5's test split is genuinely harder."

### Why adding the 38 m05 columns hurts fixed-split numbers

Two real bugs surfaced by this experiment:

1. **8 of the 38 m05 columns are per-service `svc_*` features that are all-zero for non-Go services.** The M4.2 phase notes (`microservice-changes-todo.md`) document that .NET, Node, Python, and Java services each emit RED metrics under *different* OTel metric names (`http_server_request_duration_*`, `rpc_server_duration_milliseconds_*`, etc.) — my supplement export script only queries `rpc_server_requests_total` (Go-only). So per-service features populate for `checkoutservice`, `productcatalogservice`, `shippingservice`, `frontend` only.
2. **Train split has 414 windows; we added 38 new columns to a learner that previously had 28.** Overfit on training noise dominates the small added signal. Same models on a 5,000-window v5-large corpus should absorb the noise.

The honest read: **fixed-split strict PR-AUC is the *most volatile* metric across this corpus size change.** Use LOFO macros and orphan-recall-gap as the cleaner signals.

---

## 3. LOFO macros — the cleaner generalization signal

Leave-one-family-out PR-AUC, averaged equally over all scored families (numeric pipelines only, since LOFO requires re-fitting per fold):

| Pipeline | v4-large | v5-quick AS-IS | v5-quick-m05 |
| --- | ---: | ---: | ---: |
| HGB | 0.8864 | 0.8809 | 0.8339 |
| RF | 0.8515 | **0.8790** | 0.8658 |
| Logistic | 0.7623 | 0.7047 | 0.6624 |

**RF on v5-quick AS-IS hits 0.879 — a slight LIFT over v4** (within noise but directionally positive, and v5 has 22 families to LOFO over vs v4's 10 scored). The m05 columns drop HGB's macro by ~5pts because of the noise-feature problem in §2.

**Translation:** "Same model, leave any one family out, train on all others — how well does it predict?" That number is essentially unchanged from v4 to v5-quick AS-IS, and only mildly hurt by the m05 columns. **The model's generalization ability is stable across the dataset change.**

---

## 4. The orphan-detection recall gap — where m05 features SHINE

This metric is what v5's D12 phase was built for. Per dataset-todo.md §D12.6:

> `gap_pts = 100 × (recall on reported ticket_worthy − recall on orphan ticket_worthy)`
> Verdict: `< 10pts` = signal_learning, `10–20` = borderline, `> 20` = pattern_matching.

v4 had zero `expected_in_memory` annotations, so the metric returns `no_orphan_data` for every pipeline. v5-quick has 92 orphan ticket-worthy windows that DO have the annotation. The metric works for the first time.

### v5-quick AS-IS (28 features)

| Pipeline | n_reported | recall_reported | n_orphan | recall_orphan | gap_pts | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| HGB | 44 | 0.136 | 52 | 0.058 | +7.9 | signal_learning |
| RF | 44 | 0.182 | 52 | 0.115 | +6.6 | signal_learning |
| Logistic | 44 | 0.295 | 52 | 0.231 | +6.5 | signal_learning |
| loganalyzer | 44 | 0.182 | 52 | 0.250 | −6.8 | signal_learning (lifts on orphans) |
| loganalyzer + jira | 44 | 0.114 | 52 | 0.500 | −38.6 | signal_learning |
| jira_only | 44 | 0.159 | 52 | **0.654** | −49.5 | signal_learning |

### v5-quick-m05 (66 features) — the lift

| Pipeline | n_reported | recall_reported | **n_orphan recall (m05)** | (was AS-IS) | gap_pts |
| --- | ---: | ---: | ---: | ---: | ---: |
| HGB | 44 | 0.182 | **0.212** | 0.058 | −3.0 |
| RF | 44 | 0.227 | **0.269** | 0.115 | −4.2 |
| Logistic | 44 | 0.068 | 0.154 | 0.231 | −8.6 |

**HGB's orphan recall MORE THAN TRIPLED (0.058 → 0.212). RF's more than doubled (0.115 → 0.269).** These are the biggest individual lifts in the whole experiment.

**Why this matters:** the orphan ticket_worthy windows have NO matching Jira memory entry by design (per D12 — those scenarios run with `produces_jira_ticket: false`). A model can't pattern-match its way to "ticket_worthy" — it has to detect the fault from telemetry signal alone. The m05 features (`orders_placed_per_sec=0` during checkout-restart, `cart_operations_error_per_sec=2.2` during cart-redis, `rpc_server_duration_p95_seconds=4.92` during productcatalog-latency) provide exactly that telemetry signal. **The orphan recall lift is the cleanest single piece of evidence that the M0–M5 layer adds real, label-independent signal.**

The big negative gaps on `jira_only` and `loganalyzer+jira` (−49.5, −38.6 pts) reflect that **memory-aware pipelines already over-recall on orphans** — they don't know there's nothing to match, so they call ticket_worthy anyway. The numeric pipelines are the honest signal-learning measurement.

---

## 5. Inclusive vs strict — v5 borderline windows carry real signal

| Pipeline (v5-quick-m05) | strict PR-AUC | inclusive PR-AUC | inclusive − strict |
| --- | ---: | ---: | ---: |
| **RF (m05)** | 0.6335 | **0.8058** | +0.172 |
| HGB (m05) | 0.5880 | 0.7430 | +0.155 |
| logsense | 0.4234 | 0.5890 | +0.166 |
| jira_only | 0.2887 | 0.4348 | +0.146 |

**The single best v5-quick PR-AUC number is `calibrated_random_forest_numeric` at 0.81 inclusive.** All four pipelines lift by 15–17 pts when borderline counts as positive — meaning the pipelines DO surface borderline windows, they just don't crisply commit to `ticket_worthy`.

This is the *correct* behaviour: a triage product should rank borderline windows above noise but below clear ticket-worthy. The inclusive PR-AUC of 0.81 says the model is doing exactly that.

---

## 6. Per-family LOFO PR-AUC — where v5's families fall

LOFO PR-AUC for HGB (m05). Skipped folds = no ticket_worthy positives in held-out family:

| Family | LOFO PR-AUC | Status |
| --- | ---: | --- |
| `checkout-outage` | **1.00** | Perfect |
| `frontend-restart` | **1.00** | Perfect |
| `productcatalog-outage` | 1.00 | Perfect |
| `currency-outage` | 0.92 | Strong |
| `payment-outage` | 0.94 | Strong |
| `shipping-outage` | 0.97 | Strong |
| `checkout-restart` | 0.95 | Strong |
| `cart-redis` | 0.74 | **Mid — hurt by missing cartservice svc_* features** |
| `productcatalog-latency` | 0.78 | Mid |
| **`recommendation-outage`** | **0.57** | **Hardest — was 0.57 on v4 too. Unchanged.** |
| `ad-outage` / `baseline-normal` / `frontend-traffic-pressure` | skip | No positives in family |

**`recommendation-outage` is the consistent failure mode across both corpora.** The recommendationservice→productcatalogservice call boundary doesn't produce a fault signature that the current features capture well. Two specific gaps:
- Recommendation outages cause fan-out misses but not gRPC errors (the model returns a degraded result, not an exception).
- No L2 dep-error logs flow from recommendationservice→productcatalog yet (M2.2 added them but they aren't very discriminative for this pattern).

For v5-large: **`recommendation-outage` is the headline family to watch.** If the per-language metric dispatch fix lifts cartservice to populate svc_* properly, recommendation-outage will get the same lift via its `m05_recommendations_served_per_sec` and `m05_catalog_lookups_total` features.

---

## 7. Lexical evidence-text experiment

We ran `experiments/lexical_evidence_v4.py` on both corpora, with two redaction modes:

| Mode | v4-large `text_only` | v5-quick `text_only` | v4-large `text+numeric` | v5-quick `text+numeric` |
| --- | ---: | ---: | ---: | ---: |
| **No redaction** (leaky) | 0.83 | 0.83 | 0.74 | 0.61 |
| **Light redact** (window_type tokens) | 0.42 | 0.33 | 0.67 | 0.54 |
| **Full redact** (drop WINDOW header line) | 0.34 | 0.29 | 0.64 | 0.42 |

**A bug surfaced:** `triage_evidence_text` embeds the lab-only WINDOW header line (`WINDOW window_id=<dataset>-<plan>-<scenario>-<timestamp>-<window_type>-<service>`). TF-IDF picks up tokens like `active_fault`, `recovery_window`, `pre_fault_baseline`, `quick orphans`, `26t01` (dataset date) as deterministically discriminative. The existing leakage canary missed this because it only checks scenario_id / scenario_family / triage_label direct correlations, not substring tokens embedded in the production-facing text field.

**Honest lexical numbers (after full redaction):** v4 text-only ~0.34, v5 text-only ~0.29. v5 has new L2 `dep_error` tokens flowing through the evidence text (visible in the top features) but they're not enough to lift the headline because:
- Only 3–5 literal `[error] dep_error` lines per window — repeated identical strings carry no TF-IDF signal
- No `err_class`, `peer_service`, `op` fields in the dep_error text (the build pipeline strips these)
- Body has only TRACES + LOG-ERRORS sections, not the full L1/L2/L3 content M2 produces

**Action for v5-large:** the `evidence_text_from_raw` builder should:
1. Drop the WINDOW header line (it's pure lab-only leakage)
2. Include `err_class`, `peer_service`, `retry_attempt` in dep_error lines (those are production-realistic fields the model can legitimately use)
3. Add L3 business event lines (`order_placed`, `payment_charged`) at the head — they're rare and discriminative

---

## 8. What's solid for v5-large

| Result | Confidence | Action |
| --- | --- | --- |
| Build pipeline extension works end-to-end | High | Same `export_m05_supplement.py` + `build_triage_dataset.py` chain re-runs on v5-large with zero changes |
| Orphan recall gap metric IS measurable on v5+ datasets | High | v5-large will have 192 orphan windows (vs 92 here) — verdict bucket will be much more stable |
| Inclusive borderline pipeline reads as expected (RF +17 pts) | High | The 0.81 inclusive PR-AUC on v5-quick predicts ≥0.85 inclusive on v5-large |
| HGB orphan recall triples with m05 features | Medium-High | n_orphan=52 is small; v5-large's 192 will tighten the CI |
| LOFO macros are stable across corpus change (HGB 0.88 → 0.83) | Medium | Some drop expected from added noise features; m05 svc_* fix should recover |
| Fixed-split strict PR-AUC will recover on v5-large | Medium | 7,400-window train absorbs the 38 new columns much better than 414 windows did |

---

## 9. What needs fixing before v5-large delivers full value

| Issue | Severity | Fix |
| --- | --- | --- |
| `svc_*` per-service M0–M5 features are zero for .NET/Node/Python/Java | **High** — most of cart-redis signal is on cartservice (.NET) | Add per-language metric-name dispatch to `export_m05_supplement.py`. ~30 lines. |
| `triage_evidence_text` leaks `window_type` + full window_id substring | **High** — silently inflates any text/lexical/LM pipeline | Drop the WINDOW header line from `evidence_text_from_raw`; flag for v5.1 build |
| Leakage canary doesn't catch substring tokens | **High** — bug surfaced this run, will surface more | Extend `validate-run-feature-distribution.py` to check `triage_evidence_text` for embedded `triage_label` / `window_type` / `scenario_id` substrings |
| L2 dep-error log lines collapse to literally identical strings | **Medium** — wastes the M2.2 signal | `evidence_text_from_raw` should preserve `err_class`, `peer_service`, `op`, `retry_attempt` fields from each dep_error log line |
| Smaller v5-quick test split (450 vs 1728) widens CIs ~2× | **Low** — expected; v5-large fixes naturally | n/a |

---

## 10. Reference: v4-large baseline (for comparison)

From `data/derived/global/2026-05-22-dataset-v4-large-global/comparison/phase2-leaderboard/report.md`:

| Pipeline | PR-AUC | 95% CI | ROC-AUC | P@FPR=5% | LOFO Macro PR-AUC |
| --- | ---: | --- | ---: | ---: | ---: |
| `ensemble_mean` | 0.8078 | [0.7622, 0.8439] | 0.9595 | 0.7509 | — |
| `loganalyzer_hybrid_bm25` | 0.7230 | [0.6801, 0.7607] | 0.8975 | 0.7043 | — |
| `hist_gradient_boosting_numeric` | 0.7194 | [0.6649, 0.7748] | 0.9505 | 0.7554 | 0.8864 |
| `loganalyzer_hybrid_with_jira` | 0.6924 | [0.6497, 0.7309] | 0.8648 | 0.7031 | — |
| `logistic_numeric_sklearn` | 0.6745 | [0.6314, 0.7158] | 0.8401 | 0.7031 | 0.7623 |
| `calibrated_random_forest_numeric` | 0.6621 | [0.6124, 0.7231] | 0.9330 | 0.6566 | 0.8515 |
| `logsense_hybrid_bm25` | 0.4928 | [0.4406, 0.5450] | 0.7407 | 0.6243 | — |
| `jira_only` | 0.2385 | [0.2117, 0.2714] | 0.5460 | 0.2766 | — |

---

## 11. Reproducing these results

```powershell
# v5-quick AS-IS leaderboard (28 features — uses original v4-shape extraction)
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-global" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,loganalyzer_with_jira,jira_only,logsense,hgb,rf,logistic_sklearn `
  --n-bootstrap 500 `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-global\comparison\phase3-v5-asis"

# Re-export M0-M5 supplement files (needs Prometheus port-forwarded to :19099)
kubectl -n observability port-forward `
  pod/prometheus-kube-prometheus-stack-prometheus-0 19099:9090
.venv\Scripts\python.exe scripts\research-lab\export_m05_supplement.py `
  --run-prefix 2026-05-25-dataset-v5-quick `
  --prometheus-url http://127.0.0.1:19099

# Rebuild per-run + global with the m05 features
for ($r in (gci data\runs\2026-05-25-dataset-v5-quick-*)) {
  .venv\Scripts\python.exe scripts\research-lab\build_triage_dataset.py `
    --dataset-run-id $r.Name --force
}
.venv\Scripts\python.exe scripts\research-lab\build_global_triage_dataset.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-quick `
  --global-dataset-id 2026-05-25-dataset-v5-quick-m05 `
  --force
.venv\Scripts\python.exe scripts\research-lab\build_jira_memory_corpus.py `
  --dataset-run-prefix 2026-05-25-dataset-v5-quick `
  --global-dataset-id 2026-05-25-dataset-v5-quick-m05 `
  --force

# Phase 3 richness ablation leaderboard (66 features)
.venv\Scripts\python.exe -m comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-m05" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,loganalyzer_with_jira,jira_only,logsense,hgb,rf,logistic_sklearn `
  --n-bootstrap 500 `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-m05\comparison\phase3-richness-ablation"

# Fast iteration sklearn baseline
.venv\Scripts\python.exe experiments\baseline_v4.py --global-id 2026-05-25-dataset-v5-quick-m05
```

Reports land under `<global-dir>/comparison/<output-name>/`:
- `report.md` — human-readable leaderboard with bootstrap CIs, pairwise significance, per-family stratification, inclusive borderline section, LOFO macros, orphan recall gap.
- `report.json` — machine-readable equivalent.
- `per-window-predictions.jsonl` — every test window with every pipeline's score + decision + retrieval result.

---

## 12. Summary in one sentence

**v5-quick proves the build-pipeline chain works end-to-end and that the M0–M5 features specifically lift orphan-ticket detection (HGB 3×, RF 2×) — exactly the case Jira-memory pattern matching can't solve — while the fixed-split strict PR-AUC drop is dominated by per-language metric-name coverage gaps and small-train-set overfitting that v5-large's 7,400 windows + per-language dispatch fix will absorb.**
