# ML-NEW-IDEAS.md — using raw logs as a first-class signal

**Captured:** 2026-05-28 (after v5-large validation passed).
**Last updated:** 2026-05-30 (Move C shipped; new E5 evidence makes
Move A much more compelling — see Progress log below).
**Status:** Move C **DONE** (commit `b704cb8`). Move A + Move B still
open. The recent jira_humanizer + cross-train work (E5, commits
`5ef4f1a`/`da949df`/`4464df2`/`d041ebb`/`e40a400`) sharpened the
case for Move A: BM25 retrieval on a clean memory corpus drops to
Recall@5 = 0.07. We need a richer source-side query, and logs are
the obvious lever.
**Premise:** the project is called *"Jira **And Logs** Research Lab"*,
but the trained pipelines today use logs as a coarse second-class
input behind metrics and traces. This doc captures the honest gap and
three concrete moves to fix it.

---

## Progress log

| When | What | Where |
| --- | --- | --- |
| 2026-05-28 | Doc captured. Diagnosed the gap, proposed Moves A/B/C, agreed sequencing. | this doc |
| 2026-05-29 | **Move C shipped** as `scripts/research-lab/validate_text_field_leakage.py`. Reuses the sanitizer's banned-token catalog, adds window-type strings + trace_id/span_id regexes, two-tier verdict, baseline-only legacy scope. v5-large run: triage_evidence_text PASS (0 hits / 6,720 windows); humanized_timeline_step_text PASS (0 hits / 1,502 LLM outputs); legacy_jira_memory_text FAIL (100% on 9 hard-banned tokens, 4% on each fault-scenario name, 622,793 trace_id substrings) — informational baseline. | commit `b704cb8` |
| 2026-05-30 | **E5 cross-train** on v5-large with the leak-stripped humanized corpus confirmed BM25 retrieval was riding on lab leakage: Recall@5 0.20 (legacy) → 0.07 (humanized), MRR 0.25 → 0.10, both p<0.001. Triage classification was mostly real (PR-AUC −0.054). Net read: **the legacy retrieval lift wasn't real; the humanized corpus is the honest baseline**; we need a non-trivial source-side query (Move A) to recover meaningful Recall@5. | commit `e40a400`, EXPERIMENTS.md §E5 |
| In flight | E6: dense Nomic embeddings on humanized corpus — does dense similarity rescue what BM25 lost? Results pending. | task `b8patnyeq` |
| TODO | **Move A** (characteristic log line extractor). After E5 this is no longer just "make retrieval better" — it's "make retrieval *work at all* on the clean corpus." Top priority once E6 lands. | this doc §2 |
| TODO | **Move B** (log-based service-dependency edges) — follows A. | this doc §2 |

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

Expected impact (revised 2026-05-30 in light of E5):
- **Before E5**: meaningful Recall@5 / MRR lift; modest triage PR-AUC
  lift.
- **After E5**: on the humanized corpus, Recall@5 with BM25 on
  trace-aggregate evidence_text is **0.07** — chance level. Move A is
  the natural next experiment to unlock retrieval at all. Realistic
  target on humanized: Recall@5 back to 0.15–0.20 (matching what
  legacy BM25 got with lab vocabulary, but achieved honestly).
- Explanation quality lift is unchanged from the original
  hypothesis: graph_traverse_explain will quote the smoking-gun log
  lines instead of generic component matches.

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

### Move C — Lab-leakage guard for log content [DONE 2026-05-29 — commit b704cb8]

Shipped as `scripts/research-lab/validate_text_field_leakage.py`.
Reuses the sanitizer's banned-token catalog
(`src/jira_humanizer/sanitizer.py`) and extends it with:

- Window-type strings (`active_fault`, `pre_fault_baseline`,
  `recovery_window`, `observation_window`) — lab-only by design.
- Per-request id regexes — trace_id (32-hex), span_id (16-hex).

Two-tier verdict:
- Hard-ban tokens (taxonomy, window types, trace IDs) → fail on >0
  occurrences. Zero tolerance.
- Soft-ban words (`fault`, `injected`, `lab`, …) → warn on any
  occurrence, fail when rate > --threshold (default 1% of units).

The text-stripper for raw log content sketched here (`scenario-*` /
`dataset-*` substring strips, pod-name redaction, loadgenerator-msg
suppression) is **not yet shipped** because Move A is what needs it,
and Move A hasn't started. **When Move A ships, the log signature
extractor MUST run every candidate line through the same sanitizer
catalog before persisting it** — otherwise we'd be re-creating the
exact leakage problem the humanizer fixed for Jira text. The canary
will catch it if we forget; let's not need it to.

v5-large canary results on launch (commit `b704cb8`):
- `triage_evidence_text` (6,720 windows): PASS, 0 hits
- `humanized_timeline_step_text` (1,502 LLM steps): PASS, 0 hits
- `legacy_jira_memory_text` (347 tickets): FAIL `[baseline]` — 100%
  contamination across 9 hard-banned tokens; 4% on each of 24
  fault-scenario names; 622,793 trace_id substrings across the
  comments fields. Informational only — quantifies what the
  humanizer fixed.

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

## 4. Sequencing + expected impact (revised 2026-05-30)

| Step | Status | Effort | Expected metric impact | Required for |
| --- | --- | ---: | --- | --- |
| C — text-field leakage canary | **DONE** (`b704cb8`) | shipped | safety prereq for A | A and B |
| A — characteristic log line extractor | **NEXT** | 0.5–1 day | retrieval Recall@5 0.07 → ~0.15–0.20 on humanized corpus (recovers what was lost to leakage stripping); explanations quote smoking-gun lines | next memorygraph release |
| B — log-based dependency edges | open | 0.5–1 day | better explanations + small PR-AUC lift on dependency-failure family | follows A |

Combined remaining: **1–2 days** to put logs at the center of the
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
| `todo-v5available.md` | Workflow when v5-large lands; open bugs | §3.1 (text-field leakage canary) **closed by Move C, commit `b704cb8`**. §3.5 (L3 in evidence_text) overlaps with the log-source-side query in Move A. |
| `LLM-Jira-enhancement.md` | Humanized Jira corpus design + bulk regenerator | Rule 4 of that doc ("Quote, don't summarize") references Move A's characteristic-line extractor as a hard prerequisite for production-grade ticket evidence quoting. The Phase 2 generator currently uses a placeholder line-picker; Move A replaces it. |
| `src/memorygraph/EXPERIMENTS.md` | Experiment log | Move C → noted in M5/E5 context. When Move A lands, becomes **E7** (next free slot after E5 cross-train BM25 and E6 cross-train Nomic). |
| `src/memorygraph/README.md` | Architecture, skill catalog | When Move A lands, add `log_signature_extract` + (Move B) `graph_traverse_dependency_chain` to the skill list. |
| `docs/triage-task-contract.md` | Field policy | Add `triage_log_signature` as an allowed input; reaffirm the lab-leak strip rules apply to log text. |

---

## 7. Suggested first PR if we pick this up (revised 2026-05-30)

A single, narrowly-scoped change. Note: step 4 below was originally
"extend the canary" — that's already shipped (`b704cb8`), so the
extractor just needs to honor the existing catalog.

1. `scripts/research-lab/extract_log_signatures.py` — new derivation
   step, runs per-run, writes `derived/<run>/log_signatures.jsonl`
   with one row per (window_id, service_name, top_k_lines,
   structured_fields). **Every persisted line passes through
   `jira_humanizer.sanitizer.find_lab_tokens` first; lines with any
   lab token are dropped silently.** No reason to invent a second
   stripper now that the catalog is shared.
2. `scripts/research-lab/triage_labels.py` — adds
   `triage_log_signature` to the feature column catalog (text
   column, not numeric).
3. `scripts/research-lab/build_global_triage_dataset.py` — joins the
   new field into `global-triage-examples.jsonl`.
4. ~~Extend the leakage canary~~ — already shipped as
   `validate_text_field_leakage.py` (`b704cb8`). The new
   `triage_log_signature` field becomes a fourth scope to scan; the
   single-line addition is in the canary's `scopes` dict at the top
   of `main()`.
5. `src/memorygraph/skills.py` — new `LogSignatureSimilaritySkill`
   that queries Jira memory using `triage_log_signature` text;
   wire into `memorygraph_full` chain after `lexical_similarity`.
6. Replace the placeholder `_pick_characteristic_lines` in
   `src/jira_humanizer/timeline_generator.py` with the real extractor
   from step 1 so the humanizer's "quote, don't summarize" rule
   (LLM-Jira-enhancement.md §3 Rule 4) is honored end-to-end.

Re-run `memorygraph_full_humanized` on v5-large, compare Recall@5 /
MRR + classification metrics + explanation samples vs the current
E5/E6 humanized baseline. Record numbers in
`src/memorygraph/EXPERIMENTS.md` as **E7**.

That's the smallest atomic PR that delivers a real "logs are now a
first-class signal" change.

---

## 8. Why Move A is the right next move, in one paragraph

E5 cross-train on v5-large just proved that BM25 on the
sanitizer-verified humanized Jira memory text retrieves at chance
levels (Recall@5 = 0.07, MRR = 0.10). E6 will tell us whether dense
Nomic embeddings help. Either way, the **source-side query** that
gets sent into retrieval is the trace-aggregate `evidence_text`,
which is the wrong vocabulary for matching Jira tickets that humans
write in log-derived language. Move A fixes the source side by
extracting K characteristic log lines per window and using them as
the retrieval query. That's the single change most likely to unlock
real Recall@5 on the clean corpus and to make graph_traverse_explain
quote the actual smoking-gun lines instead of generic component
matches.
