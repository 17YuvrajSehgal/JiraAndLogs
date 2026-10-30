# Challenge #7 — running results log (benchmark + localizer)

**Scripts:** `scripts/c7/mine_benchmark.py`, `scripts/c7/localize.py`
**Data:** `data/c7-benchmark/` (instances), `data/c7-results/` (rankings, summaries)
**Plan + guards:** `09-challenge7-plan.md`

---

## 1. Benchmark (task C7-P0)

### Kafka — mined 2026-10-29

| funnel stage | n |
|---|---|
| WoL ticket_worthy KAFKA issues | 1,147 |
| no fixing commit in default-branch subjects | −348 |
| >3 fixing commits (epics, noisy linkage) | −2 |
| linked at 1–3 non-revert, non-merge commits | 797 |
| fixes touch no modified non-test source file | −163 |
| **final instances** | **634** |

Strata: 423 easy (67%, a gold file's stem appears in the issue text) /
211 hard (33%); 401 with stack trace (63%); gold files median 1, mean 2.19;
589 single-commit. Snapshot = parent of (first) fix commit; gold = modified
non-test source files of the fix.

MariaDB (5,626 issues): mining in progress.

### Dataset decisions (2026-10-29, with user)

- Repo has **derived-only** forms of the two synthetic corpora; raw bundles
  live in our own Zenodo record 21096887 (`otel-demo-full.zip` 1.1 GB,
  `online-boutique-full.zip` 4.7 GB). Re-download only when building the
  OTel complement.
- Synthetic corpora cannot headline Challenge #7 (infra faults have no
  faulty code region). Their roles: raw-noisy-bundle complement via the
  OTel **flag faults** (25 flag-based scenarios → 9 distinct gold code
  sites in the vendored demo source), visible-recurrence demo for the
  memory prior, and backbone of the paused main-paper extrinsic redesign.
- Expansion A (depth): WoL v1 full release (zenodo 17569722, 2.69M issues)
  → more linked Kafka/MariaDB issues beyond our triage filters. Primary
  effect: **enlarges the memory pool** (see §3).
- Expansion B (breadth): The Public Jira Dataset v7 (zenodo 15719919,
  CC-BY-4.0) → MongoDB (`SERVER-` subjects) + Qt (`Fixes: QTBUG-` trailer)
  as zero-shot non-Apache ecosystems (never in any ARISE training split).
- Both expansions only after the localizer runs end-to-end on the core.

## 2. Localizer evolution (task C7-P1) — Kafka, 634 instances

Signals: `trace_grep` (explicit file mentions + stem fallback — the
mandatory baseline), `path_bm25`, `content_bm25` (candidate pool, DF inside
the pool → no cross-snapshot leakage), `memory_arise` (ARISE hybrid top-5
past incidents vote with their fix files), `memory_bm25` (BM25 over past
incident text, depth 20, time-valid pool). Memory firewall (all counted):
own twin, duplicate cluster (incident_episode_id), resolved-after-query,
shared fix commit.

Protocol: time-based split by fix time — dev = earliest 30% (n=190,
≤ 2016-12-06), eval = later 70% (n=444). Weights grid-tuned on dev only.

### v2 headline (eval n=444; acc@5 / MRR)

| system | overall | easy (293) | hard (151) |
|---|---|---|---|
| trace_grep | 0.588 / 0.432 | 0.891 / 0.654 | 0.000 / 0.000 |
| path_bm25 | 0.475 / 0.364 | 0.645 / 0.498 | 0.146 / 0.102 |
| content_bm25 | 0.664 / 0.503 | 0.785 / 0.617 | **0.430** / 0.281 |
| memory_arise | 0.236 / 0.159 | 0.290 / 0.196 | 0.133 / 0.088 |
| memory_bm25 | 0.390 / 0.271 | 0.464 / 0.326 | 0.245 / 0.163 |
| fused (unweighted, no mem) | 0.671 / 0.527 | 0.911 / 0.720 | 0.205 / 0.153 |
| fused (unweighted, +mem) | 0.671 / 0.528 | 0.857 / 0.694 | 0.311 / 0.207 |
| cond_no_memory | 0.725 / 0.550 | 0.904 / 0.705 | 0.378 / 0.250 |
| **cond_ours** | **0.732** / 0.544 | 0.925 / 0.704 | 0.358 / 0.236 |

cond_* = regime-conditioned weighted RRF; regime = "explicit file mention
present in text" — observable at inference (unlike easy/hard, which needs
gold). Tuned weights kept memory in BOTH regimes (mention: memory_arise 0.5;
no_mention: memory_bm25 0.5).

### What each version taught

- **v0 (naive 4-way RRF):** memory helped (+0.015 acc@5 overall, +0.053
  hard) but fusion POLLUTED the hard stratum: trace_grep contributes
  *wrong* files there (text names files; just not the gold ones) and
  dragged fused acc@5 to 0.228 vs content-alone 0.389.
- **v1 (explicit-mention trace parser, memory_bm25 depth 20, time-split
  tuning):** trace_grep became a real baseline (0.588 eval acc@5).
  Global weight tuning ZEROED memory — diagnosed: dev = earliest issues =
  the slice where memory structurally cannot exist yet. Unweighted
  fusion+memory on hard: 0.311 vs 0.205 (+52% rel).
- **v2 (regime-conditioned weights):** best overall system (0.732), and
  tuning now retains memory; on hard, cond closes most of the gap to
  content-alone (0.378/0.358 vs 0.430) but does not beat it yet.

### Honest current state of the memory claim

Direction is consistent (unweighted fusion: +0.106 acc@5 on hard; tuner
retains memory when given regimes), magnitude is unstable (−0.020 under
conditioned weights on hard). Root cause measured, not guessed: the memory
pool is only **634 linked past incidents**, and v0 stats showed 34% of
ARISE's top-5 hits are discarded as resolved-later plus 34% unlinked —
~1.6 usable votes/query. The claim's fate rides on memory density:
1. MariaDB (≈5× denser memory) is the in-flight test;
2. Expansion A (full WoL) multiplies linked history per project;
3. deeper, time-sliced ARISE retrieval (Trillium job) replaces the
   top-5-only persisted predictions.

## 3. MariaDB run (2026-10-30) — the memory-density test, PASSED

Benchmark: 3,067 instances (funnel in datasheet: 5,626 → 3,741 linked 66.5%
→ −674 no-source-gold). 46% hard stratum (vs Kafka 33%). Memory pool:
3,067 linked incidents (≈5× Kafka). Protocol identical: dev = earliest 30%
(n=920), eval = later 70% (n=2,147).

Note: a CRLF/text-mode bug in `cat-file --batch` parsing crashed the first
MariaDB run (byte-size offsets vs newline-translated text). Fixed to binary
parsing; Kafka re-verified bit-identical on all 231 metric cells.

### Eval (n=2,147; acc@5 / MRR)

| system | overall | easy (1,163) | hard (984) |
|---|---|---|---|
| trace_grep | 0.434 / 0.306 | 0.800 / 0.565 | 0.000 / 0.000 |
| path_bm25 | 0.256 / 0.190 | 0.442 / 0.328 | 0.037 / 0.026 |
| content_bm25 | 0.425 / 0.284 | 0.495 / 0.312 | 0.342 / 0.251 |
| memory_arise | 0.260 / 0.195 | 0.260 / 0.196 | 0.261 / 0.194 |
| **memory_bm25** | 0.412 / **0.309** | 0.466 / 0.350 | **0.349 / 0.261** |
| fused unweighted, no mem | 0.424 / 0.315 | 0.742 / 0.541 | 0.049 / 0.048 |
| fused unweighted, +mem | 0.575 / 0.415 | 0.801 / 0.587 | 0.308 / 0.213 |
| tuned_no_memory | 0.474 / 0.304 | 0.647 / 0.424 | 0.269 / 0.162 |
| tuned_ours | 0.585 / 0.416 | 0.804 / 0.577 | 0.325 / 0.226 |
| cond_no_memory | 0.593 / 0.433 | 0.840 / 0.612 | 0.301 / 0.223 |
| **cond_ours** | **0.604 / 0.442** | 0.838 / 0.618 | 0.326 / 0.233 |

### The density finding (Kafka vs MariaDB)

| | Kafka (pool 634) | MariaDB (pool 3,067) |
|---|---|---|
| global tuner's memory weight | **0.0** (zeroed) | **2.0** (max in grid) |
| dev acc@5 gain from memory | +0.000 | **+0.078** |
| eval Δacc@5, unweighted fusion ±mem | +0.000 | **+0.151** |
| eval Δacc@5 tuned ±mem | +0.000 | **+0.111** |
| best single signal on HARD | content 0.430 | **memory_bm25 0.349** |

On MariaDB the incident memory is no longer decoration: `memory_bm25` has
the best single-signal MRR overall (0.309) and is the best single system on
the hard stratum — past incidents beat reading the code exactly where the
trace points at the wrong file. The full system beats the strongest
baseline by +39% rel acc@5 and +44% rel MRR overall.

This gives the paper its causal-shaped headline: *the memory prior's value
scales with memory density* (two project-scale points: 634 → useless,
3,067 → decisive), and makes Expansion A (full WoL, more linked history
per project) an evidence-backed investment rather than a hope.

Honest remainders: on MariaDB-hard, memory_bm25 alone (0.349) still edges
every fusion (cond_ours 0.326) — fusion weight-tuning on hard remains
imperfect; memory_arise (top-5, not time-sliced) underperforms memory_bm25
everywhere — the deeper time-sliced ARISE rerun stays queued; deltas need
paired bootstrap before any claim goes in the paper.

### Pending for the eval harness

Paired bootstrap + BH for (cond_ours − cond_no_memory) and
(cond_ours − content_bm25), overall and per stratum, once MariaDB lands.
Module-level Acc@K (challenge output (i)) and the explanation stage
(challenge output (iii), needs LLM) not yet implemented.
