# Benchmark breadth: what the filters actually cost, and what expansion buys

Analysis date 2026-11-02. Every number below is measured, not estimated,
except where marked *projected*.

Sources: `WoL_v2_gh_so.JIRA` (489,560 docs) and `JiraReposAnon` (16 trackers,
~2.69M issues) in the `c7-mongo` container, plus the mined benchmark.

---

## 1. The three things you asked about

### "Commits with more than 3 file changes" — no such filter exists

The `1–3` limit in §II-B is on **commits per issue**, not files per commit.
Large fixes are already in the benchmark:

| fixes touching | instances | share |
|---|---|---|
| > 3 files | 2,117 | 32.9% |
| > 5 files | 1,203 | 18.7% |
| > 10 files | 449 | 7.0% |
| > 20 files | 128 | 2.0% |
| > 50 files | 25 | 0.4% |

Largest fix in the benchmark touches **143 files**; the largest gold set is
**139 files**. Median fix touches 3 files, median gold is 1.

The commits-per-issue cap costs **218 of 17,995 eligible issues (1.2%)** on
our four projects. But it is not uniform: on PDFBOX it would cost **8.3%**.
Worth raising to ~10 and recording the distribution, but it is not where the
data is being lost.

### "No truncation of description" — affects 21 of 6,437 instances (0.3%)

`MAX_QUERY_CHARS = 20_000`. Measured per project, the share of instances
sitting at the cap: Kafka 0.1%, MariaDB 0.5%, MongoDB 0.3%, Qt 0.2%. Median
query is 578–2,253 characters; p95 is 5,298–7,834.

Cheap to remove and worth removing so nobody can raise it, but it will not
move any result.

### "More projects" — this is where the real gain is

**168,502 eligible issues across 969 distinct projects.** We use 17,995 from
four, which is **10.7%** of what the data offers.

---

## 2. Where instances are actually lost today

| stage | lost | note |
|---|---|---|
| no fix commit found | **9,134 (51%)** | the dominant loss |
| > 3 fix commits | 218 (1.2%) | small |
| no non-test source gold | 2,206 (12%) | language filter + test paths + modified-only |

Per-project yield, eligible → final:

| project | eligible | linked | final | yield |
|---|---|---|---|---|
| Kafka | 1,172 | 827 (70.6%) | 680 | 58.0% |
| MariaDB | 3,004 | 2,010 (66.9%) | 1,683 | 56.0% |
| MongoDB | 6,407 | 5,093 (79.5%) | 3,618 | 56.5% |
| **Qt** | 7,412 | **713 (9.6%)** | 456 | **6.2%** |

**Qt is the anomaly and the single cheapest fix.** The QTBUG tracker covers
the whole Qt framework, roughly 40 repositories, and we mine only `qtbase`.
That one choice throws away **6,699 eligible issues**. Adding
qtdeclarative, qttools, qtmultimedia, qtwebengine, qtquickcontrols2 and a few
more recovers most of it with no new code: the `Fixes:` trailer convention is
already implemented.

Excluding Qt, yield is a stable **56.5%** across three unrelated projects.

---

## 3. Expansion is validated, not assumed

I cloned `apache/pdfbox` (30 MB treeless, a project we have never touched)
and measured linkage directly:

| | PDFBOX |
|---|---|
| eligible issues | 889 |
| linked to ≥1 commit | 739 (83.1%) |
| linked to 1–3 commits | 665 (**74.8%**) |

That sits inside the 66.9–79.5% band of our existing projects. The Apache
`KEY-123` subject convention is the same one Kafka uses, so **the existing
miner works on every Apache project with no code change.**

### Candidate pool (eligible issues, measured)

**Apache tracker — same convention, public repos, zero code change:**

| key | eligible | repo | | key | eligible | repo |
|---|---|---|---|---|---|---|
| AMBARI | 5,511 | ambari | | SOLR | 1,110 | solr |
| HIVE | 5,486 | hive | | DRILL | 1,036 | drill |
| HBASE | 5,081 | hbase | | MAPREDUCE | 1,023 | hadoop |
| HDFS | 2,482 | hadoop | | PHOENIX | 1,002 | phoenix |
| HADOOP | 2,344 | hadoop | | BEAM | 917 | beam |
| SPARK | 2,305 | spark | | PDFBOX | 889 | pdfbox ✓cloned |
| CASSANDRA | 2,106 | cassandra | | QPID | 864 | qpid-* |
| FLINK | 2,070 | flink | | PIG | 863 | pig |
| YARN | 1,836 | hadoop | | GEODE | 1,375 | geode |
| GROOVY | 1,603 | groovy | | IGNITE | 1,237 | ignite |
| IMPALA | 1,493 | impala | | CAMEL | 1,193 | camel |
| FLEX | 1,526 | flex-sdk | | DERBY | 1,187 | derby |

Four keys (HDFS, HADOOP, YARN, MAPREDUCE) share **one** repo and together
carry 7,685 eligible issues.

Subtotal ≈ **44,000 eligible** across ~19 repos → *projected* ~25,000
instances at the observed 56.5% yield.

**Non-Apache with public repos:** SAK 3,421 (sakaiproject/sakai),
QTCREATORBUG 1,504 (qt-creator), WFLY 1,594 (wildfly), ISPN 1,537
(infinispan), KEYCLOAK 933. Subtotal ≈ 9,000 eligible.

**Not usable:** JRASERVER, CONFSERVER, BAM, BCLOUD, MC, CB (Atlassian) and
NEXUS, FAB (Sonatype) have no public repo with issue-key linkage. Worth one
sentence in the paper: the tracker is public, the code is not.

### What breadth would actually buy

Today: 4 projects, 4 organizations, 2 tracker platforms, 2 language families
(JVM, C/C++).

After: ~20–25 projects, 5+ organizations, mixed Java/Scala/C++/C, and a
benchmark 3–4× larger. External validity stops being a soft spot.

One honest limit: most Apache projects are JVM. Real language diversity would
need the WoL GitHub collection (5.78M docs), but GitHub issues lack the PJD
resolution dates and duplicate links the temporal firewall depends on. That
is a reason to stay on Jira, and it is worth stating rather than hiding.

---

## 4. The cost, stated plainly

Mining is cheap and unattended. Everything downstream is not.

| work | cost | blocked? |
|---|---|---|
| clone ~20 repos | ~20 GB, a few hours | no |
| re-mine | 1–2 days CPU, unattended | no |
| memory pools, S1–S4, fusion re-tuning | 2–3 days CPU | no |
| IRBL baselines (rVSM/BugLocator/BRTracer) | expensive, scales with repo size | no |
| **LLM baselines (a1/a2/rr)** | GPU, ~4× current | **yes — server down** |
| **agent** | GPU | **yes — server down** |
| re-verify all 266 claims, 6 tables, 2 figures | 1 day | no |

**Every number in the paper becomes invalid the moment the benchmark
changes.** That includes all 266 verified claims, both figures and every
table.

---

## 5. The tension you should decide on

The reviewer did **not** ask for this. They called the benchmark a "Strong
contribution" and did not list breadth anywhere in their weakness table.
Their top ask is causal ground truth (Very high), then agent sample size
(High), then shallow causal investigation (Very high).

So expansion competes for the same 11 days as the work the reviewer said
matters most, and it invalidates everything already verified.

Against that: you are right that a 20-project benchmark is much harder to
attack, and the dataset is a standalone contribution that outlives this
paper.

### What I recommend

Do both, in parallel, with a fallback.

1. **Now, hours:** remove the 20k truncation, raise the commit cap to 10,
   record both distributions. Cheap, closes two lines of attack.
2. **Unattended, starting today:** clone and mine the expansion. Mining is
   CPU-only and needs no supervision, so it runs while the annotation work
   happens.
3. **Human time goes to the causal annotation (P0 in todolist.md)**, because
   that is the reviewer's actual objection and it needs people, not compute.
4. **Keep `data/benchmark/` frozen as the fallback.** Build the expanded set
   beside it as `benchmark-v2/`. The paper keeps compiling and verifying
   against the current numbers the whole time.
5. **Go/no-go on 2026-11-08.** If the expanded benchmark is clean and the
   CPU baselines have re-run, switch. If not, ship the current one and cite
   the expansion as released data.
6. **Keep the comparative study and the agent on a stratified sample** drawn
   across the larger benchmark, exactly as the 790 sample works now. That
   holds GPU cost roughly flat while the benchmark headline grows.

This way breadth is additive rather than a bet on finishing a full re-run
before the deadline.
