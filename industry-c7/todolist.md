# C7 todo — review-2 response

**Paper:** Log-Guided Root-Cause Code Localization (ICSE 2027 Industry Challenge)
**Branch:** `v2-industry-track-review-2`
**Deadline:** 2026-11-13 AoE · **Started:** 2026-11-02 · **Days left: 10**
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
- [x] **B2. Fresh vLLM SLURM job.** Done 2026-11-03. Job 1225458 (1xH100,
      TP=1, 12 h) served Qwen3.8-27B on trig0012 and carried the full-split
      run to completion. The forward dropped three times and the SSH control
      socket hit its 8 h `ControlPersist` expiry once; the circuit breaker
      stopped the run cleanly each time and resume retried the affected rows.
      Total cost of all outages: 38 instances re-run, 0 lost. **HUMAN**

B1 and B2 are both closed. Everything still open is CPU-only except
T7, T17, T19 and Mahsa's point 3, which need a fresh vLLM job.

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
- [x] **T5. Scope the claim.** Done. New paragraph in §1 ("What
      'root-cause localization' means here, and what it does not") defines the
      task, states that the ground truth is fix-modified files and is a proxy
      for causation rather than a measurement of it, names the four things a
      fix commit mixes, and gives the annotation result with the size curve.
      It ends by saying what the evidence does and does not support, and that
      the title's "root-cause" is the challenge's framing, not a stronger
      claim. **CPU**

---

## P1 — Bigger agent evaluation (Priority 2, severity High)

- [x] **T6. Full evaluation split.** Done 2026-11-03: **4,409 / 4,409**,
      0 hard errors, 0 `llm_error`, every row `version: 3`, 0 duplicates,
      0 instances outside the population and none missed. Agent v3 scores
      **Acc@1 0.6870, Acc@5 0.8877**. Ran in ~11 h wall at 40 workers
      (~6.5/min) on one H100. `paper/agent-v3-full-results.md`. **GPU**
- [x] **T8. Per-project and per-stratum breakdown.** Done:
      `scripts/full_split_breakdown.py` scores **36 systems on the identical
      4,409**, including the IRBL family (their per-instance metrics live in
      `-irbl-instances.jsonl`; the `-irbl-rankings.jsonl` side files hold only
      the 93 causal-gold keys, which is why a rankings-only join finds 93).
      REMEMBER v3 leads the best baseline (model re-rank) by **+8.41 Acc@1,
      95% CI [+6.9, +9.8], significant**, and the margin widens on hard
      instances (59.5% vs 41.3%). Two things the paper must say: MariaDB is
      the weakest project (0.5802) and 27% of the split, so project-balanced
      samples read optimistic; and **Acc@1 rises with fix size**
      (0.669 at 1 file to 0.732 at 8+) because the answer key loosens, the
      mirror image of T3's causal share, so the 8+ figure is not better
      localization. `memory_arise` is reported **inactive, not 0.000**: ARISE
      votes load only for non-wolv2 projects and all four study projects are
      wolv2, so it is empty on all 6,314 scored instances by construction.
      It appears nowhere in the paper. **CPU**
- [x] **T9. Document the sampling.** Done in §IV-B. The section was also
      **wrong** and is now fixed: it still said the agent used the 790
      sample. Added the seed (42), that the draw is `random.sample` over the
      time-ordered split taken before any system ran, why the code samples on
      the unfiltered list and intersects with the scored set afterwards
      (filtering first changes the indices, hence the sample), and the
      direction of the bias: the sample is near-balanced across projects
      while the real split is 55% MongoDB and 27% MariaDB, so v3 reads 70.1%
      Acc@1 on the 790 against 68.7% on the full split. **CPU**

---

## P2 — Make the investigation causal (Priority 3, severity Very high)

Reviewer: do not add more tools. Add a structured strategy that forces a chain
of evidence from symptom to suspected cause.

- [x] **T10. Agent v3: required `causal_chain`.** Built. `submit_ranking`
      in v3 requires 2–6 ordered steps from symptom to named cause, each
      citing the tool result that shows it; per-file `evidence` stays
      required. `SUBMIT_V3` is a deep copy so v2's schema is untouched.
      Not yet measured — that is T12. **CPU** (build)
- [x] **T11. Backward reachability becomes structural.** Built.
      `callers_of` now runs in phase 0 on the report's stack-frame symbols,
      before the loop, like incident memory already does. Added
      `tools.frame_symbols()` (frames only, unlike `raw_report_symbols`
      which also returns any CamelCase word in the prose) and
      `data_flow_back(symbol)` — write sites rather than call sites, the
      data-flow counterpart to `callers_of`, sharing its grep cache.
      v3-only, so the v2 tool count stays at the 8 the paper reports.
      **Coverage measured, no GPU** (`scripts/prewalk_coverage.py`, n=160,
      seed 99 → `data/results/prewalk-coverage.json`): the hop fires on
      40.6% of the balanced study sample and a gold file is in the returned
      set on 19.4% (47.7% of the times it fires). Weighted to the real
      4,409 eval split it is **31.7% fires / 15.2% gold in walk**, because
      MongoDB is 55% of the split and the worst project for this (16.2%
      fires vs 52.5% kafka and 53.5% mariadb). Quote the weighted figure
      for the full run and the sample figure for the 790 study, never one
      for the other. The hop is a no-op where the report carries no usable
      frame, and the paper must say so. **CPU** (build)
- [x] **T12. Measure causal lift.** Done: `scripts/causal_lift_v3.py` plus
      `score_causal_gold.py --v3`. **The chain is the result, not an accuracy
      gain.** All 4,409 predictions carry a chain (mean 4.15 steps); 69.6%
      name at least one file; of those **99.9% contain the system's own ranked
      top-1**, so the chain is the same claim as the ranking rather than
      decoration. On the labelled subset every chain that named a fix-gold
      file named a *causal* one (**36/36**, n=59) - report the count, not the
      percentage. v3's fix-to-causal gap is **+1.19 points of Acc@5**, the
      smallest in the table with v2.
      **A confound that must not reach the paper:** the annotation sample's
      core stratum was balanced on `(v2 right/wrong) x (hard/easy)` using v2's
      own output, so half those instances are v2 failures. v2 reads 0.620
      Acc@5 there against 0.903 on the full 790; v3 takes no equivalent hit
      because it did not exist when the sample was drawn. v3's apparent +8.3
      over v2 on that subset is **selection, not skill** - on the full 790 the
      two are indistinguishable (Acc@5 delta -0.0025, CI [-0.0165, +0.0114]),
      in every stratum including hard. The scorer now prints a warning and
      `paper/causal-lift-v3.md` states it. **CPU**

---

## P2b — Fold the full-split results into the paper

Not in the original plan. It became necessary the moment T6 landed: the
paper was still reporting a 790-instance sample as its headline.

- [x] **T23. Move every headline number to the full split.** Done.
      `tab:study` is rebuilt on all 4,409 (REMEMBER 68.7 / 88.8 / .773 /
      80.3 hard, against 53.7 / 80.5 / .652 / 66.4 for the best non-agent
      system), and the abstract, §I contributions, §V-B, §V cost, §VI and §VII
      all follow. `fusion` is now computed on the full split by the same RRF
      `stats_agent.py` uses, so "best combination of non-agent systems" is a
      real measured row rather than a sample figure. **One claim was false
      and is gone:** the old text said the Acc@1 margin is "roughly three
      times" the Acc@5 margin; on the full split it is 1.2x to 1.8x
      depending on the comparison, and the paper now says that.
      verify_claims was repointed at `full-split-breakdown.json` for the
      rendered table and given exact checks for every delta the abstract
      prints. **CPU**
- [x] **T24. Write the P0 and P4 results into LaTeX.** They existed only as
      markdown. Added §V "Is the answer key the root cause?" (the rubric, the
      six roles, kappa 0.885 reported as model-model agreement and never as
      human reliability, the 49.0% headline, the size curve, the 84-instance
      re-score) and §V "Do the explanations point at anything real?" (chain
      coverage, the 99.9% chain-contains-top-1 figure, the three mechanical
      checks, the 36/36 causal result). Also folded T20 into the function
      section. Cross-reference check: 56 labels, 78 refs, 0 dangling. **CPU**

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

- [x] **T16. Mechanical checks.** Done: `scripts/explanation_checks.py`
      over all 4,409. **99.68%** of cited paths exist in the snapshot
      (15,050/15,098), 99.2% of instances have every cited path exist,
      **99.43%** of quoted line numbers fall inside the file, and 83.41% of
      quoted symbols occur in the cited file. The 48 bad paths are not noise:
      they are plausible paths with the wrong directory
      (`src/widgets/widgets/qwidget.cpp`; Qt keeps it in `kernel/`).
      **The symbol rate is a floor on groundedness, not an error rate** --
      evidence may correctly name a symbol declared elsewhere, so it must
      never be written as "17% hallucinated". verify_claims asserts the doc
      carries that caveat. `paper/explanation-checks.md`. **CPU**
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
- [x] **T20. Function-level stage.** Done, and it worked. Pooled over the
      **4,132** eligible eval instances (identical set across all three
      variants), Acc@1 goes **0.2152 -> 0.2882** and Acc@5 **0.404 -> 0.529**.
      Two separable effects, and the paper must not conflate them:
      taking candidates from agent v3's top-10 instead of cond_ours' raises
      the **oracle ceiling** 0.7367 -> 0.8879 but moves Acc@1 only +1.89
      [+1.2,+2.7]; **ranking the functions the agent opened by name with
      `read_code` is the larger half, +5.42 [+4.3,+6.5]**, total +7.31
      [+6.0,+8.5] over the current stage, all three significant. It is an
      attention signal, not a relevance model, and it is free because the
      transcripts already existed. Per project the gain tracks the old
      ceiling: kafka 0.240 -> 0.421 (ceiling was already good), qt
      0.140 -> 0.216 (gains mostly from candidates, oracle 0.576 -> 0.853).
      No leak: `read_code` targets are chosen from the report and tools under
      the memory firewall, and gold functions come from the fix diff the
      agent never sees. `paper/function-stage-t20.md`. **CPU**
- [x] **T21. Engineer-facing walkthrough.** Done: new
      §VI "What this changes at triage", built on a real run rather than an
      invented one. KAFKA-9747 is hard (the report names no gold file), the
      lexical layer ranks no gold file first, and v3's four-step chain walks
      REST API -> `KafkaConfigBackingStore` -> `DistributedHerder.tick()` ->
      `processConnectorConfigUpdates()` and ranks the gold file first. The
      section argues three things the rank alone does not give: the account is
      checkable without trusting it (99.7% of cited paths exist), it fails
      visibly (the chain contains the top-1 in 99.9% of cases), and it changes
      the first hour rather than the fix. States plainly that no developer
      study was run, so nothing here is measured as time saved. **CPU**
- [-] **T22. Developer study.** Dropped. Explicitly optional in the CFP and it
      does not fit 11 days.

---

## Cut line for 11 days

**Must land:** T1–T5, T6, T8, T9, T10–T12, T21.
Done except **T5, T9, T21** — all three are writing, no compute.

**Should:** T13–T15 (CPU), T16 done, T18 blocked behind T17.

**Nice:** T7, T17, T19 (all GPU), T20 done.

The binding constraint is no longer compute or annotation. It is the four
paper-writing rows (T5, T9, T21 and folding the new results into the
sections), plus the fact that **the PDF has never been rebuilt** — there is
no LaTeX toolchain on this machine.

Still owed, not yet scheduled:
- the human-verified annotation subset that `RUBRIC.md` pre-registers (B1)
- Mahsa's point 3, an existing-agent baseline (**GPU**)

---

## Rules that stay in force

- Every new number gets an exact check in `scripts/verify_claims.py` (333
  now). Pin to the value **stored in the JSON**, not the one printed to the
  screen: three checks were written from rounded output this session and all
  three failed. No ranges, no `or` fallbacks. A loose `0.3 or 0.4` check is how a
  wrong number reached the reviewer.
- Verify the justification, not just the number. "No localizer can be right
  about these" was written twice and was false both times.
- Agent behaviour that matters goes in the schema, not the prompt. v1 left
  evidence optional (37% of runs recorded none); v2 asked for backward
  reachability (0.01 calls/run). Instructed-but-optional gets skipped.
- Rescore every baseline on the exact instances a new system ran. Never
  compare across populations.
- Do not `scancel` jobs or kill WSL processes blindly. The SSH control socket
  carries the only MFA'd session.

---

## Progress log

| Date | What moved |
|---|---|
| 2026-11-02 | Review-2 read; plan and this tracker written. Confirmed all four repos are local (4.8 GB, full history), so P0 needs no cluster. Confirmed the vLLM job ended 2026-11-01, so all GPU work is blocked on B2. |
| 2026-11-02 | P0 closed except T5: T1–T4 done, T2b gives kappa 0.885 on causal-vs-not and the headline reproduces under both raters. Scored set applied, verify_claims 284/284. |
| 2026-11-03 | Full-split run finished: 4,409/4,409, 0 errors, agent v3, Acc@1 0.6870 / Acc@5 0.8877. T6, T8 and T12 closed; B2 closed. v3 does NOT beat v2 on ranking (790 paired, Acc@1 -0.0215, CI [-0.0456,+0.0013], ns) - its contribution is the guaranteed causal chain, not accuracy. Caught a selection confound that made v3 look +8.3 over v2 on the causal-gold subset: that sample was stratified on v2's own outcome. `data_flow_back` was called **1 time in 4,409 runs** - the third repeat of "instructed-but-optional gets skipped", and the two v3 changes that were structural (required chain, phase-0 prewalk) both fired as designed. verify_claims 320/320. |
| 2026-11-03 | T16 (99.68% of cited paths exist, 99.43% of quoted lines, 83.41% of symbols - the last is a floor on groundedness, not an error rate) and T20 (function Acc@1 0.2152 -> 0.2882; better candidates raise the oracle 0.7367 -> 0.8879 but move Acc@1 only +1.89, while ranking the functions the agent actually read is +5.42). Then T5, T9, T21, and the paper rewrite the full-split run forced: tab:study rebuilt on 4,409, causal-gold and explanation sections written into LaTeX for the first time, a false "roughly three times" claim removed, and §IV-B corrected where it still said the agent used the 790 sample. verify_claims 344/344. |
| 2026-11-02 | Three defects found in `run_agent.py` while sizing the full-split job, all fixed before any GPU time was spent: the adjusted `n_dev` was being applied to the unfiltered benchmark and pulled 24 MongoDB dev instances into eval; there was no code path for the full split at all (`SAMPLE_N=200` hardcoded); and a second exclusion rule (`TESTY`) had drifted from `scored_set.py`. Also `bridge.sh` still defaulted to a node from a job that ended Nov 1, which would have returned empty for every call of a 15 h run. T10/T11 built behind `--version 3`, default stays 2. |
