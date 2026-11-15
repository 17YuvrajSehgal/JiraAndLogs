# benchmark numbers, ready for the paper

Generated from `data/benchmark/` by
`industry-c7/scripts/benchmark_v2_numbers.py`. Every figure here comes from
the mined data, not from notes. Re-run it after any re-mine.

**Status: dataset numbers are final. Results numbers do not exist yet.**
Nothing in §5 or §6 can be updated: the memory pools for the 23 new projects
have not been built, so incident memory, the retrieval layer, the baselines
and the agent have none of them run on v2.

---

## 1. Headline swap (abstract, §1, §8)

| claim | current paper | benchmark |
|---|---|---|
| instances | 6,437 | **38,001** |
| projects | 4 | **27** |
| organizations | 4 | **9+** |
| hard (report names no gold file) | 53% | **49%** |
| with stack trace | not stated | 30% |
| single fix commit | not stated | 85% |

In `../main.tex`: `\nInstances` becomes **38,001**, `\nHardPct` becomes **49\%**, `\nProjects` becomes **twenty-seven**.

The hard fraction moving 53% to 49% should be stated, not quietly
swapped. The expanded set is marginally easier, not different in kind, and
the claim now survives across 27 projects instead of 4, which makes
it much harder to attack.

---

## 2. Funnel (§II-B, replaces the current datasheet text)

| stage | issues |
|---|---|
| eligible: log-bearing, fixed Bug, uncertainty at most 0.05 | 70,999 |
| minus no fix commit found | -18,661 |
| minus more than 10 fix commits | -55 |
| minus no non-test source file modified | -14,207 |
| minus gold set over 50 files (bulk edit) | -75 |
| **= final instances** | **38,001** |
| minus gold entirely test code (scored set, not re-mined) | -101 |
| **= scored instances** | **37,900** |

Overall yield 53.5%.

The last row is a scoring-time exclusion, not a mining filter: gold is kept
exactly as mined, and the 101 instances whose gold is entirely
test code are dropped from the scored set: a hit there means retrieving the
test file the fix edited, not localizing a defect. They are rankable, and in
fact easier than average, so the drop lowers every system's number rather
than flattering it. Every system is scored on the same 37,900.
See `paper/test-filter-gaps.md`.

Three filter changes from the current paper, each needing a sentence:

- **No query truncation.** The old 20,000-character cap clipped 0.3% of
  instances, so it bought nothing and invited the question. 161 reports
  are now kept in full.
- **Fix-commit cap 3 to 10.** Recovers 669 instances with 4 to 10 fix
  commits. The new cap costs only 55 instances, so 10 is
  comfortably above where the distribution ends.
- **New: gold capped at 50 files.** Removes 75 instances
  (0.23%). Justification: Acc@K counts a hit if *any* gold file is retrieved,
  so HIVE-17952, a license-header edit touching 3,493 of hive's 4,819 source
  files, is a free point for every system 99.8% of the time. Such instances
  inflate every system equally and measure nothing.

---

## 3. Per-project table (§II, Table I)

`*` marks the four projects already in the paper.

| project | eligible | instances | hard | trace | 1 commit | gold median |
|---|---|---|---|---|---|---|
| hive | 5,910 | 4,692 | 59% | 15% | 94% | 1 |
| hadoop | 7,848 | 4,385 | 42% | 18% | 93% | 1 |
| mongodb * | 6,407 | 3,629 | 61% | 9% | 77% | 1 |
| ambari | 5,995 | 3,286 | 66% | 14% | 84% | 2 |
| hbase | 5,215 | 3,245 | 36% | 22% | 86% | 1 |
| mariadb * | 3,004 | 1,715 | 44% | 57% | 83% | 1 |
| spark | 2,314 | 1,565 | 37% | 51% | 90% | 1 |
| sakai | 3,420 | 1,440 | 55% | 31% | 76% | 1 |
| cassandra | 2,116 | 1,421 | 40% | 52% | 83% | 1 |
| flink | 2,076 | 1,085 | 33% | 50% | 83% | 1 |
| groovy | 1,604 | 1,007 | 71% | 36% | 78% | 1 |
| camel | 1,201 | 869 | 37% | 44% | 70% | 1 |
| infinispan | 1,546 | 862 | 36% | 62% | 77% | 2 |
| phoenix | 1,059 | 802 | 51% | 23% | 84% | 2 |
| impala | 1,492 | 776 | 49% | 55% | 95% | 2 |
| solr | 1,123 | 756 | 37% | 29% | 65% | 1 |
| wildfly | 1,604 | 725 | 57% | 49% | 84% | 1 |
| pdfbox | 890 | 713 | 25% | 57% | 65% | 1 |
| ignite | 1,244 | 695 | 31% | 54% | 92% | 2 |
| kafka * | 1,172 | 683 | 28% | 47% | 91% | 1 |
| derby | 1,192 | 677 | 58% | 38% | 70% | 1 |
| geode | 1,378 | 628 | 40% | 59% | 74% | 1 |
| pig | 868 | 606 | 49% | 38% | 87% | 1 |
| drill | 1,046 | 536 | 63% | 26% | 94% | 2 |
| qt * | 7,412 | 456 | 68% | 24% | 96% | 1 |
| keycloak | 940 | 431 | 42% | 48% | 89% | 1 |
| beam | 923 | 316 | 33% | 32% | 81% | 1 |

---

## 4. Distributions now recorded

These answer the two questions a reviewer asks about any capped benchmark.

| | median | p95 | p99 | max |
|---|---|---|---|---|
| query characters | 902 | 6,577 | 13,782 | 706,007 |
| fix commits per issue | 1 | 2 | 4 | 10 |
| files changed by fix | 3 | 16 | 41 | 2755 |
| gold files per instance | 1 | 8 | 19 | 50 |

Fixes touching more than 3 files: 14,132 (37% of
instances). Worth saying plainly in §II: large fixes are in, and there has
never been a files-per-commit filter.

---

## 5. What still blocks a paper update

1. **Memory pools for the 23 new projects do not exist.** The temporal
   firewall, the incident-memory signal and all of §III depend on them.
2. **Per-instance universe is not recorded.** Needed before claiming how many
   instances are trivially solvable. A per-project estimate is too crude:
   early Kafka had 213 source files against thousands today.
3. **Every result re-runs.** Retrieval, fusion re-tuning and the IRBL
   baselines are CPU and take days; the LLM baselines and the agent need the
   GPU, and that server is down.
4. **All 266 verify_claims checks, six tables and two figures** are tied to
   the current benchmark and will fail until the above is done.

Keep `data/benchmark/` frozen until then. The paper compiles and verifies
against it today, and that fallback is what makes the expansion safe to
attempt this close to the deadline.
