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
T7, T17, T19 and T25, which need a fresh vLLM job.

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

- [x] **T13. Mixed-incident interleaving.** Done. `mixed` merges k
      concurrent incidents of the project keeping each stream in its own
      order (k = 2, 3, 5), which `foreign` destroys by inserting at
      independent positions. Mixed is **milder** than foreign at matched
      volume (+4.0, +6.1, +6.6 points pooled). The k=5 pairing uses
      foreign x5 because there is no x4 level, so it is flagged
      `mixed_pairing_exact: false` and is conservative in mixed's favour.
      **The reason is lexical, not positional** — a bag-of-words retriever
      cannot read order; drawing whole incidents introduces fewer distinct
      vocabularies than sampling lines from every issue. Say that, not
      "order matters". **CPU**
- [x] **T14. Cascading failures.** Done, and it is a **negative result**.
      `cascade` appends downstream timeouts, retries and circuit-breaker
      errors naming a symbol the report contains. The hypothesis was that
      on-topic noise competes with real evidence and costs more than
      unrelated noise. It does not: cascade lands within **0.9 points** of
      generic at every ratio. On-topic lines add no new vocabulary so they
      barely move a lexical score, while generic chatter introduces fresh
      terms that do. The doc picks its own heading from the sign of the
      data and ends "Reported as measured, not as hypothesised", which
      verify_claims asserts, so a later draft cannot restate the
      hypothesis as a finding. **CPU**
- [x] **T15. Missing decisive evidence.** Done, and it is the strongest of
      the three. `decisive` removes the **single** line whose tokens alone
      rank a gold file highest. Pooled, that one line costs **5.76 points**
      of Acc@5 against **11.88** for deleting every mention and stack
      frame: **one line is 48% of the entire mention-and-frame channel**.
      Log evidence is concentrated, not distributed. Two readings, both
      worth stating: a bundle that truncates before that line costs half of
      what losing the whole channel costs, and our benchmark is easier than
      production partly because the line is reliably present (identified
      for 200/200 instances in all four projects). Limit: "decisive" means
      decisive *for a lexical retriever*, since it is found by BM25 against
      the gold files. **CPU**

---

## P3b — Two defects found while adding the arms above

- [x] **T26. The noise experiment had a dev/eval leak.**
      `noise_robustness.py` read `data/benchmark/{p}.jsonl` directly
      instead of `load_bench`, then sliced it with the scored-set-adjusted
      `n_dev`. For MongoDB that is `3618 - 1061 = 2557` "eval" rows where
      the real split has 2434 — **24 development instances and 99 excluded
      instances in the pool it sampled from**. The same defect was found
      and fixed in `run_agent.py` on 11-02; this script was missed.
      `function_stage.py` was checked and is clean (it reads
      `{p}-instances.jsonl`, which localize.py already filters).
      verify_claims now asserts structurally that the experiment loads
      through `load_bench`. **CPU**
- [x] **T27. "Rescore every system" (f5068c9) skipped this experiment.**
      Every other artifact was regenerated on 11-02 20:59-21:24 when the
      scored set was applied; the noise summaries kept values computed on
      10-31 and were never revisited, so the paper's noise table has been a
      population behind since then. Regenerated all four. MongoDB moved
      most (the leak plus 123 removed instances), MariaDB by one instance
      in four conditions (the token caches were rebuilt on 11-02, which
      changes which blobs each `cat-file` batch fetches), Kafka and Qt not
      at all. **The pins were not silently refreshed** — the reason is
      recorded in `verify_claims` beside them.

      **Lesson for the next sweep:** "rescore every system" must mean every
      script that reads the benchmark, not every script in `data/results/`.
      Two of them did not route through `load_bench` and only one had been
      caught. **CPU**

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
- [x] **T17. Judged correctness. MODEL RATER DONE 2026-11-04; the
      human calibration pass is still open.** `scripts/judge_explanations.py`. A model other than the one
      under test grades whether the chain actually runs from the reported
      symptom, through the log evidence, to the code region it names, on a
      three-point rubric (sound / partial / unsound). 400 instances judged,
      50 of them also rated by a human so the judge is calibrated rather
      than trusted. Two raters, because the agent is Qwen and a Qwen judge
      grades its own work; second rater from a different family, same as
      T2b.

      **The judge is blind, and that is tested rather than asserted.** Not
      by searching the prompt for gold paths -- a report legitimately names
      the gold file on the easy stratum, and the agent legitimately names
      it when it is right. Instead the prompt is rebuilt with the answer
      key replaced by a sentinel; if the sentinel lands, the run refuses to
      start. Negative-control checked: it passes clean prompts and catches
      both an injected gold list and an injected `acc@1`.

      **Two defects found while building it.** The first guard flagged 2 of
      400 prompts because the REPORT named the gold file, which is not a
      leak at all. The second is the one that mattered: `query_text` is not
      on the agent result row, so `r.get("query_text", "")` returned empty
      and the judge would have graded 400 chains **with no issue report in
      front of it** -- grading prose, and the blindness guard would never
      have noticed, because it only looks for leaks and not for
      completeness. The report is now loaded from the benchmark.

      Packets for the human pass: `data/results/judge/packets/` (50).
      `--packets` / `--rate` / `--agreement`. **GPU + HUMAN**
- [x] **T18. "Right answer, wrong reason" rate. DONE 2026-11-04.** Of correct top-1 rankings,
      what share carry a correct explanation? Fits the paper's existing
      honest-negatives style. **CPU** · needs T16, T17

---

## P5 — Generalization and leftovers

- [x] **T28. Metric definitions (Mahsa, 2026-11-06). Code DONE, paper TODO.**
      Her point: Top-k only asks whether ONE ground-truth file was found
      and ignores the rest, so on multi-cause issues it overstates
      localization. She asked for Hit@k, Precision@k and Recall@k.

      Our `acc@k` was already Hit@k by the same rule, so that is a rename.
      `recall@k` already existed. Precision@k was the trap: **51.3% of our
      issues touch exactly one file, so a perfect answer at rank 1 scores
      1/5 = 0.2 at k=5.** Dataset-wide the Precision@5 ceiling is 0.425.
      Printing 0.239 bare makes a correct system look broken.

      `scripts/localize.py::evaluate()` now emits `hit@k` (alias of the
      old `acc@k`, which is kept so the 417 pinned claims still resolve),
      `recall@k`, `precision@k`, **`precision_ceiling@k`**,
      **`r_precision`** and **`ap`**. R-Precision and AP reach 1.0 on
      every instance, so they are the honest precision numbers for a
      benchmark with a variable number of right answers.

      Measured on the 4,409 run, agent-only ranking:
      Hit@1 0.687, Hit@5 0.879, Recall@5 0.667, **R-Precision 0.548**,
      AP 0.635, MRR 0.770, Precision@5 0.239 (ceiling 0.425, 56% of
      achievable).

      The split that must go in the paper, because Hit@k hides it:
      single-file (n=2260) Hit@5 0.864 / Recall@5 0.864 / R-Prec 0.669;
      multi-file (n=2149) Hit@5 **0.895** / Recall@5 **0.460** / R-Prec 0.422.
      Hit@5 is HIGHER on multi-file issues while recall collapses, because
      more gold files mean more chances to hit one. State it as a limit.

      STILL TODO: (a) rename acc@k -> hit@k in the LaTeX tables and
      figures; (b) add a metric-definitions paragraph to the evaluation
      section saying exactly the above, including the ceiling; (c) add the
      single/multi-file recall split as a limitation; (d) note that
      recall@10 has a ceiling of 0.624 on the 4.0% of instances with more
      than 10 gold files; (e) say gold is a fault LOCATION label (files the
      fix touched), not a root-cause label -- 89.2% of multi-file fixes
      stay inside one module, so multi-file usually means one cause with
      local ripple, and we have no annotation for cause count.

- [x] **T25. An agentic baseline (Mahsa's point 3). DONE 2026-11-04.**
      Her wording: "Add an existing localization agent with access to the
      same reports and snapshots, using the same model where supported and
      a comparable inference budget."

      **Built 2026-11-03: TWO arms, not one.** The user chose LocAgent
      (ACL 2025) and CoSIL (arXiv 2503.22424v3), the two agentic localizers
      already cited in related work.

      **Neither released repo runs on this benchmark, and the reason is
      not an input adapter.** Both build their code graph with Python's
      `ast` module, and both say so in print: LocAgent §3.1 ("we focus our
      study on Python repositories and leave codebases with other
      programming languages as future work", repeated in its Limitations),
      CoSIL's External Validity threat ("it remains uncertain whether CoSIL
      can generalize to other programming languages"). Our four projects
      are Java, Scala, C and C++ -- not one Python repo. The graph layer
      *is* the contribution in both papers, so replacing it is the port.
      Run as released they would localize nothing, on every instance.

      **So: their search strategies, our tree-sitter graph layer**, named
      "LocAgent-style" and "CoSIL-style" exactly as the paper already says
      "BRTracer-style". Never claimed to be the published systems.

      Files: `agent/codegraph.py` (contain/import/invoke/inherit edges over
      java, scala, cpp; LocAgent's `path:QualifiedName` entity ids),
      `agent/baselines.py` (both loops), `agent/BASELINES.md` (every
      deviation, written to be copied into threats to validity),
      `agent/test_baselines.py` (**35/35**, runs with no server),
      `run_agent.py --arm {ours,locagent,cosil}`. verify_claims +8 = 361.

      **Faithful on purpose, including the weaknesses.** Both papers parse
      a free-text answer, so neither baseline gets our structured
      `submit_ranking`: CoSIL's Table II reports LocAgent's **empty rate at
      13-22%** with Qwen models for exactly that reason, and repairing it
      with our engineering would void the comparison. CoSIL-style keeps its
      own fix (reflective alignment); LocAgent-style does not, because
      LocAgent has none. **Free sanity check on the port: CoSIL-style
      should show the lower empty rate.** If it does not, suspect the port
      before believing the result.

      Fairness held constant: same served model, temperature 0, same seed,
      same snapshot, same report *with logs*, same metric. LocAgent-style
      gets our full 14-turn budget (its Table 5 reports 6-9 rounds), so a
      loss cannot be blamed on budget. Withheld from both, because neither
      design has it: `recall_incidents`, our phase-0 pre-searches and
      pre-walked backward hop. That withholding is the thing being
      isolated.

      Both arms report `ranking` (their own output, empty allowed, scored
      as a miss the way CoSIL defines it) AND `ranking_fused` (the same
      lexical fallback ours gets), so no reviewer can argue the gap is our
      safety net.

      **Population: SETTLED on a stratified 1,000, with evidence.**
      Anchored on our own run, not an estimate: the 4,409 `v3-full`
      transcripts span 01:13-12:25 on 11-03, so **11.2 h elapsed** at 12.1
      LLM calls and 94k prompt tokens per instance. LocAgent-style is the
      same shape (~11 h on 4,409); CoSIL-style is the expensive arm at ~26
      calls per instance (~20-28 h). Both arms on the full split is 31-39 h
      = three or four overnight jobs. Both on 1,000 is ~8 h = **one job**.

      The argument for the full split was that a subsample forces every
      other system to be re-run. **It does not.** Every system already
      stores per-instance results keyed by issue_key, so a restricted score
      is a recomputation: `full_split_breakdown.py --subset=` rescores
      **all 37 systems in 6.4 s**. The same-population rule is satisfied
      for free.

      Population fixed on disk BEFORE any GPU time:
      `scripts/baseline_sample.py` ->
      `data/results/baseline-sample.json` (1,000, proportional over project
      x hard/easy, matching the full split to 3dp on every stratum) and
      `baseline-pilot.json` (30, drawn **disjoint**, because a pilot instance
      is one we will have looked at before fixing anything). Both come from
      ONE invocation so the pair regenerates byte for byte, and
      verify_claims pins both id digests -- the first version drew them in
      separate runs reading each other, and re-running it produced a
      different 1,000. Restricted to the 1,000 the headline barely moves --
      REMEMBER 0.667/0.885 against 0.687/0.888, same best baseline -- which
      is evidence the subsample is representative, measured before any
      baseline ran on it.

      **Order: pilot 30 first (~20 min), then the 1,000 (~8 h).** The pilot
      catches the two things that would waste the job: the model not
      calling the baselines' tools at all (the `qwen3_xml` failure, and
      "instructed-but-optional gets skipped" now measured three times), and
      the port's own sanity check that CoSIL-style shows the lower empty
      rate.

      **If it does not get run**, say so plainly in threats to validity:
      the comparison covers IRBL, lexical, retrieval+memory and a strong
      non-agent LLM pipeline, but no published *agent*. Do not leave it
      unmentioned. **GPU** · needs a fresh vLLM job

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

## P6 — Challenge coverage gaps (agent audit 2026-11-09)

Audit of `agent/` against the challenge PDF. Each row is one gap. Code for
T29–T36 lives in `agent/logs.py`, `agent/lc_agent.py` and `run_agent.py`;
all of it is scored by `scripts/c7_coverage.py`. The log layer can be
switched off (`--no-log-layer`) so its value is an ablation, not a claim.

- [~] **T29. CODE DONE 2026-11-09, needs the T38 run.** Affected module from the agent (output i).** Today the module
      is computed after the run by cutting file paths at `module_metrics.DEPTH`.
      Add a required `module` field to the submission, give the agent the
      project's module list in the briefing, and score agent-module against
      the collapsed-ranking module on the same rows. **CODE + GPU run**
- [x] **T30. DONE 2026-11-09 (`agent/logs.py`).** Select log events from the bundle.** Reports are pasted raw and
      cut at 18,000 chars (MongoDB max is 706,007). Mask variables into
      templates, collapse repeats, rank events (first error before later
      ones, generic timeout/retry lines down), number them E1..En, and
      compress the report so the cut drops repeats, not evidence. **CODE**
- [~] **T31. CODE DONE 2026-11-09, needs the T38 run.** Log-to-code retrieval.** Index the logging statements and
      exception messages of the snapshot (Java/Scala loggers, `throw new`,
      MariaDB `sql_print_*`/`ib::*`/`my_error`, MongoDB `LOGV2*`/`uassert`,
      Qt `qWarning`...). Match each selected event to the statement that
      printed it, then walk one hop back from that function. New tool
      `match_log`, plus the same probe in the preamble. **CODE + GPU run**
      **CPU result (`c7_coverage.py --log-sites --limit 300`, seed 42,
      `data/results/c7-log-sites.json`):** among eval reports whose log
      events match a statement in the snapshot, the printing file is a gold
      file in kafka 64/160 (0.40), mariadb 27/155 (0.17), mongodb 6/40
      (0.15), qt 0/10. So 60-100% of the time the code that printed the log
      is NOT the fixed file -- the challenge's third difficulty, measured.
      Coverage is the limit: qt matched only 10/300, mongodb 40/300.
- [~] **T32. CODE DONE 2026-11-09, needs the T38 run.** The explanation cites log events.** Required
      `ChainStep.log_event` (an event id or a quoted report line, empty when
      the step is about code). Check mechanically that each cited event
      exists in the report. **CODE + GPU run**
- [~] **T33. CODE DONE 2026-11-09, needs the T38 run.** Ranked code regions, not ranked files.** Allow several regions
      per file; give lexical-only files after fusion a region from their
      best-matching function (marked `source: lexical`). Score region
      Acc@K/MRR against `*-functions.jsonl` gold functions. **CODE**
- [x] **T34. DONE 2026-11-09 (`dependencies` tool).** Component dependencies.** Our agent never uses `codegraph.py`
      (only the baselines do). Add a `dependencies(path)` tool: imports and
      imported-by. **CODE**
- [~] **T35. CODE DONE 2026-11-09 (`c7_coverage.py`), needs a run.** Crash vs non-crash strata.** Report every metric on three
      strata: stack trace / log lines but no trace / prose only. Uses
      results already on disk plus the new run. **CPU**
- [~] **T36. CODE DONE 2026-11-09, dumps on CPU, needs the T38 run.** The agent under noise.** T13–T15 ran on the lexical pipeline
      only. `run_agent.py --noise COND:RATIO` perturbs the report with the
      same `noise_robustness.perturb`, seeded per instance. Run `generic:2`,
      `cascade:2` and `decisive` on the 1,000 sample. **GPU run**
- [x] **T37. DONE 2026-11-09 (§V agentic subsection).** Why not Rafi et al. [1] and RCAgent [2].** Paper text: [1] needs
      failing tests and coverage (not available at report time, our own
      premise); [2] targets cloud job RCA, is closed, and does not output
      code regions. Our LocAgent/CoSIL ports are the closest runnable
      agents. **WRITING**
- [ ] **T38. Runs.** (a) 30-instance pilot of the new schema first: the
      comments in `lc_agent.py` record that schema shape changes can stall
      decoding, so check `no_answer` rate before anything big. (b) 1,000
      sample, log layer ON vs OFF, same seed, paired. (c) T36 noise arms.
      **GPU**

- [~] **T39. CODE DONE 2026-11-09, needs a run.** Staged workflow arm (`--arm wf`, `agent/workflow.py`).**
      The free investigation loop is replaced by SHORTLIST -> EXAMINE (one
      file per step, fixed-form verdict) -> WALK BACK (code) -> RANK (cards
      only). Designed from `scripts/trace_analysis.py` over all 26,541
      answered rows of the main run (digest: `scripts/trace_decisions.py`,
      `data/agent/full/`): 83.2% of runs end only because the budget removed
      the tools; 72.7% of read_code calls re-read a file; a gold file is
      first named on turn 1 in 82.8% of runs and turns 4-14 add 5.1 points;
      55.8% of failures have gold in the list but not first, 79.2% of those
      READ gold, and the wrong top file was read later than gold in 67.7%
      (33.9% in right runs). `--arm lc` stays as the free-loop ablation.
      Diagram: `agent/AGENT-DIAGRAM.md`. **GPU run**

- [x] **T40. DONE 2026-11-10 (CPU). Would a code graph find the files the evidence misses? No.**
      `scripts/graph_headroom.py` on the 1,000 sample
      (`data/results/graph-headroom.jsonl`). A gold file is in the top-20
      seeds for 83.2% and in the evidence table for 87.8% (reformulation
      stubbed, so a lower bound). For the 122 where it is in neither, one
      hop of imports + callers + callees reaches a gold file in 18.9% while
      adding a median 84 files (0.23 gold per 100 added). The structure-free
      control, same-directory siblings of the top-5 seeds, reaches 36.9% at
      0.26 per 100. Upper bound on coverage gained by one graph hop: 2.3% of
      all instances. Not worth building for candidate generation.
- [~] **T41. CODE DONE 2026-11-10, pilot running.** Function-level localization.**
      `scripts/function_diagnosis.py` on 24,851 main-run rows with gold
      functions: top region right 48.2%; file wrong 33.8%; file right but a
      real wrong function 12.7%; file right but a function the file does
      not contain 5.3% (upper bound, C++ name bug in v3 rows). Given the
      right file the function is right 72.8%. In the 4,470 right-file
      wrong-function runs: gold function never on screen 32.0%, fix touches
      2+ functions of that file 39.1%. Changes: (1) EXAMINE shows the whole
      file or whole functions up to `C7_WF_FILE_CHARS` (24,000), (2) up to
      3 functions per file from the file's own list, (3) both arms: 2
      BM25-ranked functions per file after the agent's own, marked
      `lexical` (replayed on the main run by name: region acc@5 0.607 ->
      0.678, acc@10 0.607 -> 0.724, acc@1 0.482 unchanged).

- [ ] **T42. FULL RUN of the workflow arm, SUBMITTED 2026-11-10 ~02:15 on FOUR clusters.**
      Same five shards queued on nibi (26684057, 59-62), fir (3264075-79),
      rorqual (26266450-54) and trillium (1282728-32); narval left out (no
      agent venv, A100-40GB would serve at TP=2). The first five Nibi jobs
      (26681423-27) were cancelled while pending and replaced, because the
      job script changed.
      Each job runs, in order, skipping any tag another cluster already
      started: `wf-sN` (seed 42) -> `lc1000-sN`, `wfoff1000-sN`,
      `wfnoise-{generic_x2,cascade_x2,decisive}-sN` on its part of the fixed
      1,000 sample -> `wf-sN-seed7` -> `wf-sN-seed123` -> then it KEEPS the
      server hosted and takes tasks from `queue/pending/<name>.task` (one
      line = the arguments of one `run_agent.py` call) until 15 min before
      walltime. Output `data/agent/agent-<tag>.jsonl` on whichever cluster
      ran it; the v3 main run (`agent-full-*`, trillium) is untouched.
      One run per tag: `c7_fleet.sh monitor` (WSL, started 02:20, log
      `c7-fleet-monitor.log` in the repo root, runs 24 h) reads
      `queue/started/<tag>` on every cluster and writes `queue/skip/<tag>`
      on the others. It dies if the laptop sleeps or the SSH sockets expire;
      restart with `wsl bash ~/c7_fleet.sh monitor 1440`. Without it the
      only harm is duplicated work.
      Checked before submitting: code identical file by file on all four
      clusters and the laptop (89 files); the 194 input files (benchmark,
      instances, summaries, noise dumps, sample ids) byte-identical
      everywhere; 405 sampled snapshot commits present in each cluster's
      repos; `test_e2e_v4.py` 43/43 in each cluster's venv.
      Scheduler estimates at submission (`--test-only`): nibi at once, rorqual
      2026-11-11 02:36, fir 2026-11-12 17:14, trillium 2026-11-22.
      Commands: `wsl bash ~/c7_fleet.sh status | stage | verify | submit`.
      **REPLACED 2026-11-10 16:33 by short workers.** None of the 20 jobs
      started in 14 h (nibi estimate 11-17, rorqual 11-13 22:39, fir and
      trillium none), so all 20 were cancelled while pending. Now queued:
      42 queue-only workers (`WORKER=1`, `c7_submit_workers.sh`): rorqual
      6x3h + 6x12h (16 cores), fir 10x3h + 5x12h (12 cores), nibi 10x3h +
      5x12h (14 cores); none on trillium (a 3 h job there is also estimated
      11-21). Cores are one GPU's share of its node, not 24. Work is the 30
      tasks in `cluster/tasks/` (10 project groups x seeds 42, 7, 123; tags
      `wf-tNN`, `wf-tNN-seed7`, `wf-tNN-seed123`), copied to `queue/pending`
      on those three clusters. Monitor restarted from `~/c7_fleet2.sh`.
      Known limit: a task cut off by walltime can only be resumed on the
      cluster that started it (the others hold a skip marker); remove
      `queue/skip/<name>` there by hand if that cluster has no worker left.
      Code staged is commit 1aba0cf plus the core-count change in
      `c7_submit_workers.sh`.
      Pilot 4 (login node, same 20 ids, before the `why` change): all forms
      answered; file acc@1 0.80 (pilot 3: 0.95; three flips in three
      different stages), region acc@1 0.579 in both; lc on the same ids
      0.85 / 0.368. Output tokens per run 2,690 -> 2,024.

**Login-node pilot 3 (2026-11-10, T41 design, debugging only, NOT paper numbers):**
same 20 ids, rows `data/agent/login/agent-login3-{wf,lc}.jsonl`. Bug found:
the model copies names as `name@line` from the function list and 17 of 39
cards failed to resolve; fixed (`workflow.resolve_listed`) and the code-only
last stage re-run offline with `scripts/wf_repackage.py` (no GPU, file
ranking asserted unchanged) -> `agent-login3-wf-repackaged.jsonl`, 39 of 39
cards resolve. On the 19 ids answered in every run (18 with gold functions):
file acc@1 wf 0.947 / lc 0.842; region acc@1 wf 0.444 / lc 0.333; region
acc@5 0.667 / 0.667; region MRR 0.530 / 0.461. Paired wf - lc (n=20): file
acc@1 +0.10 (CI 0.00..0.25), region acc@1 +0.105 (CI -0.105..+0.316): the
direction is right, 18 instances cannot confirm it. lc itself moved by one
instance between pilot 2 and 3 (region acc@1 0.389 -> 0.333), which is the
noise floor here. Cost per run: wf 14.6 calls / 101,271 input tokens / 219 s,
lc 14.2 / 109,573 / 170 s -- the whole-file view spends the token saving of
pilot 2 (48,798).

**Login-node pilot (2026-11-09/10, debugging only, NOT paper numbers):**
20 ids = `baseline-pilot.json[:20]`, Qwen served TP=2 on two shared login
GPUs at 65,536. Rows: `data/agent/login/agent-login2-{wf,lc}.jsonl`.
19 paired (one wf row died on the login node's 1,024-process cap,
`BlockingIOError`): top-1 wf 15/19, lc 16/19 (diff -0.05, CI -0.21..+0.11);
hit@5 19/19 both; region acc@1 0.389 both; module 19/19 both;
no_answer 0 both. Cost per run: wf 15.0 calls / 46,358 input tokens / 209 s,
lc 13.6 / 106,150 / 184 s. wf stages: gold in table 0.95, examined 0.95,
verdict on gold 22 cause / 6 unrelated, on non-gold 62 unrelated / 7 cause /
2 detects; walk-back added nothing, tier rule moved nothing.
First attempt found a bug: the "must answer" check (and `commit_check` in
lc) treated the framework's ToolMessage after a structured answer as prose,
so every answered step was sent back (36 calls per run). Fixed with a
`type == "ai"` test; in the v3 main run `commit_check` therefore never had
any effect (its question was appended to an already finished run).

**Main run check (2026-11-09):** the 26,544-row seed-42 run has 26,541
`submitted`, 3 `error:GraphRecursionError` and 0 `no_answer`, so the
`commit_check` bug below cost no rows there.

**Found while building P6 (fix is in v4, both arms):** `commit_check` in
`lc_agent.py` appended its question but never returned `jump_to`, so when
the model answered in prose first the graph ended and the row became
`no_answer`, scored on the lexical fallback. Check the `no_answer` count in
every earlier `--arm lc` result before any of those numbers is reused.
Regression test in `test_lc_agent.py`.

**Local check before any GPU time:** `python industry-c7/agent/test_e2e_v4.py`
drives the real runner and scorer with a scripted model through ON, OFF and
a noise arm (22/22 on 2026-11-09).

**Run commands (from the cluster, after staging the tree + the
`data/results/*-noise-dump.jsonl` files; the dumps now also cover the 30
pilot ids, 4,120 rows = 1,030 instances x 4 conditions):**

```bash
# (a) pilot: 30 instances through EVERY arm shape, so one job debugs all.
#     Add --test-only as a last argument first to dry-run the submission.
WALL=4:00:00 MIN_FOLLOW_ON_S=600 FOLLOW_ON_SEEDS= TAG=v4-pilot-on SUBSET=data/results/baseline-pilot.json ARMS="v5-pilot-wf=--arm wf;v4-pilot-off=--no-log-layer;v4-pilot-generic_x2=--noise generic_x2;v4-pilot-cascade_x2=--noise cascade_x2;v4-pilot-decisive=--noise decisive"   bash industry-c7/cluster/submit-shard.sh s1
# what to read first: stop reasons, no_answer rate, tool use, module validity
python industry-c7/scripts/c7_coverage.py --run industry-c7/data/agent/agent-v4-pilot-on.jsonl   --base industry-c7/data/agent/agent-v4-pilot-off.jsonl
# (b)+(c) one 24h job: log layer ON, then OFF, then the three noise arms
TAG=v4-on SUBSET=data/results/baseline-sample.json FOLLOW_ON_SEEDS= ARMS="v4-off=--no-log-layer;v4-noise-generic_x2=--noise generic_x2;v4-noise-cascade_x2=--noise cascade_x2;v4-noise-decisive=--noise decisive"   bash industry-c7/cluster/submit-shard.sh s1
# score: ablation, then each noise arm against the clean ON run
python industry-c7/scripts/c7_coverage.py --run industry-c7/data/agent/agent-v4-on.jsonl   --base industry-c7/data/agent/agent-v4-off.jsonl
for c in generic_x2 cascade_x2 decisive; do
  python industry-c7/scripts/c7_coverage.py --run industry-c7/data/agent/agent-v4-noise-$c.jsonl     --base industry-c7/data/agent/agent-v4-on.jsonl; done
# earlier lc runs hit by the commit_check bug: how many rows lost their answer
grep -c '"stop_reason": "no_answer"' industry-c7/data/agent/agent-full-*.jsonl industry-c7/data/agent/agent-seed*.jsonl
```

---

## Cut line for 11 days

**Must land:** T1–T5, T6, T8, T9, T10–T12, T21.
Done except **T5, T9, T21** — all three are writing, no compute.

**Should:** T13–T15 done, T16 done, T18 blocked behind T17.

**Nice:** T7, T17, T19 (all GPU), T20 done.

The binding constraint is no longer compute or annotation. It is the four
paper-writing rows (T5, T9, T21 and folding the new results into the
sections), plus the fact that **the PDF has never been rebuilt** — there is
no LaTeX toolchain on this machine.

Still owed, not yet scheduled:
- the human-verified annotation subset that `RUBRIC.md` pre-registers (B1)
- an agentic baseline, Mahsa's point 3 — now written up as **T25** in P5,
  including why the scope is smaller than it first looks (the model-alone
  arm is already Agentless-style) and the population decision to settle
  before any GPU is spent (**GPU**)

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
| 2026-11-04 | **T25, T17 and T18 closed.** Both agentic arms ran the full 1,000-instance sample (0 errors) and the judge graded 400 chains. **LocAgent-style is now the STRONGEST baseline in the paper**, ahead of the LLM re-ranker, and at Acc@1 the gap to \sys{} is NOT significant: +0.023 [-0.004,+0.049]. Everything else favours us and is significant -- Acc@5 +0.116, hard Acc@1 +0.050, hard Acc@5 +0.163 -- and the margin is widest on hard instances. But LocAgent-style does it in 90 s/instance against our 321 s, so the cost story goes in the paper rather than being left to a table of accuracies. T18: 64.5% of correct top-1 predictions carry a sound chain against 25.6% of incorrect ones. Two things recorded as limits rather than buried: the judge used `unsound` once in 400 grades, so the rubric is effectively two-way; and the port's own sanity check FAILED -- CoSIL-style was predicted to show the lower empty rate and did not (3.9% vs 3.2%). traverse_graph, LocAgent's signature tool, ran 0.06 times per run. verify_claims 404/404. |
| 2026-11-03 | T25 agentic baselines BUILT (LocAgent-style + CoSIL-style). Read both papers: neither released repo runs here, and not for want of an adapter -- both parse Python with `ast` and say so in print, while all four of our projects are Java/Scala/C/C++. The graph layer IS their contribution, so replacing it is the port. Their strategies on our tree-sitter layer; `agent/BASELINES.md` records every deviation. Kept their weaknesses on purpose: free-text answers, no structured submit, so LocAgent-style can show the 13-22% empty rate CoSIL's Table II reports -- and CoSIL-style showing the LOWER empty rate is a free check that the port is faithful. **Population settled with evidence:** our own 4,409 run took 11.2 h (transcripts 01:13-12:25), so both arms on the full split is 31-39 h = 3-4 jobs, against ~8 h = one job on a stratified 1,000. The case for the full split was that a subsample forces re-runs; it does not -- `--subset` rescores all 37 systems in 6.4 s. Sample fixed on disk before any GPU: 1,000 matching the split to 3dp on every stratum (REMEMBER 0.667/0.885 vs 0.687/0.888, same best baseline), plus a disjoint 30-instance pilot drawn in the same invocation so the pair regenerates byte for byte. **Correction: Trillium login nodes have no GPU** (no nvidia-smi, no /dev/nvidia*, every partition CPU-only); the H100s are on Nibi. test_baselines 35/35 with no server, verify_claims 372/372. |
| 2026-11-02 | Review-2 read; plan and this tracker written. Confirmed all four repos are local (4.8 GB, full history), so P0 needs no cluster. Confirmed the vLLM job ended 2026-11-01, so all GPU work is blocked on B2. |
| 2026-11-02 | P0 closed except T5: T1–T4 done, T2b gives kappa 0.885 on causal-vs-not and the headline reproduces under both raters. Scored set applied, verify_claims 284/284. |
| 2026-11-03 | Full-split run finished: 4,409/4,409, 0 errors, agent v3, Acc@1 0.6870 / Acc@5 0.8877. T6, T8 and T12 closed; B2 closed. v3 does NOT beat v2 on ranking (790 paired, Acc@1 -0.0215, CI [-0.0456,+0.0013], ns) - its contribution is the guaranteed causal chain, not accuracy. Caught a selection confound that made v3 look +8.3 over v2 on the causal-gold subset: that sample was stratified on v2's own outcome. `data_flow_back` was called **1 time in 4,409 runs** - the third repeat of "instructed-but-optional gets skipped", and the two v3 changes that were structural (required chain, phase-0 prewalk) both fired as designed. verify_claims 320/320. |
| 2026-11-03 | T13-T15 done, and adding them exposed two defects in the existing noise experiment (T26, T27). `noise_robustness.py` never routed through `load_bench`, so MongoDB's sample was drawn from a pool containing **24 dev instances and 99 excluded ones**; and the 11-02 "rescore every system" sweep skipped this experiment entirely, so its numbers had been a population behind since 10-31. All four projects regenerated, pins updated with the reason recorded rather than silently refreshed. New findings: one decisive line is worth **48% of the whole mention-and-frame channel**, and T14 is a negative result (on-topic noise costs no more than unrelated noise). verify_claims 353/353. |
| 2026-11-03 | T16 (99.68% of cited paths exist, 99.43% of quoted lines, 83.41% of symbols - the last is a floor on groundedness, not an error rate) and T20 (function Acc@1 0.2152 -> 0.2882; better candidates raise the oracle 0.7367 -> 0.8879 but move Acc@1 only +1.89, while ranking the functions the agent actually read is +5.42). Then T5, T9, T21, and the paper rewrite the full-split run forced: tab:study rebuilt on 4,409, causal-gold and explanation sections written into LaTeX for the first time, a false "roughly three times" claim removed, and §IV-B corrected where it still said the agent used the 790 sample. verify_claims 344/344. |
| 2026-11-02 | Three defects found in `run_agent.py` while sizing the full-split job, all fixed before any GPU time was spent: the adjusted `n_dev` was being applied to the unfiltered benchmark and pulled 24 MongoDB dev instances into eval; there was no code path for the full split at all (`SAMPLE_N=200` hardcoded); and a second exclusion rule (`TESTY`) had drifted from `scored_set.py`. Also `bridge.sh` still defaulted to a node from a job that ended Nov 1, which would have returned empty for every call of a 15 h run. T10/T11 built behind `--version 3`, default stays 2. |
