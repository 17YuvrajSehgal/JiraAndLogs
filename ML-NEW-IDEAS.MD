# ML-NEW-IDEAS.md — using raw logs as a first-class signal

**Captured:** 2026-05-28 (after v5-large validation passed).
**Status:** ideas only — not implemented. Captures the diagnosis + the
proposed moves so a future session can pick this up without re-deriving
the analysis.
**Premise:** the project is called *"Jira **And Logs** Research Lab"*,
but the trained pipelines today use logs as a coarse second-class
input behind metrics and traces. This doc captures the honest gap and
three concrete moves to fix it.

---

## 1. The honest diagnosis

### What's actually happening with logs today

| Pipeline | What it reads | Is it really using logs? |
| --- | --- | --- |
| `loganalyzer_hybrid_bm25` | `triage_evidence_text` (~2 KB derived summary per window) | **No.** evidence_text is *trace-heavy, log-light* — most lines are `TRACES total_spans=…` and `root=grpc.…`. The L1/L2 log content is aggregated into a couple of lines, not the actual messages. |
| `logsense_hybrid_bm25` | Raw `raw/loki/*.json` files via Drain-lite template mining | **Yes — and it's the only one.** PR-AUC 0.49 on v5-quick. Drain overfits to scenario-specific tokens (timestamps, IDs, specific error codes that only appear in one fault), so it memorizes templates rather than learning generalizable patterns. |
| `memorygraph` / `memorygraph_hybrid` / `memorygraph_full` | `evidence_text` + numeric features | **No.** I never opened a `raw/loki/` file when building this. |
| `hgb`, `rf`, `logistic_sklearn`, `bi_encoder_hybrid`, `nomic_*` | Numeric features and/or `evidence_text` | **No.** |

Of 13 pipelines, one consumes raw logs, and it's the weakest scoring
one.

### Why this happened (no excuses)

1. **The derived dataset was built trace-first.** `evidence_text_from_raw`
   surfaces trace + RED summaries; log lines were added later and capped
   to avoid blowing up evidence_text size. Pipelines that "read logs"
   via evidence_text are mostly reading trace aggregates.
2. **Drain template mining is a 2016-era technique** that struggles on
   lab-style datasets where the same scenario emits the same templates
   every run. The model can't tell whether it learned "this template =
   ticket-worthy" because of real signal or because it memorized the
   training scenario.
3. **38.75M log lines is intimidating**, so the easy path is to
   pre-aggregate into counts (`log_error_count`, `log_warning_count`).
   Those counts are in the numeric features today — but a count of 12
   errors doesn't tell you *which* 12 or *what they said*.
4. **Memorygraph followed the existing wiring.** The Skill protocol
   reads `evidence_text` because that's what `TriageWindow` exposes.
   We never asked "what's in `raw/loki/`?".

### Why logs would specifically help retrieval (not just classification)

The memorygraph thesis is **bridge observability context → Jira
context** through shared entities. Right now we bridge via a watered-
down source-side query (trace summaries). Logs are the highest-signal
source we're ignoring because:

- Jira tickets are written by humans **after they read the logs**.
  Descriptions contain phrases like *"Redis connection refused on
  cart-redis:6379"*, *"DeadlineExceeded calling paymentservice from
  checkoutservice"*, *"productcatalogservice returned 503 on
  /listProducts"*. These are paraphrases of actual log lines.
- Trace summaries in evidence_text contain
  `root=grpc.hipstershop.CartService/AddItem count=141 errors=12` —
  the *fact* of failure with none of the *language* the Jira ticket
  mirrors.
- BM25 and dense retrieval work much better when source-side query
  and destination-side documents share vocabulary. Logs share
  vocabulary with Jira; trace summaries don't.

So the source-side query in every retrieval-based pipeline is using
the wrong words today.

---

## 2. Proposed moves (in priority order)

### Move A — Characteristic log line extractor (high leverage, ~half day)

For each window, find the K log lines that are **rare** relative to
that service's `pre_fault_baseline` windows. Roughly:

1. Build a baseline TF-IDF vector per service over all pre-fault
   baseline windows for that service.
2. For each `active_fault` / `recovery_window`, score every log line
   against the baseline; lines with high TF-IDF lift are
   "characteristic" of the fault.
3. Keep the top-K (start with K=20) as a new derived field
   `triage_log_signature`: an ordered list of the most
   fault-distinctive log messages, with their L2 structured fields
   (`dep`, `op`, `err_class`, `peer_service`, `retry_attempt`)
   preserved.

Then use it everywhere:

- **As retrieval text** in `lexical_similarity` and
  `embedding_similarity` skills — query against Jira `memory_text` +
  `resolution_notes` using words humans actually wrote about similar
  incidents.
- **As entity source** in `extract_obs_entities` — error_class
  entities come from real log content (broader vocabulary than the
  current 10-bucket regex), not regex over evidence_text. Dependency
  hints (`peer_service` field from L2 logs) become first-class graph
  entities.
- **As explanation evidence** — `graph_traverse_explain` can show the
  3 specific log lines that drove the match, not just "shared
  component=cartservice".

Expected impact: meaningful Recall@5 / MRR lift on retrieval-heavy
pipelines (`memorygraph_*`, `nomic_retrieval`); modest triage PR-AUC
lift (numeric still dominates there); big improvement on explanation
quality — explanations will quote the actual smoking-gun log lines.

### Move B — Log-based service-dependency edges in the graph (medium leverage, ~half day)

Right now memorygraph's graph has `service` and `component` entity
nodes but no `service → calls → service` edges. L2 logs explicitly
say `{dep: "redis", op: "GET", err_class: "ConnectTimeoutException",
peer_service: "cartservice"}`. That is a labeled directed edge
waiting to be added.

Plan:

1. Mine L2 lines for `(caller, callee, err_class)` triples per window.
2. Add edges to the graph: `service:cartservice --calls--> service:redis-cart`
   weighted by frequency, with `err_class` as an attribute.
3. New skill `graph_traverse_dependency_chain` — for an active fault
   on `checkoutservice`, traverse `calls` edges to find which
   downstream service most likely caused it; explanations list the
   suspected chain.

This is the actual mechanism on-call engineers use: *"the call chain
says we're stuck on Redis, look there first."*

### Move C — Lab-leakage guard for log content (mandatory prerequisite to A and B)

Hard part. Lab logs contain scenario-revealing tokens. Before any log
content flows into a model input, we need a stripper similar to the
Jira lab-leakage stripper that already lives in
`src/memorygraph/entities.py`. Drop:

- Anything matching `scenario-*`, `dataset-*`, `chaos-*` substrings
- Pod-name suffixes that encode the run id (e.g.
  `cartservice-5cb7b6d8d-xz9pq` is fine; `cartservice-v5quick-r03-…`
  is leaking)
- Loadgenerator-specific messages (deterministically structured —
  not what real prod emits, would let the model identify lab traffic)
- Any string from `scripts/research-lab/triage_labels.py`
  `_SCENARIO_FAMILIES` / `_SCENARIO_IDS` taxonomy
- chaos-mesh controller messages naming the fault

Then validate with the **existing leakage canary
(`validate_run_feature_distribution.py`)** — if any feature derived
from logs perfectly correlates with `scenario_id` / `scenario_family`
/ `triage_label`, the stripper is incomplete.

Also extend the canary itself per `todo-v5available.md` §3.1:
currently it only checks numeric columns; it doesn't catch substring
leaks in text fields. With raw log content flowing into features,
this gap becomes a real risk and needs closing first.

---

## 3. What *not* to do (calibrated tradeoffs)

Tempting log-related directions we should explicitly skip for now:

- **Train a deep model directly on raw log token sequences.** 38.75M
  lines + a small labeled set (6,720 windows, ~1,400 ticket-worthy)
  is a recipe for overfitting. Defer until D6 brings cross-app data
  (Sock Shop / TrainTicket) so a single corpus doesn't dominate
  pretraining.
- **Build a custom log parser to replace Drain-lite.** Drain is fine
  — the problem isn't the parser, it's that template counts are too
  coarse and too lab-overfittable. The fix is *using log content
  directly* (Move A), not parsing better.
- **Index every log line into Elasticsearch / a search engine.** We'd
  index 38.75M lines so the model can query ~6,720 times. Move A
  gives us the same end state with 1000× less storage and no extra
  infra.
- **Add raw log content to `triage_evidence_text` wholesale.** Risks
  blowing past Parquet column-size limits, lab-leakage explosion, and
  embedding cost. The characteristic-line extractor is the right
  granularity.

---

## 4. Sequencing + expected impact

| Step | Effort | Expected metric impact | Required for |
| --- | --- | --- | --- |
| C — text-field leakage canary | 0.5 day | none on its own | A and B (safety prerequisite) |
| A — characteristic log line extractor | 0.5–1 day | retrieval Recall@5 / MRR lift; explanations quote smoking-gun lines | next memorygraph release |
| B — log-based dependency edges | 0.5–1 day | better explanations + small PR-AUC lift on dependency-failure family | follows A |

Combined: **1.5–2.5 days** to put logs at the center of the
memorygraph retrieval and explanation pipeline.

---

## 5. Open questions / things to confirm before building

1. **Does `evidence_text` already include some L1/L2 log content?** Per
   `todo-v5available.md` §3.5 it has structured L1/L2 lines plus
   TRACES summary — but capped. Run an audit: dump the L1/L2 line
   count and avg-words for a sample of windows. Tells us *how much*
   uplift is possible.
2. **What's the average raw-loki size per active_fault window?** Need to
   size the extractor's per-window read budget. From the v5-large
   metadata: avg ~5,000 lines per per-window per-service dump. That's
   fine for a streaming top-K TF-IDF scorer; not fine if we tried to
   embed every line.
3. **Are L2 logs actually populated for the v5-large families that
   matter?** Per `todo-v5available.md` §3.2, Node / Python / Java
   services don't emit per-service RED metrics. Need to confirm L2
   `dep_error` lines are present in their `raw/loki/` files even if
   the metrics aren't. If not, Move B (dependency edges) only works
   for cartservice + checkoutservice + frontend.
4. **Will the leakage canary need a tokenizer?** For substring leak
   detection in text fields, a naive `in` check is O(N×M); we may need
   a faster index. Investigate before extending the canary.

---

## 6. Where this fits in the existing roadmap

| Doc | What it owns | Relationship |
| --- | --- | --- |
| `todo.md` | The 4-phase ML/AI roadmap (Phase 0–8) | This doc proposes work that extends Phase 4 (Hybrid retrieval-augmented triage) with log content. |
| `todo-v5available.md` | Workflow when v5-large lands; open bugs | §3.1 (text-field leakage canary) and §3.5 (L3 in evidence_text) overlap directly with Moves A and C here. |
| `src/memorygraph/EXPERIMENTS.md` | What was tried, what worked on v5-quick | Once Moves A/B/C ship, EXPERIMENTS.md gets new entries (E5, E6) with the headline numbers. |
| `src/memorygraph/README.md` | Architecture, skill catalog | When Move A lands, add `log_signature_extract` + (Move B) `graph_traverse_dependency_chain` to the skill list. |
| `docs/triage-task-contract.md` | Field policy | Add `triage_log_signature` as an allowed input; reaffirm the lab-leak strip rules apply to log text. |

---

## 7. Suggested first PR if we pick this up

A single, narrowly-scoped change:

1. `scripts/research-lab/extract_log_signatures.py` — new derivation
   step, runs per-run, writes `derived/<run>/log_signatures.jsonl`
   with one row per (window_id, service_name, top_k_lines,
   structured_fields).
2. `scripts/research-lab/triage_labels.py` — adds
   `triage_log_signature` to the feature column catalog (text
   column, not numeric).
3. `scripts/research-lab/build_global_triage_dataset.py` — joins the
   new field into `global-triage-examples.jsonl`.
4. `scripts/research-lab/validate_run_feature_distribution.py` —
   extends leakage canary with substring-in-text checks for
   `scenario-*` / `dataset-*` / `chaos-*` tokens.
5. `src/memorygraph/skills.py` — new `LogSignatureSimilaritySkill`
   that queries Jira memory using `triage_log_signature` text;
   wire into `memorygraph_full` chain after `lexical_similarity`.

Re-run `memorygraph_full` on v5-large, compare Recall@5 / MRR +
classification metrics + explanation samples vs the current
v5-large baseline. Record numbers in
`src/memorygraph/EXPERIMENTS.md` as E5.

That's the smallest atomic PR that delivers a real "logs are now a
first-class signal" change.
