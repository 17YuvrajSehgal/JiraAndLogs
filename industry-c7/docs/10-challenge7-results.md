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

## 4. Four-project v3 run (2026-10-30) — PJD pools + creation-time firewall

Protocol v3 supersedes v2: memory pools from PJD (kafka 4,033 / mariadb
6,014 / mongodb 19,820 / qt 2,315 entries), visibility cutoff = the query's
TRUE creation time (strictly harder than the fix-time proxy — it blocks
65–71% of candidate votes), duplicate clusters from PJD Duplicate links.
Benchmark: 7,775 instances; eval split (later 70% per project) n = 444 /
2,147 / 2,533 / 320.

### eval acc@5 (full table in data/c7-results/<p>-summary.json)

| system | kafka | mariadb | mongodb | qt |
|---|---|---|---|---|
| trace_grep | 0.588 | 0.434 | 0.354 | 0.263 |
| content_bm25 (strongest baseline) | 0.651 | 0.423 | 0.644 | 0.456 |
| memory_bm25 alone | 0.387 | 0.392 | 0.377 | 0.278 |
| fused unweighted, no mem | 0.671 | 0.425 | 0.530 | 0.353 |
| fused unweighted, +mem | 0.669 | **0.561** | **0.629** | **0.463** |
| cond_no_memory | 0.719 | 0.595 | 0.693 | 0.456 |
| **cond_ours** | **0.714** | **0.599** | **0.700** | **0.541** |

### The three claims these numbers support

1. **Beats the strongest baseline on all four projects**: +0.063 / +0.176 /
   +0.056 / +0.085 acc@5 over content-BM25.
2. **Memory lifts raw fusion on 3 of 4 projects** (+0.136 mariadb, +0.099
   mongodb, +0.110 qt; kafka −0.002). Under conditioned fusion the deltas
   compress (+0.004/+0.007/+0.085/−0.005) because conditioning already
   extracts trace/content value — EXCEPT on Qt.
3. **Qt is the memory showcase**: 68% hard, 24% traces — conditioning
   without memory only matches content-BM25 (0.456); adding memory gives
   0.541 (+0.085). Where text and traces are weakest, history matters most.

Kafka memory neutrality is explained, not mysterious: WoL-slice Kafka
queries are the OLDEST in the benchmark and the strict creation-time
firewall blocks 65% of their candidate votes (vote_stats in summary). The
density→value relationship holds within and across projects.

Hard stratum: cond_ours ≈ content-BM25 on mongodb (0.544 vs 0.548) and qt
(0.361 = 0.361); memory_bm25 alone remains the best single signal there
for mariadb-class density. Fusion on hard still has headroom.

## 5. Significance (paired bootstrap 2,000×, BH over all 64 tests)

`scripts/c7/stats.py` → `data/c7-results/stats.json`. Four pre-specified
comparisons × {acc@5, mrr} × {overall, hard} × 4 projects.

**Confirmed significant:**
- **Ours > strongest baseline (content-BM25), overall: 8/8 tests SIG** —
  acc@5 +0.063 [+0.027,+0.099] kafka, +0.175 [+0.152,+0.197] mariadb,
  +0.057 [+0.046,+0.068] mongodb, +0.084 [+0.053,+0.119] qt.
- **Memory lifts unweighted fusion on the HARD stratum on all four
  projects:** +0.080 kafka, +0.242 mariadb, +0.165 mongodb, +0.153 qt
  (all SIG). This is the universal form of the memory claim.
- Ours > trace-grep everywhere (max delta: +0.544 acc@5, mongodb hard).
- Conditioned-memory ablation: SIG only on Qt overall (+0.084); mongodb
  mixed (+0.008 acc@5 SIG, −0.013 mrr SIG); kafka/mariadb n.s.

**Confirmed honest negatives (quantified, to report):**
- On HARD, cond_ours < content-BM25 on kafka (−0.093 SIG) and mariadb
  (−0.035 SIG); statistical ties on mongodb/qt. Conditioned fusion still
  under-serves the hard stratum relative to content-alone — fusion
  headroom, stated openly.

## 6. Module-level metrics (challenge output (i))

`scripts/c7/module_metrics.py` → `data/c7-results/module-metrics.json`.
Module = first D path components (kafka 1, mariadb 2, mongodb 3, qt 2 —
a single top-level dir is meaningless under src/); system module ranking =
file ranking collapsed by first occurrence; eval split only.

cond_ours module Acc@1 / Acc@5: kafka 0.815/0.991 · mariadb 0.797/0.963 ·
mongodb 0.841/0.979 · qt 0.669/0.925. The affected-module output is
near-solved at K=5 on all four projects; at module Acc@1, memory_bm25 is
the best SINGLE signal on mariadb (0.744 vs content 0.729), and memory
lifts Qt's module Acc@1 from 0.613 (cond_no_memory) to 0.669.

All four re-runs with persisted fused rankings reproduced the committed
results exactly: per-project summary tables line-identical, and all 64
bootstrap tests match the committed stats.json with zero mismatches.

## 7. UNIFIED protocol (2026-10-30, supersedes §4-6 numbers)

Population unified on public data for all four projects (WoL v2 log-bearing
+ fixed Bug + uncertainty ≤0.05; query = summary+description): kafka 680 /
mariadb 1,683 / mongodb 3,618 / qt 456 = **6,437 instances** (53% hard).
Eval split n = 476/1,179/2,533/320. memory_arise retired (no ARISE
predictions for the unified windows; pipeline now fully reproducible from
public artifacts). Results moved UP for kafka/mariadb (cleaner queries):

- cond_ours acc@5: **0.794 / 0.658 / 0.700 / 0.541** vs content-BM25
  0.708/0.471/0.644/0.456 → +0.086/+0.187/+0.057/+0.084, **8/8 SIG**
  (MRR +0.058..+0.148, also all SIG).
- Module Acc@1 0.861/0.843/0.841/0.669 (beats content everywhere);
  Acc@5 0.998/0.983/0.979/0.925.
- Memory on hard (unweighted fusion): +0.209/+0.165/+0.153 SIG on
  mariadb/mongodb/qt; kafka +0.081 q=0.068 n.s. (n=124) — the old "4/4"
  claim weakens to 3/4 + same-direction. Conditioned-memory increment now
  SIG on THREE projects overall (mariadb +0.016, mongodb +0.008, qt
  +0.084). **Standalone-memory beats content on mariadb-hard (0.442 vs
  0.406).**
- Density claim REFRAMED: time-quartile analysis shows memory weakest in
  the earliest eval quartile in 3/4 projects, but no clean monotone rise
  (only mongodb). Paper's RQ3 = "memory matters where textual evidence is
  weakest" (hard-share gradient + firewall cost 67-71% + Q1 minima); no
  scaling-law claim.
- Honest negatives: kafka-hard cond_ours −0.065 SIG below content (only
  project still SIG below; was two); qt-easy conditioned-no-memory
  collapses (0.654) from noisy small-regime dev tuning, full system
  recovers (0.913).

Paper §§2–5 written against these numbers (industry-c7/paper/).

## 8. Module sanity baselines (reviewer W5) — claim corrected

`module_baselines.py` → `module-baselines.json`. Exact per-snapshot module
counts; analytical random@K; most-frequent-module from dev gold.

| | kafka | mariadb | mongodb | qt |
|---|---|---|---|---|
| modules (median) | 8 | 79 | 36 | 116 |
| random@5 | .610 | .076 | .153 | .099 |
| frequency@1 / @5 | .361 / .763 | .612 / .905 | .756 / .894 | .334 / .809 |
| ours @1 / @5 | .861 / .998 | .843 / .983 | .841 / .979 | .669 / .925 |

The reviewer's instinct was right in kind: defects concentrate (frequency
alone = 0.76–0.91 Acc@5; ABB's Pareto observation reproduced), and
Kafka's 8-module space makes random@5 = 0.61. **"Near-solved at K=5"
retracted from the paper**; module claims now lead with Acc@1, where ours
beats frequency by +0.08 (mongodb) to +0.50 (kafka). Abstract/§1/§5/§8
updated; verify_claims extended (6 new assertions). Smallest margin is
mongodb (+0.085 @1) — frequency is genuinely strong there.

### Pending for the eval harness

Paired bootstrap + BH for (cond_ours − cond_no_memory) and
(cond_ours − content_bm25), overall and per stratum, once MariaDB lands.
Module-level Acc@K (challenge output (i)) and the explanation stage
(challenge output (iii), needs LLM) not yet implemented.

## 9. IRBL baselines + firewall-leakage experiment (reviewer W1/W2) — in paper

`baselines_irbl.py` → `{proj}-irbl-{instances,summary}.json(l)`;
`stats_irbl.py` → `stats-irbl.json` (96-test BH family, 2,000 resamples).

Firewalled baselines, acc@5/mrr (Table II band 2):

| | kafka | mariadb | mongodb | qt |
|---|---|---|---|---|
| rVSM | .214/.192 | .239/.188 | .127/.097 | .122/.101 |
| BugLocator (α=.3) | .267/.199 | .300/.250 | .245/.152 | .166/.131 |
| BRTracer-style | .599/.479 | .516/.382 | .456/.380 | .316/.284 |

Consequence: strongest baseline is now per-project — S3 on kafka/mongodb/qt,
**BRTracer-style on mariadb** (.516 > S3 .471). RQ1 reframed; headline range
is now Acc@5 +0.057..+0.142 (mariadb vs BRTracer +0.142 [+0.119,+0.167] SIG;
vs S3 alone still +0.187). ours_vs_brtracer +0.142..+0.245 overall,
+0.133..+0.371 hard, all 8 SIG.

Leakage (new §V-D "What the firewall is worth"): leaky−firewalled SimiScore
acc@5 = +0.044/+0.031/+0.058/+0.094 (k/m/mo/qt), all BH-SIG; relative
inflation 9%–43%. Decomposition: re-opening rule 4 alone (future reports)
reproduces leaky on 3 projects (kafka 0.368=0.368 exactly); noR2/noR3 alone
recover nothing (future duplicates double-blocked); Qt remainder is the
R4×R2 interaction. BugLocator leak diluted by α-blend: SIG kafka/mariadb
(+0.019/+0.014), ns mongodb/qt. Fair fight: S4 memory_bm25 beats classic
SimiScore under identical firewall on all 4 overall (+0.160/+0.122/+0.109/
+0.059, all SIG); qt hard ns (+0.037).

Paper updates: Table II +3 rows, §IV-C baseline defs (+wong2014brtracer ref),
§IV-D two BH families (64+96), §V-A rewritten for per-project strongest,
§V-D new subsection, abstract + intro (now 5 contributions) + conclusion
carry the leakage finding. 0.1425 renders as +0.142 (banker's rounding).
Compiled 8pp, 0 overfull. verify_claims: 146/146.

## 10. W4 answered: latency, function level, noise robustness

**Latency** (localize.py instrumented, full deterministic re-run, 168/168
claims bit-identical): per-issue median 0.07/0.41/0.41/0.22 s
(k/m/mo/qt), p95 < 0.7 s everywhere, mem-index build <= 0.1 s. In §VI
deployment notes.

**Function stage** (`function_stage.py`, tree-sitter spans × `git diff
-U0` snapshot-side hunks; candidates = functions in top-10 cond_ours
files, BM25-ranked, untuned): eligible 95/92/94/87 %; eval acc@5
.478/.274/.467/.288; oracle ceiling .856/.718/.747/.576. Bottleneck
differs: qt = file stage (oracle .58), mariadb = in-file ranking (oracle
.72, acc .27 — huge C++ files). Table IV + §V-E.

**Noise** (`noise_robustness.py`, 200-sample/project, 11 conditions,
clean-tuned frozen weights, seed 42; clean anchors within 0.025 of main
runs): dup ×5 costs ≤.055; generic ×5 .06–.135 + mongodb .235; drop
mentions .07–.165; foreign lines catastrophic (acc@5 → ≤37 % of clean at
×5; mariadb .635→.285 already at ×1) via regime hijack (flips 1/3–1/2 at
×1). Deployment reading: segment logs by incident before matching.
Table V + §V-F.

Paper now 9 pp, 0 overfull; abstract/intro carry both experiments;
verify_claims 168/168.

## 11. Dense-retrieval baselines (reviewer W1/W4 + fix #4)

`dense_baselines.py` (bge-small-en-v1.5, CPU, 200-sample/project, frozen
clean-tuned weights, seed 42). Two swaps, acc@5:

- **code slot (S3)**: dense LOSES everywhere — content_dense
  .485/.350/.460/.425 vs BM25 .690/.425/.665/.460 (max −.205; 4×350-word
  chunk truncation vs full-text BM25; identifier matching is lexical's
  game). cond_dense_s3 hurts on all 4.
- **memory slot (S4)**: dense WINS 3/4 — memory_dense .530/.515/.425/.290
  vs BM25 .460/.455/.410/.305 (+.070/+.060/+.015/−.015);
  cond_dense_s4 lifts mariadb +.045 even with frozen weights.

Paper: new §V-G + Table VI; §VI semantic-retrieval paragraph updated to
the measured answer. verify_claims 182/182; 10pp 0 overfull.

Remaining review items needing the user: LLM localizer (API key; ~<$10
on GPT-6 Luna for 800 instances), gold validation (validation/ sheets,
2 raters), §7 related work (user-deferred).

## 12. LLM localizer baseline — PRE-REGISTRATION (written before results)

Model: **Qwen3.8-27B** (Apache 2.0, Aug 2026) self-hosted on 1x H100
(Trillium, vLLM 0.32.0, 131k ctx). temperature 0, seed 42,
schema-constrained JSON output. Full 6,437-instance benchmark.

### Conditions

| id | condition | input | isolates |
|---|---|---|---|
| a1+a2 | Agentless-style standalone, 2 stages: dirs -> files | report+logs, snapshot tree only | LLM as an independent localizer (reviewer W1) |
| rr | LLM rerank of our top-20 (+tree-sitter skeletons) | report+logs, our candidates | does the LLM add value ON TOP of retrieval? |
| cp | contamination probe: issue KEY only (±title) | no report body | how much of the fix is MEMORISED from pretraining |
| a1d+a2d | de-identified replay (issue keys scrubbed) | report with keys masked | recall-by-key vs genuine localization |
| think | thinking-mode ON replay, 800-sample | same as a1/a2 | does disabling reasoning handicap the baseline? |

Why hierarchical, not a flat repo dump: MongoDB's tree is ~150k tokens
against a 131k context cap, so a flat Agentless prompt is impossible;
hierarchical is both faithful to Agentless and the only feasible form.

### Pre-committed analysis

- Primary: Acc@5 / Acc@10 / MRR on the eval split, same `evaluate()` as
  the lexical pipeline; paired bootstrap (2,000 resamples, shared
  indices) vs `cond_ours` on matched instances, BH-corrected.
- Parse failures are scored as **misses** (headline), with a
  parsed-only view reported alongside. Neither view is suppressed.
- Path resolution reported as exact / prefix-strip / basename / suffix /
  dropped. Dropped paths never occupy a rank.
- Pipeline oracles reported, not hidden: stage-1 directory recall and
  stage-2 candidate-set recall bound what the LLM could possibly score.

### Harness validation (before the full run)

- 100% parse rate, 0 errors, all `finish_reason=stop` (n=1,025).
- Stage-1 directory recall **0.936** (k .934 / m .981 / mo .934 / qt .894).
- Stage-2 candidate cap raised 500 -> 1500 after measuring that 500
  truncated ~10% of instances and cost ~4 points of oracle, biased
  alphabetically. At 1500 nothing truncates (0/60).
- Resolver has a committed self-check (`test_llm_score.py`, 10 cases).

### Throughput note (for the artifact)

24 concurrent workers is the measured sweet spot on this server:
Running 23 / **Waiting 0** / KV cache 77-84% / prefill 9.7-13.1k tok/s =
72-75 requests/min. Pushing concurrency higher drives KV past ~95% and
vLLM begins preempting and re-prefilling the same requests; while the
GPU was shared the effective rate collapsed to 1.4/min.
