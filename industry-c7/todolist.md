# C7 todo — review-2 response

**Paper:** Log-Guided Root-Cause Code Localization (ICSE 2027 Industry Challenge)
**Branch:** `v2-industry-track-review-2`
**Deadline:** 2026-11-13 AoE · **Started:** 2026-11-02 · **Days left: 11**
**Now:** Borderline / Weak Reject, 6.8/10, 35–45% accept
**Design doc:** `paper/review-2-plan.md` (why each task exists)
**Review:** `paper/review-2.md`

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked · `[-]` dropped
Needs: **CPU** (laptop, no cluster) · **GPU** (needs vLLM job) · **HUMAN** (user effort)

---

## Blockers — decide these first

- [x] **B1. Second annotator for the causal study?** Answered 2026-11-02: no
      second human is available, so the annotator is Claude Opus 5 against a
      pre-registered rubric, and the second rater will be an independent model
      pass. Reported as exactly that, never as human ground truth. Still
      outstanding: the agreement number itself (see T2b). **HUMAN**
- [ ] **B2. Fresh vLLM SLURM job.** Job 1211031 ended 2026-11-01 20:05 ET, so
      the server is down. Every GPU task below is blocked until a new job runs
      and the MFA'd SSH tunnel is open. **HUMAN**

All of P0 is CPU-only and unblocked. Start there while B2 is pending.

---

## P0 — Causal ground truth (reviewer Priority 1, severity Very high)

The objection: fix-modified files mix up four different things — the file
holding the defect, the file that reported the failure, a file changed to stop
recurrence, and incidental refactoring. Four of the eight weaknesses in the
review follow from this one gap.

- [x] **T1. Annotation kit.** Done. `annotation_sample.py` (seed 20261102)
      and `annotation_render.py`. Sample grew to 151 over 27 projects, not 4,
      because it was drawn from benchmark-v2. Agent outcome deliberately not
      stored in `sample.json` so it cannot reach the annotator. **CPU**
- [x] **T2. Annotate.** Done: 151 of 151 labelled against `RUBRIC.md`,
      0 invalid, compiled to `data/causal-gold/`. Conventions that emerged
      while applying the rubric are recorded in `annotation/CONVENTIONS.md`
      and must be disclosed beside the rubric. **One rater.**
- [x] **T2b. The agreement number.** Blind second pass by a different model
      (Claude Sonnet 5.5, six parallel raters, rubric and schema only, no
      sight of pass 1 or of CONVENTIONS.md). Cohen's kappa **0.885** on
      causal vs not, 0.793 on the full six-role scheme, 0.504 on `relation`
      (the weakest field, and not used to build causal-gold). Identical
      causal set on 136 of 151 instances. T3 is 49.0% under rater 1 and
      50.1% under rater 2, and the size curve falls monotonically under
      both. T4 re-scored under rater 2 gives the same gaps to within a tenth
      of a point. Written up in `paper/annotation-agreement.md`. Reported as
      model-model agreement, never as human reliability. **Still owed:** the
      human-verified subset that RUBRIC.md pre-registers.
- [x] **T3. Headline number.** 49.0% of fix-modified gold files are causal
      (171/349), mean 71.8% per instance, median 100%. The result that
      matters is the curve: 89% causal when the fix touches 1 file, 57% at
      2–3, 30% at 4–7, 21% at 8+. Gold is accurate for small fixes and
      increasingly diluted for large ones. 14 of 151 have no causal file.
- [x] **T4. Re-score on causal gold.** `scripts/score_causal_gold.py`, no
      re-runs needed: 93 of the 151 annotated instances exist in v1 with the
      same gold and the same snapshot, 84 of those have a causal file, and
      every system already stored a ranking for them. Ordering survives;
      every system loses 1.2 to 4.8 points of Acc@5, and REMEMBER loses least
      (+1.2) with 95% of its top-1 hits landing on a causal file. Nine pairs
      change order, all of them already tied on both keys at n=84, so the
      subset confirms nothing about the top of the table and the paper says
      so. Written up in `paper/causal-gold-results.md`. **CPU**
- [ ] **T5. Scope the claim.** Define "root-cause localization" in §1 before
      using it. Say plainly that the ground truth is fix-modified files and
      point to the annotation study. The title keeps "root-cause" (it is the
      challenge's own name) but the paper states what it has and has not
      shown. **CPU**

---

## P1 — Bigger agent evaluation (Priority 2, severity High)

- [ ] **T6. Full 4,508 evaluation split.** About 15 h at 20 workers, 21 h at
      14. Fits one 24 h job, and the harness is already restart-safe. Retires
      the "only 790 instances" objection instead of arguing it.
      **GPU** · needs B2
- [ ] **T8. Per-project and per-stratum breakdown.** Re-analysis of T6, no
      extra GPU. **CPU** · needs T6
- [ ] **T9. Document the sampling.** The seed, that the sample was drawn
      before any system ran, and the test-only-gold removal with its
      conservative-direction evidence, made visible from the agent section.
      **CPU**

---

## P2 — Make the investigation causal (Priority 3, severity Very high)

Reviewer: do not add more tools. Add a structured strategy that forces a chain
of evidence from symptom to suspected cause.

- [ ] **T10. Agent v3: required `causal_chain`.** Ordered steps from symptom
      to cause in `submit_ranking`, each citing a tool result, enforced by the
      schema. Same mechanism that made `evidence` required in v2, which was
      worth +14.0 points of hard Acc@1. Proven on this system. **CPU** (build)
- [ ] **T11. Backward reachability becomes structural.** `callers_of` sits at
      0.01 calls per issue because the model never asks. Auto-run it on the
      top stack-trace symbol in Phase 0, the way incident memory already is.
      Add `data_flow_back(symbol)`. **CPU** (build)
- [ ] **T12. Measure causal lift.** Score v3 against causal-gold from T4, not
      just fix-gold. This is the measurement the reviewer asks for. Report it
      either way: a null result here is still a finding.
      **GPU** · needs T4, T10, T11, B2

---

## P3 — Realistic noise (Priority 4, severity Medium–high) — all CPU

The current dup / generic / foreign / drop arms are a fair start but are not
production bundles. These run on the laptop, so they fill GPU wait time.

- [ ] **T13. Mixed-incident interleaving.** Time-order lines from k concurrent
      incidents of one project. Different from `foreign`, which splices with
      no temporal structure. **CPU**
- [ ] **T14. Cascading failures.** Append downstream timeout, retry and
      circuit-breaker errors caused by the primary fault, so the decisive line
      is buried under consequences rather than noise. **CPU**
- [ ] **T15. Missing decisive evidence.** Delete the single highest-signal
      line (largest BM25 contribution to a gold file), not every file mention.
      Sharper than the current `drop` arm. **CPU**

---

## P4 — Evaluate the explanations (Priority 5, severity Medium)

The challenge asks for an explanation linking symptoms, log events and code.
We produce one and never score it.

- [ ] **T16. Mechanical checks.** Does the cited path exist in the snapshot,
      does the cited line exist, does the cited symbol occur there? Fully
      automatic, no judge needed. **CPU**
- [ ] **T17. Judged correctness.** A different model as judge on whether the
      evidence truly links report symptom to log event to code region,
      calibrated on about 50 human-rated examples. **GPU + HUMAN** · needs B2
- [ ] **T18. "Right answer, wrong reason" rate.** Of correct top-1 rankings,
      what share carry a correct explanation? Fits the paper's existing
      honest-negatives style. **CPU** · needs T16, T17

---

## P5 — Generalization and leftovers

- [ ] **T7. Three seeds** on the 790 sample, mean with CIs. One seed today;
      reviewer severity Medium–high. About 8 h. **GPU** · needs B2
- [ ] **T19. Second model.** GLM-5.3-Flash was already staged on the cluster.
      Shows the gain is architectural, not one model's quirk. About 4–6 h.
      **GPU** · needs B2
- [ ] **T20. Function-level stage.** Acc@1 of 13.2–25.9% is weak, and it is
      our only "code region" result. Try ranking the functions the agent
      actually read (nearly free once T6 transcripts exist) before falling
      back to reframing it as a baseline with the oracle ceiling as the
      headline. **CPU** · needs T6
- [ ] **T21. Engineer-facing walkthrough.** What an engineer sees at triage,
      what the ranked list plus evidence gives them, and how it changes the
      work. Industrial *relevance* is required by the CFP; deployment is not.
      **CPU**
- [-] **T22. Developer study.** Dropped. Explicitly optional in the CFP and it
      does not fit 11 days.

---

## Cut line for 11 days

**Must land:** T1–T5, T6, T8, T9, T10–T12, T21. Covers every Very-high and
High row in the review.

**Should:** T13–T15 (CPU, runs during GPU waits), T16, T18.

**Nice:** T7, T17, T19, T20.

The binding constraint is not compute. It is annotation effort in T2 and the
B1 decision.

---

## Rules that stay in force

- Every new number gets an exact check in `scripts/verify_claims.py` (266
  now). No ranges, no `or` fallbacks. A loose `0.3 or 0.4` check is how a
  wrong number reached the reviewer.
- Rescore every baseline on the exact instances a new system ran. Never
  compare across populations.
- Do not `scancel` jobs or kill WSL processes blindly. The SSH control socket
  carries the only MFA'd session.

---

## Progress log

| Date | What moved |
|---|---|
| 2026-11-02 | Review-2 read; plan and this tracker written. Confirmed all four repos are local (4.8 GB, full history), so P0 needs no cluster. Confirmed the vLLM job ended 2026-11-01, so all GPU work is blocked on B2. |
