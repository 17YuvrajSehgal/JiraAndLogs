# Final to-do list: the ICSE 2027 Challenge #7 paper

Deadline: **Nov 13, 2026 AoE** (Nov 14, 06:59 Eastern). Track rules: 5 to 10
pages including tables and figures, plus at most 2 pages of references,
IEEEtran 10pt conference, double-anonymous.

Decision 2026-11-13: the paper reports **one seed (42)** of the staged
workflow arm (`--arm wf`) and only results we already have. No more GPU
money unless a line below says so.

Work through the tasks in order. Tick each one when it is done.

---

## A. Where the paper stands (read first)

- `paper/main.pdf` (Nov 4 build): **20 pages**, ~16,700 words, 10 tables,
  3 figures. Needs to lose ~55% of its words and about half its tables.
- Every number is from the **old benchmark** (4 projects, 6,437 instances,
  4,409 evaluated) and the **old agent** (v3 free tool loop, 14 turns).
- Page map today: Intro 1-2, Benchmark 3, Retrieval 4-5, Agent 6-7,
  Setup 7-8, **Results 9-15**, Discussion 16-17, Related 18, Conclusion 19,
  refs 20.
- Word counts: intro 1,356; benchmark 1,450; approach 1,196; agent 1,267;
  setup 1,523; **results 6,563**; discussion 2,067; related 690;
  conclusion 465; main.tex 570.
- LaTeX works in WSL: `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/c/workplace/JiraAndLogs/industry-c7/paper && latexmk -pdf main.tex'`.
  Page count: `grep "Output written" main.log`.

---

## B. Result inventory: what exists on the 27-project benchmark

| Paper item | Status |
|---|---|
| Benchmark datasheet | HAVE. `paper/docs/benchmark-numbers.md`: 38,001 final, 37,900 scored, **26,544 in the evaluation split**, 49% hard, 30% with a trace, 85% single fix commit. Per-project table included there. |
| Headline agent (`wf`) on the full split | HAVE. 26,544 instances, 26,540 answered, 4 scored as misses. |
| Retrieval layer on the same instances | HAVE. `metrics_lexical` in the wf rows; per-project `data/results/<p>-summary.json` (27 files, Nov 7). |
| Free-loop agent (old design, `--arm lc`) on the full split | HAVE. 26,541 rows in `data/agent/full/agent-full-*.jsonl`. Paired with wf below. |
| LocAgent-style / CoSIL-style | HAVE on the 1,000 sample (Nov 13). `data/results/agentic-baselines.json`. |
| Function level | HAVE. BM25 stage: `data/results/<p>-functions-summary.json` (27). wf regions: in the coverage file. |
| Module level | HAVE for retrieval layer (`data/results/module-metrics.json`, 27 projects) and wf. Random/frequency baselines only for the old 4 (`module-baselines.json`, Nov 2); re-run is CPU: `scripts/module_baselines.py`. |
| Dense vs lexical | HAVE. `data/results/<p>-dense-summary.json` (27, 200-instance samples). |
| rVSM / BugLocator / BRTracer-style | OLD 4 PROJECTS ONLY. Not re-run. |
| Model alone, model re-ranker, fusion | OLD 4 PROJECTS ONLY. Needs GPU. |
| Firewall leakage experiment | OLD 4 PROJECTS ONLY. |
| Contamination probe, shuffle check, LLM judge | OLD 4 PROJECTS, OLD AGENT. |
| Structural-vs-instructed ablation (168 instances) | OLD AGENT. Replaced by free loop vs wf. |
| Noise robustness table | Retrieval layer, OLD 4 PROJECTS. Agent noise arms never ran. |
| Causal annotation (151 instances) | OLD 4 PROJECTS. Still a valid gold-quality study if labelled. |
| Figures | `figures/agent.pdf` shows the OLD free loop. `research.pdf` and `architecture.pdf` say four projects. Diagram source for the new arm: `agent/AGENT-DIAGRAM.md`. |

### Row files and scores (laptop)

- wf, one good row per instance plus the 4 misses:
  `C:\Users\17yuv\AppData\Local\Temp\c7cmp\lcwf\wf-seed42.jsonl`
  (built from `data/agent/cluster/agent-wf-*.jsonl` and
  `data/agent/vm/agent-wf-[nsm]*.jsonl`; first good row wins).
- free loop, all 5 shards concatenated:
  `C:\Users\17yuv\AppData\Local\Temp\c7cmp\lcwf\lc-main.jsonl`
- wf score alone: `C:\Users\17yuv\AppData\Local\Temp\c7cmp\lcwf\c7-coverage-seed42-all.json`
- wf vs free loop, paired: `C:\Users\17yuv\AppData\Local\Temp\c7cmp\lcwf\c7-coverage-wf-seed42.json`
- Scorer: `python industry-c7/scripts/c7_coverage.py --run <wf> --base <lc>`
  (writes into `data/results/`; move the output out afterwards).
- Baseline rows: `data/agent/agent-locagent-eval.jsonl`,
  `data/agent/agent-cosil-eval.jsonl` (gitignored).
  Rebuild the comparison with `scripts/agentic_baselines_compare.py`
  after pointing it at the wf rows (today it reads the main-run glob).

---

## C. The verified numbers (use these; every one traces to a file above)

### C1. wf on the full evaluation split (seed 42)

| population | n | Acc@1 | Acc@5 | MRR |
|---|---|---|---|---|
| all | 26,544 | 68.6 | 85.9 | .761 |
| hard (report names no gold file) | 12,799 | 52.8 | 73.6 | .618 |
| easy | 13,745 | 83.3 | 97.4 | .895 |
| with stack trace (scored rows) | 7,808 | 66.5 | 86.7 | |
| logs, no trace | 5,739 | 66.6 | 84.6 | |
| prose only | 12,993 | 70.8 | 86.1 | |

- Module (agent's own answer) 90.2; module from top file 90.9;
  invalid module 0.02%.
- Region (function) level, 24,850 eligible: Acc@1 53.8, Acc@5 69.9,
  MRR .600. Agent-only regions: 53.5 / 69.4.
- Cost per instance: 15.7 model calls, 106,426 prompt tokens, 286 s wall
  at 32 concurrent requests per H100.
- Chains: 112,143 steps; 57.4% of steps cite a log event; 85.7% of those
  citations exist in the report; 99.99% of runs with events cite one.
- Workflow stages: route trace 8,907 / prose 15,109 / logs 2,523;
  gold file in the candidate table 92.3%; gold examined 86.4%;
  5.7 cards per run; walk-back added a file in 14.1% of runs;
  shortlist and rank answered 100%.
- Four misses (both runs hit the step limit in RANK): hadoop:YARN-8948,
  impala:IMPALA-2491, mongodb:SERVER-28958, spark:SPARK-31102.
  Cause: `causal_chain` returned as a string by the `qwen3_xml` tool
  parser (3), or the 1,500-token output cap (1). Scored as misses.
- Non-determinism, 20 instances, same seed: same top-1 file 18/20 on one
  machine, 14 to 15/20 across machines; same top-10 10 to 12/20;
  module 20/20. Acc@1 0.65 to 0.70 across repeats.

### C2. Retrieval layer on the same 26,544 instances

| | Acc@1 | Acc@5 | MRR |
|---|---|---|---|
| all | 41.2 | 70.3 | .533 |
| hard | 20.3 | 48.7 | .322 |
| easy | 60.6 | 90.3 | .731 |

Pooled over 27 projects (weighted by n): cond+memory 41.2/70.3;
cond, no memory 40.5/68.8; unweighted fusion +memory 38.0/67.1;
unweighted, no memory 35.5/59.7; content BM25 32.3/61.5;
trace mentions 26.0/43.2; memory alone 22.8/42.1; path BM25 19.7/38.6.
Pooled over the 27 projects, eval split, from `<p>-instances.jsonl`
(`C:\Users\17yuv\AppData\Local\Temp\c7cmp\paper-numbers.json`), Acc@1 / Acc@5:

| system | all (26,544) | hard (12,799) | easy (13,745) |
|---|---|---|---|
| cond + memory (the retrieval layer) | 41.2 / 70.3 | 20.3 / 48.7 | 60.6 / 90.3 |
| cond, no memory | 40.5 / 68.8 | 19.3 / 46.5 | 60.3 / 89.7 |
| unweighted fusion + memory | 38.0 / 67.1 | 14.4 / 41.8 | 60.0 / 90.6 |
| unweighted fusion, no memory | 35.5 / 59.7 | 7.4 / 26.4 | 61.6 / 90.6 |
| S3 content BM25 | 32.3 / 61.5 | 24.4 / 50.2 | 39.7 / 72.1 |
| S1 trace mentions | 26.0 / 43.2 | 0.0 / 0.0 | 50.1 / 83.4 |
| S4 memory alone | 22.8 / 42.1 | 21.0 / 40.2 | 24.4 / 43.8 |
| S2 path BM25 | 19.7 / 38.6 | 6.0 / 17.8 | 32.4 / 58.0 |

Memory on the hard stratum: unweighted fusion 26.4 -> 41.8 Acc@5 with
memory (+15.4); conditioned 46.5 -> 48.7 (+2.2). Memory alone is the
second-best standalone signal on hard (40.2 Acc@5, after content 50.2).

### C2b. Function stage (BM25 over the retrieval layer's top-10 files), pooled

24,820 eligible eval instances (93.9% of all rows have a derivable gold
function). Acc@1 21.9, Acc@5 42.1, Acc@10 51.1, MRR .314; oracle (gold
function in the candidate set) 77.0%. Hard (weighted by eligible n,
approximate): Acc@1 14.0, Acc@5 29.3. Compare wf regions: 53.8 / 69.9
overall; hard 39.2 / 55.2 (11,921 eligible); easy 67.3 / 83.5.

### C2c. Dense vs lexical, 27 x 200-instance samples, mean Acc@5

content slot: BM25 58.4 vs dense 44.9 (dense wins 0 of 27 projects).
memory slot: BM25 37.6 vs dense 40.4 (dense wins 22 of 27).
Full system: cond 67.7; with dense S4 69.1 (better on 16 of 27); with
dense S3 61.2; both 61.8.

### C2d. wf by difficulty

hard (12,797): file 52.8 / 73.6, module 85.5, region 39.2 / 55.2 (MRR .453).
easy (13,743): file 83.3 / 97.4, module 94.6, region 67.3 / 83.5 (MRR .736).

### C3. Free loop (old design) vs wf, paired on 26,537 instances

| metric | free loop | wf | wf minus free loop [95% CI] |
|---|---|---|---|
| file Acc@1 | 67.9 | 68.6 | **+0.7 [+0.2, +1.3]** |
| file Acc@5 | 86.8 | 85.9 | **−0.9 [−1.2, −0.6]** |
| file MRR | .761 | .761 | 0.0 [−.003, +.004] |
| region Acc@1 | 39.8 | 53.8 | **+14.1 [+13.4, +14.7]** |
| region Acc@5 | 50.7 | 69.9 | **+19.3 [+18.6, +19.9]** |
| region MRR | .446 | .600 | +.155 |
| module from top file | 90.9 | 90.9 | (free loop gives no module of its own) |
| chain steps citing a log event | 0% | 57.4% | |
| calls / prompt tokens / wall | 13.6 / 98.9k / 199 s | 15.7 / 106.4k / 286 s | |

By report type, file Acc@1: trace −0.3 [−1.3, +0.7] (n 7,808);
logs no trace +1.4 [+0.3, +2.4] (5,739); prose +1.1 [+0.3, +1.8] (12,990).
Free loop on hard (12,797): 53.3 / 74.7.

Measured failure modes of the free loop that the workflow was designed
from (`agent/workflow.py` header, `scripts/trace_analysis.py`): 83.2% of
runs end only because the budget removed the tools (runs that stop on
their own are right 95.8%, forced ones 62.2%); 72.7% of read_code calls
re-read a file; a gold file is first named on turn 1 in 82.8% of runs and
turns 4 to 14 add 5.1 points; 55.8% of failures have the gold file in the
answer but not first, and 79.2% of those read it; at the answering call a
median 55.7% of tool output is no longer in context; callers_of was called
in 3.8% of runs; answers name 2.8 to 3.7 files.

### C4. Against reimplemented published agents, 1,000-instance sample (483 hard)

| system | Acc@1 | Acc@5 | hard@1 | hard@5 | calls | prompt tokens | empty |
|---|---|---|---|---|---|---|---|
| wf | .671 | .851 | .522 | .721 | 15.8 | 107,883 | 0% |
| LocAgent-style | .599 | .715 | .404 | .524 | 13.9 | 105,563 | 8.2% |
| CoSIL-style | .472 | .594 | .172 | .277 | 18.8 | 23,312 | 10.1% |

Paired, wf minus theirs: LocAgent Acc@1 +.072 [+.045, +.100], Acc@5 +.136
[+.110, +.162], hard@1 +.118 [+.075, +.164], hard@5 +.197 [+.153, +.240].
CoSIL Acc@1 +.199 [+.168, +.229], Acc@5 +.257 [+.229, +.287], hard@1 +.350
[+.304, +.398], hard@5 +.443 [+.395, +.491]. All significant.
LocAgent-style called traverse_graph 0.09 times per run (search_entity
14.5). Port check fails again: CoSIL-style has the higher empty rate.
Do not compare wall time (different GPU load during the runs).

### C5. Per project (wf vs retrieval layer, Acc@1 / Acc@5, %)

| project | n | hard% | wf@1 | wf@5 | lex@1 | lex@5 |
|---|---|---|---|---|---|---|
| hive | 3,285 | 59 | 69.7 | 86.9 | 42.3 | 72.1 |
| hadoop | 3,070 | 39 | 79.6 | 91.6 | 52.0 | 80.4 |
| mongodb | 2,535 | 59 | 72.9 | 86.2 | 43.9 | 69.5 |
| ambari | 2,301 | 70 | 58.5 | 77.6 | 31.6 | 63.0 |
| hbase | 2,272 | 37 | 78.3 | 91.4 | 51.5 | 78.1 |
| mariadb | 1,201 | 45 | 60.4 | 85.1 | 33.6 | 64.9 |
| spark | 1,096 | 39 | 70.0 | 88.0 | 37.3 | 70.0 |
| sakai | 1,008 | 47 | 74.3 | 91.4 | 52.5 | 80.3 |
| cassandra | 995 | 40 | 60.0 | 84.0 | 36.0 | 70.4 |
| flink | 760 | 33 | 60.5 | 81.8 | 35.8 | 61.3 |
| groovy | 705 | 72 | 60.7 | 82.8 | 36.3 | 61.4 |
| camel | 609 | 36 | 74.2 | 89.8 | 46.6 | 73.4 |
| infinispan | 604 | 38 | 54.3 | 75.2 | 30.5 | 55.8 |
| impala | 544 | 47 | 66.7 | 84.0 | 36.2 | 65.3 |
| solr | 516 | 35 | 75.8 | 93.4 | 39.9 | 76.2 |
| phoenix | 511 | 55 | 67.3 | 87.1 | 49.3 | 77.1 |
| wildfly | 508 | 57 | 60.8 | 79.9 | 35.8 | 62.8 |
| pdfbox | 500 | 22 | 71.6 | 89.6 | 42.8 | 80.0 |
| ignite | 487 | 31 | 63.0 | 86.0 | 38.4 | 71.0 |
| kafka | 479 | 26 | 76.2 | 92.5 | 49.3 | 79.5 |
| derby | 474 | 58 | 55.5 | 73.4 | 25.5 | 53.2 |
| geode | 440 | 39 | 61.6 | 81.8 | 31.1 | 62.5 |
| pig | 424 | 46 | 60.4 | 80.0 | 29.0 | 57.3 |
| drill | 376 | 61 | 60.6 | 81.6 | 27.7 | 58.8 |
| qt | 320 | 68 | 62.5 | 80.3 | 30.6 | 54.1 |
| keycloak | 302 | 44 | 63.2 | 82.8 | 34.4 | 66.9 |
| beam | 222 | 35 | 67.1 | 82.0 | 36.0 | 61.7 |

---

## D. Decisions still open (answer these before C and E below)

- [x] **D1. Old 4-project results: DROP ALL OF THEM** (decided Nov 13).
      Every number in the paper is from the 27-project benchmark. Gone:
      IRBL table, model-alone, re-ranker, fusion, leakage experiment,
      causal annotation, judge, shuffle, contamination, rolling origin,
      noise table, 168-instance ablation. The gold-is-a-proxy point stays
      as a threat, without the old numbers.
- [ ] **D2. One small GPU run** for model-alone and model re-ranker on
      the 1,000 sample. Explained in the chat on Nov 13; waiting for
      yes / no. If yes: ~$10 to $15 on the 8x VM (boot + two dependent
      stages), ~1 hour of setup, prompts built and scored on the VM
      because both need the snapshot file lists.
- [x] **D3. Title: change it** (decided Nov 13). Working title:
      "Log-Guided Root-Cause Code Localization from Production Issues:
      A Staged Agent Evaluated on 26,544 Real Incidents". Final wording
      at the end.
- [x] **D4. System name: keep REMEMBER** for now; revisit at the end.

---

## E. Page budget (target ~7,200 words, 5 tables, 1 figure)

| section | now | target | what goes |
|---|---|---|---|
| abstract | 0.5 p | 0.3 p | rewrite around C1, C3, C4 |
| 1 intro | 2 p | 1 p | keep KAFKA-6624 and the hard-stratum point; "what root cause means" to 3 sentences; 3 contributions; drop `research.pdf` |
| 2 benchmark | 1.5 p | 1.2 p | 27-project funnel table; compact per-project list; cut second hard-definition paragraph; limits to 3 sentences |
| 3 retrieval layer | 1.5 p | 0.7 p | one paragraph per signal; firewall as 4 bullets; fusion in 3 sentences; drop `architecture.pdf` |
| 4 agent | 1.5 p | 1.5 p | REWRITE: measured failure modes of the free loop, then the staged workflow (gather, route, shortlist, examine, walk back, rank, check); one new figure; drop the tool-usage table |
| 5 setup | 1.5 p | 0.6 p | split; two populations (26,544 full; 1,000 sample for agent baselines); metrics; stats; cut sampling and test-only-gold passages to 3 sentences each |
| 6 results | 7 p | 3 p | KEEP: headline table (wf vs free loop vs retrieval, by stratum, file+module+region); LocAgent/CoSIL table; retrieval layer and memory on the hard stratum (pooled); function level; module level; cost; short dense paragraph; honest negatives. DROP: per-project retrieval table, full module table, noise table, judge, shuffle, contamination, 168-instance ablation, RQ2/RQ3 |
| 7 discussion + threats | 2 p | 0.8 p | three difficulties, one paragraph each; threats; drop KAFKA-9747 walkthrough and deployment notes |
| 8 related | 0.7 p | 0.5 p | trim |
| 9 conclusion | 0.5 p | 0.2 p | |

---

## F. Tasks, in order

### F1. Numbers and data (no writing yet)
- [x] 1. Pooled numbers computed (`paper_numbers.py` ->
      `C:\Users\17yuv\AppData\Local\Temp\c7cmp\paper-numbers.json`, see
      C2, C2b-d). Module baselines for 27 projects: running on the laptop
      (`scripts/module_baselines.py` -> `data/results/module-baselines.json`,
      log `C:\Users\17yuv\AppData\Local\Temp\c7cmp\module-baselines.log`).
- [x] 2. SKIPPED. `explanation_checks.py` was written for the v3 rows;
      c7_coverage already reports log-citation grounding for wf (85.7% of
      cited events exist in the report). The paper uses that.
- [x] 3. `agentic_baselines_compare.py --ours <rows>` added; key is now
      `ours`; `data/results/agentic-baselines.json` regenerated (Nov 13
      16:45). The LocAgent/CoSIL rows are in `data/agent/`.
- [x] 4. Model-alone (a1->a2), re-ranker (rr), contamination probe (cp)
      on the 1,000 sample: DONE Nov 13, 21:38-22:06 UTC on the VM
      (~$9.50; VM stopped by the guard at 22:06). Results on the laptop in
      `data/llm-27/` (`scored-{a2,rr,cp}.jsonl`, `results/llm-*-summary.json`,
      raw `resp-*.jsonl`, prompts not copied). Pooled over the 1,000:
      model alone Acc@1 52.7 / Acc@5 71.0 (2 calls, 15.7k prompt tokens);
      re-ranker 60.8 / 79.0 (1 call, 2.8k tokens); contamination probe:
      key only 0.0 / 0.0, claimed recall 0%; key + title 1.6 / 1.6,
      claimed 2.1%. No parse failures. `paper_tables.py` adds the two
      rows to `tables/agents.tex` and the paired deltas to `sources.json`.

### F2. main.tex
- [x] 5. Macros replaced (Nov 13 ~17:00). Still placeholders:
      `\moduleFreq` (waits for `module-baselines.json`, laptop job).
- [x] 6. New title and abstract written. Abstract still lacks the
      model-alone / re-ranker numbers (add when F1.4 lands).

### F3. Sections, results first (all drafted Nov 13, 17:00-18:00)
- [x] 7. §6 Results drafted. Tables come from `scripts/paper_tables.py`
      -> `paper/tables/{headline,agents,retrieval,functions,modules}.tex`
      (+ `sources.json`), included with `\tablebody{}` (the primitive
      `\@@input`; LaTeX's `\input` breaks `\bottomrule` inside a tabular).
      Model-alone and re-ranker rows appear automatically once
      `data/llm-27/scored-{a2,rr}.jsonl` exist; then add their paired
      intervals to the text (from `tables/sources.json`).
- [x] 8. §4 Agent rewritten; figure `figures/workflow.svg` -> `.pdf`
      (rsvg-convert in WSL). Re-check it on the compiled page.
- [x] 9. §2 Benchmark rewritten (funnel table, 27 projects, strata,
      memory pool 172,331 entries).
- [x] 10. §1 Intro rewritten (three contributions).
- [x] 11. §3 Retrieval layer cut; architecture figure dropped.
- [x] 12. §5 Setup cut.
- [x] 13. §7 Discussion + threats cut.
- [x] 14. §8 Related, §9 Conclusion cut.
- [x] 14b. `module-baselines.json` done 17:45 (27 projects). Pooled:
      random 5.7 / 25.8, frequency prior (live modules) 49.3 / 76.8;
      `\moduleFreq` = 49.3%; rows in `tables/modules.tex`.
- [x] 14c. Model-alone / re-ranker / contamination numbers are in §6.3,
      the abstract, the intro and the discussion (the "ladder" paragraph).

### F4. Build and check
- [x] 15. Compiles (11 pages: body to mid page 10, refs to page 11),
      0 overfull. `verify_paper.py`: 99 of 100 checks pass; the open one
      is `\moduleFreq` (module-baselines job still running on the laptop).
      Gotchas found: every file this session wrote had CRLF (fixed with
      `sed -i 's/\r$//'`; `paper_tables.py` now writes LF); `\input`
      inside a tabular fails (use `\tablebody`).
- [x] 16. Superseded by `scripts/verify_paper.py` (117 checks, all
      pass, tables regenerated and byte-identical). `verify_claims.py` is
      left as the record of the old four-project paper.
- [x] 17. Anonymity grep clean (no cluster, vendor or author names);
      references end on page 11 (allowed); figure checked at print
      resolution.
- [x] 18. Committed Nov 13 17:52: `2725f7c` (paper, tables, figure,
      paper scripts) and `65d6bde` (fleet scripts, todolist). Not pushed;
      `1aba0cf` was not pushed either.

### Submission
- PDF: `industry-c7/paper/main.pdf` (11 pages; body ends mid page 10).
- Rebuild: `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/c/workplace/JiraAndLogs/industry-c7/paper && latexmk -pdf main.tex'`
- Re-verify: `python industry-c7/scripts/verify_paper.py --wf <wf rows> --loop <loop rows>`
  (rows: `C:\Users\17yuv\AppData\Local\Temp\c7cmp\lcwf\{wf-seed42,lc-main}.jsonl`;
  rebuild them from `data/agent/` if the temp folder is gone).

### F5. After submission (not today)
- [ ] Delete the Nebius disk `c7-boot` (250 GB, still billed).
- [ ] Delete the RunPod API key that appeared in chat.
- [ ] Trillium-gpu still holds seed-42 tasks in `queue/pending` (skip
      markers block them); move them to `queue/cancelled` when the login
      works again.
- [ ] Fix `llm_step` to catch `GraphRecursionError` so RANK falls back to
      the cards instead of killing the run.

---

## G. Page log

| time | build | pages | note |
|---|---|---|---|
| Nov 4 | main.pdf | 20 | old benchmark, old agent |
| Nov 13 17:05 | main.pdf | 10 | first full build of the rewrite; two tables too wide |
| Nov 13 17:20 | main.pdf | 11 | tables fixed, model-baseline rows and text added; body ends mid page 10, refs run to page 11 (allowed: 10 + up to 2 pages of refs) |
| Nov 13 17:48 | main.pdf | 11 | FINAL: module baselines in; 0 overfull; `verify_paper.py` 117 of 117 (tables regenerated and identical) |
| Nov 14 01:50 | main.pdf | 11 | final review: new agent figure (`figures/final.pdf`) + author's prose abstract; conclusion trimmed so the body ends on page 10 and refs start there; 0 overfull; `verify_paper.py` 121 of 121 |

### Final review (Nov 14)
- Abstract is now hand-typed prose; its 13 numbers are pinned in
  `verify_paper.py` (new block "abstract") against the macros and result files.
- `paper_numbers.py` and `c7_coverage.py` stored percentages rounded to
  4 decimals, so exact ties (0.5385, 0.6525) were rounded twice and the
  verifier disagreed with the text by 0.1. Both now store 6 decimals,
  the verifier rounds half-up like a reader, and three sentences were
  corrected to the exact values: chain steps citing a log event 57.3 %
  (was 57.4), module on easy reports 94.6 % (was 94.5), region Acc@1
  without pilots 53.8 % (was 53.9), LocAgent-parsed wf Acc@1 68.8 % (was 68.9).
- Known: Fig. 1 is the full draw.io diagram at text width; its 9 pt
  labels print at about 1.7 pt. The author chose it over a compact variant.
- Nov 14 02:10: `paper_tables.py` rounds with the same tie rule as the
  verifier and the ablation table compares both arms on the 26,537 paired
  instances (its loop row now reads 39.8 like the text). Tables regenerated;
  cells that moved by the tie rule: MRR 0.538→0.539, cites 57.4→57.3,
  BM25 MRR 0.314→0.313, sample retrieval hard Acc@5 48.6→48.7, LocAgent MRR
  0.646→0.647, model-alone hard Acc@5 51.5→51.6. Verifier 127 of 127 with
  table regeneration; refs still start on page 10.
- Artifact: `C:\workplace\remember-artifact` (own git repo, author "The
  Authors"); benchmark zip built (96 MB); code+results zip on hold until the
  system name is settled.

### Verification
- `scripts/verify_paper.py --wf <rows> --loop <rows>` checks every macro,
  regenerates the tables and diffs them, and checks the intervals and
  percentages quoted in the sections. Supersedes `verify_claims.py` for
  this paper (the old script's 267 checks pin the 4-project numbers).
- The run-to-run variation rows were fetched from the VM on Nov 13
  (3-minute start, ~$1) into `data/agent/vm/check20/`; the verifier now
  checks those numbers too (109 of 110 pass; `\moduleFreq` pending).
- Decided Nov 13: commit the paper and scripts when the build is final.
