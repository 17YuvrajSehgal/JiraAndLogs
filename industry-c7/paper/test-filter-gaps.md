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
solr 20, mongodb 8, pig 1. On those, no localizer can be right, because the
answer key contains only test code. That is 0.27% of the benchmark.

For scale: the test filter already removes 1,717 files across 1,166
instances, so it is catching roughly two thirds of the test code and
missing this third.

## Examples from the sample

- `phoenix:PHOENIX-3308` — all 7 gold files are under `src/it/java/`,
  e.g. `phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java`
- `solr:SOLR-14247` — the single gold file is
  `solr/test-framework/src/java/org/apache/solr/SolrTestCase.java`
- `mongodb:SERVER-15763` — `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

## Why this is not fixed yet

Tightening TEST_PATH changes gold, which invalidates every baseline
measurement already run, the 151-packet sample, and the annotation labels
derived from it. That is the author's call, not a unilateral one. The same
trade-off was taken earlier for the 5.3% of instances whose fixes land in
added files, which were left in deliberately.

Three options, in increasing cost:

1. **Report it.** State the rate in threats, note that ~0.27% of instances
   are unanswerable and ~1.3% carry some test code in gold. No re-run.
2. **Exclude at scoring time.** Keep gold as mined, drop the 101
   all-test instances from the scored set, and re-score every system on the
   same reduced set. Cheaper than re-mining, and the same-population rule is
   preserved because every system is rescored.
3. **Re-mine with a tightened filter.** Cleanest benchmark, invalidates all
   existing measurements and the annotation sample.

Option 2 is the recommendation: it removes the instances that cannot be
answered without disturbing the gold construction, and it is auditable.
