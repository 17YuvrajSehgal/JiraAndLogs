# Pathidea: Improving IR-Based Bug Localization by Re-Constructing Execution Paths Using Logs

**An Ran Chen, Tse-Hsun (Peter) Chen, Shaowei Wang. IEEE TSE 48(8):2905–2919, 2022. DOI 10.1109/TSE.2021.3071473.**
PDF: `pdfs/pathidea-tse2022.pdf` · Data: github.com/SPEAR-SE/Pathidea_Data

## Why this paper matters to us most

It is the closest prior work to our setting: Jira bug reports that CONTAIN
LOGS, localized to files of the pre-fix snapshot. It is simultaneously (a) a
baseline candidate, (b) the main threat to any "first benchmark with logs"
claim, and (c) independent evidence for our symptom-vs-cause stratum.

## Method (exact mechanics, needed if we re-implement)

Four additive score components over files of the snapshot "commit prior to
the bug fixing commit" (identical snapshot convention to ours):

1. **VSM score**: cosine VSM over 800-token file segments (BRTracer-style
   segmentation; file score = max segment score). Preprocessing: tokenize,
   drop language keywords, camelCase/underscore split, NLTK stopwords,
   Porter stemming.
2. **Log score**: regex-extract logs from the report. Stack-trace frames:
   score 1/rank for the top-10 frames, 0.1 beyond, rank resets per trace.
   Log-snippet lines: map the fully-qualified logger class to its file,
   constant α = 0.1 per distinct file. Files not in the repo (external
   libraries) are dropped.
3. **Path score**: the novel part. Build a file-level call graph
   (JavaParser ASTs), then BFS between each consecutive pair of log
   statements to recover the code that must have run BETWEEN the observed
   log lines. Every file on such a path gets β × N(VSMScore), β = 0.2.
   This finds files that produced NO log line — their running example and
   Fig. 1/2 (YARN-8209) is exactly our KAFKA-6624 story: the fix landed in
   PrivilegedOperation, which the stack trace never names because its frame
   was already popped.
4. **Final** = N(VSM) + LogScore + PathScore.

Call-graph + path construction costs 22 min per system (79k–1.2M LOC) on a
4-core VM, once, incrementally updatable.

## Dataset (the benchmark-claim threat, precisely)

8 Java systems (ActiveMQ, Hadoop Common, HDFS, MapReduce, YARN, Hive,
Storm, ZooKeeper). Jira issues: Resolved/Fixed, priority Major+, created
2010+, fix commit found by grepping the issue key in commit messages,
non-Java-touching fixes excluded. 6,535 linked reports, of which **1,273
(≈20%) contain logs** — that subset is the evaluation set. So: issue text +
logs + pre-fix snapshot + gold fix files all exist here. Our §2 "to our
knowledge first" sentence must be narrowed to what is actually new:
multi-language (C/C++/Java/Scala), 5× larger (6,437 vs 1,273), two tracker
ecosystems, time-ordered split, leakage-controlled memory pool, and the
easy/hard stratification. Cite Pathidea's dataset explicitly.

Their 20%-of-reports-have-logs number is also a useful external anchor for
our population definition (WoL's log-bearing filter).

## Results and what the numbers mean

- **Table 2 (vs baselines):** average MAP 0.35 vs BRTracer 0.31 vs VSM
  ~0.15; MRR 0.43 vs 0.38. Per-system MAP improvement over BRTracer 8–24%
  relative (ActiveMQ +21%, HDFS +24%, Hadoop +8%). All significant by
  Wilcoxon rank-sum (note: rank-sum, not paired signed-rank — a weaker,
  arguably wrong test for paired data; our paired bootstrap is stronger).
- Meaning of the absolute level: Recall@10 = 50.3% average — i.e., even the
  best log-aware IRBL of 2022 finds only half the buggy files in the top
  ten, on log-bearing Java reports. Our MongoDB file Acc@10 and their
  Recall@10 are not directly comparable (different metric and population),
  but the headroom message matches our hard stratum.
- **RQ2 (ablation):** adding just the path analysis to BRTracer gives +10%
  MAP, +8% MRR; biggest gains at Top@1 (+12% precision, +14% recall).
  Meaning: the between-the-log-lines files are real signal, not decoration.
- **RQ3 (sensitivity):** α and β best in 0.1–0.2 everywhere; larger values
  degrade. Segmentation best at 400–800 tokens.
- **Discussion gold for us:** systems whose log-bearing reports are mostly
  stack-trace-only (Hive 86.5%, Storm 69.8%) gain the LEAST from path
  analysis, and they cite prior work that "many bug fixing locations may
  not be directly related to the reported stack traces." That is the
  symptom-vs-cause difficulty, observed independently. Also: improvement
  correlates with LOG DENSITY (ZooKeeper, 32 logging lines per kLOC, gains
  +40% P@1; Hive, 8/kLOC, gains least). For our paper this suggests a
  per-project covariate we could report (logging density of the four
  projects) and a reason Qt (UI framework, low logging) is hard.

## Weaknesses / gloss-overs

- Java-only machinery (JavaParser, fully-qualified logger names, `.java`
  frame regex). Porting path analysis to C++ (MariaDB/MongoDB/Qt) is a
  research task in itself — this is the honest reason Pathidea cannot be a
  baseline on 3 of our 4 projects; we can state it and optionally run a
  Pathidea-style log-boost on Kafka only.
- No history signal at all: no similar-report component, so no leakage
  surface — but also no memory. Orthogonal to our S4.
- Not time-aware in evaluation beyond the snapshot choice; no duplicate
  handling; no multiple-test correction; rank-sum instead of paired test.
- Priority filter (Major+) silently drops minor bugs; population therefore
  skews severe. Our benchmark has no priority filter — worth one sentence.
- 1,273 reports across 8 systems is small per system (38–257); per-system
  deltas ride on few dozen instances in places.

## Use in our paper

- Related work §3 (logs for localization): the flagship citation, one
  sentence on mechanism + the trace-only finding supporting our stratum.
- §2 benchmark: cite when narrowing the "first" claim; compare populations
  in one line (1,273 Java log-bearing vs our 6,437 multi-language).
- §6 difficulties: log-density observation supports "memory matters where
  textual evidence is weakest."
- Baseline table: "Pathidea (Java-only; snapshot convention identical to
  ours)" — candidate on Kafka if time permits; otherwise cited with the
  porting-cost justification.

## Thesis connection

The path-reconstruction idea (logs → which code MUST have executed between
two observed events) is the static sibling of what kernel tracing does
dynamically; the authors are the SPEAR lab (Concordia — performance
analysis). If the thesis ever argues for log-guided replay of executions in
the RCA framework, this is the canonical SE-side citation.
