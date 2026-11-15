# Open issues — gaps, unverified items, things to settle

---

## Resolved while writing this reference (recorded as a warning)

**Gold-set size was computed over the wrong population.** The draft quoted
"the average query has 288 relevant items (0.75% of memory)" in a section about
the **held-out test queries**, but 288 is the figure across *all splits*. On the
test queries the metrics are actually averaged over, it is **410** (1.06%,
median 218) coarse and **50** (0.13%, median 16) strict.

That propagated into the random-ranker reference points, which were understated:

| | was | correct (test population) |
|---|---|---|
| coarse: mean relevant / query | 288 (0.75%) | **410 (1.06%)** |
| strict: mean relevant / query | 34.5 (0.09%) | **50 (0.13%)** |
| random Hit@5, coarse | 0.036 | **0.051** |
| random Hit@5, strict | 0.0044 | **0.006** |
| "× above random" | 27× / 169× | **19× / 116×** |

Fixed in `06-results.tex`. The direction of the argument is unchanged — the
coarse relation is *more* permissive than we said, which strengthens the case
for co-headlining the strict relation.

**Lesson:** two scripts computed the same statistic over different populations
(`scripts/rebuttal/01` test-only, `scripts/rebuttal/02` all-splits) and the
paper picked up the wrong one. Statistics about the evaluation must be computed
over the evaluated population. Neither script stores its output, which is why
`verify_claims.py` could not catch it — see below.

---

## Claims traceable to a script but with no stored artifact

`verify_claims.py` cannot check these; they require a re-run to confirm. This is
exactly the gap that hid the error above.

| Claim | Script |
|---|---|
| component coverage 75.3%, dropped queries 23.9% | `scripts/rebuttal/01_component_metadata_and_gold_stats.py` |
| random-ranker baselines, gold-set sizes | `scripts/rebuttal/02_random_baseline_and_kg_vocab_overlap.py` |
| KG/gold vocabulary overlap 9.9% | `scripts/rebuttal/02_...py` |
| indexed-corpus leakage 0/3000, 34.6%, 15.9% | `scripts/rebuttal/03_indexed_corpus_leakage_check.py` |
| seed variance decomposition (28% / 1%) | `scripts/v2/seed_variance_decomposition.py` |

**Fix:** make each write its output to `paper-results-v2/`, and add rows to
`verify_claims.py`. Small, and it closes the last hole in the traceability net.

---

## Experiments not run

| Item | Why it matters | Cost |
|---|---|---|
| **Human relevance + page-worthiness study** | R1-Q1 and R1-Q3 are still unanswered. Nothing substitutes. Longest lead time. | recruiting + ~200–400 pairs |
| **Learned policy with the score-margin feature** | The feature is now persisted (mean 0.068, median 0.038, max 0.74) but the policy was never retried with it. Decides whether the learned controller is a contribution. | one experiment, local |
| **Real telemetry + real tickets** | R1-Q2's actual fix; we only narrowed the claim. Also the strongest novelty play. | large; needs a data source |
| **Cost microbenchmark** | Would let us drop "modelled". Lower priority — the result is shown insensitive to the table. | small cluster job |
| **FLASH and COMET** | R1-Q4 named four systems; we covered DeepCT and Triangle from primary sources. FLASH surfaces only as an unindexed MSR tech report; COMET returns a commercial product. | needs the references |
| **Hybrid seeds on the telemetry datasets** | We have bi-encoder × 5 seeds on all three, hybrid × 5 only on WoL. Fine if WoL carries the claims; a gap if OB/OTel comparisons are kept. | 2 short jobs |

---

## Decisions outstanding

1. **Target venue** — sets length, deadline, and whether the real-telemetry
   dataset is feasible. A journal removes the page pressure that drove the
   "final reduction" commits and suits a negative-results framing.
2. **The contribution** — all three reviewers said Novelty=2 and none raised it
   as a question, so the rebuttal could never address it. See
   `todo-list.md` P0-2 for the four options.
3. **Artifact publication** — code is ready and dry-run verified (54 files,
   2.07 GB). Publishing creates a new version of a public DOI already printed in
   the submitted paper, so it needs a human decision.
4. **Metareview** — the one we received (#5913D) describes a *different paper*
   (coding agents, agent context files, "not-to-do instructions"). Email sent to
   the PC chairs. We currently have **no AC assessment of our paper**, which is
   normally the most useful input to a resubmission.

---

## Things to re-check before submitting

- Run `python scripts/v2/verify_claims.py` — must be all-green.
- Rebuild figures: `fig_adaptive_execution`, `fig_significance_forest`,
  `fig_triage_reframing` all read from result files and will drift if those
  change.
- `pdflatex` has never been run in this environment. Structure and
  cross-references check clean via a custom script, but overfull boxes and
  float placement are unverified — build on a machine with LaTeX.
- Branch hygiene: cluster checkout sits on `master-agent-new`, which stopped
  2026-06-30 and lacks the reviews. Local `master` is canonical. Analysis code
  is identical between them, so results are unaffected.
