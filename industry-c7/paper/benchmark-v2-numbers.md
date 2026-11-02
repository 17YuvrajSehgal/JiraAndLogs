# benchmark-v2 numbers, ready for the paper

Generated from `data/benchmark-v2/` by
`industry-c7/scripts/benchmark_v2_numbers.py`. Every figure here comes from
the mined data, not from notes. Re-run it after any re-mine.

**Status: dataset numbers are final. Results numbers do not exist yet.**
Nothing in §5 or §6 can be updated: the memory pools for the 23 new projects
have not been built, so incident memory, the retrieval layer, the baselines
and the agent have none of them run on v2.

---

## 1. Headline swap (abstract, §1, §8)

| claim | current paper | benchmark-v2 |
|---|---|---|
| instances | 6,437 | **38,295** |
| projects | 4 | **27** |
| organizations | 4 | **9+** |
| hard (report names no gold file) | 53% | **49%** |
| with stack trace | not stated | 30% |
| single fix commit | not stated | 84% |

In `main.tex`: `\nInstances` becomes **38,295**, `\nHardPct` becomes **49\%**, `\nProjects` becomes **twenty-seven**.

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
| minus no non-test source file modified | -13,901 |
| minus gold set over 50 files (bulk edit) | -87 |
| **= final instances** | **38,295** |

Overall yield 53.9%.

Three filter changes from the current paper, each needing a sentence:

- **No query truncation.** The old 20,000-character cap clipped 0.3% of
  instances, so it bought nothing and invited the question. 163 reports
  are now kept in full.
- **Fix-commit cap 3 to 10.** Recovers 731 instances with 4 to 10 fix
  commits. The new cap costs only 55 instances, so 10 is
  comfortably above where the distribution ends.
- **New: gold capped at 50 files.** Removes 87 instances
  (0.23%). Justification: Acc@K counts a hit if *any* gold file is retrieved,
  so HIVE-17952, a license-header edit touching 3,493 of hive's 4,819 source
  files, is a free point for every system 99.8% of the time. Such instances
  inflate every system equally and measure nothing.

---

## 3. Per-project table (§II, Table I)

`*` marks the four projects already in the paper.

| project | eligible | instances | hard | trace | 1 commit | gold median |
|---|---|---|---|---|---|---|
| hive | 5,910 | 4,736 | 59% | 15% | 94% | 1 |
| hadoop | 7,848 | 4,386 | 42% | 18% | 92% | 1 |
| mongodb * | 6,407 | 3,746 | 60% | 10% | 77% | 2 |
| ambari | 5,995 | 3,294 | 66% | 14% | 83% | 2 |
| hbase | 5,215 | 3,249 | 36% | 22% | 85% | 1 |
| mariadb * | 3,004 | 1,718 | 44% | 57% | 82% | 1 |
| spark | 2,314 | 1,564 | 37% | 51% | 89% | 1 |
| sakai | 3,420 | 1,451 | 55% | 31% | 74% | 1 |
| cassandra | 2,116 | 1,421 | 40% | 52% | 82% | 1 |
| flink | 2,076 | 1,091 | 33% | 50% | 83% | 1 |
| groovy | 1,604 | 1,012 | 71% | 36% | 76% | 1 |
| camel | 1,201 | 870 | 37% | 44% | 69% | 1 |
| infinispan | 1,546 | 866 | 37% | 61% | 77% | 2 |
| phoenix | 1,059 | 804 | 51% | 23% | 84% | 2 |
| impala | 1,492 | 801 | 46% | 56% | 94% | 2 |
| solr | 1,123 | 758 | 36% | 30% | 64% | 1 |
| wildfly | 1,604 | 728 | 56% | 49% | 82% | 1 |
| pdfbox | 890 | 714 | 25% | 57% | 64% | 1 |
| ignite | 1,244 | 695 | 31% | 54% | 92% | 2 |
| kafka * | 1,172 | 684 | 29% | 47% | 91% | 1 |
| derby | 1,192 | 683 | 58% | 38% | 68% | 1 |
| geode | 1,378 | 648 | 40% | 59% | 72% | 1 |
| pig | 868 | 606 | 49% | 38% | 87% | 1 |
| drill | 1,046 | 536 | 63% | 26% | 93% | 2 |
| qt * | 7,412 | 456 | 68% | 24% | 96% | 1 |
| keycloak | 940 | 436 | 42% | 48% | 89% | 1 |
| beam | 923 | 342 | 32% | 30% | 80% | 1 |

---

## 4. Distributions now recorded

These answer the two questions a reviewer asks about any capped benchmark.

| | median | p95 | p99 | max |
|---|---|---|---|---|
| query characters | 900 | 6,578 | 13,782 | 706,007 |
| fix commits per issue | 1 | 2 | 4 | 10 |
| files changed by fix | 3 | 16 | 41 | 2755 |
| gold files per instance | 1 | 8 | 19 | 50 |

Fixes touching more than 3 files: 14,290 (37% of
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
