# Research Charter — Memory-Augmented Incident Triage

**Status:** LOCKED 2026-06-01. Any change to scope, claims, metrics, or experimental design requires explicit re-charter, not ad-hoc updates.

**Purpose of this document:** Single source of truth for the research goal, claims, scope, deliverables, and protocol. When in doubt about whether to pursue an idea, check this file first — if the idea isn't here, it's out of scope.

---

## 1. One-sentence positioning

> **We do not improve anomaly detection. We add a retrieval-augmented diagnosis head that turns a flag into a citation — and we characterize when, why, and how well this works.**

---

## 2. Problem statement

Modern SRE teams have mature anomaly detectors (Prometheus alerts, ML-based detectors on numeric telemetry, log-volume regressions). The bottleneck is no longer "is something wrong?" — it's **"what is wrong, has this happened before, and what should I do?"**.

When an on-call engineer gets paged, the bottleneck is *diagnosis time*: dig through dashboards, search Jira manually, find the relevant past ticket (if any), apply the known fix. Past Jira tickets contain rich, structured knowledge about root causes and remediations, but they are unindexed against live telemetry. There is no automatic bridge from "this trace + these logs + this k8s event" to "this is Jira INCIDENT-1234, run the cart-redis cache flush playbook."

We build and characterize that bridge.

---

## 3. Headline claim (the one thing the paper proves)

> **A retrieval-augmented incident triage system, fed with a memory of past humanized Jira tickets, produces meaningfully better diagnosis suggestions as deployment history accumulates — going from 0% Recall@5 with no prior tickets to 36% Recall@5 once 100+ similar tickets are logged. This retrieval capability is orthogonal to anomaly detection (a mature task that pure numeric ML already saturates) and provides measurable engineer-time savings via top-K candidate citation.**

The claim has three properties that make it defensible:
1. **Empirically grounded** — directly supported by the depth-stratification we ran on V2 SOTA.
2. **Honestly scoped** — we explicitly disclaim improving anomaly detection (HGB-on-numerics already wins that with PR-AUC 0.77 vs memorygraph's 0.62; memory does not help triage detection at any depth).
3. **Industrially resonant** — matches the lived SRE experience that "the longer the team has been logging incidents, the easier the next similar incident is to resolve."

---

## 4. What we are NOT claiming (explicit non-goals)

These are off-limits for the paper and for further engineering effort:

| Non-claim | Why we drop it |
|---|---|
| "Memory improves anomaly detection / triage PR-AUC" | Refuted by our own depth stratification. HGB beats memorygraph at every history depth on PR-AUC. We surface this honestly as a limitation, not a contribution. |
| "We outperform commercial SOTA observability tools" | We have no commercial-tool comparison. Out of scope. |
| "Our system is production-ready" | It is a research prototype on a synthetic-but-realistic corpus. Production hardening (auth, multi-tenancy, latency SLOs, etc.) is out of scope. |
| "We solve cold-start" | We characterize cold-start behavior; we do not solve it. With zero prior tickets, retrieval is 0% by definition. |
| "Our humanized Jira corpus is indistinguishable from real Jira" | We do not claim parity with real production Jira; we claim engineer-voice realism on the dimensions that matter for retrieval (length, multi-channel evidence, log signatures). |

If a question we get during review reduces to one of the above, the answer is "out of scope — we make a narrower claim, see §3."

---

## 5. What we build (the system)

A skill-chain pipeline that, for each incoming telemetry window, produces a structured triage decision:

```
INPUT:  5-minute telemetry window
        - logs (Loki)
        - traces (Tempo)
        - metrics (Prometheus, k8s events, derived numeric features)
        - service / component context

PIPELINE STEPS (the "skill chain"):
  entity_extract           extract service, component, error_class, severity from evidence
  component_filter         pre-filter Jira memory by entity overlap
  lexical_similarity       BM25 retrieval over Jira memory text
  log_signature_similarity Move-A characteristic log lines on both sides
  cross_encoder_rerank     MS-MARCO MiniLM joint rerank, top-20 BLEND policy
  graph_score              bridge-weighted scoring on entity graph
  numeric_blend            HGB head over 94 derived numeric features
  triage_decide            blend numeric + similarity → triage score
  novelty_check            flag if no good past-ticket match
  graph_traverse_explain   explanation citing graph entities

OUTPUT:
  - triage_score          ∈ [0,1]    "is this ticket-worthy?"
  - top_5_candidates       ranked     past Jira tickets ordered by combined similarity
  - is_novel               bool       no good match found
  - explanation            string     "matches INCIDENT-1234 via shared service=cartservice + error_class=DeadlineExceeded"
```

**Existing infrastructure (do not rebuild):**
- V2 humanized memory corpus: 347 engineer-voice tickets with `description_code` + per-step `body_code`
- 110-ticket distractor set (60 TAWOS-derived + 25 in-architecture + 25 cross-architecture)
- 94 derived numeric feature columns per window
- Persistent embedding cache (commit `5cea334`)
- Cross-encoder skill with BLEND policy
- Comparison harness with bootstrap CIs and stratified metrics

**The final product is a research prototype + paper.** It is not a deployed system.

---

## 6. The three sub-claims (everything in the paper ladders to these)

### Sub-claim 1 — "Retrieval quality scales with deployment history"
**The anchor figure of the paper.** Recall@5 grows monotonically with the number of prior Jira tickets in memory related to the incident's scenario family.

- **Metric:** Recall@5 (primary), MRR (secondary), Recall@1 (tertiary)
- **Stratification axis:** `n_prior_family_tickets ∈ {0, 1-2, 3-5, 6-20, 21+}`
- **Statistical envelope:** 95% bootstrap CI per bucket, 1000 resamples
- **Comparison:** memorygraph_v2_sota_nw080 (with memory) vs HGB (structurally zero retrieval — the flat baseline)
- **Plus:** cold-start experiment — hold out first-occurrence-by-family at training, evaluate with empty memory, then add 1, 2, 3, N prior tickets and re-evaluate. Produces a forward-time learning curve.

### Sub-claim 2 — "Memory utility comes from corpus realism + multi-channel evidence + joint reranking"
**Justifies the engineering investment in the V2 humanizer and the skill chain design.**

Three ablations, each measured against the SOTA:
1. **Corpus quality** — V1 (CS-voice, ~800 chars) vs V2 (engineer-voice, ~2400 chars + description_code): +24% MRR
2. **Per-channel evidence** — drop logs / drop traces / drop k8s events independently; measure R@5 delta per channel. (NEW WORK)
3. **Reranking architecture** — BM25 only vs +log_signature vs +cross_encoder REPLACE vs +cross_encoder BLEND

- **Metric:** R@5, MRR for each ablation row
- **Output:** a single table with relative deltas vs SOTA for each ablation

### Sub-claim 3 — "The system degrades gracefully under realistic memory noise (distractors)"
**Reviewer-defense against "what if Jira is full of irrelevant tickets?"**

- **Setup:** vary distractor ratio in memory ∈ {0%, 10%, 25%, 50%}; SOTA pipeline; same test split
- **Metric:** R@1, R@5, MRR vs distractor ratio
- **Key existing finding:** at 24% distractor ratio (110 / 457), R@5 drops only 1% relative while R@1 drops 23% relative
- **Output:** a robustness curve showing where the system breaks

### Utility framing (cross-cutting, not a separate sub-claim)
A **time-to-diagnose simulation** converts retrieval metrics into engineer-minutes saved. Assumptions: engineer reviews ranked candidates serially, ~30s per candidate; if gold appears in top-K, diagnosis time = 30s × rank; if no hit, diagnosis falls back to a 30-minute manual baseline. Compute expected diagnosis time per pipeline. This gives reviewers a single number ("memory-augmented system saves ~12 minutes per resolvable incident vs flag-only baseline") and is what makes the paper actionable.

---

## 7. Datasets and corpora (frozen)

| Asset | Description | Source / path | Locked |
|---|---|---|---|
| Telemetry windows | 2796 train / 984 val / 2940 test (5-min windows from microservices-demo synthetic incidents) | `data/derived/global/2026-05-25-dataset-v5-large-global/` | ✓ |
| V2 humanized Jira memory | 347 engineer-voice tickets, 90.2% have `description_code`, sanitizer-clean per §14.11 | `jira-shadow-humanized-v2/bulk-20260531/` | ✓ |
| Distractor set | 110 tickets (60 TAWOS + 25 in-arch + 25 cross-arch) | `jira-shadow-humanized-v2-distractors/mint-20260601/` | ✓ |
| TAWOS reference | 458k real Jira issues, local MySQL `root/root/tawos` | (reference only, not in train) | ✓ |
| Numeric features | 94 derived `triage_feature_*` columns | embedded in window records | ✓ |

**No new corpus work.** The corpus is frozen. If a corpus issue surfaces, document it as a limitation, do not regenerate.

---

## 8. Pipelines compared (the locked panel)

The paper compares exactly these pipelines. Everything else from the 18 registered is excluded from the paper (kept in the codebase for reference).

> **Note (2026-06-12).** The `logsense_hybrid_bm25` baseline previously listed here has been **removed from the panel** and from the codebase. The post-2026-06-06 paper headline is the **TCH cascade** (see [[project-tch-cascade-design]]), and the post-WoL pivot is moving toward an **agentic system** (see `docs7/AGENTIC-SYSTEM.md`, in preparation). The logsense baseline was orthogonal to both — it was a retrieval-only system over a log-template memory, not a Jira-as-memory system — so it has stopped earning its place in the comparison table. The cascade's L2 retrievers (BiEncoder, Hybrid-RRF, LogSeq2Vec, KG-Retrieval) now provide the retrieval-modality comparison contrast that `logsense_hybrid_bm25` originally served. The three sub-claims and metrics remain unchanged; only the pipeline panel shrank.

| Pipeline | Role | Memory? | Status |
|---|---|---|---|
| `hist_gradient_boosting_numeric` (HGB) | Detection baseline | None | Existing |
| `memorygraph_hybrid_humanized` (V1) | Corpus-quality ablation | V1 CS-voice memory | Existing |
| `memorygraph_v2_sota_nw080` | **SOTA** | V2 + Move-A + cross-encoder BLEND + nw=0.80 | Existing |
| `memorygraph_v2_sota_nw080_ft` | **Headline SOTA after fine-tune** | + fine-tuned cross-encoder on (window→gold) pairs | NEW WORK |
| `memorygraph_v2_sota_nw080_no_logs` | Ablation: drop log channel | V2 + cross-encoder, no Move-A | NEW WORK |
| `memorygraph_v2_sota_nw080_no_traces` | Ablation: drop trace channel | V2 + Move-A + cross-encoder, masked trace text | NEW WORK |
| `memorygraph_v2_sota_nw080_no_k8s` | Ablation: drop k8s channel | V2 + Move-A + cross-encoder, masked k8s text | NEW WORK |
| `memorygraph_v2_sota_nw080_distractors_X%` | Robustness sweep | SOTA, X ∈ {0, 10, 25, 50} % distractors | NEW WORK (extend existing) |

---

## 9. Metrics (locked)

### Triage detection metrics (HGB owns these; we report honestly)
- **PR-AUC** (primary triage metric)
- **ROC-AUC**
- **F1 @ FPR ≤ 5%**
- **ECE** (calibration)

### Retrieval metrics (where we make our claims)
- **Recall@5** (PRIMARY for headline claim)
- **MRR** (secondary, captures rank quality beyond top-5)
- **Recall@1** (tertiary; sensitive to distractors)
- **Recall@3** (reported for context)

### Robustness metrics
- **Distractor confusion rate** = relative R@1 drop when distractors mixed into memory at ratio R
- **R@5 invariance** = relative R@5 drop at the same R

### Utility metric (derived, single number)
- **Expected time-to-diagnose** per resolvable incident, under the simulation in §6 utility framing

### Statistical envelope
- All headline numbers include **95% bootstrap CI** with 1000 resamples
- Pairwise pipeline comparisons reported with bootstrap CIs on the delta
- Stratified metrics reported per: `scenario_family`, `service_name`, `is_hard_case`, `is_novel`, `n_prior_family_tickets`

---

## 10. Experimental protocol (frozen)

- **Splits:** train/val/test = 2796/984/2940 windows, chronologically split. **Do not re-split** for any sub-claim experiment.
- **Memory composition for the main results:** V2 humanized corpus only (347 tickets), distractor-free, unless a sub-claim explicitly varies this.
- **Cold-start protocol (sub-claim 1 extension):**
  1. For each scenario_family, identify the first-occurrence window in train (`min(window_ts)` with non-null gold).
  2. Construct N memory subsets: `mem_0` = empty for that family; `mem_1` = first prior ticket only; `mem_2` = first 2; …; `mem_full` = unrestricted.
  3. Evaluate SOTA on test windows of that family, varying the memory subset.
  4. Plot R@5 vs number of prior tickets, per family.
- **Reproducibility:** every result must come from a pipeline `fit()` whose config + metrics + predictions are written to `data/derived/global/<id>/training_runs/<pipeline>__<UTC>__<sha8>/` via the existing `training_registry`. **Wire the registry into the comparison runner before running any new experiment** (current blocker).
- **Bootstrap CIs:** seed = 42, n_resamples = 1000.

---

## 11. Phased work plan (locked priorities)

### Phase A — Anchor experiment (Sub-claim 1) — *the paper rises or falls on this*
- A1. Wire `training_registry` into the comparison runner.
- A2. Recompute depth-stratification with **scenario_family proxy** (replace the service proxy from the sketch). For each test window, count memory tickets sharing scenario_family with the gold ticket. Bucket into {0, 1-2, 3-5, 6-20, 21+}.
- A3. Add 95% bootstrap CI per bucket to the harness.
- A4. Produce the anchor figure: R@5 vs `n_prior_family_tickets`, with HGB at 0 as the flat baseline.
- A5. Design and run the cold-start experiment per §10.
- **Exit criterion:** monotone R@5 curve with non-overlapping CIs between the 0 bucket and the highest bucket. If the curve is not monotone or CIs overlap, re-examine the proxy before moving on.

### Phase B — Technical contribution (cross-encoder fine-tune)
- B1. Build train pairs: `(window_evidence_text, gold_jira_text)` from train split, ~650 positives.
- B2. Hard-negative mining: for each positive, retrieve top-K wrong candidates via current bi-encoder; use as negatives.
- B3. Fine-tune `cross-encoder/ms-marco-MiniLM-L-6-v2` with sentence-transformers `CrossEncoder` API, 5-10 epochs, val-loss early stopping.
- B4. Register as `memorygraph_v2_sota_nw080_ft`. Run on test split. Compare to off-the-shelf SOTA on the depth curve.
- **Exit criterion:** measurable R@5 lift at the 21+ depth bucket. Magnitude not promised in advance; whatever it is gets reported honestly.

### Phase C — Multi-channel ablation (Sub-claim 2)
- C1. Implement channel-masking variants in `humanized_loader.py`: `no_logs`, `no_traces`, `no_k8s`.
- C2. Run each on test split with the SOTA pipeline.
- C3. Produce the ablation table: which channel contributes how much R@5.
- **Exit criterion:** every ablated channel produces a measurable R@5 drop, even if small. If a channel contributes zero, document and remove from the system.

### Phase D — Robustness (Sub-claim 3)
- D1. Implement distractor-ratio sweep: subsample 0%, 10%, 25%, 50% from the 110-ticket distractor pool.
- D2. Run SOTA at each ratio on test split.
- D3. Produce the distractor robustness curve: R@1, R@5, MRR vs distractor ratio.
- **Exit criterion:** R@5 is shown to be robust (≤5% drop at 25% ratio) and R@1 is shown to degrade (≥20% drop) — this is the existing finding, just packaged.

### Phase E — Utility framing
- E1. Implement the time-to-diagnose simulator (~50 lines, stdlib).
- E2. Compute expected diagnosis time per pipeline. Single-number summary.
- E3. Produce a small bar chart: minutes-per-incident, HGB vs SOTA vs SOTA_ft.

### Phase F — Write
- F1. Draft paper following the outline in §13.
- F2. Internal review.
- F3. Submit.

**Phase ordering is sequential.** Do not start B before A's exit criterion is hit; do not start C before B finishes; etc. The only parallelism allowed: F1 can begin partway through C/D once A and B are locked.

---

## 12. Success criteria (the definition of "done")

The project is **done** when ALL of the following are true:

1. The anchor figure (Phase A) shows a monotone R@5 curve with non-overlapping 95% CIs between the 0-prior bucket and the highest-prior bucket.
2. Phase B (cross-encoder fine-tune) is run and its result, lift or no lift, is reported.
3. Phases C and D produce their respective tables/curves.
4. Phase E produces a single time-to-diagnose number per pipeline.
5. The paper draft (Phase F1) contains all five experiments above, the limitations section explicitly disclaims the §4 non-claims, and the headline claim in §3 is supported by the data.

If a result contradicts the headline claim (e.g., R@5 does not grow with deployment history), **we re-charter the claim, we do not p-hack the result**. The integrity of the negative finding is more valuable than a confirmed positive of a wrong claim.

---

## 13. Paper outline (target structure)

1. **Introduction** — anomaly detection is mature; the next bottleneck is diagnosis-by-citation; we build and characterize a memory-augmented retrieval head
2. **Related work** — IR over operational data, RAG, log-template mining, Jira-as-knowledge-base prior work
3. **Approach**
   - 3.1 System architecture (the skill chain)
   - 3.2 The humanized Jira memory corpus (V2)
   - 3.3 Multi-channel evidence representation
4. **Experimental setup** — splits, metrics, statistical protocol
5. **Anchor result: retrieval quality scales with deployment history** (Sub-claim 1) — the headline figure
6. **What makes the memory useful** (Sub-claim 2) — corpus ablation + per-channel ablation + reranker ablation
7. **Robustness to memory noise** (Sub-claim 3) — distractor sweep
8. **Utility** — time-to-diagnose simulation
9. **Limitations and non-claims** — explicit disclaimers per §4
10. **Conclusion**

Target venue: one of {workshop on AIOps, SoCC, OSDI ML systems track, an MLSys-adjacent venue}. **Final venue selection deferred until paper draft.**

---

## 14. Out-of-scope items (the firewall against scope drift)

If you find yourself considering any of these, **stop and re-read this section**:

- New corpus generation runs. Corpus is frozen.
- Pipeline variants outside §8. They stay in the codebase for reference but do not enter the paper.
- LLM-based skill planners. The deterministic RulePlanner is the only planner in the paper.
- Active-learning / human-in-the-loop. Out of scope.
- Multi-tenant deployment, latency SLO benchmarks, cost analysis. Out of scope.
- Comparison against commercial observability tools. Out of scope.
- Adversarial robustness beyond random distractors. Out of scope.
- Real-Jira ingestion (vs TAWOS reference). Out of scope.

If the user proposes work in these areas, the response is: "that's out of scope per the charter §14; do you want to re-charter or table it for future work?"

---

## 15. Risks and pre-committed mitigations

| Risk | Mitigation |
|---|---|
| Anchor curve (Phase A) does not show monotonicity | Re-examine the proxy (try service-only, scenario_family, error_class); if still non-monotone, report it as a negative finding and pivot the claim to "depth helps in specific families" |
| Cross-encoder fine-tune (Phase B) shows no lift | Report honestly; the off-the-shelf SOTA stays as the headline; ablate why (insufficient train pairs, domain mismatch) |
| Per-channel ablation (Phase C) shows one channel does all the work | Report; potentially remove the redundant channels from the system; reframe as "X is the dominant channel" |
| Distractor ratio sweep (Phase D) shows R@5 collapse at 50% | Report; defines a useful operating ceiling for the system |
| Reviewer asks "is your synthetic corpus realistic?" | Cite the TAWOS-anchored humanizer redesign and the per-ticket length / comment / code-block targets (memory file [[project-jira-humanizer-redesign-tawos]]) |

---

## 16. Memory pointers (auto-memory cross-references)

- [[project-ml-training-pass-plan]] — pre-charter audit and infrastructure work
- [[project-triage-pivot]] — earlier framing pivot (now superseded by this charter)
- [[project-jira-humanizer-redesign-tawos]] — V2 corpus design rationale
- [[reference-per-run-artifacts]] — what each output file contains
- [[reference-derived-feature-columns]] — the 94 numeric columns

---

## 17. Cross-app validation (added 2026-06-08)

**Scope addition:** Cross-app evaluation on the OpenTelemetry Demo (Astronomy Shop) is in scope as a single external-validity test, per the strategy plan in `docs5/00-otel-demo-cross-app-plan.md` and the file-level implementation specification in `docs5/01-otel-demo-implementation-plan.md`.

**What this changes:**
- §5 (system) — unchanged; the locked TCH cascade is dataset-agnostic.
- §7 (datasets) — adds a second locked corpus on the OTel Demo (~9,300 windows across 47 scenarios, 100+ runs). The OB v5-large corpus remains frozen and primary.
- §8 (panel) — unchanged; the same locked pipelines run on the second dataset.
- §9 (metrics) — unchanged for L1 single-fault windows. Additionally reports `AllGold@K` and `PrimaryGold@K` for multi-fault L2 (concurrent), L3 (cascade), and L4 (compound) scenarios. Metric definitions in `docs5/00 §5.5.4`.
- §13 (paper outline) — adds §6.5 "Cross-app generalization" between current §6 and §7. The new section reports zero-shot transfer (locked cascade, no retraining) and L1-retrained columns, plus the graded-difficulty (L1–L4) table.
- §14 (non-claims) — IoT / ThingsBoard generalization remains out of scope; this addition is a single new app within the same broad domain (microservice e-commerce) with architectural-distance evidence from Kafka async, longer trace depth, and the LLM service.

**What is NOT changing:** the headline claim (§3), the three sub-claims, the locked OB cascade artifacts (`comparison/v2g-final-models/final/`), or the locked OB dataset.

**Exit criterion:** the cross-app section (§6.5) reports Hit@1 / Hit@5 / MRR / PR-AUC / novel-precision / novel-recall on the OTel Demo test split under both zero-shot and L1-retrained settings, with 95% bootstrap CIs, per-stratum breakdowns, and the graded-difficulty (L1–L4) table from `docs5/00 §5.5`. If zero-shot Hit@5 collapses below 0.5 or L1-retrained Hit@5 misses the OB locked number by more than 20% rel, the result is reported honestly and the cross-app framing is reduced rather than removed (same negative-finding discipline as the rest of the project).

**Hard isolation contract:** see `docs5/01 §1`. Five rules (R1–R5) prevent any modification or override of the locked OB v5-large dataset, cascade artifacts, or pipeline scripts. New files live under new paths (`data/derived/global/2026-XX-XX-otel-demo-v1-global/`, `deploy/otel-demo/`, `deploy/research-lab/scenarios/otel-demo/`, `scripts/research-lab/otel-demo/`, `src/v2_advanced/tch/otel_demo/`). Existing scripts are parameterized additively only, with regression diffs proving OB behavior is bit-identical. Locked TCH artifacts are read-only. All work happens on branch `otel-demo-cross-app` cut from `master-final-models`.

---

## Change log

| Date | Change | Rationale |
|---|---|---|
| 2026-06-01 | Charter created and locked | Pivot from "memory improves anomaly detection" (refuted) to "memory adds retrieval that scales with deployment history" (supported by depth stratification). |
| 2026-06-08 | §17 added: cross-app validation on OTel Demo | External-validity addition per `docs5/00` + `docs5/01`. Non-destructive: OB primary claim, dataset, and cascade unchanged. Adds a second locked corpus and a graded-difficulty (L1–L4) result axis. |
