# ARISE v2 — work plan

**Branch:** `v2-research` (from master @ 7ddfd53)
**Target:** fresh submission (FSE / ASE / ICSE'28), not an ICSE major revision
**Novelty strategy:** learned cost-sensitive escalation controller (§P2)
**Started:** 2026-10-01

Source reviews: `ICSE/reviewers-comments/R{1,2,3}.txt`.
Evidence backing the diagnoses below: `scripts/rebuttal/` (see its README).

---

## The strategic read

The three reviews split into two very different problems.

The **listed questions are all rigor and clarity** — every one is fixable, and
several already have their answers computed in `scripts/rebuttal/`. But all
three reviewers independently scored **Novelty = 2 ("Incremental")**, and *not
one of them raised it as a question to the authors*. That means a rebuttal
cannot move it. Fixing only what was asked gets us to weak accept and stops
there.

So v2 has two jobs, and the second one is the one that decides the outcome:

1. Repair the rigor and clarity defects (P0/P1 below).
2. Replace the weak half of the contribution — hand-tuned threshold gating —
   with a **learned escalation policy** that has a stated objective and a
   cost-quality Pareto result (P2).

---

## P0 — Correctness. These are errors in the published record, not weaknesses.

### 1. The "collapses to chance" claim is wrong
The WoL triage classifiers were fed the 94 `triage_feature_*` columns, which
`build_wol_real_corpus_v3.py` zero-fills unconditionally — **0 of 78,140 rows
has a non-zero feature**. The reported ROC-AUC 0.500 / PR-AUC 0.506 is a
degenerate constant predictor. Our own artifact reports the CI as exactly
`[0.5000, 0.5000]`, which should have caught it.

Re-run on the input the corpus actually has (text): **ROC-AUC 0.572–0.601**,
CI excludes 0.500. The qualitative conclusion survives — 1.000 on injected
telemetry vs ~0.59 on real tickets — but "no better than chance" must go from
the abstract, intro, §VII-D, §VIII and conclusion.

### 2. ARISE's own 0.506 triage accuracy is partly self-inflicted
The controller emits a third `borderline` decision for suppressed pages on
**3,061 of 13,388** windows, which binary resolution-derived gold can never
score correct. Fix the label-space mapping and re-run.

Related: `pages_per_incident = 1.0` is structural — `n_incidents ==
n_pages_emitted == 7505` — so the ratio is 1.0 by construction and is not
evidence of anything. Replace with suppression count and rate, or drop it.

### 3. Cost is estimated, not measured
§VI-C says "measured per window as wall-clock time and language-model token
usage". It is gate-skip counting priced with a hardcoded `PER_SKILL_COST`
table in `scripts/agent/cost_vs_cascade.py`. Instrument real measurement and
re-run adaptive vs run-all on identical hardware.

Also correct the narrative: WoL's 78% is almost entirely **one** gated skill
(`reformulate_query`, 10,566/13,376 skipped). "The saving grows with scale" is
really "the reformulation gate closes more often on WoL".

### 4. The artifact ships WoL-v2 while the paper reports v3
`scripts/agent/bundle_dataset_for_publication.py:44` hard-codes
`2026-06-15-wol-real-v2-global`. `make_release_archives.sh` correctly uses v3;
the publication bundler does not. R1 scored the artifact "Partially
Satisfactory" for exactly this.

Also **quarantine `jira-memory-corpus.jsonl`**: its `memory_text` embeds a
literal `Components: X, Y` line (100% of gold component names present). It is
*not* what was indexed — the humanized loader is — but it ships unlabelled, and
anyone reproducing from it gets leaked results.

---

## P1 — Evidence the reviewers asked for

### 5. Blinded human relevance + page-worthiness study ← highest value
R1-Q1 and R2-Q1 both demand it; `ICSE/response.txt` already promises it as "our
top priority". It is the only thing that converts the construct-validity
objection from *unanswered* to *answered*.

- judge the **actual top-ranked results** from ARISE and baselines, blinded —
  not the gold
- **hard negatives from the same project**, not uniform draws from 38,642 items
- ≥2 annotators, documented rubric, Cohen's/Fleiss kappa
- second axis per R1-Q3: page-worthiness (urgent / valid-not-urgent / no action)

Our own judge data already concedes the point: **only 6.3%** of coarse-gold
matches were rated ≥4/5 — a number the submission omitted.

### 6. Rebuild the LLM judge with hard negatives, calibrate against humans
Report the full prompt and sampling procedure (R3: currently undocumented), and
give the judge a measured human-agreement number so it can be used at scale.

### 7. Every baseline under both relevance relations, with significance
R2 asked directly. The strict numbers exist in the result JSONs and were never
reported. Strict-relation leaderboard (n=4,362), already computed:

| Method | Hit@1 | Hit@5 | MRR@5 |
|---|---|---|---|
| **Hybrid fusion (ours)** | **0.511** | **0.744** | **0.602** |
| BGE (zero-shot) | 0.474 | 0.706 | 0.564 |
| TF–IDF | 0.445 | 0.715 | 0.559 |
| E5 (zero-shot) | 0.450 | 0.698 | 0.544 |
| Cross-encoder rerank | 0.418 | 0.694 | 0.523 |
| Dense bi-encoder (ours) | 0.260 | 0.523 | 0.356 |
| BM25 (raw corpus) | 0.015 | 0.740 | 0.332 |
| Knowledge graph (ours) | 0.016 | 0.036 | 0.023 |

Still to do: re-run TF-IDF and MPNet retaining per-query predictions (currently
missing, so they could not enter the paired tests), and run LLM-RAG under the
strict relation.

**Promote the strict relation to co-headline.** 0.744 against a 0.0044
random-ranker baseline is more defensible than 0.970 against 0.036, and it is
what survives scrutiny.

### 8. Five seeds on all three datasets, including WoL
R3-Q1, and promised in `response.txt`. Measured so far:

| Dataset | Seed SD | Sampling SD | Seed share of variance |
|---|---|---|---|
| Online Boutique | 0.018 | 0.026 | **32%** — not negligible |
| OTel Demo | 0.005 | 0.043 | 1.2% |
| World of Logs | *trained once* | — | **unknown — this is the gap** |

Report seed-aware intervals `sqrt(SD_seed² + SD_sample²)` everywhere a CI
appears, and plot per-seed points in Fig 3.

### 9. Figure 4 confidence intervals
R3-Q2. Already computed. Two consequences:
- "extended-trace reader is net-harmful" **survives but only in isolation**:
  −0.018 Hit@1, CI [−0.033, −0.006] against the empty tool set; only −0.003,
  CI [−0.009, +0.000] on top of the peer lookup.
- "the peer-incident lookup is the only clearly beneficial tool" **does not
  survive** — +0.015, CI [−0.006, +0.033] includes zero. Withdraw it.
- On OTel and WoL every tool effect is identically 0.000. Report it; it
  *supports* the argument that the controller's value is in not running them.

### 10. Component-metadata quality and the undisclosed query-conditioning
R1 asked. Measured: 75.3% of issues carry ≥1 component (80.5% on test);
**1,621 of 6,773 held-out ticket-worthy queries (23.9%) have none** and so have
no gold by construction — which is exactly why the table says n=5,150 and not
6,773. That conditioning step was never disclosed.

### 11. Non-leakage evidence as a first-class validity section
R2's central attack. Four independent lines, none currently in the paper:
1. the indexed corpus has no `Components:` field (0/3,000); only 34.6% of gold
   component names appear anywhere in indexed text, 15.9% query-side
2. KG component vocabulary overlaps the gold vocabulary by **9.9%** (109/1,101)
3. the graph retriever is the **worst** system (strict Hit@5 0.036), and
   ±graph is non-significant everywhere
4. decisive: the component trained *on* coarse gold — our bi-encoder — degrades
   **most** under the strict relation (0.905 → 0.523, below zero-shot BGE)

### 12. Define `maxconf`, sweep the thresholds
R2-Q2. It is the max over retrievers of a calibrated ticket-worthiness
probability in [0,1] (`rule.py::make_reformulation_gate`) — **not** the fused
RRF score, whose ceiling R2 correctly computes as ~0.049. Observed WoL range:
0.177–0.862, median 0.510. Rename the symbol, specify where the score comes
from per configuration, and sweep both gates.

Note: on WoL the 0.90 gate **never fires** (0.0% of windows).

### 13. Incident-level system comparison
R1-Q4: Triangle (ASE'25), FLASH, DeepCT, COMET. We cite `chen2019triage` but
never name it as DeepCT or position against it. Build a task/capability table
from **primary sources only**, and reimplement what is reimplementable on our
public corpus as actual baselines.

---

## P2 — Novelty. This is what decides the score.

### 14. Learned cost-sensitive escalation controller ← primary contribution
Replace the hand-set 0.90/0.5 gates with a policy that predicts **whether
escalating will change the answer**, and spends budget only where predicted
value exceeds cost.

Why this is defensible rather than incremental:
- the counterfactual training data already exists — every cell in
  `paper-results/agent-value/*/{skill,tool}-cells` records what the answer *was*
  and *would have been* per window
- our own measurements show the current gates are poorly targeted: the 0.90
  gate never fires on WoL, and `reformulate_query` escalates on 2,810 windows
  with no measurable Hit@5 benefit — there is real, demonstrable headroom
- it gives R3's "favourite part" a method contribution with a stated objective

Target headline: a **cost-quality Pareto curve** where the learned policy
dominates both the hand-tuned gates and the run-all cascade. Ablate against
always-escalate, never-escalate, and random-escalate at matched budget.

### 20. Escalation-value training set ← prerequisite for #14
Join the ablation cells into one `window_id × configuration` table and derive
the per-window escalation-value label. Quantify the headroom up front: what
fraction of windows does escalation help / hurt / not change? The large
"no change" mass *is* the opportunity.

### 21. Paper restructure for fresh submission
New spine:
1. **Problem** — triage is retrieval over incident memory, under a cost budget,
   across heterogeneous evidence
2. **Findings** — the corrected empirical reframing; fusion conclusions *flip*
   between small synthetic and large real corpora; evidence tools are
   non-load-bearing. These negative results are our most surprising content and
   should be stated as findings, not buried in ablations.
3. **Method** — hybrid retrieval + the learned escalation policy. The policy is
   the contribution; fusion is supporting.
4. **Evaluation** — dual relations, human-validated, multi-seed, Pareto.

Demote: on-demand telemetry evidence-gathering (it is a negative result);
novelty detection (confounded on text-only corpora); any claim that
capability-gated telemetry reasoning transfers to production telemetry.

---

## P3 — Clarity (R3 scored Presentation 2, Verifiability 2)

### 15. Rewrite the formalism around a concrete incident definition
R3: *"it's never clear where the incident comes from, who wrote it, and what is
the core document behind the incident. I assume it is a jira ticket."* It is,
and we never said so. State it before any notation; say per dataset what
`d_j`, `E_j`, `tau_j` are drawn from; justify windowing (the window is the unit
at which the **label** exists).

### 16. Label provenance end-to-end
There is **no human labelling anywhere** in the submission — say so outright
instead of implying a manual process. Document all three label sources. Fix the
misleading "human-annotation kit" phrasing in §IX. Rename the real-data target
"resolution-derived labels".

### 17. Writing pass
- **Naming:** "Hybrid-RRF" appears in Fig 3 but nowhere in the text; RRF is used
  once in Algorithm 1 unexpanded. Also settle **ARISE vs "Remedy"** — commit
  7c64207 renamed the architecture, `main.tex` still says ARISE.
- **Training vs inference:** R3 thought fine-tuning might be per-incident and
  carried forward. It is a single offline once-per-dataset step; the model is
  frozen for every test query.
- Rewrite both flagged sentences; full editing pass for the same class.

---

## P4 — Infrastructure

### 19. v2 branch and Trillium runs
- ✅ branch `v2-research`; `*.tar.zst` now ignored (data.tar.zst, 11GB, was not)
- sync v3 corpus + code to Trillium, verify checksums
- reuse `scripts/research-lab/trillium_*.sbatch`
- **run registry**: one row per experiment with git SHA, seed, dataset id,
  config hash, output path — directly addresses the Verifiability=2 score
- re-run preflight: the SciNet switch failure (Sep 26–28) may have silently
  killed jobs
- budget GPU early: 5 seeds × 3 datasets (WoL ~3h each) + cascade panel per
  seed + judge + measured-cost runs

---

## Ordering

**Start now, long lead times dominate:** #19 (GPU allocation), #5 (recruit
raters).

**Cheap, data already computed — mostly writing up:** #7, #9, #10, #11.

**Dependency chain:** #19 → #20 → #14 → #21.

**Blocked on experiments:** #21 needs #1, #5, #14.
