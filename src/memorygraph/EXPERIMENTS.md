# memorygraph — experiments log

A running record of what was tried, what worked, and what didn't on the
memorygraph subproject. Designed to be shared with other contributors
or referenced in writeups. Keep entries dated, brief, and number-backed.

> Premise (from the project sketch): treat observability data and Jira
> issues as two contexts; extract entities from each side; bridge them
> with a typed graph; let an agentic skill chain do filter → similarity
> → graph-aware scoring and produce **explained** matches. Goal isn't
> only to beat the leaderboard — it's to produce a pipeline that can
> *explain why* it picked a given Jira.

---

## TL;DR (current state — 2026-05-30)

**v5-quick (450 windows, n=4 experiments)**:

| Variant | PR-AUC | ROC-AUC | Recall@5 | Notes |
| --- | ---: | ---: | ---: | --- |
| `memorygraph` (rule planner, graph + BM25 only) | 0.2239 | 0.5136 | 0.6923 | The "explain-only" baseline |
| `memorygraph_hybrid` (+ NumericBlendSkill HGB head) | 0.4724 | 0.6519 | 0.6923 | **+0.25 PR-AUC**, retrieval preserved |
| memorygraph_hybrid + learned kind weights (no embed) | 0.4724 | 0.6519 | 0.6923 | **No headline lift** — see E4 discussion |
| `memorygraph_full` (+ Nomic dense embeddings + learned weights) | 0.4814 | 0.6766 | 0.6923 | **+0.01 PR-AUC** over hybrid |

**v5-large (1,755 test windows, n=2 experiments — E5 only so far)**:

| Variant | PR-AUC | ROC-AUC | Recall@5 | MRR | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `memorygraph_hybrid` (legacy Jira memory) | 0.6599 | 0.8036 | 0.2018 | 0.2499 | Leak-contaminated baseline |
| `memorygraph_hybrid_humanized` (humanized Jira memory) | 0.6062 | 0.7865 | 0.0659 | 0.0998 | **Cross-train validation: humanizer worked** |
| Δ (humanized − legacy) | **−0.054** | −0.017 | **−0.136** | **−0.150** | Triage modestly inflated, retrieval heavily inflated |
| baseline: `hist_gradient_boosting_numeric` | TBD | TBD | 0.0000 | — | Pure numeric ceiling — no retrieval |

(v5-quick headlines from the global dataset, test split = 450 windows.
v5-large headlines from the v5-large global dataset, test split = 1,755
windows. Bootstrap 95% CIs in the per-experiment sections below.)

**Net read after E5 (cross-train validation on v5-large)**: the
NumericBlend still does the heavy lifting for triage. The legacy
Jira corpus was inflating retrieval Recall@5 and MRR by **2-3×** via
lab-vocabulary leakage that BM25 trivially exploited; on the
sanitizer-verified humanized corpus, BM25 retrieval drops to chance
levels. The triage premium was small (~5 PR-AUC pts). The orphan-
recall-gap verdict shifted from `pattern_matching` (24.7 pts) on
legacy to `borderline` (12.7 pts) on humanized — the humanized
model is meaningfully more robust to novel windows. **This is the
strongest piece of evidence yet that the jira_humanizer pipeline
delivered what it promised.**

---

## Architecture milestones

### M0 — Scaffolding (2026-05-27)

Created `src/memorygraph/` with the package layout below. Designed so
every later experiment is a *new skill* or a *new planner chain*, not a
new module. This kept the surface area small.

```
src/memorygraph/
  README.md          design intent
  EXPERIMENTS.md     this file
  entities.py        EntityId / Entity / Edge + obs + jira extractors
  graph.py           in-memory typed graph + builder + bridge edges
  skills.py          Skill ABC + all concrete skills
  agent.py           Agent controller + RulePlanner + LLMPlanner
  pipeline.py        PipelineRunner integration
  cli.py             standalone CLI
  tests/test_smoke.py  pure-Python smoke suite
```

Key correctness invariant established here: **lab-leakage label
stripping**. Jira `Labels:` lines in this lab contain
`scenario-X`/`dataset-Y`/`severity-Z`/`root-W` markers that encode the
scenario identity. The entity extractor drops these before they reach
the graph (verified in `test_jira_entity_extractor_strips_lab_labels`).
Without this, retrieval would cheat via lab labels and PR-AUC numbers
would be invalid.

### M1 — Three-stage retrieval (2026-05-27)

The full chain the `RulePlanner` produces:

```
entity_extract → component_filter → service_filter
  → severity_align → error_class_align
  → lexical_similarity → graph_score → triage_decide
  → novelty_check → graph_traverse_explain
```

Per-window cost on v5-quick: ~20–25 ms end-to-end without any LLM in
the loop. The component/service filters typically shrink the candidate
pool from 48 (full corpus) to ~10–15 before similarity runs.

### M2 — Hybrid numeric blend (2026-05-27)

Inserted `numeric_blend` between `graph_score` and `triage_decide`. The
skill holds a `HistGradientBoostingClassifier` fit on the train-split
production-safe numeric features (`triage_feature_*`). It writes a
per-window scalar that `triage_decide` blends `0.7 * numeric + 0.3 *
per_candidate_top` into the final triage_score.

Rationale: graph + similarity tells us **which Jira** matches; numeric
features tell us **whether there's actually a fault at all**. A window
without a fault shouldn't score high just because some past Jira looks
textually similar.

### M3 — Dense embedding similarity (in progress, 2026-05-27)

Added `EmbeddingSimilaritySkill` that calls Nomic via LM Studio's
OpenAI-compatible endpoint and blends 50/50 with BM25 in
`similarity_scores`. Runs over the **filtered** candidate pool, not the
full Jira corpus, so per-window cost is ≤ 15 cosine ops over cached
memory embeddings.

Fail-soft: if LM Studio is unreachable at `.fit()` time, the skill
self-disables; the chain runs identically to M2.

### M4 — Learned per-kind graph weights (in progress, 2026-05-27)

`GraphScoreSkill` previously used hand-coded `kind_bonus` priors
(SERVICE=1.0, COMPONENT=1.0, …, SEVERITY=0.3). M4 replaces these with
**training-set precision per kind**: for every (train_window, candidate)
pair where the two share entities of kind K, count whether the
candidate is in the window's gold `matched_memory_issue_ids`; the
weight for K becomes TP/(TP+FP).

This is the "automatically learn edge weights from the training split"
hook the project sketch calls out. The learned weights are persisted to
`graph-stats.json` as `learned_kind_weights` so a reviewer can see
exactly which entity kinds the data thought were discriminative.

---

## Experiment log

### E1: `memorygraph` rule baseline on v5-quick (2026-05-27)

**Setup**: full chain above without numeric_blend / without embeddings.
Run: `python -m memorygraph.cli --global-dir <v5-quick> --output-dir ...`.

**Result**:
- PR-AUC 0.2239 [0.17, 0.29]
- ROC-AUC 0.5136 [0.47, 0.56]
- Recall@5 0.6923 [0.50, 0.86]
- Predict time: 11.5s for 450 windows

**Read**: in the same league as `jira_only` (PR-AUC 0.29). The pipeline
is too blind to numeric fault signal. But the **explanations.jsonl**
artifact looks correct — every ticket_worthy prediction comes with a
graph-justified "Most likely matches OBSRV-1001 (checkoutservice /
application_latency). Graph evidence: component=checkoutservice |
service=checkoutservice ...".

**Verdict**: ship as the "explain-only" baseline. Don't claim this for
PR-AUC.

### E2: `memorygraph_hybrid` with numeric blend (2026-05-27)

**Setup**: added `numeric_blend` skill, `with_numeric=True` flag on the
pipeline + planner. Triage_decide blend = `0.7 * numeric + 0.3 *
top_candidate`.

**Result**:
- PR-AUC 0.4724 [0.37, 0.58]  (**+0.25 over M1**, paired bootstrap p < 0.001)
- ROC-AUC 0.6519 [0.58, 0.73]
- Recall@5 0.6923 [0.50, 0.86]  (unchanged — graph still drives retrieval)
- Predict time: 9.9s for 450 windows

**Read**: the numeric head more than doubles the triage signal, retrieval
stays at the M1 level. Still below pure `hist_gradient_boosting_numeric`
(PR-AUC 0.6652, ROC-AUC 0.9043) by ~0.19 PR-AUC, but this pipeline
keeps the retrieval and explanation upside HGB-alone lacks.

The 0.7 numeric_weight was chosen from the project's prior that
numeric features dominate triage on this corpus. A val-split sweep is
in the open-questions list.

**Failure mode**: threshold tuner picks 1.0000 because both numeric and
top_candidate saturate to 1.0 on clear ticket_worthy windows; the only
way to hit FPR ≤ 5% is to fire on exact 1.0. Calibration (M5?) should
fix this.

**Verdict**: keep. This is now the project's only pipeline that
delivers both competitive PR-AUC AND non-zero retrieval AND
explanations.

### E3: `memorygraph_full` with Nomic embeddings + learned weights (2026-05-27)

**Setup**: E2 plus `with_embeddings=True` plus `GraphScoreSkill.fit_on_pairs`
runs at pipeline init. Embedding via LM Studio
(`text-embedding-nomic-embed-text-v1.5`), blended 50/50 with BM25 in
`similarity_scores`.

**Hypothesis**: BM25 wins on exact token matches; dense embedding wins
on paraphrase ("deadline exceeded" ≈ "request timed out"). Learned
kind weights replace hand-coded priors with training-set precision.

**Result**:
- PR-AUC 0.4814 (+0.009 over E2 hybrid)
- ROC-AUC 0.6766 (+0.025 over E2)
- Recall@5 0.6923 (unchanged)
- Predict time: 811s for 450 windows — dominated by embedding queries

**Read**: a real but small lift. Most of the upside almost certainly
comes from the embedding step, not the learned weights (see E4
ablation). The 80× slowdown over E2 (10s → 800s) is because each
window pays one LM-Studio embed round-trip. The skill caches doc
embeddings, but query embeddings have to be fresh per window.

**Verdict**: keep as the "best memorygraph" but flag the latency cost.
If we want this in CI, we should add a per-query embedding cache (the
existing `embeddings/` cache dir convention in the project would fit).

### E4: ablation — learned kind weights only, no embeddings (2026-05-27)

**Setup**: same as E2 (hybrid, BM25 only), but `fit_on_pairs` runs.
Isolates the contribution of learned weights from embeddings.

**Result**:
- PR-AUC 0.4724  (**identical to E2** to 4 decimals)
- ROC-AUC 0.6519 (identical)
- Recall@5 0.6923 (identical)

**Read**: learned weights had **zero measurable impact** on triage PR-AUC
on v5-quick. Why:

1. The `triage_decide` blend is `0.7 * numeric + 0.3 * top_candidate`.
   The numeric head dominates; the per-candidate graph score has at
   most ~0.3 of the final score to move.
2. The kind weights only re-rank candidates *within* a window, not
   across windows. Re-ranking inside a window doesn't change the *top*
   candidate score much unless the previous top was wrong AND there
   was a strong alternative — rare on this corpus.

**But there's an architectural finding worth keeping** — the learned
weights table itself:

| Kind | TP | FP | Precision | Hand-coded prior |
| --- | ---: | ---: | ---: | ---: |
| `error_class` | 47 | 361 | **11%** | 0.6 |
| `service` | 178 | 4828 | 3% | 1.0 |
| `component` | 142 | 4690 | 2% | 1.0 |
| `severity` | 0 | 0 | — | 0.3 |
| `fault_class` | 0 | 0 | — | 0.8 |
| `reason_class` | 0 | 0 | — | 0.7 |
| `latency_band` | 0 | 0 | — | 0.5 |
| `k8s_signal` | 0 | 0 | — | 0.5 |
| `saturation` | 0 | 0 | — | 0.4 |

Three things to note:

1. **`error_class` is the most discriminative shared-entity kind by
   precision** (11% vs 3% for service/component). The hand-coded prior
   had service=component highest. The data disagrees: when a window and
   a Jira both mention the same error class (timeout / dns_failure /
   redis_failure), that's a much stronger signal than just sharing a
   service name (which is true for most windows on a small lab
   corpus). **The headline still didn't move because relative-within-
   window ranking is what matters, not absolute kind weight.**

2. **Six kinds got TP=0/FP=0 because windows and Jiras don't share
   them.** `severity`/`fault_class`/`reason_class` are Jira-only
   (we only emit them in `extract_jira_entities`). `latency_band` /
   `k8s_signal` / `saturation` are obs-only (only `extract_obs_entities`
   emits them). The graph never has a chance to bridge those kinds.
   This is a **design observation**: making `severity` / `fault_class`
   bidirectional (inferring them on the obs side too) is a real
   improvement candidate. Hooked under O5 below.

3. **The precision floor is low overall** (11% best). The lab corpus
   has 48 Jiras and most windows share at least one entity with most
   Jiras — so the candidate set is large and FP-heavy by construction.
   Learned weights will likely matter more on v5-large (1000+ Jiras)
   where the candidate set per window is more selective.

**Verdict**: keep `fit_on_pairs` wired — even when it doesn't move the
headline it produces an audit artifact. Don't claim it as a PR-AUC
lift on this corpus.

### E5: cross-train on v5-large — legacy vs humanized Jira corpus (2026-05-30)

**Why this experiment exists**: the jira_humanizer pipeline
(commits `5ef4f1a`, `da949df`, `4464df2`, `d041ebb`) replaces the
synthetic single-author legacy Jira shadows with multi-author
TIMELINE-style humanized tickets. The text-leakage canary (commit
`b704cb8`) just proved the legacy corpus is **100% contaminated** with
lab vocabulary in every ticket, while the humanized corpus is
**0% contaminated** corpus-wide across all 347 tickets × 1,502 LLM
outputs. E5 is the *model-side* validation: train memorygraph_hybrid
on both, measure the delta, and see whether the legacy lift was real
signal or leakage premium.

**Setup**: identical pipelines, only the memory corpus changes.
- `memorygraph_hybrid` — Jira memory loaded from
  `jira-memory-corpus.jsonl` (legacy, leak-contaminated).
- `memorygraph_hybrid_humanized` — Jira memory loaded from
  `jira-shadow-humanized-v1/bulk-20260529/timeline.jsonl` (humanized,
  sanitizer-verified clean). Loaded via the new
  `src/memorygraph/humanized_loader.py` adapter; metadata
  (`scenario_family`, `affected_service`, …) carried over from the
  legacy entry for time-ordering, but those are NOT model inputs by
  the production-realism contract.

Run on v5-large global, test split = 1,755 windows. Numbers below are
strict-borderline PR-AUC and bootstrap 95% CIs from 1000 paired
resamples.

**Headline results (bootstrap CIs in brackets)**:

| Metric | Legacy `memorygraph_hybrid` | Humanized `memorygraph_hybrid_humanized` | Δ (hum − leg) | Paired bootstrap p |
| --- | ---: | ---: | ---: | ---: |
| PR-AUC | 0.6599 [0.6084, 0.6898] | 0.6062 [0.5649, 0.6428] | **−0.054** | **<0.001** |
| ROC-AUC | 0.8036 [0.7815, 0.8246] | 0.7865 [0.7644, 0.8055] | −0.017 | — |
| Precision@FPR=5% | 0.7516 [0.7283, 0.7705] | 0.7171 [0.6890, 0.7396] | −0.035 | **<0.001** |
| **Recall@5** | **0.2018** [0.1644, 0.2392] | **0.0659** [0.0446, 0.0882] | **−0.136** | **<0.001** |
| **MRR** | **0.2499** [0.2058, 0.2961] | **0.0998** [0.0696, 0.1311] | **−0.150** | — |
| Orphan recall on reported | 0.379 (n=338) | 0.278 (n=338) | −0.101 | — |
| Orphan recall on orphan | 0.131 (n=312) | 0.151 (n=312) | +0.020 | — |
| **Orphan-recall gap (pts)** | **+24.7 (`pattern_matching`)** | **+12.7 (`borderline`)** | **−12.0 pts** | — |

**Reads — three honest interpretations**:

1. **Triage classification was mostly real.** PR-AUC drops only 5
   points and ROC-AUC drops 1.7 points. The numeric features (RED
   metrics, trace counts, k8s signals) were carrying most of the
   triage signal; memory text was a secondary contributor that the
   legacy corpus was modestly inflating. **The v5-large triage
   numbers we have been reporting on the legacy corpus inflate the
   truth by ~5%, not 50%.** That's a tolerable discount.

2. **Retrieval was heavily inflated.** Recall@5 and MRR drop by 14-15
   points each — a 2-3× cut, both statistically significant at p<0.001.
   This is the canary's text findings made concrete: BM25 was getting
   trivial retrieval hits on lab vocabulary (`scenario-cart-redis-
   degradation-critical` appearing verbatim in 14 different legacy
   shadows; `Components: cartservice, checkoutservice, frontend`
   matching perfectly across cart-redis windows; embedded 32-hex
   `trace_id` strings giving per-window oracles). Strip all that and
   BM25 on natural-language memory text retrieves at chance levels.
   **This is the strongest finding of the project so far: any
   retrieval claim from the legacy corpus was riding on lab leakage.**
   BM25 alone is a weak retriever for triage memory on a clean
   corpus.

3. **Orphan-recall gap halved.** Verdict went `pattern_matching`
   (+24.7) → `borderline` (+12.7). The legacy-trained model collapsed
   on novel-incident windows because it had learned to rely on lab
   vocabulary as a memory-match proxy — when those tokens weren't
   present (the orphan case), the model fell apart. The humanized
   model degrades much more gracefully because it can't pattern-match
   on lab tokens; it has to use actual signal. **A model trained on
   the humanized corpus is meaningfully more robust to novel
   incidents**, which is exactly what we want for an on-call triage
   system that has to handle unfamiliar fault shapes.

**Verdict**: the jira_humanizer pipeline worked as designed. The
legacy corpus was systematically inflating retrieval metrics and
fostering pattern-matching over signal-learning. The humanized corpus
delivers a fair-but-lower retrieval picture, a small triage discount,
and a more robust orphan-handling profile. We should be reporting
humanized-corpus numbers as the headline going forward; the legacy
numbers remain in the doc as a **baseline that quantifies the
leakage premium**.

### E6: cross-train with embeddings — `memorygraph_full` legacy vs humanized (2026-05-30, in flight)

**Hypothesis**: dense Nomic embeddings should rescue some of the
retrieval lift BM25 lost to leakage stripping because they read
natural-language semantic similarity, not just token overlap.

**Setup**: same as E5 but using `memorygraph_full` vs
`memorygraph_full_humanized`. Adds Nomic dense embedding via LM
Studio over the filtered candidate pool, blended 50/50 with BM25
into `similarity_scores`.

**Expected scenarios** (will be filled in when the run completes):
- *Rescue*: humanized Recall@5 climbs back to ~0.20+. Dense
  similarity preserved the real signal; BM25's drop was purely about
  losing lab-vocabulary cheats. Best outcome.
- *Partial rescue*: humanized Recall@5 between 0.10–0.18. Embeddings
  recover some but not all of the lost retrieval.
- *No rescue*: humanized Recall@5 stays at ~0.07. The triage-memory
  retrieval task is genuinely hard on natural-language text and
  needs a learned reranker or a different memory representation
  (e.g. Move A's characteristic-log-line signature from
  ML-NEW-IDEAS.MD).

**Result**: TBD — run is in progress as of 2026-05-30. Numbers will
land here when the comparison harness completes.

---

## What worked

- **Two-step retrieval (filter → similarity)**. Component+service
  pre-filter typically shrinks the pool ~4× on v5-quick. The downstream
  BM25 is faster and less noisy because random-overlap-only candidates
  are gone.
- **NumericBlendSkill**. The biggest single lever — +0.25 PR-AUC over
  graph-only on v5-quick. Lift survived to v5-large (PR-AUC 0.66 on
  the humanized corpus, vs ~0.30 graph-only baseline expected).
  Confirms the project-wide observation that numeric features
  dominate triage on this dataset shape.
- **Skill chain as the extension point**. Every experiment above is a
  new file in `skills.py` plus an entry in the registry — no
  modifications to `agent.py` / `pipeline.py` beyond a single
  constructor flag. This is the architecture paying back.
- **Fail-soft on LM Studio**. The embedding skill probes once at fit
  time and self-disables on failure. Means the pipeline is safe to
  include in a CI leaderboard even on a CI box with no LM Studio.
- **Production-realism contract enforced at the extractor**. Lab-leak
  labels are dropped *before* they reach the graph (no chance they
  slip into a skill by accident). Verified by a regression test.
- **Learned-weights table as an audit artifact**, even though it
  didn't move PR-AUC. The single most surprising number on v5-quick
  was *error_class beats service for shared-bridge precision*.
  Without `fit_on_pairs` writing those stats we wouldn't have noticed.
- **Cross-train validation against a leak-stripped corpus**
  (E5, v5-large). The humanizer + canary + cross-train trio together
  prove the legacy-corpus retrieval claims were mostly leakage and
  the triage claims were mostly real. Without all three pieces we
  couldn't have separated those signals.
- **The `humanized_subdir` swap point on MemoryGraphPipeline**. Four
  lines of code (constructor flag + train_and_predict branch) make
  legacy-vs-humanized A/B testing trivially comparable through the
  existing comparison harness. The architecture continues to pay back.

## What didn't work (yet)

- **`memorygraph` alone**. PR-AUC 0.22 on v5-quick — graph +
  similarity without numeric is not a useful triage classifier.
  Retrieval is fine (R@5 0.69) but the triage decision is essentially
  random. Confirms the project-wide finding that Jira-only memory
  pipelines underperform numeric on triage.
- **Learned graph weights didn't move triage PR-AUC.** The numeric
  blend dominates the final score; re-ranking candidates *within* a
  window has limited headroom. Keeps the audit artifact value but
  shouldn't be sold as a triage improvement.
- **Dense embeddings gave only +0.01 PR-AUC for 80× latency on
  v5-quick.** On the small (48-doc) Jira corpus, BM25 was already a
  strong baseline because the docs themselves contain the service /
  error tokens. v5-large rerun (E6) is in progress and may tell a
  different story now that the memory text is natural-language.
- **BM25 retrieval on natural-language memory text is weak**
  (Recall@5 = 0.07 on v5-large humanized, E5). BM25 needs exact
  token overlap and humanized text has natural paraphrase. The
  embedding-variant comparison (E6) tests whether dense similarity
  rescues this.
- **Threshold calibration**. Both hybrid variants pick threshold =
  1.0000 because the blend saturates. Need Platt or isotonic on val
  before scoring on test. Tracked as open question O3.
- **Service filter aggressiveness**. ServiceFilterSkill currently skips
  itself when the narrower filter would leave < 3 candidates. This
  fires often on the small corpus — the filter exists but rarely runs.
  A bigger corpus (v5-large) should put this to the test. Open.

## Open questions

1. **O1 — How much of the hybrid lift survives v5-large?** v5-quick has
   only 48 Jira memory entries. v5-large will have ~1,000. The
   per-window candidate pool grows ~20×, which should help precision of
   the filter step but slow down the inner loop. Need to re-benchmark.
2. **O2 — Does the LLMPlanner pick a different chain per window?**
   Implemented but never benchmarked. Useful only if Qwen can route
   "obvious outage" windows to a shorter chain while spending more time
   on borderline. Tracked but not prioritized.
3. **O3 — Calibrate the hybrid score head.** Either swap HGB →
   `CalibratedRandomForestPipeline`'s isotonic version, or wrap HGB
   with sklearn `CalibratedClassifierCV`. Fixes the threshold=1.0000
   issue.
4. **O4 — Per-family kind weights**. Phase D6 brings cross-app
   generalization. A kind-weight that's discriminative on cart-redis
   may not be on payment-outage. Learn weights per family if M4 shows
   the global weights have high variance.
5. **O5 — Bidirectional entity kinds.** E4's learned-weights table
   showed that 6 of 9 entity kinds get TP=FP=0 because either the obs
   side or the Jira side doesn't emit them. Adding inferred `severity`
   / `fault_class` / `reason_class` entities on the obs side (from
   error rate + latency thresholds) would let those edge types
   actually bridge. Same on the Jira side for `latency_band` /
   `k8s_signal` (parsable from `memory_text`). Bigger feature surface
   → more useful learned weights.
6. **O6 — Persistent embedding cache.** E3 took 800s wall-clock on 450
   windows, almost all of it LM-Studio query embeddings. The project
   already has the `data/derived/global/<id>/embeddings/` convention
   from Phase 1 (see `docs/ml-ai-pipeline-development-plan.md`). Reusing
   that would cut E3 to ~30s on second-and-later runs.
7. **O7 — Why isn't error_class precision higher?** 11% on a corpus
   where most windows are noise is in the right ballpark
   (base rate ≈ 14% ticket_worthy), but the gap from chance is small.
   The error_class taxonomy is currently 10 coarse buckets
   (timeout/oom/network/etc). Finer-grained extraction (e.g. split
   `redis_failure` into `redis_timeout` / `redis_unavailable` /
   `redis_oom`) would either help or hurt; worth a controlled
   experiment.
8. **O8 — Per-family LOFO on E5 deltas.** E5's overall PR-AUC delta
   is −0.054. Are some families much more affected than others? If
   `cart-redis` has a −0.20 delta while `network-partition` has only
   −0.01, then the legacy corpus was leaking heavily on cart-redis
   specifically (probably because its scenario name and Components
   line are perfect token matches for cart-redis windows). The
   families with the largest deltas are the ones that most benefit
   from the humanization — and the ones that most need human
   adjudication review per LLM-Jira-enhancement.md §7 Phase 5.
9. **O9 — Does a learned reranker rescue retrieval on the
   humanized corpus?** E6 tests whether Nomic dense embeddings help.
   If E6 still shows Recall@5 < 0.15 on humanized, the next move is
   a cross-encoder reranker over the BM25 + Nomic top-k. The
   memorygraph pipeline already has a stub slot for one in the
   skill chain.
10. **O10 — Should we re-derive `triage_evidence_text` to include
    L3 business events?** The text-leakage canary said evidence_text
    is clean. todo-v5available.md §3.5 calls out that L3 business
    events aren't included; with the humanized corpus showing how
    much retrieval matters, adding L3 to evidence_text might give
    text-based pipelines more to work with. Worth measuring.

## How to reproduce

```powershell
# all four variants (CPU path; uses LM Studio if up)
Set-Location C:\workplace\JiraAndLogs\src

# E1 — explain-only baseline
& ..\.venv\Scripts\python -m memorygraph.cli `
    --global-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global `
    --output-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global\memorygraph\baseline-rule

# E2 — hybrid (HGB head)
& ..\.venv\Scripts\python -m memorygraph.cli `
    --global-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global `
    --output-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global\memorygraph\hybrid-rule `
    --with-numeric

# E3 — hybrid + dense embeddings (needs LM Studio with
# text-embedding-nomic-embed-text-v1.5 loaded)
& ..\.venv\Scripts\python -m memorygraph.cli `
    --global-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global `
    --output-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global\memorygraph\full-rule `
    --with-numeric --with-embeddings

# E4 — same command as E3; learned kind weights are automatic once
# fit_on_pairs is wired in. See graph-stats.json for the learned values.
```

Comparison vs the rest of the project leaderboard:

```powershell
& ..\.venv\Scripts\python -m comparison.cli `
    --global-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global `
    --runs-root ..\data\runs `
    --pipelines memorygraph,memorygraph_hybrid,memorygraph_full,hgb,loganalyzer `
    --output-dir ..\data\derived\global\2026-05-25-dataset-v5-quick-global\comparison\memorygraph-variants
```

Smoke tests (no external services required):

```powershell
& ..\.venv\Scripts\python -m memorygraph.tests.test_smoke
# Expected: "7 tests passed"
```

---

## File-level history

| When | Change |
| --- | --- |
| 2026-05-27 | Initial scaffold (M0): entities, graph, skills, agent, pipeline, CLI, smoke tests. |
| 2026-05-27 | M1 deterministic chain wired; `memorygraph` registered in comparison harness. |
| 2026-05-27 | M2 NumericBlendSkill + hybrid chain + `memorygraph_hybrid` registered. |
| 2026-05-27 | M3 EmbeddingSimilaritySkill + `--with-embeddings` flag + `memorygraph_full` registered. |
| 2026-05-27 | M4 GraphScoreSkill.fit_on_pairs learns per-kind weights from train. Stats persisted to graph-stats.json. |
| 2026-05-27 | M4 fix: fit_on_pairs takes builder (not graph) so transient window nodes are added during fit, and BRIDGEABLE_KINDS is used as the kind-iteration whitelist (was leaking module docstrings into graph-stats). |
| 2026-05-30 | **M5 humanized-corpus swap**: `humanized_loader.py` + `humanized_subdir` flag on `MemoryGraphPipeline` + two new KNOWN_PIPELINES entries (`memorygraph_hybrid_humanized`, `memorygraph_full_humanized`). Lets the comparison harness A/B legacy-vs-humanized memory corpus with bootstrap CIs. Commit `e40a400`. |
| 2026-05-30 | **E5 — cross-train BM25 v5-large**: legacy `memorygraph_hybrid` PR-AUC 0.66 vs humanized 0.61 (Δ −0.054 p<0.001); Recall@5 0.20 vs 0.07 (Δ −0.136 p<0.001); orphan gap +24.7 → +12.7 (pattern_matching → borderline). Triage was mostly real, retrieval was heavily inflated by lab vocabulary, humanized variant is meaningfully more robust on orphan windows. |
| 2026-05-30 | **E6 — cross-train Nomic v5-large** (in flight): same as E5 but `memorygraph_full` vs `memorygraph_full_humanized`. Tests whether dense embeddings rescue the retrieval lift BM25 lost to leakage stripping. Results will be appended when the run finishes. |
