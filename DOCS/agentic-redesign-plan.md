# Remedy → ARIA: A Fully-Agentic Redesign Plan (ICSE 2027)

**Status:** Synthesis v1 (2026-06-29). Integrates the best-scoring, best-validated elements of all four
adversarially-reviewed paradigms (react-reflexion, orchestrator-worker / CONCLAVE, hypothesis-scientist / ADL,
grounded-meta-policy / SAGE), drops their fatal flaws, and applies every referee fix. This is the build spec.

**Working name:** **ARIA** — *Autonomous Retrieval-grounded Incident Agent*. (Drop the "Remedy / capability-gating"
branding to the level of one mechanism, per supervisor critique #2.)

---

## 0. TL;DR for the impatient builder

- **Spine (depth-first, the one thing we must nail): Compound-incident decomposition on REAL clusters**, scored with
  set-recall@k / cluster-F1, **benchmarked against a deterministic KG-decompose-then-retrieve-then-union baseline**
  (NOT against single-shot Hit@5). This is the only surface where a fixed pipeline is *structurally* blind and where
  real gold already exists on disk.
- **Three secondary RQs** carry the other payoffs without over-claiming: (A) live re-retrieval recovery on a
  pre-registered, non-circular tail; (C) grounded+calibrated diagnosis with an *isolating* citation-validator baseline;
  (D) emergent tool/retriever policy framed as **off-distribution / zero-shot-tool generalization**, NOT an OB Hit@5 win.
- **One honest headline:** *"ARIA matches the 0.970 retriever on the head (provably, by construction) while adding
  three capabilities a fixed pipeline cannot express — set-valued compound retrieval, grounded calibrated diagnosis,
  and an emergent tool policy that generalizes off-distribution — and we quantify the price of that autonomy."*
  **We never claim "beats 0.970 aggregate Hit@5."**
- **The single new piece of agentic infrastructure:** a **re-planning runner** (model emits the next action each step,
  replacing the frozen `plan.invocations` for-loop) + a **live retriever subsystem** (closes the documented
  reformulation no-op). Everything else reuses existing primitives.

---

## 1. EXECUTIVE SUMMARY

The current system is, by the supervisor's own (citable) test, a **Routing workflow** — `RuleController` maps a
`window_type` label to a fixed branch of skills with hand-set numeric gates. We replace this with a genuinely
autonomous agent: an LLM that **emits its next action each step** from a model-callable tool library, **reflects** on
uncertain trajectories, **decides its own stopping**, and **decomposes compound incidents** into per-component
sub-investigations — all over a 38,642-ticket episodic memory of resolved incidents.

The thesis is **selective, grounded autonomy**: agency is spent only where a fixed pipeline *structurally cannot win*
(set-valued compound retrieval, grounded diagnosis, off-distribution tool routing, the ambiguous tail), and is
**provably constrained to never regress the strong Hybrid-RRF retriever** (the documented −5 Hit@1 rerank trap and
−0.272 Hit@5 verifier trap are retired by a hard non-regression invariant, not hoped away).

**What changes vs. the "workflow":** control flow moves from engineer-owned (`_select_branch` if/elif, fixed gate
constants) to **model-owned** (per-step action emission, model-chosen tools, dynamic stop). The window-type branch
table becomes an **oracle baseline** we beat off-distribution, not the policy.

**Headline claim (honest):** ARIA *matches* the 0.970 retriever on the saturated head **by construction**, and on the
axes a single ranked list cannot express it delivers **significant, defensible wins** — set-recall@k / cluster-F1 on
real compound incidents over a deterministic decomposition baseline; grounded, citation-faithful, calibrated
diagnosis; and an emergent tool policy that matches an oracle on-distribution and **beats it off-distribution / on
held-out tools** — at a quantified autonomy cost (frontier vs. local Qwen).

---

## 2. REPOSITIONING & NARRATIVE

### 2.1 Tone down "capability gating" (critique #2)
"Capability gating" is demoted from headline contribution to **one safety guardrail among several** — specifically the
mechanism that lets the agent *emergently rediscover* "don't run the net-harmful WoL verifier" from feedback, rather
than hardcoding `VerifierCalibration`. The "cuts cost 78%" number is **retired as a headline** (it is an OB-synthetic
artifact: gating is inert on WoL where every window is `active_fault` with no numeric features). It survives only as
one *point on the Autonomy Operating Characteristic (AOC)* — and we show the old `RuleController` is a single
**dominated** point on that curve.

### 2.2 Reframe the contribution as genuine autonomy (critique #1)
We adopt Anthropic's *Building Effective Agents* taxonomy explicitly and put the **agent-vs-workflow discriminator
table** in the paper (control of process, tool selection, planning, reflection, stopping, trajectory, feedback loop).
We *name our own old system* as a Routing workflow and show, mechanism-by-mechanism, that ARIA satisfies each
discriminator with a tested mechanism (per-step action emission = model owns control flow; emergent tool choice;
reflection; dynamic stop) — not prose.

### 2.3 Turn synthetic-trivial / real-hard into a STRENGTH that DEFENDS the dataset (critique #4)
We do **not** question our own data. We argue the synthetic-trivial / real-hard split is **field-consensus**:
- Cite **Cloud-OpsBench** ("the transition to agentic RCA necessitates benchmarks that evaluate *active reasoning*
  rather than *passive classification*") — our RQ4 finding (classification saturates synthetic, at-chance on real WoL)
  is the *same thesis the field is converging on*.
- Cite **ITBench** (SOTA agents resolve 11.4% of SRE scenarios) to establish the task is genuinely hard and "throw a
  frontier LLM at it" is not a free win.
- We pre-empt "is WoL gold reliable?" with a **human spot-check** that produces a Cohen's κ on the load-bearing gold —
  specifically **cluster membership** ("are these tickets one compound incident, or temporal co-occurrence?"), since
  the decomposition headline rests on it. This converts the dataset from a liability into a validated asset and is the
  direct answer to "it can question the proposed dataset then."

### 2.4 The "tie is not a win" problem (critique #3) — solved by changing the scoreboard
Referees unanimously flagged that a non-regression guard makes aggregate Hit@5 a **tie by construction**. We therefore
**never headline aggregate Hit@5**. We headline the axes with structural headroom (set-F1, grounded faithfulness,
AOC area, off-distribution routing) and present non-regression as a *design property in one sentence*, with the entire
burden of proof on **net-positive AOC area** and **set-metric wins over the correct deterministic baseline**.

---

## 3. PROBLEM FORMULATION

**Agentic incident triage as autonomous, memory-grounded diagnosis.**

**Input** (per window `w`): a telemetry window *or* a text-only incident report, with fields available in the data
(`window_id, scenario_family, service_name, triage_evidence_text, severity, …`), and access to:
- an **episodic memory** `M` = 38,642 resolved tickets (the corpus + KG extractions),
- a **tool library** `T` (retrieval skills + ReAct evidence tools + composition + live re-retrieval),
- a **budget** `B` (tokens / wall / usd / calls).

**Agent output** `O(w)` is a *structured triage record*, not just a ranked list:
1. `matched_precedents`: a **set** (possibly partitioned into sub-incidents) of memory ticket ids, each rank-ordered;
2. `decomposition`: optional partition of `w` into sub-incidents with per-component precedents;
3. `diagnosis`: a grounded narrative — root cause hypothesis + matched precedents + recommended remediation, **every
   claim citing a retrieved precedent id**;
4. `decision`: `page | no-page | ABSTAIN` with a calibrated confidence;
5. `trajectory`: the full audited action sequence (for trajectory-quality eval).

**Evaluation contract (the new scoreboard):**
- **Head (≈85–97% of windows):** O's `matched_precedents[0]` MUST equal the retriever's confident top-1 whenever
  retriever confidence > τ. This is a **hard, unit-tested invariant** (not a soft floor) — non-regression is provable.
- **Tail / compound / novel strata:** scored on **set-recall@k, cluster-F1, faithfulness, calibration/risk-coverage,
  trajectory quality, tool-efficiency**, each against a *fair, set-/cost-optimized baseline*.
- Every contrast carries paired-bootstrap CIs with Benjamini-Hochberg correction (reuse `eval_harness/bootstrap.py`).

---

## 4. THE AGENT ARCHITECTURE

### 4.1 Control loop — the re-planning runner (the one substantive new agentic piece)
Replace the frozen execution loop (`runner.py:245-251`, which iterates a static `plan.invocations`) with a
**per-step decision loop**:

```
state <- initial_observation(w, cheap_retrieval_prior)
while not done and budget.ok():
    action <- LLM.decide_next_action(state, tool_library, memory, reflections)   # structured-output (chat_json schema)
    result <- execute(action)            # action ∈ tool_library ∪ {REFLECT, DECOMPOSE, DEFER/STOP}
    state  <- update(state, result)
    if action == REFLECT: reflections.append(critique(state))     # Reflexion
    done   <- LLM.decide_stop(state) OR non_regression_satisfied  # dynamic stopping
finalize(state) -> O(w)   # enforce non-regression invariant + citation validation as a HARD post-filter
```

- **Model owns control flow.** Tool selection, ordering, fan-out, and stopping all emerge from the model's reasoning
  via `ctx.llm.chat_json(schema=…)` (the existing structured-output path). This is the literal refutation of "every
  decision is if/elif."
- **Cheap-first prior, not cheap-first gate.** The loop is *seeded* with the O(1) cached Hybrid-RRF prior so the head
  is answered for free; the model then decides whether any further action has positive expected value. This keeps the
  bulk run cheap (cached predictions for the head, frontier calls only when the model escalates).

### 4.2 Model-callable TOOL LIBRARY (reuse by exact name + the new ones)
**Reused, predictions-backed (O(1), head path):** `triage_numeric`, `retrieve_dense` (BiEncoder),
`retrieve_hybrid_fusion`, `retrieve_hybrid_fusion_llm`, `retrieve_knowledge_graph`, `retrieve_log_sequence`.
**Reused composition (trace-readers):** `compose_l2`, `compose_triage`, `compose_novelty`.
**Reused ReAct evidence tools (OB/OTel data-lake; auto-drop on WoL via capability gating):** `request_pod_events`,
`request_extended_trace_window`, `request_pod_metrics`, `request_similar_incident_window`, consumed by
`rerank_with_evidence` (inherits its `min_overlap_for_boost` "never demote confident top-1" discipline).
**New tools (the structurally-missing capabilities):**
1. **`live_retrieve`** — the genuinely-new capability. A live BiEncoder/SPLADE/Neo4j query over the 38,642-ticket
   index that can re-query a *reformulated or hypothesis-conditioned* string (the current predictions are
   window-keyed and cannot re-query — the documented no-op in `reformulate_query.py:21-26`). Built via the documented
   live-model extension point (`predictions_backed.py:30-32`), subclassing to override `invoke()`. **This is real new
   infra, not a one-line override** — it is scoped, budgeted, and benchmarked for latency/cost (see Risk R3, Roadmap P1).
2. **`decompose_incident`** — model-emitted partition of `w` into sub-incidents (by reasoning, optionally seeded by KG
   `affected_services/components/error_classes`), each dispatched to a per-component retrieval.
3. **`emit_diagnosis`** — structured `GroundedReport` (root cause + cited precedents + remediation + page/no-page/abstain).
4. **`REFLECT`, `DEFER/STOP`** — first-class meta-actions (defer = identity = return the retriever prior unchanged).

### 4.3 Memory (episodic + semantic)
- **Semantic memory** = the 38,642-ticket corpus + KG extractions (the retrieval substrate). This *is* the
  language-agent episodic store (Generative Agents / Voyager lineage) — we frame triage-by-retrieval as memory recall.
- **Episodic trajectory memory** = stored reflections + successful/failed action sequences (Reflexion store). **Guard
  against the "overfitting relabeled as emergence" critique:** trajectory memory is populated ONLY from the train
  split and is **never** the mechanism that produces the OB retriever-selection result (see §5.D). Off-distribution
  generalization is tested with trajectory memory *disabled* to prove the policy is reasoning-driven, not lookup.

### 4.4 Planner & emergent tool selection
No branch table. The planner is the LLM's `decide_next_action`. For evaluation we **compare its emergent tool choices
against the old `window_type→branch` table treated as an oracle routing policy** (routing-agreement metric, §5.D).

### 4.5 Reflection / self-correction
On low-confidence or contradictory evidence, the model emits `REFLECT`: a verbal self-critique appended to context
(Reflexion). Bounded by budget; the loop-detection guard (`tool_protocol.py`, threshold 3) and `MAX_TOOL_CALLS`
become *active* constraints (they never bind today).

### 4.6 Dynamic stopping
The model emits `STOP` when it judges evidence sufficient; the loop also force-stops when the non-regression invariant
is satisfied and no positive-EV action remains. This is the "model decides when evidence suffices" discriminator.

### 4.7 Multi-agent decomposition for compound incidents (orchestrator–worker, the spine)
For windows the planner flags as compound, an **Incident-Commander** emits a decomposition and dispatches **parallel,
hypothesis-scoped Investigator sub-agents** (each runs the loop scoped to one sub-incident over the substrate), then
**synthesizes** a partitioned `matched_precedents` set. This is genuine orchestrator–worker control (decompose /
dispatch / synthesize / finalize are real structured-output decisions). Sub-agents reuse the same tool library and
the same non-regression discipline.

### 4.8 The "grounded autonomy" guarantee — never regress vs the 0.970 retriever
Three stacked, *tested* mechanisms (synthesis of all four proposals' best safety ideas):
1. **DEFER = identity.** The default action returns the retriever prior unchanged. The agent can only ADD/group/annotate.
2. **Protected prefix / hard top-1 invariant.** A unit-tested invariant: `O.matched_precedents[0] == retriever_top1`
   whenever `retriever_confidence > τ_conf`. Not a soft heuristic — a post-filter that *cannot* be violated.
3. **Counterfactual commit gate.** Any agent action that would change the returned set is committed only if it does
   not lower a validation-estimated lower-confidence-bound on head accuracy. τ_conf is **calibrated on val** so head
   Hit@5 CI-lower-bound ≥ anchor.

This retires both documented traps by *construction* and is presented as a one-sentence design property — the *result*
burden is elsewhere.

### 4.9 Budget / safety
Reuse `Budget` (tokens/wall/usd/calls), `StateLayer` (ring buffer + page suppression), `Trace` (full audited event log
→ trajectory eval), `SkillCache`, hallucination guard `validate_tool_request` (`tool_protocol.py:253-281`). Frontier
calls are *only* on escalated/compound/tail windows; the head is cached.

### 4.10 Backend story
- **Frontier-primary (headline):** a Claude/GPT-class model as the autonomous planner (strong planning/tool-use).
- **Local-Qwen ablation (reproducible, low-cost):** the same loop on offline Qwen2.5-7B via the existing provider
  abstraction (`llm/factory.py` + `providers/{anthropic,openai,ollama,vllm,lm_studio}`). The **frontier-vs-Qwen delta
  is the "price of autonomy" result** — cheap to run, high value, and de-risks the cost story.
- **LLM-judge de-confounding:** any judge-based metric uses a *different model family* than the agent (avoid
  frontier-judges-frontier shared blind spots), gated on judge↔human κ above a pre-stated threshold.

---

## 5. HOW EACH OF THE 4 PAYOFFS IS ACHIEVED & MEASURED

### Payoff B — Compound-incident decomposition (THE SPINE / primary headline)
- **Mechanism:** §4.7 orchestrator–worker decomposition; returns a *set* (partitioned by sub-incident).
- **Why agency is necessary:** single-shot Hit@5 rewards finding *one* gold; on WoL ≈99.8% of retrieval-evaluable test
  windows have ≥2 gold tickets. A ranked list is structurally blind to returning the correct *set*.
- **Metric:** **set-recall@k and cluster-F1** over the **2,456 REAL WoL clusters** (gold on disk:
  `window-memory-matchings.jsonl`), plus **per-sub-incident recall on OTel multifault** (where injected faults give
  TRUE, non-circular sub-incident gold).
- **THE BASELINE THAT MATTERS (all four referees demanded it):** a **deterministic KG-decompose-then-retrieve-per-
  component-then-union** pipeline (split by `v2_kg_extractions` `affected_services/components/error_classes`, retrieve
  per component, union) AND a **deep-flat retriever** (hybrid top-k for k=20/50) + agglomerative/MMR clustering. The
  agent must beat **these**, not single-shot. **Go/no-go (Phase 0):** run the deep-flat + deterministic-decompose
  baselines FIRST; if they are already near-ceiling on set-recall@20, **pivot the headline to OTel multifault +
  diagnosis**, and report "decomposition, not agency, is the win" honestly if the agent only ties.
- **Anti-circularity:** the gold partition is **never** derived from the same KG signal the agent consumes. We grade
  per-sub-incident gold on (i) OTel injected-fault ground truth, and (ii) the human-validated cluster-membership
  subset. We state explicitly in the paper that cluster-F1 is not graded against the agent's own decomposition seed.
- **VERIFIED-GROUNDING ADDENDUM (2026-06-29, measured on disk):** OTel-multifault — the cleanest TRUE-gold surface —
  is **statistically thin**: of the 247-window OTel resplit-test, only ≈61 windows are multifault/concurrent/cascade
  families and only ≈15–25 of those are `active_fault` (where the compound fault is actually present and decomposition
  is meaningful). At that n, a BH-corrected paired-bootstrap contrast will almost certainly be **underpowered** →
  treat OTel-multifault as **clean-gold DIRECTIONAL/qualitative corroboration**, not the powered headline. The
  **quantitative spine therefore MUST be the WoL clusters** (2,456; the only large real compound surface). Implication:
  the human-κ validation of WoL cluster membership (§2.3, §7.1) is *even more load-bearing* than stated — it is the
  thing standing between "powered real-data decomposition headline" and "thin directional result." Also note the OTel
  multifault YAMLs DO carry exploitable gold structure (`cascade_primary_target`/`cascade_secondary_target`,
  `composition_type`, `difficulty_level: L1/L2/L3`, full component set, `root_cause_category`) — rich for the
  qualitative case study and the L1/L2/L3 difficulty ladder, just not for a powered CI.

### Payoff A — Autonomous recovery on the tail (secondary RQ; honest about power)
- **Mechanism:** `live_retrieve` (§4.2) — hypothesis-conditioned re-retrieval that adds evidence the static index
  never saw (data-lake pod-events/traces/peers on OB/OTel; KG-neighbor expansion + reformulated live query on WoL).
  **Justification it can beat RRF recall (referee demand):** it must add NEW evidence (live re-query / data-lake), not
  re-phrase over the same frozen index — otherwise it is the −5 Hit@1 rerank trap and we CUT it.
- **Stratum:** a **pre-registered, non-circular** hard slice defined on features INDEPENDENT of hybrid's own errors:
  `is_novel=True` (1,623 windows), `cluster-size≥2`, `triage_reason_class != other` (≈3,440 windows),
  `coarse-but-no-strong-gold` (788 windows). Hybrid-miss@5 recovery is reported ONLY as a clearly-labeled,
  selection-biased *secondary diagnostic*.
- **Metric:** Hit@5 / set-recall on the slice. **Power analysis up front:** report the MDE for paired-bootstrap+BH at
  n≈155 (full-test miss) and n≈3,440 (reason-class slice). If the tail is underpowered, we report it as
  **directional-only** and lean on the larger slices — pre-committed, not post-hoc.

### Payoff C — End-to-end grounded diagnosis + action (secondary RQ)
- **Mechanism:** `emit_diagnosis` → `GroundedReport` with a **hard citation validator** (every claim must cite a
  retrieved precedent id; uncited claims dropped).
- **Metrics (with ISOLATING baselines — the referee fix):**
  1. **Faithfulness/groundedness** — fraction of claims with valid precedent citations. **Baseline: single-shot
     frontier + the SAME citation validator.** Only a gain over THIS isolates the *loop* from the *validator*.
  2. **Remediation correctness (objective signal, not just citation-validity):** where the matched precedent is a
     resolved ticket, check whether the recommended remediation matches the precedent's actual held-out resolution
     text (retrieval-style precision). This gives a scalable correctness signal beyond "the id was retrieved."
  3. **Calibration / risk-coverage for page/no-page/ABSTAIN.** Given RQ4 (WoL ticket-worthiness PR-AUC 0.506), we do
     NOT assume abstention is calibrated — we **test whether the abstention score is discriminative** (AUROC of the
     abstain signal ≫ 0.5; retained-set accuracy rises monotonically as coverage drops). If it is not, we reframe
     "knows when not to act" *qualitatively* and do not claim a quantitative calibration win.
  - Faithfulness denominator tied to the **human-verified subset only** (de-circularize: don't measure groundedness
    against unreliable gold).

### Payoff D — Emergent tool/retriever policy (secondary RQ; reframed to off-distribution)
- **Mechanism:** the planner's emergent tool choices (§4.4), trajectory memory OFF for the generalization test.
- **The win that survives review = OFF-DISTRIBUTION, not OB Hit@5.** We **do not** headline "emergent policy picks
  BiEncoder on OB (0.634>0.559)" — every referee flagged it as (a) a 1-bit decision reproducible by a one-line val
  policy and (b) contradicting our own "OB is trivial" reframing. Instead:
  - **On-distribution:** show the emergent policy *matches* a trivial **best-retriever-per-dataset validation policy**
    AND matches the `window_type→branch` oracle (routing-agreement) — cheaply. (A match, not a claimed win.)
  - **Off-distribution / held-out tools / unseen evidence regimes:** show the emergent policy **generalizes where both
    a rule table and a supervised classifier have no entry/label**. This is the one regime that *distinguishes the LLM
    from a logistic gate* and is the actual headline for D.
- **Metric:** routing-agreement vs oracle (on-dist), and task metric on held-out-tool / unseen-regime splits (off-dist).

---

## 6. RESEARCH QUESTIONS

- **RQ1 (spine, B):** Can an autonomous decomposition agent return the correct *set* of precedents for real compound
  incidents better than a deterministic KG-decompose-then-union and a deep-flat-retrieve-then-cluster baseline
  (set-recall@k, cluster-F1)? On which dataset/stratum, and is the gain BH-significant?
- **RQ2 (C):** Does the abductive/grounded diagnosis loop produce more faithful, more correct, better-calibrated
  triage reports than a single-shot frontier baseline *with the same citation validator*? Is the abstention signal
  discriminative on real WoL despite at-chance classification?
- **RQ3 (D):** Do the agent's tool choices, emerging from reasoning, match an oracle routing policy and a supervised
  gate on-distribution, and **generalize off-distribution / to held-out tools** where both have no entry?
- **RQ4 (A + autonomy):** On a pre-registered non-circular hard slice, does live hypothesis-conditioned re-retrieval
  recover misses the frozen retriever cannot — and what is the shape of the **Autonomy Operating Characteristic**
  (accuracy/recall retained vs autonomy budget spent), with the old `RuleController` as a single dominated point?
- **RQ5 (rigor/dataset defense):** Is the real WoL compound-incident gold reliable (human κ on cluster membership),
  and what is the price of autonomy (frontier vs local Qwen cost/accuracy)?
- **RQ6 (non-regression, stated as property + verified):** Across all strata, does the agent provably never regress the
  Hybrid-RRF head (unit-tested invariant + empirical head Hit@1/5 within CI)?

---

## 7. EXPERIMENTAL DESIGN

### 7.1 Datasets + strata
- **3 existing datasets** via `build_harness_for_dataset`: OB (full stack), OTel (multifault, true sub-incident gold),
  WoL-v3 (real; 13,388 test / 38,642 memory / 2,456 clusters).
- **Curated HARD slice — derived empirically (note: `is_hard_case` is UNPOPULATED in WoL-v3, all False).** A
  **versioned, pre-registered derivation script** producing strata on signals INDEPENDENT of hybrid's errors:
  `is_novel`, `cluster-size≥2`, `triage_reason_class != other`, `coarse-but-no-strong-gold`. Hybrid-miss is a
  separate, labeled, secondary diagnostic slice only.
- **Human spot-check (150–200 cases, 2 raters, Cohen's κ):** concentrated on **cluster membership** ("one compound
  incident vs temporal co-occurrence") — the load-bearing gold for the spine — plus a smaller diagnosis-faithfulness
  rater pass. (~40 cases is too thin; budget 150–200 on the cluster question specifically.)

### 7.2 Baseline ladder (every rung answers a specific referee objection)
1. **Retrieval-only:** Hybrid-RRF (0.970), BiEncoder, BM25, KG-alone. (Head anchor.)
2. **Current deterministic `RuleController`** (the workflow we replace; also the oracle routing policy for D).
3. **Deterministic set baselines (REQUIRED for B):** (a) KG-decompose→retrieve-per-component→union; (b) deep-flat
   hybrid top-k (k=20/50) + agglomerative/MMR clustering.
4. **Vanilla-ReAct** (no anchor / no memory / no reflection / no non-regression guard) — included specifically to show
   it **regresses**, turning the central risk into a measured result.
5. **Frontier-no-agency** (single-shot frontier, no loop) — for C, *plus* a variant **with the same citation validator**
   (isolates the loop from the validator).
6. **Supervised LearnedController** (LogReg/GBT escalation gate over the deterministic uncertainty signals) — the
   self-defeating baseline we MUST run: if it matches the agent on-distribution, we pre-commit that the contribution
   is the **off-distribution/zero-shot-tool** regime (D), not on-distribution accuracy.
7. **Best-retriever-per-dataset validation policy** (one-line) — the trivial baseline for the OB selection decision.
8. **FrugalGPT / RouteLLM-style cost-cascade + selective-prediction (Geifman–El-Yaniv) risk-coverage** — cited and
   differentiated for the AOC (novelty-overlap fix).
9. **Component ablations:** −live_retrieve, −reflection, −decomposition, −citation-validator, −non-regression-guard,
   frontier↔Qwen.

### 7.3 Metrics
- **Retrieval:** Hit@1/5/10, MRR (reuse `eval_harness/metrics.py`) — head, reported for non-regression only.
- **Set/compound:** set-recall@k, cluster-F1, per-sub-incident recall.
- **Diagnosis:** faithfulness (cited-claim fraction), remediation precision vs held-out resolution, LLM-judge quality
  (cross-family judge, κ-gated).
- **Calibration:** ECE, AUROC of abstain signal, risk-coverage curve.
- **Agentic axes (instantiate the 2025–26 standard):** trajectory quality (tool-selection/argument correctness, order
  satisfaction, path efficiency — TRAJECT-Bench-style), tool-efficiency (calls/tokens/usd per resolved window),
  the **Autonomy Operating Characteristic** (accuracy/recall vs autonomy-spend, defer/abstain as first-class actions).
- **Cost:** frontier vs Qwen $ and wall per window (price of autonomy).

### 7.4 Significance
Reuse `eval_harness/bootstrap.py`: `paired_bootstrap_delta`, `benjamini_hochberg`, `bootstrap_eval_report`
(N=1000, seed 42). Report **per-stratum** CIs. **Pre-register** strata definitions and τ_conf/τ_voi sweep grids
BEFORE running; report on the full set too. Up-front **power analysis / MDE** for every small-n stratum; underpowered
contrasts are reported directional-only, not spun as wins.

---

## 8. RISK REGISTER (brutally honest)

| # | Risk (how this yields a WEAK result) | Mitigation |
|---|---|---|
| R1 | **Agent only ties the deterministic decompose/deep-flat baseline** (the spine's headroom evaporates). | Phase-0 go/no-go runs those baselines FIRST. If near-ceiling, pivot headline to OTel multifault + diagnosis; report "decomposition not agency is the win" honestly. Don't build the agent until the gap is measured. |
| R2 | **Non-regression makes Hit@5 a tie-by-construction** → reviewer computes the 0.2pt aggregate delta and rejects. | Never headline aggregate Hit@5. Present non-regression as a one-sentence design property; burden of proof on set-F1 / AOC area / off-dist routing. Pre-empt the 0.2pt computation in the abstract. |
| R3 | **`live_retrieve` is unbuilt infra mis-sold as a one-line override** → payoff A has no working mechanism; cost model breaks. | Treat live BiEncoder/SPLADE/Neo4j over 38,642 tickets as a first-class subsystem (Roadmap P1), measure its latency/cost, cached head + live tail cost model. If Trillium can't host it, DROP A-as-headline and report it as a negative/ablation — do NOT fall back to the net-harmful no-op reformulation. |
| R4 | **Tail too small (n≈155)** → CI contains 0, BH suppresses. | Pre-registered non-circular larger slices (reason-class ≈3,440; novel 1,623); up-front MDE; directional-only labeling; never headline the 155. |
| R5 | **Per-sub-incident gold is circular** (graded against the same KG seed the agent uses). | Grade only on OTel injected-fault gold + human-validated cluster membership; state explicitly cluster-F1 is not graded against the agent's seed. |
| R6 | **Faithfulness win is the validator, not the loop.** | Mandatory "single-shot + same citation validator" baseline arm. |
| R7 | **Abstention is calibrated-but-useless** (0.5-AUC signal). | Test discriminative power (AUROC, monotone risk-coverage) before claiming; else reframe qualitatively. |
| R8 | **LearnedController == agent on-distribution** → "your LLM agency is decorative." | Pre-commit the falsifier: contribution becomes the off-distribution/zero-shot-tool regime. Headline that regime, not on-dist accuracy. |
| R9 | **OB-selection win contradicts "OB is trivial."** | Drop OB Hit@5 as a headline; keep OB only as routing-agreement/off-dist. Resolve in writing. |
| R10 | **Cost blows up** (frontier on 13,388 windows). | Cached head; frontier only on escalated/compound/tail/sampled-head. Qwen ablation bounds cost. Budget caps enforced. |
| R11 | **Non-determinism hurts reproducibility.** | Fixed seeds, temperature 0 where possible, persisted `Trace` for every run (replayable), report variance across seeds, release trajectories. |
| R12 | **Reviewer STILL says "workflow"** (agency gated by a hand-coded stratifier — critique reappears one level up). | The head/hard routing decision is made BY THE MODEL (a scored first-pass call), compared to the heuristic oracle as part of RQ3 — not a hardcoded `if head defer`. The stratifier is for *evaluation slicing*, not for *gating the agent*. |
| R13 | **Cluster gold is temporal co-occurrence, not causal compound incidents** → decomposition solves an artifact. | Human κ on "is this one compound incident?" BEFORE building the headline on it. |
| R14 | **Scope is 2–3 papers** (every leg shallow). | Depth-first: B is the spine; A/C/D are bounded secondary RQs. Cut metrics/baselines not tied to a chosen payoff. Keep frontier+Qwen (cheap, valuable). |
| R15 | **Novelty overlaps uncited FrugalGPT/RouteLLM/selective-prediction.** | Cite and differentiate Geifman–El-Yaniv, FrugalGPT, RouteLLM explicitly; our delta = grounded triage-by-retrieval + non-regression + real compound gold. |

---

## 9. IMPLEMENTATION ROADMAP (mapped to the codebase)

**Phase 0 — De-risk the headline BEFORE building the agent (go/no-go #1).**
- Add `eval_harness/set_metrics.py`: `set_recall_at_k`, `cluster_f1`, `per_subincident_recall`.
- Implement deterministic baselines: `src/baselines/kg_decompose_union.py` (split by `v2_kg_extractions`, retrieve
  per component via existing predictions, union) and `deep_flat_cluster.py` (hybrid top-k=20/50 + agglomerative/MMR).
- Run on WoL clusters + OTel multifault. **GO if** deterministic baselines leave headroom on set-recall@20; **NO-GO/pivot**
  to OTel+diagnosis if near-ceiling.
- Pre-register: strata derivation script `scripts/research-lab/derive_hard_slices.py` (versioned), τ sweep grids,
  power/MDE report.

**Phase 1 — Core agentic infra.**
- `src/agent/runner/replanning_runner.py`: per-step `decide_next_action` loop replacing the static-plan for-loop
  (`runner.py:245`). Keep `Trace`, `Budget`, `StateLayer`, `SkillCache` intact.
- `src/agent/skills/live_retrieve.py`: subclass the predictions-backed base, override `invoke()` to drive live
  BiEncoder/SPLADE/Neo4j (extension point `predictions_backed.py:30-32`). Stand up the live index on Trillium; measure
  latency/cost. **Go/no-go #2:** if live infra infeasible, drop A-as-headline.
- Non-regression stack: `src/agent/safety/non_regression.py` — DEFER=identity, hard top-1 invariant (unit-tested),
  counterfactual-commit gate; τ_conf calibrated on val.

**Phase 2 — The four payoffs.**
- B: `src/agent/orchestrator/commander.py` + `investigator.py` (decompose/dispatch/synthesize); `decompose_incident`
  tool. **(Spine — most engineering effort here.)**
- C: `src/agent/skills/emit_diagnosis.py` (`GroundedReport` schema) + `src/agent/safety/citation_validator.py`
  (hard post-filter); remediation-vs-held-out-resolution scorer in `eval_harness/diagnosis_eval.py`.
- D: emergent-policy eval `eval_harness/routing_agreement.py` (vs `RuleController` oracle + held-out-tool splits);
  trajectory-memory toggle for the off-dist test.
- A: wire `live_retrieve` + reflection into the loop on the pre-registered slice.

**Phase 3 — Eval + agentic axes.**
- `eval_harness/trajectory_quality.py` (tool-selection/order/path-efficiency), `aoc.py` (Autonomy Operating
  Characteristic; plot RuleController as a dominated point), cross-family LLM judge harness with κ gating.
- Baselines: vanilla-ReAct, frontier-no-agency(±validator), LearnedController, best-retriever-per-dataset,
  FrugalGPT/RouteLLM cascade, selective-prediction risk-coverage.
- Reuse `bootstrap.py` for all CIs/BH; per-stratum reporting.

**Phase 4 — Human study + write-up.**
- 150–200-case cluster-membership κ + diagnosis-faithfulness rater pass.
- Frontier vs Qwen price-of-autonomy run.
- Tables/figures (§10).

**Go/no-go checkpoints:** (#1) Phase-0 deterministic-baseline headroom; (#2) live_retrieve feasibility; (#3) after
Phase 2, agent beats deterministic decompose baseline on set-F1 with BH significance on ≥1 real stratum — if not, the
paper pivots to "decomposition + grounded diagnosis + AOC, agency demoted," reported honestly.

---

## 10. PAPER OUTLINE & POSITIONING

1. **Intro** — incident triage as memory-grounded autonomous diagnosis; the agent-vs-workflow problem; thesis of
   selective grounded autonomy; honest headline ("matches 0.970, adds what a list cannot").
2. **Background & Motivating Example** — the WoL compound-incident vignette; the agent-vs-workflow discriminator table
   (Anthropic taxonomy); we name our old RuleController as a Routing workflow.
3. **Problem Formulation** (§3) — inputs/outputs, the new evaluation contract, non-regression as a property.
4. **ARIA Architecture** (§4) — re-planning runner, tool library, memory, orchestrator–worker decomposition, the
   grounded-autonomy guarantee. **Fig 1:** control loop. **Fig 2:** decomposition orchestrator.
5. **Experimental Setup** — datasets, pre-registered strata, baseline ladder, metrics, significance, human study.
6. **Results** —
   - **Table 1 (spine):** set-recall@k / cluster-F1, ARIA vs deterministic-decompose vs deep-flat-cluster, per stratum, BH.
   - **Table 2:** grounded diagnosis — faithfulness/remediation-precision/calibration vs single-shot±validator.
   - **Table 3:** routing-agreement (on-dist) + off-distribution / held-out-tool generalization (D).
   - **Fig 3:** Autonomy Operating Characteristic, with RuleController as a dominated point + FrugalGPT/selective-pred
     baselines.
   - **Table 4:** non-regression verification + price-of-autonomy (frontier vs Qwen).
   - **Table 5:** ablations (vanilla-ReAct regresses; −live/−reflect/−decompose/−validator/−guard).
   - **Table 6:** human κ on cluster membership + diagnosis faithfulness.
7. **Related Work** — agent-vs-workflow (Anthropic); ReAct/Reflexion/Plan-and-Solve/ToT/LATS; cloud-incident lineage
   (**Ahmed'23** generation-in-isolation; **RCACopilot** = alert-type Routing workflow we replace; **D-Bot** = single-DB
   self-diagnosis); benchmarks (**AIOpsLab** AgentOps vision we operationalize for triage-by-retrieval; **ITBench** 11.4%
   = task is hard; **Cloud-OpsBench** active-reasoning-over-classification = corroborates our reframing; **SREGym**
   compound faults but synthetic vs our REAL clusters; **MicroRemed/ThinkRemed** remediation we defer-to-retrieval
   against). Cite FrugalGPT/RouteLLM/Geifman–El-Yaniv for the AOC. One-line gap statement: none studies autonomous
   triage-by-retrieval over a real heterogeneous resolved-incident memory with provable non-regression.
8. **Threats to Validity** — selection bias (pre-registration), small-n strata (power analysis), gold reliability (κ),
   judge confounds (cross-family), non-determinism (seeds + released traces).
9. **Conclusion / Data Availability.**

**Positioning one-liner:** *We operationalize the AgentOps vision for the one lifecycle stage AIOpsLab under-specifies —
triage-by-retrieval from a real resolved-incident memory — replacing RCACopilot's alert-type Routing workflow with an
emergent, provably-non-regressing agent, and evaluating it with trajectory-level and autonomy-operating-characteristic
metrics most agentic papers lack.*

> **CITATION-INTEGRITY CAVEAT.** The 2025–26 prior art above (ITBench "11.4%", Cloud-OpsBench, SREGym,
> MicroRemed/ThinkRemed, AIOpsLab) was surfaced by an automated literature pass and is **NOT yet author-verified**.
> This repo already has one unverifiable-citation incident (the "World of Logs" / `xiao2026worldoflogs` key — see
> `DOCS/` notes), so **every one of these keys must be checked against a real DOI/arXiv/proceedings record before it
> enters `refs.bib`**, and any unverifiable claim (e.g. the exact "11.4%") dropped or re-sourced. Do not ship a
> number you cannot point to a stable record for.

---

## 11. OPEN DECISIONS FOR THE AUTHOR (with recommendations)

1. **Headline payoff if Phase-0 baselines are near-ceiling on WoL set-recall.**
   *Recommendation:* pivot to OTel-multifault decomposition (true gold) + grounded diagnosis as co-headlines; keep WoL
   set-recall as a secondary. Decide AFTER Phase 0 — do not pre-commit the WoL spine blindly.
2. **Build live_retrieve subsystem, or drop payoff A?**
   *Recommendation:* attempt the live index on Trillium (it's the only structurally-new capability). Hard go/no-go at
   Phase 1; if infeasible, demote A to an ablation/negative result — never ship the no-op reformulation as "recovery."
3. **Frontier model choice (Claude vs GPT-class) for the headline.**
   *Recommendation:* Claude-class as primary (strong tool-use), GPT-class as a robustness check on the spine table
   only (cost-bounded). Qwen2.5-7B as the reproducible local ablation regardless.
4. **LLM judge family.**
   *Recommendation:* judge with a different family than the agent; gate every judge claim on κ ≥ 0.6 (pre-stated).
5. **How much of the head to run through the agent (cost).**
   *Recommendation:* cached retriever on 100% of the head; frontier only on escalated/compound/tail + a 10% random
   head sample (to verify non-regression empirically, not just by construction).
6. **Does the model make the head/hard routing decision, or a heuristic?**
   *Recommendation:* the MODEL emits a first-pass head/hard call that is itself scored (vs the heuristic oracle) — this
   is what keeps critique #1 answered (the "where to be an agent" decision is part of the learned policy, R12).
7. **Pre-registration mechanics.**
   *Recommendation:* commit the strata-derivation script, τ grids, and power analysis to the repo with a tagged commit
   BEFORE running headline cells, and cite the tag in the paper.

---

### Provenance
Synthesized from the repo audit (Grounding Brief A), the agentic-framing/literature brief (Grounding Brief B), and the
four adversarial referee critiques (react-reflexion, orchestrator-worker/CONCLAVE, hypothesis-scientist/ADL,
grounded-meta-policy/SAGE). Every fatal flaw flagged by ≥1 referee has a corresponding mitigation in §8; every
"salvageable idea" is incorporated in §4–§5; every "fix" is reflected in §7/§9.
