# Test files that survive the test filter (measured 2026-11-02)

Found by the annotation pass, which is what the `test` role in RUBRIC.md
exists for: "label and flag any that leak through, because that is a
benchmark defect worth knowing about". Four instances in the 151-packet
sample turned up gold files that are plainly test code.

## Scale across benchmark-v2 (38,001 instances, 98,376 gold files)

| pattern | files | instances |
|---|---|---|
| `src/it/` — Maven Failsafe integration-test source root | 815 | 476 |
| `*IT.java` — Failsafe naming convention | 796 | 471 |
| `test-framework/` module (shipped test support) | 93 | 61 |
| `*_test_fixture.*` / `testfixture` | 92 | 56 |

The first two overlap heavily; together they are the dominant gap.

**101 instances have a gold set that is entirely such files**: phoenix 72,
solr 20, mongodb 8, pig 1. That is 0.27% of the benchmark.

An earlier draft of this file said no localizer could be right on those.
**That was wrong and is corrected below.** The ranking universe is filtered
by `TEST_PATH`, which is exactly the pattern these files escape, so they sit
in the universe and are perfectly rankable. Measured, not argued: on v1's
123 such instances the retrieval layer puts a gold file somewhere in the
ranking 103 times and inside the top 5 **91 times, Acc@5 74.0%**, against
68.6% on the instances that are kept. For v2 all 101 likewise have gold in
the universe. They are not unanswerable. They are easier than average.

For scale: the test filter already removes 1,717 files across 1,166
instances, so it is catching roughly two thirds of the test code and
missing this third.

## Examples from the sample

- `phoenix:PHOENIX-3308` — all 7 gold files are under `src/it/java/`,
  e.g. `phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java`
- `solr:SOLR-14247` — the single gold file is
  `solr/test-framework/src/java/org/apache/solr/SolrTestCase.java`
- `mongodb:SERVER-15763` — `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

## Decision: exclude at scoring time (option 2, taken 2026-11-02)

Gold is left exactly as mined. The instances whose gold is entirely test code
are dropped from the **scored set**, and every system is re-scored on the
reduced population, so the same-population rule holds.

**Why they are dropped, stated correctly.** Not because they cannot be
answered, but because answering them is not the task this paper measures. A
hit on one of these means retrieving the test file that the fix edited, and
the paper claims to localize the code that holds the defect. Keeping them
also inflates every system, since they are 5.4 points of Acc@5 easier than
the rest. So the drop moves our own headline number *down*. That is what
makes it a defensible exclusion rather than a self-serving one, and it is
the check to report, not the claim of unanswerability.

The drop is recorded as data, not as a flag inside a script:

- `scripts/scored_set.py` defines `TEST_PATH_EXTRA`, writes the excluded ids
  to `data/benchmark*/excluded-test-only-gold.json`, and is the single place
  the rule lives.
- `localize.load_bench()` applies it, and the IRBL baselines and the LLM
  prompt builder load through it, so a fresh run on either benchmark is
  already on the scored set.
- `scripts/apply_scored_set.py` retrofits the result files that were already
  on disk. Removed rows are kept under
  `data/results/removed-test-only-gold/`, and each summary keeps its
  pre-drop blocks under `pre_scored_set`, so the operation is reversible and
  auditable.

### The dev/eval boundary was not moved

Every analysis script takes `n_dev` from the run's summary and slices
`rows[n_dev:]`. The retrofit lowers `n_dev` by the number of excluded rows
that sat in dev, which leaves the boundary exactly where the original run put
it. Re-splitting would have moved about 24 instances from eval into dev,
and the tuned weights were fit on the original dev set, so that would have
leaked. Weights were **not** re-tuned: the point is to change the population,
not the system.

### How many are dropped

| benchmark | instances | dropped | scored | rate |
|---|---|---|---|---|
| v1 (4 study projects, current paper) | 6,437 | **123** | 6,314 | 1.91% |
| v2 (27 projects) | 38,001 | **101** | 37,900 | 0.27% |

v1 is the worse of the two, and all 123 are MongoDB. It was mined with an
earlier `TEST_PATH`: 141 of its excluded gold files match today's pattern
(`query_planner_test.cpp`, `dbtests/`, `time_support_test.cpp`), which the
current miner would have removed at mine time. Only 13 need the new
`TEST_PATH_EXTRA`. v2 is cleaner because it was mined with the fixed pattern,
and what remains there is the Failsafe `src/it/` and `*IT.java` convention
that neither pattern knew about.

Eval split: 4,508 instances to **4,409**. The agent's 790-instance study set
loses nothing, because it already excluded test-only gold before the run
(`data/agent/excluded-test-only-gold.json`, 10 instances); the generalised
rule agrees with that sample exactly, which is a useful check on both.

### Effect on every measured system

Pooled over the four projects on the eval split, before and after the drop:

| system | Acc@5 before | Acc@5 after | delta | MRR before | MRR after | delta |
|---|---|---|---|---|---|---|
| `content_bm25` | 59.20% | 59.06% | -0.14 | 43.48% | 43.32% | -0.16 |
| `fused_no_memory` | 51.95% | 51.49% | -0.46 | 41.03% | 40.49% | -0.54 |
| `fused_ours` | 61.67% | 61.33% | -0.34 | 47.56% | 47.30% | -0.26 |
| `tuned_ours` | 64.13% | 64.10% | -0.03 | 46.95% | 46.87% | -0.08 |
| `cond_no_memory` | 67.31% | 67.11% | -0.19 | 53.40% | 53.12% | -0.28 |
| `cond_ours` | 68.79% | 68.63% | -0.16 | 53.05% | 52.89% | -0.15 |
| `rvsm` | 16.53% | 16.45% | -0.08 | 13.12% | 13.09% | -0.03 |
| `buglocator_fw_a5` | 29.70% | 30.03% | +0.33 | 22.26% | 22.45% | +0.19 |
| `brtracer_fw` | 47.65% | 47.34% | -0.31 | 38.43% | 38.13% | -0.29 |
| `simiscore_fw` | 28.86% | 29.35% | +0.49 | 20.08% | 20.40% | +0.32 |
| LLM two-stage | 77.51% | 77.84% | +0.33 | 64.63% | 64.92% | +0.29 |
| LLM re-rank | 77.24% | 77.16% | -0.08 | 67.47% | 67.42% | -0.05 |
| REMEMBER (790 study set) | 90.25% | 90.25% | +0.00 | 79.93% | 79.93% | +0.00 |

No system moves more than half a point, and the ordering of the pooled table
is unchanged for every metric. Nine orderings do change inside MongoDB's
per-stratum breakdowns, the only project the drop touches. Most are exact
ties between firewall-ablation variants that rank identically and so break
arbitrarily; the largest genuine swap is 0.83 points, `buglocator_leaky_a2`
against `simiscore_fw` at Acc@10 on MongoDB's easy stratum. Nothing the paper
claims rests on either. Per-project and per-stratum figures are in
`data/results/rescored-test-only-gold.json`.

That is the result to report: the gap was real and worth fixing, and fixing
it does not change a conclusion.

Instances that carry *some* test code in gold are kept, because a localizer
can still be right on them. In v1 that is 766 instances, in v2 493.

## Alternatives considered

Three options, in increasing cost:

1. **Report it.** State the rate in threats, note that ~0.27% of instances
   are unanswerable and ~1.3% carry some test code in gold. No re-run.
2. **Exclude at scoring time.** Keep gold as mined, drop the 101
   all-test instances from the scored set, and re-score every system on the
   same reduced set. Cheaper than re-mining, and the same-population rule is
   preserved because every system is rescored.
3. **Re-mine with a tightened filter.** Cleanest benchmark, invalidates all
   existing measurements and the annotation sample.

Option 2 was taken. Option 3 was rejected: it would invalidate the
151-packet annotation sample and every baseline measurement, to move
numbers that option 2 shows move by less than half a point.
