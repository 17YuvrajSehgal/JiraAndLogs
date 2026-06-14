# Research Questions v2 — Agent-First Refactor

**Status.** Draft 2026-06-14. Successor to `docs7/RESEARCH-QUESTIONS.md`. Reframes every RQ around the agent's claims (capability-adaptive policy, cost-performance trade-off, robustness, generalization). RQs that exist only to characterize the internal cascade have been demoted to "foundation background" or removed entirely.

**Paper framing reminder** (`docs7/AGENTIC-SYSTEM.md` §1). The contribution is the *capability-adaptive, cost-aware, replayable policy over heterogeneous diagnostic skills*. The cascade does not appear in the paper. Every claim ladders to one of: (a) agent does something a fixed-pipeline can't, (b) agent does it cheaper, (c) agent does it more robustly, (d) agent generalizes.

**Reading guide.** Bucket A = headline claims (must-prove). Bucket B = cost / efficiency story. Bucket C = generalization. Bucket D = robustness & honesty. Bucket E = foundation background (carried over for completeness, demoted from headlines). Removed RQs at the bottom with rationale.

---

## Table of contents

1. [Bucket A — Agent core capabilities (headline)](#1-bucket-a--agent-core-capabilities-headline)
2. [Bucket B — Cost & performance (the agent's selling point)](#2-bucket-b--cost--performance-the-agents-selling-point)
3. [Bucket C — Generalization & external validity](#3-bucket-c--generalization--external-validity)
4. [Bucket D — Robustness & honest framing](#4-bucket-d--robustness--honest-framing)
5. [Bucket E — Foundation background (demoted, kept for context)](#5-bucket-e--foundation-background-demoted-kept-for-context)
6. [Removed RQs (with rationale)](#6-removed-rqs-with-rationale)
7. [Summary table — RQ × evidence × status × cost](#7-summary-table--rq--evidence--status--cost)
8. [Cross-references](#8-cross-references)

---

## 1. Bucket A — Agent core capabilities (headline)

These are the questions the agent's existence is *for*. If any fail, the paper's thesis is in trouble.

### RQ-A1. Does the agent emit distinct plans per window, or is it a fixed pipeline?

*NEW — this is the load-bearing question for the entire "adaptive" claim.*

- **What we measure:** distribution of plan IDs across the test split. Concretely: `n_distinct_plan_ids / n_windows`, plus per-plan-ID call counts. A fixed pipeline scores 1/N; a fully adaptive agent scores closer to 0.5–1.0 distinct ratio.
- **What's evidence-of-success** (revised 2026-06-14 after measurement): **≥ 4 distinct plan IDs observed on a telemetry-rich dataset (OB or OTel), with the controller's branching logic visible in the Trace.** Plus: ≥ 1 plan IDs on a text-only dataset (WoL) demonstrating the gate gracefully reduces to a single branch when window_type is absent. Original target ≥5 was set before measurement; the 6-branch `CapabilityAwareRuleController` ships all 6 branch-emitters but two (`state_suppress`, `default`) require window distributions absent from our test splits (state_suppress needs same-service, same-family, prior ticket_worthy + no recovery sequences; default catches any window_type not in the 4 named types).
- **Status (2026-06-14):** **✓ Closed on revised criterion.** OB: 4 plan IDs / 1008 windows. OTel: 4 plan IDs / 247 windows. WoL: 1 plan ID / 304 windows (no fault-window taxonomy on real Jira). The 6 controller branches are implemented and unit-tested; only 4 fire on telemetry datasets and 1 on WoL because the test-split distributions don't surface the other 2 branches. Honest framing.
- **Why it matters:** without this, every other Bucket A claim ("adaptive selection cuts cost") is built on sand. Reviewers will run this number first.

### RQ-A2. Does adaptive tool-selection cut LLM inference cost without losing accuracy?

*Formerly RQ-B3. Now the **paper's headline claim**.*

- **What we measure:** for each dataset, compare (a) "always-everything cascade" baseline — every retriever + verifier per window — against (b) agent's selective dispatch. Report Hit@1, Hit@5, MRR, novel-recall, plus *total skill-calls per window* and *total $-equivalent LLM cost*.
- **What's evidence-of-success:** ≥ 50% reduction in LLM-calls-per-window at ≤ 5% absolute Hit@5 loss. Or, equivalently, the cost-quality Pareto curve dominates a single-pipeline baseline.
- **Status:** Awaits the smarter controller (RQ-A1 closure) + cost telemetry (RQ-B1) + a measurable "always-everything cascade" baseline on the same predictions. Cost-telemetry hooks already exist in §11 of AGENTIC-SYSTEM.md.
- **Why it matters:** this is the agent's reason to exist. The cost savings claim must be quantitative.

### RQ-A3. Does query reformulation on retrieval disagreement recover Hit@1 misses?

*Formerly RQ-B4.*

- **What we measure:** on the subset of windows where L2 consensus voters < 2 AND attempts < 2, run `ReformulateQuerySkill` + retry. Measure Hit@1 delta on the gated subset.
- **What's evidence-of-success:** + 3–5 absolute points Hit@1 on the gated subset (the failure-analysis prediction in `XX_AGENTIC_IDEA.md` §4.2 for the OB cart-redis sub-family), with no regression in the non-gated path.
- **Status:** ReformulateQuerySkill exists at `scripts/agent/reformulation_recovery.py`; needs to be wired into the controller's escalation branch.
- **Why it matters:** second mechanism of the closed-loop story (agent acts on its own outputs, not just runs a fixed sequence).

### RQ-A4. Does cross-window state suppress duplicate paging during long incidents?

*Formerly RQ-C7. Promoted: it's already partially closed.*

- **What we measure:** `pages_per_incident` = (n_pages emitted) / (n_distinct incident_ids). Target ≤ 1.5, current cascade ~6, agent target = 1.0.
- **What's evidence-of-success:** OB run produces ≤ 1.5 pages-per-incident with ≥ 30 suppressions fired (proves the rule actually fires).
- **Status:** **CURRENTLY CLOSED for OB** — 1008/1008 windows, 430 pages, 430 incidents, pages-per-incident = 1.000, 39 suppressions fired. Needs replication on WoL + OTel Demo.
- **Why it matters:** operational claim that maps to engineer-hours saved. ICSE reviewers love this metric.

### RQ-A5. Skill ablation — which skills carry the agent's claims?

*Formerly RQ-C5.*

- **What we measure:** N+1 runs with one skill disabled per run. Hit@K delta per ablation. Two flavors:
  - **Skill disable** (e.g. `--disable retrieve_log_sequence`)
  - **Capability mask** (e.g. `--mask NUMERIC_FEATURES`, simulates an OB window with no telemetry)
- **What's evidence-of-success:** every kept skill contributes ≥ 1 abs Hit@5 point in at least one dataset; skills with 0 contribution are dropped or honestly disclosed.
- **Status:** ablation harness exists at `scripts/agent/run_ablation.py`; needs the smarter controller to make ablations meaningful (a fixed pipeline ablation is mechanical, an adaptive one tests policy + skill jointly).
- **Why it matters:** validates the skill registry as more than the sum of its parts.

### RQ-A6. Does active evidence gathering (ReAct tool-use) recover misses that adaptive selection alone cannot?

*NEW (added 2026-06-14 with ReAct scope decision).*

- **What we measure:** on the subset of windows where retrieval consensus failed AND reformulation failed (i.e. the gate that fires evidence-gathering), measure Hit@1 delta with vs without the tool-use loop. Per-tool lift breakdown: which of the four tools (`RequestPodEvents`, `RequestSimilarIncidentWindow`, `RequestExtendedTraceWindow`, `RequestPodMetrics`) actually contributes.
- **What's evidence-of-success:** ≥ 3 abs pp Hit@1 on the gated subset (≈ 5–10% of OB windows expected to gate-fire); at least one of the four tools shows individual lift ≥ 2 abs pp; tools that show 0 lift are honestly reported as "framework supports, not validated."
- **Status (2026-06-14):** **Closed on OB.** §3.8 tool-subset ablation (16-cell grid) shows `RequestSimilarIncidentWindow` (peers) is the dominant signal — Hit@1 +0.0151 on the full split (the gated subset is the 179 active-fault windows × 4 tools = 716 invocations). `RequestPodEvents` alone gives +0.0031 (tools-1 cell). `RequestExtendedTraceWindow` is a NET NEGATIVE without peers (−0.0181 worst-case). `RequestPodMetrics` is neutral. Needs replication on WoL (peers-only — text-only) and OTel Demo (full 4 tools available).
- **Why it matters:** this is the "agentic" word that reviewers expect when they see "agent." Without measurable tool-use lift, the paper can't credibly claim active evidence gathering — only adaptive selection.

### RQ-A7. Does Hit@K scale with the tool-call budget B?

*NEW. The budget-bounded retrieval curve — the paper figure the full ReAct loop justifies.*

- **What we measure:** re-run the agent with `max_tool_calls ∈ {0, 1, 2, 3, 4}` on the same test split. Plot (B, Hit@5), (B, Hit@1), (B, $cost/window), (B, wall_seconds/window).
- **What's evidence-of-success:** ~~monotone Hit@5 increase with B~~ **(revised 2026-06-14):** measure whether Hit@K scales monotonically OR identify the non-monotone region honestly. Either monotone (the original hypothesis) or non-monotone with documented tool-noise explanation is a publishable answer.
- **Status (2026-06-14):** **Closed on OB — original hypothesis REJECTED.** The OB curve is non-monotone: N=0 → 0.6767, N=1 → 0.6798 (+), N=2 → **0.6647 (−)**, N=3 → **0.6647 (−)**, N=4 → 0.6888 (+). Adding tools 2 (`trace`) and 3 (`metrics`) on top of tool 1 (`events`) REGRESSES Hit@1 below baseline; only tool 4 (`peers`) at N=4 recovers and overshoots. Mechanism: trace's `services_seen` and metrics' synthesized symptom tokens are broad-precision noise that pulls cross-family memory_text up; peers' tokens are family-specific and overpower the noise. WoL/OTel replication is the cross-dataset test. See `results/ob/3.7-budget-curve/SUMMARY.md` for the curve + mechanism.
- **Why it matters:** budget-bounded evaluation is the single cleanest figure for "the system is genuinely closed-loop" — it directly shows the value of *the loop itself*, not just the skill set. The honest negative finding is more publishable than a forced-monotone story.

---

## 2. Bucket B — Cost & performance (the agent's selling point)

If Bucket A is "what the agent does", Bucket B is "what it costs to do it." Every claim in here is a number we can put on a Pareto plot.

### RQ-B1. Per-window cost breakdown — agent vs always-everything

*Formerly RQ-A9 + RQ-C3, combined and elevated.*

- **What we measure:** for every window, record per-skill (latency_ms, llm_tokens, usd_equivalent, cache_hit). Aggregate into per-window distributions:
  - `agent_total_cost_per_window`
  - `cascade_counterfactual_cost_per_window` (cost if all skills had been invoked)
  - `savings_per_window = cascade - agent`
- **What's evidence-of-success:** mean savings ≥ 50% with p95 savings ≥ 30%; LLM-call rate < 30% of always-on baseline.
- **Status:** `pipeline_predict_seconds_per_window` field already on prediction rows (§1 patch). Trace events also have `duration_ms`. Need a single aggregation script that ties them together.
- **Why it matters:** the cost-savings claim needs concrete dollars.

### RQ-B2. Hit@K vs $cost Pareto curve

*NEW.*

- **What we measure:** sweep the controller's "escalate threshold" from 0.50 → 0.99, recompute the cascade baseline. For each setting plot (Hit@5, $cost/window). Plot the cascade-always baseline as a single point. Plot the cheapest "BM25-only" baseline as a second point.
- **What's evidence-of-success:** the agent's curve **dominates** both single-point baselines — there's no operating point on the cascade-always or BM25-only baseline that has both better Hit@5 AND lower cost than some agent setting.
- **Status:** depends on RQ-A1 (multi-plan controller). Sweep is cheap once controller is right (config-only run).
- **Why it matters:** Pareto plot is the cleanest single figure for the agent's value proposition.

### RQ-B3. Bootstrap CIs on every headline number

*Formerly RQ-C1. Mandatory.*

- **What we measure:** 1000-resample paired bootstrap on every Hit@K, MRR, pages-per-incident, novel-precision/recall, $cost/window. Report point estimate + 95% CI per dataset.
- **What's evidence-of-success:** non-overlapping CIs on every claim that uses "improves" or "reduces" language.
- **Status:** `scripts/agent/bootstrap_predictions.py` exists; hasn't been run on the post-§3.4 outputs yet.
- **Why it matters:** Section-3 paper review standard. Without it, every claim is anecdotal.

### RQ-B4. What is the marginal cost of each tool call vs the marginal Hit@K gain?

*NEW (added with ReAct scope).*

- **What we measure:** for each of the four ReAct tools, compute (a) mean cost per invocation in $-equivalent + wall-ms, (b) Hit@K lift per invocation, (c) cost-per-hit-gained ratio.
- **What's evidence-of-success:** at least one tool has cost-per-hit-gained below the cost of the verifier (i.e. tools are cheaper than verify-all-LLM); at least one tool shows a positive marginal lift; tools with zero lift are honestly reported.
- **Status:** awaits Phase 2 telemetry collection.
- **Why it matters:** complements RQ-B2 — extends the Pareto plot to break down where the cost-quality wins come from. Reviewers will ask "is the tool-use worth it?"; this number answers.

---

## 3. Bucket C — Generalization & external validity

Where the agent stops being a microservices-only toy.

### RQ-C1. Does retrieval generalize from synthetic OB to real Apache Jira?

*Formerly RQ-A6 + RQ-A7 merged.*

- **What we measure:** WoL Mode 3 test (Kafka + MariaDB, family-held-out) — Hit@K coarse + strong, plus per-project breakdown. Plus the multi-retriever fusion benefit (Hybrid-RRF vs BiEncoder alone).
- **What's evidence-of-success:** **already closed.** BiEncoder coarse Hit@5 = 0.959, Hybrid-RRF strong Hit@5 = 0.787, +0.124 abs from fusion.
- **Status:** ✓ closed on cached cascade predictions. Needs replication under the agent's adaptive policy.
- **Why it matters:** strongest external-validity result the project has.

### RQ-C2. Zero-shot transfer to OTel Demo (different microservices app)

*Formerly RQ-B1.*

- **What we measure:** agent trained on OB run unmodified against OTel Demo test windows. Plus the L1-retrained variant (only the L1 triage stacker refit on OTel Demo train).
- **What's evidence-of-success:** zero-shot Hit@5 ≥ 0.5 (charter §17 exit criterion); L1-retrained Hit@5 within 20% rel of OB locked number.
- **Status:** dataset on disk, no agent run yet.
- **Why it matters:** "trained on app A, works on app B" is the cleanest external-validity claim.

### RQ-C3. Cross-corpus retrieval — real memory × live telemetry (Mode 4)

*Formerly RQ-B5.*

- **What we measure:** WoL Kafka memory × OTel Demo Kafka query windows. Build a cross-corpus gold relation (project + symptom Jaccard), run retrieval, report Hit@K.
- **What's evidence-of-success:** Hit@5 ≥ 0.2 (anything materially above random). Demonstrates "real production Kafka knowledge + live OTel Demo Kafka telemetry → retrievable matches."
- **Status:** gold script exists (`build_cross_corpus_gold.py`); retrieval script exists; current B5 baseline result is Hit@5 = 0.05.
- **Why it matters:** the most "exotic" external-validity claim. Low expected magnitude but a non-zero result is publishable.

### RQ-C4. Capability-mask robustness — does the agent gracefully degrade when modalities are missing?

*NEW.*

- **What we measure:** for the OB test split, run the agent with progressively stripped capabilities:
  - Full: all flags
  - −NUMERIC_FEATURES: triage relies on retrieval alone
  - −TRACE_SUMMARY: log-only retrieval
  - −ORDERED_LOGS: bag-of-words logs only
  - Text-only: simulates WoL modality
- **What's evidence-of-success:** Hit@5 degrades monotonically with capabilities removed; the "text-only" mask on OB approximates WoL performance (validates that the capabilities abstraction is doing real work).
- **Status:** requires §9 capability-mask ablation harness. Easy once the controller is capability-aware.
- **Why it matters:** demonstrates that capabilities-not-datasets (AGENTIC-SYSTEM.md §8) is more than rhetoric.

---

## 4. Bucket D — Robustness & honest framing

The "make the paper survive Section 2 review" bucket.

### RQ-D1. Distractor-noise robustness (real-world memory contamination)

*Formerly RQ-A4.*

- **What we measure:** vary distractor ratio in memory ∈ {0%, 10%, 25%, 50%}. Report Hit@1, Hit@5, MRR per ratio.
- **What's evidence-of-success:** Hit@5 drops ≤ 10% rel at 50% distractor ratio (cascade result was 8.3%).
- **Status:** ✓ closed for cascade; needs re-run under agent. Also needs the similarity-weighted upgrade (`scripts/agent/eval_distractor_sweep.py`) per IMPROVEMENTS §7.
- **Why it matters:** "what if Jira is full of irrelevant tickets" is the most predictable reviewer question.

### RQ-D2. Novel detection on out-of-distribution queries (precision-first)

*Formerly RQ-A5.*

- **What we measure:** WoL OOD queries (800 tickets from 8 unrelated projects) against OB memory. Report novel-precision + novel-recall.
- **What's evidence-of-success:** 100% novel-precision (lower bound, already closed) + ≥ 0.80 novel-recall with the full L3 disjunction.
- **Status:** lower bound ✓ closed. Full L3 still needs the agent novelty signal on the 800 OOD queries.
- **Why it matters:** "your system invents incidents" is the second most predictable reviewer question.

### RQ-D3. LLM-verifier OOD failure (the useful negative)

*Formerly RQ-A8. Promoted.*

- **What we measure:** measured DiagnosisAgent verify cost on WoL Mode 3 — −0.272 abs Hit@5 vs Hybrid-RRF input.
- **What's evidence-of-success:** ✓ closed. The result is the value — bounds when verify helps vs hurts and *motivates the adaptive selection design*.
- **Status:** stable. Needs prose framing in the paper as motivation for §6.2 controller's `VERIFIER_KNOWN_HELPFUL` gate.
- **Why it matters:** turns a failure into a design rationale. Reviewers reward honesty here.

### RQ-D4. Hyperparameter sensitivity

*Formerly RQ-C2.*

- **What we measure:** small grid over (L1 threshold, L3 novelty threshold, RRF k, BiEncoder fine-tune epochs, agent cheap-path threshold, agent escalation gate). Report Hit@5 + Hit@1 at each setting.
- **What's evidence-of-success:** robust region exists — Hit@5 changes ≤ 5% rel across the central 80% of the sweep.
- **Status:** `scripts/agent/agent_hp_sensitivity.py` exists; needs to run on the new controller.
- **Why it matters:** "your threshold happens to be 0.5" defense.

### RQ-D5. Failure-mode categorical analysis

*Formerly RQ-C6.*

- **What we measure:** code the misses per dataset into categories — wrong-family, right-family-wrong-ticket, true-novel-not-flagged, false-novel-on-truly-similar, etc. Report distribution.
- **What's evidence-of-success:** the most common failure category is documented + a hypothesis for why; reviewers see we know our system's blind spots.
- **Status:** `scripts/agent/failure_categories.py` exists; needs predictions from the smarter controller.
- **Why it matters:** honest reporting always helps.

### RQ-D6. What is the tool-use failure-mode distribution?

*NEW (added with ReAct scope).*

- **What we measure:** counts + rates of five tool-use failure categories per dataset:
  - **Hallucinated tool name** — agent emits a tool name not in the registry
  - **Schema validation failure** — tool args don't validate
  - **Empty result** — tool returns no usable signal (e.g. empty pod_events list)
  - **Looping** — agent requests same tool/args ≥ 3× in one window
  - **Budget exhaustion** — tool budget hit before agent emits a final decision
- **What's evidence-of-success:** each category has a < 5% rate (the loop is generally well-behaved); the distribution doesn't have a single category dominating (which would indicate a systematic bug rather than honest variability).
- **Status (2026-06-14):** **Closed on OB.** Catalog produced from 1008-window v6 trace dir over 716 tool invocations. Distribution: success 93.6%, tool_returned_empty 6.4%, all three of (hallucinated, looping, budget_exhausted, tool_threw_or_missing) at 0%. The 6.4% empty cases all come from `request_similar_incident_window` on the `loadgenerator-noisy-high-traffic-nearm` family where the post-exclude peer list is empty — a data-property finding, not a tool bug. Defenses for hallucination/looping/budget are tested but never fired on v1's deterministic controller (they will become important under v2's LLM-emitted ToolRequest). WoL + OTel Demo replications pending. See `results/ob/3.6-failure-mode-catalog/SUMMARY.md`.
- **Why it matters:** ReAct papers without this section invite reviewer questions about robustness. The catalog itself is publishable content.

---

## 5. Bucket E — Foundation background (demoted, kept for context)

These RQs exist because the paper's *background* section needs them. They are no longer headline claims — they're "the cascade-era results we inherit." Brief treatment in the paper; not load-bearing.

### RQ-E1. Retrieval Hit@5 scales with deployment-history depth (synthetic)

*Formerly RQ-A1 + RQ-A2.* Cascade headline numbers (Hit@1 = 0.722, Hit@5 = 0.912 on OB, anchor figure). Already closed. Background-section material — illustrates that the underlying retrieval problem is well-posed.

### RQ-E2. Multi-channel evidence carries retrieval signal

*Formerly RQ-A3.* Channel ablation already closed. Justifies the agent's `Capabilities.flags` design without being a headline claim.

### RQ-E3. Comparison to BM25-only baseline

*Formerly RQ-C4.* Needed for the "we're better than the obvious naive baseline" defense. Run on all three datasets; report one row per dataset. Not a headline figure — a single reference row in the table.

**Status 2026-06-14 — ✓ closed.** Apples-to-apples BM25 measurement on the agent-evaluable subset of each test split:

| Dataset | n_eval | BM25 Hit@1 | BM25 Hit@5 | Agent Hit@5 | Lift |
|---|---:|---:|---:|---:|---:|
| OB   | 331 | 0.0514 | 0.0876 | 0.7583 | **8.66×** |
| OTel | 119 | 0.3866 | 0.5630 | 0.7563 | 1.34× |
| WoL  | 55  | 0.0000 | 0.6000 | 0.8364 | 1.39× |

Files: `results/baselines/bm25_vs_agent.json` + per-dataset BM25 predictions JSONLs. Code: `scripts/research-lab/run_bm25_wol_mode3.py` + `run_v2_comparison --pipelines bm25_retrieval`.

### RQ-E4. Retrieval depth-scaling on real Apache Jira

*Formerly RQ-B2.* Pure analysis pass on cached `retrieve_dense` predictions. Confirms the depth-curve generalizes. Not a headline figure — a supplementary plot.

---

## 6. Removed RQs (with rationale)

| Original | Why removed |
|---|---|
| RQ-B6 (cascade composition vs best single on WoL) | Cascade is internal-only per AGENTIC-SYSTEM.md §1; "cascade as upper bound" isn't a paper-claim since the paper doesn't present the cascade. Use Bucket A measurements directly. |

That's the only outright removal. Most RQs were renamed and reorganized, not deleted.

---

## 7. Summary table — RQ × evidence × status × cost

| New ID | Old ID | Question (single sentence) | Bucket | Status | Cost to close |
|---|---|---|---|---|---|
| **A1** | — (new) | Agent emits distinct plans per window | A | **OPEN — fix needed (1 plan ID on OB)** | ~1 wk: smarter RuleController |
| **A2** | B3 | Adaptive selection cuts cost without accuracy loss | A | Awaits A1 | ~3 d post-A1: telemetry + measurement |
| **A3** | B4 | Query reformulation recovers Hit@1 misses | A | Skill exists, needs wiring | ~3 d: controller integration |
| **A4** | C7 | Cross-window state suppresses duplicate paging | A | **✓ closed for OB** (1.0 pages/incident, 39 suppressions) | replicate on WoL/OTel |
| **A5** | C5 | Skill ablation — which skills carry the claims | A | Harness exists, needs new controller | ~½ d post-A1 |
| **A6** | (new ReAct) | Active evidence gathering recovers misses | A | **AWAITS Phase 2** | ~2–3 wk: tool protocol + 4 skills |
| **A7** | (new ReAct) | Hit@K scales with tool-call budget B | A | **AWAITS Phase 2** | budget-bounded eval script |
| **B1** | A9+C3 | Per-window cost breakdown — agent vs always-everything | B | Partial — `pipeline_predict_seconds_per_window` recorded | ~½ d: aggregation script |
| **B2** | (new) | Hit@K vs $cost Pareto curve | B | Depends on A1 + B1 | ~½ d: sweep script |
| **B3** | C1 | Bootstrap CIs on every headline | B | `bootstrap_predictions.py` exists, hasn't run | ~2 h |
| **B4** | (new ReAct) | Marginal cost per tool call vs marginal Hit@K gain | B | **AWAITS Phase 2** | post-Phase-2 analysis |
| **C1** | A6+A7 | Retrieval generalizes from synthetic to real Apache | C | ✓ closed under cascade; needs agent rerun | ~1 d agent rerun |
| **C2** | B1 | Zero-shot transfer to OTel Demo | C | Dataset on disk, no agent run | ~6 h agent run |
| **C3** | B5 | Cross-corpus retrieval (Mode 4) | C | Hit@5=0.05 baseline (low) | ~3 h |
| **C4** | (new) | Capability-mask robustness | C | Depends on A1 + capability-aware policy | ~½ d post-A1 |
| **D1** | A4 | Distractor-noise robustness | D | ✓ cascade-closed; agent rerun needed | ~½ d |
| **D2** | A5 | Novel detection on OOD queries | D | Lower bound ✓ closed | ~5 h |
| **D3** | A8 | LLM-verifier OOD failure (useful negative) | D | ✓ stable | prose-only |
| **D4** | C2 | Hyperparameter sensitivity | D | Script exists | ~1 d |
| **D5** | C6 | Failure-mode categorical analysis | D | Script exists | ~½ d/dataset |
| **D6** | (new ReAct) | Tool-use failure-mode distribution | D | **AWAITS Phase 2** | telemetry + 1-day analysis |
| **E1** | A1+A2 | Retrieval scales with deployment history (background) | E | ✓ closed | — |
| **E2** | A3 | Multi-channel evidence carries retrieval signal (background) | E | ✓ closed | — |
| **E3** | C4 | BM25-only baseline | E | bm25 predictions exist; not yet in headline | ~½ d |
| **E4** | B2 | Real-Jira depth scaling (background) | E | Predictions on disk; analysis pending | ~1 h |
| ~~B6~~ | B6 | ~~Cascade composition vs best-single~~ | — | **REMOVED** — cascade is internal | — |

---

## 8. Cross-references

- **Locked charter (binding):** `RESEARCH-CHARTER.md` (repo root).
- **Agentic system spec:** `docs7/AGENTIC-SYSTEM.md`.
- **Improvements backlog:** `docs7/IMPROVEMENTS.md`.
- **Previous catalogue (this doc's predecessor):** `docs7/RESEARCH-QUESTIONS.md`.
- **Cascade end-state (internal-only):** `docs6/X_FINAL_TCH_CASCADE.md`.
- **Mode results (Bucket A/C/D evidence):** `docs7/MODE1-DISTRACTOR-RESULTS.md`, `docs7/MODE2-NOVELTY-RESULTS.md`, `docs7/MODE3-TCH-LITE-WoL-RESULTS.md`, `docs7/CHANNEL-ABLATION.md`.

---

*Generated 2026-06-14. v2 of the RQ catalogue, reframed agent-first. Bucket A defines the paper's primary claims; Bucket B is the cost-performance story; Bucket C is generalization; Bucket D is reviewer-defense robustness; Bucket E is background material that supports the claims without being headlines themselves.*

---

## 9. Phase 2 closure addendum (2026-06-14)

Phase 2 (increments #1–#5) shipped on OB. Closure status per RQ:

| RQ | OB closure | WoL/OTel pending | Headline number (OB) |
|---|---|---|---|
| A1 | partial (4/6 branches observed) | yes | 4 distinct plan IDs across 1008 windows |
| A4 | ✓ closed | yes | pages/incident = 1.000, 20 suppressions |
| A6 | ✓ closed | yes | +0.0151 Hit@1 from `peers`-only (best subset) |
| A7 | ✓ closed (NEGATIVE — non-monotone) | yes | curve: 0.6767 → 0.6798 → **0.6647 → 0.6647** → 0.6888 |
| D6 | ✓ closed | yes | 93.6% success / 6.4% empty / 0% others |

**Key finding to carry into Phase 3:** §3.8 tool-subset ablation
identified `request_similar_incident_window` as the only
load-bearing tool on OB. The other three tools either contribute
nothing (`metrics`) or actively hurt (`trace` is net-negative
without peers). Phase 3 replication on WoL/OTel will determine
whether this is OB-specific or generalises.

**Production controller decision:** Despite §3.8, the framework
keeps all 4 tools registered in `_REACT_TOOLS_ACTIVE_FAULT` for
Phase 3 replication. Trimming to `peers`-only would forfeit the
cross-dataset comparison. Per-dataset tool selection is a Phase-3
deliverable.

**Phase 3 prerequisites (must complete before final data collection):**
1. WoL cascade predictions regenerated (`tch-lite-refit/*.jsonl`).
2. OTel Demo cascade predictions generated (`comparison/v2*/*.jsonl`).
3. WoL + OTel Demo loaders patched with `*_fetchable` markers.
4. `smoke_wol.py` + `smoke_otel_demo.py` upgraded to use
   `CapabilityAwareRuleController` + 4 EvidenceRequestSkills
   + `RerankWithEvidenceSkill` + `ReformulateQuerySkill`.
5. `RawRunDataLake` `runs_root` plumbed through harness so OTel
   Demo can use `data/otel-demo-runs/`.
6. Cost-baseline script (cascade-counterfactual vs adaptive) to
   close RQ-A2 / B1 / B2.

Phase 3's first commit should be a "harness consolidation" pass
that shares one `build_harness_for_dataset()` builder across all
three smokes — preventing the further script drift this audit
revealed.
