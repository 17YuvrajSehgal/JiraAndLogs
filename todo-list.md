# ARISE — post-rejection plan

**Branch:** `v2-research` · **Status:** rejected after rebuttal, 2026-10
**Prior work:** 24 commits already landed; see "Already fixed" at the bottom.

Reviews: `ICSE/reviewers-comments/R{1,2,3}.txt`
Evidence: `scripts/rebuttal/`, `scripts/v2/`, `paper-results-v2/`

---

## Read the rejection correctly

Scores were 2/2/3 on merit. But **every reviewer scored Novelty = 2
("Incremental")**, and none of them raised it as a question — so the rebuttal
could never touch it. We answered the rigor questions well and still got
rejected. That tells us the rigor fixes were necessary and not sufficient.

Second, harder problem: **we found a defect the reviewers did not.** The
WoL bi-encoder varies ±0.020 Hit@5 across seeds, and the published 0.905 was a
low draw. The headline "+0.065 for fusion" was computed against that draw with
a CI that ignored seed variance entirely. Against the 5-seed mean it is +0.051;
against the best seed, +0.025. **The fusion claim is currently unverified**, and
resolving it may remove the paper's main quantitative result.

So: do not rewrite the paper until P0 settles what we actually have.

---

## P0 — Find out what survives

### 1. Finish the hybrid seed sweep, restate the fusion margin
Script is fixed and committed (`scripts/v2/trillium_v2_hybrid_seeds.sbatch`);
two earlier attempts died on walltime because I rewrote the sbatch instead of
reusing the working one. Submit, get hybrid on seeds 42/1/2/3/4, compute the
seed-matched margin with a seed-aware interval.

Three outcomes, all publishable, but they are different papers:
- margin holds (≳0.04, interval clears 0) → fusion stays a contribution
- margin shrinks but positive → report honestly, demote from headline
- margin within noise → **fusion is not a result**; the paper is the datasets
  and the empirical findings

### 2. Decide the contribution, given #1
The learned-controller plan already failed its first test: it did not beat
thresholding the confidence signal the controller already computes (+0.0012 /
−0.0012 across two folds). Do not build the paper on it without new evidence.

Options, to choose deliberately:
- **(a) Benchmark-validity paper.** Lead with the negative results, which are
  genuinely surprising and all ours: triage saturation is a fault-injection
  artifact; evidence tools are non-load-bearing; fusion conclusions flip with
  corpus scale; GPU training does not reproduce at fixed seed. Cheapest, and
  the one the evidence already supports.
- **(b) Real telemetry + real tickets dataset.** Closes R1-Q2, which we never
  fixed — we only narrowed the claim. Strongest contribution, longest lead.
- **(c) Learned controller, rescued.** Needs the score-margin feature (now
  persisted) to beat the confidence baseline. One experiment decides it.
- **(d) SafeSet** (`DOCS/SafeSet-research-design.md`) — likely a separate paper.

### 3. Pick the target venue
Determines format, length, deadline, and whether (b) is feasible at all.

---

## P1 — Reviewer asks still open

### 4. Human study: relevance + page-worthiness
R1-Q1 and R1-Q3. The only item nothing substitutes for, and the longest lead
time — start recruiting regardless of P0.
- blinded, system top-1 vs hard same-project negative, ≥2 annotators, kappa
- second axis: urgent / valid-not-urgent / no-action, to test whether Jira
  resolution proxies page-worthiness at all (R1-Q3 — currently unanswered)
- the hard-negative LLM judge is built and run; it gives this study a
  pre-registered quantity to validate against (system 3.65 vs hard 3.10,
  p≈1e-8), but it is a model, not people

### 5. Real telemetry paired with real tickets
R1-Q2's actual fix. We currently claim graceful degradation but cannot show
evidence-gathering transfers to production telemetry, because our telemetry is
synthetic and our real data is text-only. Either collect this, or cut every
claim that depends on it. Overlaps with P0 option (b).

### 6. Finish the incident-level comparison
DeepCT and Triangle are done from primary sources. FLASH and COMET were left
out because I could not obtain them — FLASH surfaces only as an unindexed MSR
tech report, COMET returns a commercial product. Get the references (ask the
reviewer's citation trail, or search ACM/IEEE directly) or justify the omission.

### 7. Measure per-call costs instead of modelling them
The saving is counts × a modelled cost table. Shown robust (79.0% measured-unit
vs 77.9% modelled), but the table is wrong by large factors in both directions.
Microbenchmark the reformulator and peer-lookup for real, then drop "estimated".

### 8. Publish the v3 artifact
Code ready and dry-run verified: 54 files / 2.07 GB, contaminated corpus
quarantined, pools excluded. Needs a human decision — it creates a new version
of a public DOI printed in the submitted paper.

---

## P2 — Rebuild the paper

### 9. Restructure around whatever P0 leaves standing
Do not start before #1 and #2 report.

### 10. Verification pass: every number traces to a run
The submitted paper contained a claim built on an all-zero feature matrix, and
I later propagated a second false claim from a draft without checking the
scoring path. Before submission, each reported number gets checked against the
script and result file that produced it. This is the habit that would have
prevented the rejection-grade defect.

### 11. Final editing pass
R3 scored Presentation 2. Naming and the two flagged sentences are fixed; the
broader pass should come last, after the restructure.

---

## Already fixed (24 commits, do not redo)

| | Reviewer ask | What changed |
|---|---|---|
| ✅ | R2-Q3, R1-Q3 | "Triage collapses to chance" was an artifact of a zero-filled feature matrix. Re-run on text: ROC-AUC 0.572–0.601 (paper binarization), 0.704 (strict). Retracted paper-wide. |
| ✅ | R2-Q1 | Strict-relation panel, all 9 systems, 23/24 comparisons significant. Non-leakage analysis: indexed corpus has no `Components` field, KG vocabulary overlaps gold by 9.9%, graph retriever is worst, and the component trained on coarse gold degrades most. |
| ✅ | R2-Q2 | `maxconf` defined as its own equation, two gates separated, threshold sensitivity table. |
| ✅ | R3-Q2 | Figure 4 CIs. Withdrew "peer lookup is the only clearly beneficial tool" — its interval includes zero. |
| ✅ | R3-Q1 (part) | 5 seeds on both telemetry sets + WoL bi-encoder. Seed contributes 1% of variance on OTel, 28% on OB. |
| ✅ | R1 metadata | 75.3% component coverage; disclosed that 23.9% of held-out queries are dropped (why n=5,150 not 6,773). |
| ✅ | R3 clarity | Incident defined concretely, windowing justified, label provenance documented, "human-annotation kit" corrected, naming unified. |
| ✅ | R1-Q4 (part) | DeepCT + Triangle comparison table from primary sources. |
| ✅ | R2 cost | Reframed as counts × modelled table, with a robustness argument. |

**Also worth keeping:** eight exact reproductions of published baseline numbers
(tfidf, mpnet, bge, e5, ce + 3 seeds) — a Verifiability answer the submission
could not have claimed.
