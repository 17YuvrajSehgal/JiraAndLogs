# Related Work and Baselines for REMEMBER: A Literature Survey for Log-Guided Root-Cause Code Localization

The closest prior work to REMEMBER is classic information-retrieval-based bug localization (IRBL), and BugLocator's "SimiScore" (ICSE 2012) already uses fixed files from textually similar past bug reports to rank files.\[1\]\[2\] So "incident memory" is not new as an idea. What can be new is how REMEMBER uses it: a strict temporal firewall, duplicate-cluster exclusion, log-bearing reports, multi-language C/C++/Java/Scala projects, regime-conditioned fusion, and module-level output with provenance. Reviewers will expect at least three kinds of external baselines: (1) a BugLocator-style rVSM+SimiScore re-implementation, (2) a stack-trace/log-aware IRBL tool (BRTracer or Pathidea), and (3) one LLM-based localizer that runs from issue text and code only (Agentless localization stage, LocAgent, or LLM-BL).

## TL;DR

- **Biggest novelty threat:** BugLocator (Zhou, Zhang, Lo, ICSE 2012) scores each file by summing the similarity of past fixed reports that touched it, divided by how many files each fix changed, and mixes this with text similarity using α ≈ 0.2–0.3. AmaLgam, AmaLgam+, BLIA, ABLoTS and RCACopilot also reuse history. REMEMBER must present S4 as a leakage-safe, evaluated version of this idea, and it must include a SimiScore baseline.
- **Biggest benchmark threat:** Pathidea (Chen, Chen, Wang, TSE 2022) already uses 1,273 Jira bug reports *with logs* from eight Java systems, linked to fix commits. Long Code Arena and SWE-bench give issue text, snapshot and gold files, and their issue text sometimes contains stack traces. So "first public benchmark with issue + logs + snapshot + gold files" is too strong. Make the claim narrower: first *large-scale, multi-language (C/C++/Java/Scala), time-split* benchmark of log-bearing production reports.
- **Best baselines to add:** BugLocator (rVSM + SimiScore), BRTracer, Pathidea (or a Pathidea-style log-path signal), Locus or AmaLgam (history), BLAZE (cross-language dense + BM25 with RRF), and one LLM localizer (Agentless localization, LocAgent or LLM-BL). Bench4BL found "no significant differences" among the six classic IRBL tools, so one or two of them is enough. Pick BugLocator and BRTracer.

## Key Findings

1. BugLocator's SimiScore is the direct ancestor of S4. Its formula is SimiScore(q, d) = Σ over past reports b that fixed d of sim(q, b) / n_b, where n_b is the number of files fixed for b. FinalScore = (1−α)·N(rVSM) + α·N(SimiScore).\[3\]\[4\] Bench4BL ran it with α = 0.3.\[5\]
2. Bench4BL (Lee et al., ISSTA 2018) re-ran six IRBL tools on 46 new projects (61,431 Java files, 9,459 bug reports). It found no clear winner. BRTracer had the best MAP/MRR on new subjects (0.333 / 0.469), and BLUiR was best on the old subjects.\[5\]\[6\]
3. Time-aware evaluation is an accepted concern but is not standard practice. Bench4BL showed that "single version" evaluation is flawed.\[5\] Broccoli (2021) showed that time-aware evaluation gives significantly different results.\[7\] The ABLoTS replication (2026) found that using fixed dates instead of creation dates leaks data.\[8\] REMEMBER's firewall answers a known problem, and this supports its contribution.
4. LLM localizers report high numbers on SWE-bench Lite (file Acc@1 ≈ 77–84%), but those numbers drop sharply on harder or less-known benchmarks. LocAgent falls below 40% Acc@5 on MULocBench. SWE-Bench+ (Aleithan et al., arXiv 2410.06992) found that "32.67% of the successful patches involve cheating as the solutions were directly provided in the issue report or the comments," and that "over 94% of the issues were created before LLM's knowledge cutoff dates." This matches REMEMBER's "hard stratum" argument well.
5. Cloud AIOps RCA (RCACopilot, RCAgent, OpenRCA, RCAEval) works at the level of service, component or root-cause category, not source files. RCACopilot retrieves the top-5 similar past incidents with a time-decay weight, but it does not use a strict past-only filter.\[9\] This is a related idea at a different granularity.

## 1. Information-Retrieval-Based Bug Localization (IRBL)

**BugLocator.** Jian Zhou, Hongyu Zhang, David Lo. "Where Should the Bugs Be Fixed? More Accurate Information Retrieval-Based Bug Localization Based on Bug Reports." ICSE 2012, pp. 14–24. DOI 10.1109/ICSE.2012.6227210.\[1\]
- What it does: a revised Vector Space Model (rVSM) that favors larger files, plus SimiScore from similar past fixed reports (see Section 2 for the exact formula).\[10\]\[11\]
- Inputs: report text, code snapshot, past fixed reports with their fixed files. No tests.
- Granularity: file.
- Data and numbers: Eclipse 3.1, AspectJ, SWT, ZXing (more than 3,000 bugs). For 62.60% of Eclipse 3.1 bugs, a buggy file is ranked in the top 10 among 12,863 files.\[12\] The reported MAP range is about 0.22–0.55 across the four projects.\[3\]
- Code: the Bench4BL replication package (github.com/exatoa/Bench4BL) contains a runnable version (Java only).\[3\]\[5\]
- For REMEMBER: **must-have baseline and main novelty threat.** It is simple to re-implement for C/C++/Scala because rVSM and SimiScore are language-independent.

**BLUiR.** Ripon K. Saha, Matthew Lease, Sarfraz Khurshid, Dewayne E. Perry. "Improving Bug Localization Using Structured Information Retrieval." ASE 2013, pp. 345–355.\[13\]
- What it does: splits code into class names, method names, identifiers and comments, and splits the report into summary and description. It then sums similarities over these fields. A later version also adds SimiScore.\[14\]
- Inputs: report, code (Java AST). Granularity: file.
- Code: in Bench4BL (Java only).\[15\]
- For REMEMBER: related work, and an optional baseline. Its field-based idea is close to REMEMBER's S2 (path tokens) plus S3 (contents).

**BRTracer.** Chu-Pan Wong, Yingfei Xiong, Hongyu Zhang, Dan Hao, Lu Zhang, Hong Mei. "Boosting Bug-Report-Oriented Fault Localization with Segmentation and Stack-Trace Analysis." ICSME 2014, pp. 181–190.\[16\] DOI 10.1109/ICSME.2014.40.
- What it does: splits each file into segments, represents a file by its best segment, and boosts files that appear in stack traces (and files they reference). It extends BugLocator, including SimiScore.\[5\]\[17\]\[18\]
- Inputs: report with stack traces, code, past reports. Granularity: file.
- Data: Eclipse, AspectJ, SWT (3,459 bug reports). It significantly beats BugLocator on all three.\[19\]
- Code: brtracer.sourceforge.net and Bench4BL.\[15\]
- For REMEMBER: **strong baseline.** It is the classic "stack trace signal" and is the direct ancestor of S1.

**Moreno et al. / Lobster.** Laura Moreno, John Joseph Treadway, Andrian Marcus, Wuwei Shen. "On the Use of Stack Traces to Improve Text Retrieval-Based Bug Localization." ICSME 2014.\[20\]
- What it does: combines textual similarity with structural distance between code classes and classes in the stack trace.
- For REMEMBER: related work for S1. Its key idea, that the fault is often *near* but not *in* the trace, supports your "detected vs caused" observation.

**AmaLgam.** Shaowei Wang, David Lo. "Version History, Similar Report, and Structure: Putting Them Together for Improved Bug Localization." ICPC 2014, pp. 53–63. DOI 10.1145/2597008.2597148.\[21\]
- What it does: combines three things. (a) A Google-style bug-prediction score from recent version history (recently and often-fixed files). (b) BugLocator's SimiScore. (c) BLUiR's structure score.\[22\]\[23\]\[24\]
- Inputs: report, code, commit history, past reports. Granularity: file.
- Numbers: it reports an average MAP improvement of 24.4% over a history-aware baseline, and beats approaches using only similar reports and structure by an average of 12.5%.\[23\]\[24\]
- Code: in Bench4BL.\[15\]
- For REMEMBER: **novelty threat and baseline candidate** (history plus similar reports, fused).

**AmaLgam+.** Shaowei Wang, David Lo. "AmaLgam+: Composing Rich Information Sources for Accurate Bug Localization." Journal of Software: Evolution and Process 28(10), 2016. DOI 10.1002/smr.1801.\[25\]
- What it does: five sources. These are version history, similar reports, structure, stack traces and reporter information.\[26\]\[27\]
- Numbers: 6.0% MAP gain over AmaLgam on average (12.0% on AspectJ and Eclipse, where many reports have stack traces), and 33.1% over BugLocator.\[25\]\[26\]\[28\]
- For REMEMBER: related work. It shows that "fusing many weak signals" is an established IRBL design, so your fusion alone is not novel. Your regime conditioning and temporal firewall are what make it different.

**BLIA.** Klaus Changsun Youm, June Ahn, Jeongho Kim, Eunseok Lee. "Bug Localization Based on Code Change Histories and Bug Reports." APSEC 2015, pp. 190–197.\[29\]
- What it does: combines text similarity, similar reports, stack traces, structure and change history.\[5\]\[30\]
- Code: in Bench4BL.
- For REMEMBER: related work. It is another "all signals" fusion that includes similar reports.

**Locus.** Ming Wen, Rongxin Wu, Shing-Chi Cheung. "Locus: Locating Bugs from Software Changes." ASE 2016, pp. 262–273.
- What it does: ranks change hunks from history, not files, and adds a recency boost.
- Inputs: report, commit history. Granularity: change hunk (can be mapped to file).
- Code: in Bench4BL.
- For REMEMBER: optional baseline. It is the strongest "history-only" view and had the best MAP on 17 projects in Bench4BL.\[5\]

**Learning to Rank (LR).** Xin Ye, Razvan Bunescu, Chang Liu. "Learning to Rank Relevant Files for Bug Reports Using Domain Knowledge." FSE 2014, pp. 689–699.\[31\] DOI 10.1145/2635868.2635874. Journal version: "Mapping Bug Reports to Relevant Files: A Ranking Model, a Fine-Grained Benchmark, and Feature Evaluation," TSE 2016.\[32\]
- What it does: an SVMrank over 19 features, including text similarity, API-doc similarity, collaborative filtering (similar past reports), bug-fix recency and bug-fix frequency.
- Data: AspectJ, Birt, Eclipse Platform UI, JDT, SWT, Tomcat (over 6,400 reports in the first paper). It is right in the top 10 for over 70% of reports on Eclipse Platform UI and Tomcat.\[33\]
- Dataset: public on Zenodo (record 268486). It uses chronological folds.\[11\]\[34\]
- For REMEMBER: related work. Its "collaborative filtering" feature is another similar-report signal. Its chronological folds are a precedent for your time split.

**DNNLoc and deep IRBL.** An Ngoc Lam, Anh Tuan Nguyen, Hoan Anh Nguyen, Tien N. Nguyen. "Combining Deep Learning with Information Retrieval to Localize Buggy Files for Bug Reports," ASE 2015, and "Bug Localization with Combination of Deep Learning and Information Retrieval," ICPC 2017. (Venue details are from general knowledge; check before adding to BibTeX.)
- What it does: a DNN that bridges words in the report and tokens in the code, combined with rVSM and metadata.
- For REMEMBER: related work only. It needs per-project training. The survey "When Deep Learning Meets Information Retrieval-based Bug Localization: A Survey" (ACM Computing Surveys 57(11), Article 296, 2025) is a good single citation for the whole deep-IRBL family.\[35\]

**FBL-BERT.** Agnieszka Ciborowska, Kostadin Damevski. "Fast Changeset-Based Bug Localization with BERT." ICSE 2022.
- What it does: ranks changesets (commits) using a BERT model.\[36\]
- Granularity: changeset or hunk.
- For REMEMBER: related work. It needs training and answers "which commit," not "which file in this snapshot."

**BLAZE.** Partha Chakraborty, Mahmoud Alfadel, Meiyappan Nagappan. "BLAZE: Cross-Language and Cross-Project Bug Localization via Dynamic Chunking and Hard Example Learning." IEEE TSE 2025. DOI 10.1109/TSE.2025.3579574 (arXiv 2407.17631).\[37\]
- What it does: a fine-tuned GPT-style embedding model with dynamic chunking. **It fuses a dense retriever (Milvus) and a lexical retriever (ElasticSearch) with reciprocal rank fusion.**\[38\]
- Data: the BeetleBox dataset (23,782 bugs, 29 projects, Java, C++, Python, JavaScript, Go), plus SWE-bench and Ye et al. The TSE abstract reports "up to an increase of 120% in Top 1 accuracy, 144% in Mean Average Precision (MAP), and 100% in Mean Reciprocal Rank (MRR)" against "six state-of-the-art baselines."
- Code and model: on Hugging Face (bug-localization/BLAZE).\[37\]
- For REMEMBER: **good baseline.** It is cross-language, needs no per-project training, covers C++ and Java, and is also a precedent for RRF in bug localization.

**LLM-BL.** Zhengliang Li, Zhiwei Jiang, Qiguo Huang, Qing Gu. "LLM-BL: Large Language Models are Zero-Shot Rankers for Bug Localization." ICPC 2025, pp. 548–559. DOI 10.1109/ICPC66645.2025.00064.\[35\]
- What it does: four steps. These are report expansion, candidate retrieval, content reduction, and listwise LLM ranking (ChatGPT, Llama 3). No fine-tuning is needed.\[39\]
- Inputs: report and code only.
- For REMEMBER: **good LLM baseline.** It has the same inputs as REMEMBER and the same "retrieve then rerank" shape.

**GenLoc.** "Leveraging Large Language Model for Information Retrieval-based Bug Localization" (arXiv 2508.00253, 2025).
- What it does: embedding retrieval plus a ReAct-style LLM that explores the code.\[40\]
- Data: over 9,000 bug reports from six large Java projects. It is compared with five state-of-the-art tools.\[40\]
- For REMEMBER: baseline candidate if code is released. Otherwise cite it as recent LLM-IRBL work.

**Other recent IRBL work to cite briefly:**
- BRaIn ("Improved IR-based Bug Localization with Intelligent Relevance Feedback," arXiv 2501.10542, 2025).\[41\]
- Rahman et al. "The Forgotten Role of Search Queries in IR-based Bug Localization" (EMSE; arXiv 2108.05341).\[42\]
- FinerBench4BL (method level, arXiv 2302.14293).\[43\]
- "Bug-Report–Driven Fault Localization: Industrial Benchmarking" (ABB Robotics, arXiv 2604.25700). This is a useful industry-track precedent: 660 industrial reports linked to fix commits, with component-level labels.\[44\]

**Bench4BL.** Jaekwon Lee, Dongsun Kim, Tegawendé F. Bissyandé, Woosung Jung, Yves Le Traon. "Bench4BL: Reproducibility Study on the Performance of IR-Based Bug Localization." ISSTA 2018, pp. 61–72. DOI 10.1145/3213846.3213856.\[6\]
- What it does: re-runs BugLocator, BLUiR, BRTracer, AmaLgam, BLIA and Locus on 46 new projects (Apache, Spring, JBoss; 9,459 reports) and 5 old ones.\[5\]
- Pooled MAP/MRR on new subjects (single-version setting):\[5\]

| Tool | MAP | MRR |
|---|---|---|
| BugLocator | 0.305 | 0.422 |
| BRTracer | 0.333 | 0.469 |
| BLUiR | 0.288 | 0.387 |
| AmaLgam | 0.291 | 0.390 |
| BLIA | 0.301 | 0.416 |
| Locus | 0.329 | 0.443 |

- Main messages: (1) multiple-version matching (code version at report time) should be used, and it raises scores (BugLocator MAP 0.305 → 0.371). (2) There are "no significant differences" among the six tools. (3) Merging duplicate reports can raise performance.\[5\]\[45\]
- For REMEMBER: cite it as the IRBL reproducibility reference. Its tool set is the standard set of runnable classic baselines. Point (3) matters for your duplicate-cluster exclusion: duplicates carry real signal, so leaving them in the memory inflates scores.

## 2. Historical Bug Reports and Similar Incidents as a Signal

**BugLocator SimiScore (exact mechanism).**
- Step 1: compute the cosine similarity between the new report q and every previously fixed report b.
- Step 2: each past report b spreads its similarity equally over the n_b files its fix changed. File d gets SimiScore(q, d) = Σ_{b fixed d} sim(q, b) / n_b.\[3\]\[4\] The secondary sources we found give no top-k cutoff, so all linked past reports contribute.
- Step 3: FinalScore = (1−α)·N(rVSM) + α·N(SimiScore), with min-max normalization N. The paper reports MAP/MRR rising as α goes from 0 to 0.3.\[1\]\[3\]
- Differences from REMEMBER S4:
  - S4 uses BM25 and only the top 20 neighbors, not all reports.
  - S4 votes by 1/rank of the neighbor, not by similarity / n_b.
  - S4 enforces a strict creation-time cutoff, plus exclusion of the query's duplicate cluster and of reports that share the fix commit.
  - S4 is fused by weighted RRF, conditioned on whether a file is named.
  - The original BugLocator text says it uses bugs "fixed before."\[1\] We could not confirm whether its evaluation enforced a per-query time cutoff, so do not claim it leaks. Say instead that it does not describe duplicate or shared-commit exclusion.

**ABLoTS.** Michael Rath, David Lo, Patrick Mäder. "Analyzing Requirements and Traceability Information to Improve Bug Localization." MSR 2018, pp. 442–453.\[8\]
- What it does: adds "TraceScore," a similar-report component built on issue–commit trace links. It is reported to beat both SimiScore and Ye et al.'s CollabScore.\[46\]
- A 2026 replication ("An Extensive Replication Study of the ABLoTS Approach for Bug Localization," arXiv 2605.11790) warns: "any commit information taken for file candidate scoring must have been already available by the fictive recommendation time (e.g., bug creation date)… using the bugs' fixed date may lead to data leakage."\[8\]
- For REMEMBER: **novelty threat** (history through Jira–commit links, like yours). It is also **strong support** for your firewall: a replication found the exact leakage your firewall blocks.

**Sisman and Kak.** Bunyamin Sisman, Avinash C. Kak. "Incorporating Version Histories in Information Retrieval Based Bug Localization." MSR 2012. (Details from general knowledge.)
- What it does: a prior probability that a file is buggy, from its past defect and modification history.\[24\]
- For REMEMBER: related work. It is a file-prior signal, not report similarity.

**Duplicate bug report detection.** (Details from general knowledge; check before citing.)
- Runeson, Alexandersson, Nyholm, ICSE 2007 (NLP-based).
- Wang, Zhang, Xie, Anvik, Sun, ICSE 2008 (text plus execution traces).
- Sun et al., ICSE 2010 (discriminative model).
- Sun, Lo, Khoo, Jiang, ASE 2011 (REP, BM25F-based).
- For REMEMBER: these find the *same* bug; S4 looks for *similar* bugs. Cite them to explain why you exclude the duplicate cluster: without that step, S4 would partly become a duplicate detector that copies the answer.

**Cloud incident linking and triage.** (Details from general knowledge.)
- Chen et al., "An Empirical Investigation of Incident Triage for Online Service Systems," ICSE-SEIP 2019.
- DeepTriage (Pham et al., KDD 2019).
- These route incidents to teams. They do not localize code.
- We could not verify "COLA" or "LinkCoM" with exact citations within our search budget. Do not cite them unless you find the papers yourself.

**RCACopilot.** Yinfang Chen, Huaibing Xie, Minghua Ma, et al. (Microsoft and UIUC). "Automatic Root Cause Analysis via Large Language Models for Cloud Incidents." EuroSys 2024, pp. 674–688. DOI 10.1145/3627703.3629553.\[47\]
- How it works: it matches incidents to handlers, collects diagnostic data, and predicts a root-cause *category* with an LLM. Its prompt includes the top K = 5 similar historical incidents.\[9\]\[48\]
- Retrieval details: a FastText embedding trained on its own incident history (GPT embeddings did much worse: Micro-F1 0.257 vs 0.766). Similarity is 1/(1+‖a−b‖)·e^(−α|T(a)−T(b)|) with α = 0.3, a time-*decay* weight.\[9\]
- Data and numbers: 653 incidents from one Microsoft email service, 75/25 split. Micro-F1 is 0.766 with GPT-4.\[9\]
- For REMEMBER: **novelty threat at the idea level** (retrieve similar past incidents). The differences are: category output, not files; time decay, not a strict past-only filter; no duplicate exclusion; private data.

**Time-aware and leakage-aware evaluation.**
- Broccoli (Hirsch and Hofer, arXiv 2109.11902): benchmarked eight approaches on 82 projects. It found that time-aware bug localization "leads to significantly different results," and it filters out reports "not fixed upon the time of the creation of the bug."\[7\]
- The 2025 deep-IRBL survey criticizes random splits and recommends chronological ("consecutive") validation and before-fix code versions.\[49\]
- "An Empirical Study on Data Leakage and Generalizability of Link Prediction Models for Issues and Commits" (arXiv 2211.00381) shows that random splits of issue–commit data inflate accuracy.\[50\]
- For REMEMBER: these are your citations for the time split and the firewall. None of the IRBL tools above describes excluding the duplicate cluster and reports that share the fix commit. That combination appears to be REMEMBER's own contribution. Say "to our knowledge."

## 3. Log-Based Fault Localization and Log-to-Code Mapping

**Pathidea.** An Ran Chen, Tse-Hsun (Peter) Chen, Shaowei Wang. "Pathidea: Improving Information Retrieval-Based Bug Localization by Re-Constructing Execution Paths Using Logs." IEEE TSE 48(8): 2905–2919, 2022. DOI 10.1109/TSE.2021.3071473.\[13\]
- What it does: parses logs pasted in bug reports, maps log lines to logging statements in code, and rebuilds possible execution paths with static analysis. Files on these paths get a boost on top of BRTracer-style IRBL.\[51\]
- Data: 8 Java systems, 1,273 Jira bug reports that contain logs.\[52\] Recall reaches up to 51.9% at Top-5. MAP improves by 8–21% and MRR by 5–21% over BRTracer.\[53\]
- For REMEMBER: **the closest prior work on log-bearing reports, and a must-cite.** It is both a baseline candidate and a benchmark novelty threat (see Section 6). Its dataset was reused by "Crash Report Enhancement with Large Language Models" (arXiv 2509.13535; 492 crash reports).\[52\]
- Related paper: "How Does Execution Information Help with Information-Retrieval Based Bug Localization?" (Dao, Zhang, Meng, ICPC 2017). It found that "logs often provide a good indication of where a bug is located."\[53\]

**LogFaultFlagger.** Anunay Amar, Peter C. Rigby. "Mining Historical Test Logs to Predict Bugs and Localize Faults in the Test Logs." ICSE 2019, pp. 140–151. DOI 10.1109/ICSE.2019.00031.\[54\]
- What it does: represents each log line with line-IDF, removes lines that also appear in passing logs, and uses exclusive kNN against *historical* failing logs to flag the failure-relevant *log lines*.\[55\]\[56\] Industrial setting (Ericsson).
- For REMEMBER: related work. It uses history and logs, but it localizes log lines, not code files, and it needs test logs.

**SherLog.** Ding Yuan et al. "SherLog: Error Diagnosis by Connecting Clues from Run-time Logs." ASPLOS 2010. (From general knowledge.)
- What it does: static analysis that infers which code paths must or may have run, given the logs.
- For REMEMBER: related work. It is the origin of the "logs to code paths" idea that Pathidea builds on, and it targets C programs.

**Crash and stack-trace localization.**
- CrashLocator (Rongxin Wu, Hongyu Zhang, Shing-Chi Cheung, Sunghun Kim, ISSTA 2014; from general knowledge) expands crash stacks using a call graph and ranks functions.
- Gu et al. "Does the Fault Reside in a Stack Trace? Assisting Crash Localization by Predicting Crashing Fault Residence." Journal of Systems and Software 148: 88–104, 2019 (CraTer). It uses 89 features to predict whether the fault is inside the trace, with 92% accuracy on 7 projects.\[57\]\[58\]
- For REMEMBER: this is **the best citation for your "detected ≠ caused" observation.** Crash studies already show that many faults lie outside the trace.\[59\]\[60\] Your 53% "hard" stratum gives the same message for logs in production reports.

**SBEST.** "Spectrum-Based Fault Localization Without Fault-Triggering Tests" (arXiv 2405.00565).
- Data: only 89 of 803 Defects4J bugs have stack traces in their reports.\[61\]
- For REMEMBER: a useful number to explain why Defects4J is a poor fit for log-guided localization.

**Other log work to cite:**
- Defects4Log (arXiv 2508.11305; logging-code defects).\[62\]
- "A Survey on Automated Log Analysis for Reliability Engineering" (He et al., ACM Computing Surveys 2021; arXiv 2009.07237).\[63\]\[64\]
- "Failure Diagnosis in Microservice Systems: A Comprehensive Survey and Analysis" (ACM TOSEM; DOI 10.1145/3715005).\[56\]

## 4. LLM and Agent-Based Localization (SWE-bench Style)

**Agentless.** Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, Lingming Zhang. "Agentless: Demystifying LLM-based Software Engineering Agents" (arXiv 2407.01489, 2024; FSE 2025).\[65\]
- What it does: hierarchical localization. The LLM picks files from the repo tree, then classes and functions, then edit lines. It also uses embedding retrieval.
- Inputs: **issue text and code only for localization.** Reproduction tests are used only in the later repair step.
- Numbers: reported file Acc@1 of about 67–73% on SWE-bench Lite (GPT-4o / Claude-3.5, as reported by LocAgent and SWE-Debate).\[66\]
- Code: github.com/OpenAutoCoder/Agentless.\[67\]
- For REMEMBER: **best LLM baseline candidate.** It is cheap, has no tests in the localization step, and is easy to point at C/C++/Java repos.

**LocAgent.** Zhaoling Chen, Xiangru Tang, Gangda Deng, et al. "LocAgent: Graph-Guided LLM Agents for Code Localization." ACL 2025 (arXiv 2503.09089).\[68\]
- What it does: builds a heterogeneous code graph (contain, import, invoke, inherit) and gives the agent search and traversal tools. It also introduces Loc-Bench (660 issues: bugs, features, security, performance).\[68\]\[69\]
- Numbers on SWE-bench Lite: BM25 has file Acc@1 38.7% and Acc@5 61.7%. LocAgent with Claude-3.5 has Acc@1 77.7%. According to the abstract, the fine-tuned Qwen-2.5-Coder-Instruct-32B cuts cost by "approximately 86%," reaches "up to 92.7% accuracy on file-level localization," and improves "downstream GitHub issue resolution success rates by 12% for multiple attempts (Pass@10)."
- Code: github.com/gersteinlab/LocAgent.\[67\]\[70\]
- Limitation: the graph builder targets Python.
- For REMEMBER: strong baseline if you can port the parser. If not, cite its BM25 vs agent gap.

**CoSIL.** Zhonghao Jiang et al. "Issue Localization via LLM-Driven Iterative Code Graph Searching" (arXiv 2503.22424, 2025).\[71\]
- Numbers: Top-1 accuracy of 43.3% (Lite) and 44.6% (Verified) with Qwen2.5-Coder-32B.\[71\]
- Inputs: issue and code only. Python only.
- For REMEMBER: related work or an optional baseline.

**OrcaLoca.** "OrcaLoca: An LLM Agent Framework for Software Issue Localization" (arXiv 2502.00350, 2025).\[72\]
- Numbers: 65.33% function match rate on SWE-bench Lite.\[72\]
- CoSIL's authors note that it uses traceback from reproduction tests. **So it is not a fair no-test baseline.**\[73\]
- For REMEMBER: related work only.

**Newer agents (2025–2026), cite as a group:**
- GraphLocator (arXiv 2512.22469; reports results on Multi-SWE-bench Java).\[67\]
- SHERLOC (arXiv 2606.24820; 84.33% Acc@1 on Lite).\[74\]
- BLAgent (arXiv 2605.17965).\[75\]
- SWE-Debate (arXiv 2507.23348; 81.67%).\[66\]
- Rafi et al. "Reformulate, Retrieve, Localize: Agents for Repository-Level Bug Localization" (arXiv 2512.07022).\[42\] This one is from the same group as your cited Rafi et al. paper and evaluates on Long Code Arena.\[76\]

**Test-based LLM fault localization (not fair baselines for REMEMBER, since they need failing tests):**
- AutoFL (Sungmin Kang, Gabin An, Shin Yoo, "A Quantitative and Qualitative Evaluation of LLM-Based Explainable Fault Localization," FSE 2024; Defects4J, needs a failing test).
- AgentFL (Qin et al., arXiv 2403.16362).
- FlexFL (IEEE TSE 2025).\[65\]
- SoapFL (IEEE TSE 2025).\[20\]
- Rafi et al. multi-agent FL (arXiv 2409.13642, already cited).\[42\]
- For REMEMBER: put these in a "requires executions/tests" paragraph to show why they do not apply.

**Benchmark caveats you should cite:**
- SWE-Bench+ (Aleithan et al., arXiv 2410.06992) found that 32.67% of successful patches came from "solution leakage" in the issue text.\[77\]
- The "SWE-Bench Illusion" study (Liang, Garg and Zilouchian Moghaddam, Purdue/Microsoft, arXiv 2506.12286) reports that "state-of-the-art models achieve up to 76% accuracy in identifying buggy file paths using only issue descriptions" (o3-mini on SWE-Bench Verified), against "merely up to 53% on tasks from repositories not included in SWE-Bench." This points to memorization.
- MULocBench (arXiv 2509.25242) shows LocAgent below 40% Acc@5, Agentless at 23.9% Acc@5, and BM25 below 10%.\[78\]
- For REMEMBER: these support the claim that high SWE-bench numbers do not carry over to production reports. They also warn that Kafka, MongoDB and Qt are surely in LLM training data, so an LLM baseline may be inflated by memorization. Report LLM baselines separately on issues created after the model's training cutoff.

## 5. Cloud and AIOps Root Cause Analysis

- **RCAgent.** Zefan Wang et al. "RCAgent: Cloud Root Cause Analysis by Autonomous Agents with Tool-Augmented Large Language Models." CIKM 2024.\[79\] A tool-using agent over logs, metrics and code at Alibaba. Output: root cause and explanation at the job or service level. Already cited.
- **RCACopilot** (EuroSys 2024): see Section 2. Output is a root-cause category.
- **Ahmed et al.** "Recommending Root-Cause and Mitigation Steps for Cloud Incidents Using Large Language Models."\[79\] ICSE 2023 (SEIP). Toufique Ahmed, Supriyo Ghosh, Chetan Bansal, Thomas Zimmermann, Xuchao Zhang and Saravan Rajmohan (arXiv 2301.03797) ran "a rigorous study at Microsoft, on more than 40,000 incidents," comparing models "in zero-shot, fine-tuned and multi-task setting." It works from the title and summary. Output: free-text root cause.
- **Xpert** (ICSE 2024; KQL query recommendation for incidents).\[79\]
- **"Automated Root Causing of Cloud Incidents using In-Context Learning with GPT-4"** (FSE Companion 2024; arXiv 2401.13810).\[79\] It retrieves similar past incidents as in-context examples. This is another history-retrieval precedent.
- **X-Lifecycle Learning** (FSE 2024 Companion).\[47\]
- **Microservice RCA (service or metric level):** Nezha (FSE 2023), Eadro (ICSE 2023), DiagFusion (IEEE TSC 2023). These details are from general knowledge.
- **Benchmarks:**
  - OpenRCA ("Can Large Language Models Locate the Root Cause of Software Failures?", ICLR 2025): telemetry to a root-cause component, time and reason.\[79\]
  - RCAEval (WWW 2025 Companion): microservice telemetry.\[79\]
  - AIOpsLab and ITBench (2025): agent environments.
  - A 2026 multi-dataset microservice benchmark (arXiv 2606.29193).\[80\]
- **How to position REMEMBER:** all of these output a *service, component, pod, metric or category*, often from live telemetry. REMEMBER outputs *source files and modules* from a *static snapshot plus a written report*. One clear sentence is enough: "AIOps RCA answers *which service failed and why*; REMEMBER answers *which code to open*."

## 6. Benchmarks and Datasets

| Dataset | Issue text | Logs/traces | Code snapshot | Gold fix files | Tests | Notes |
|---|---|---|---|---|---|---|
| Defects4J (Just et al., ISSTA 2014) | link only | rarely (89/803 reports have traces) | yes | yes | **yes** | Java; test-based FL |
| Bench4BL (ISSTA 2018) | yes | sometimes | yes (multi-version) | yes | no | 46+5 Java projects, 10,017 reports |
| Ye et al. 2014 dataset | yes | sometimes | yes | yes | no | 6 Java projects |
| Pathidea dataset (TSE 2022) | yes (Jira) | **yes, all reports have logs** | yes | yes | no | 8 Java systems, 1,273 reports |
| BeetleBox (BLAZE, TSE 2025) | yes | sometimes | yes | yes | no | 23,782 bugs, 5 languages incl. C++ |
| Long Code Arena BL (2024) | yes (GitHub) | sometimes (code blocks, stack traces) | yes (base SHA) | yes | no | Python/Java/Kotlin |
| SWE-bench / Lite / Verified / Multimodal / Multilingual; Multi-SWE-bench | yes | sometimes (tracebacks) | yes | yes | **yes** | mostly Python; solution leakage |
| Loc-Bench (LocAgent), MULocBench | yes | sometimes | yes | yes | no | Python-heavy |
| BugsJar, BugsInPy, GHRB | yes | sometimes | yes | yes | **yes** | test-reproducible |
| Loghub / LogPAI | no | **yes** | no | no | no | logs only, anomaly labels |
| World of Logs v2 (MSR 2026) | yes (Jira) | **yes** | no | no | no | logs in issues |
| Public Jira Dataset v7 (MSR 2022) | yes | in text | no | no | no | issue metadata |

**Verdict on the "first benchmark" claim.**
- The Pathidea dataset already has all four parts: issue text, logs, a code version, and fixed files.
- Long Code Arena and SWE-bench have three parts reliably and logs sometimes.\[81\]\[82\]
- So "first public benchmark combining issue text, logs, snapshot and gold files" is **not safe**. A defensible claim: "the largest public benchmark of log-bearing production issue reports (6,437 instances) across four multi-language systems (C/C++, Java, Scala), with a time-ordered split and a leakage-controlled history pool."
- Cite Pathidea directly and compare against it.

## 7. Fusion and Reciprocal Rank Fusion

- **Origin.** Gordon V. Cormack, Charles L. A. Clarke, Stefan Büttcher. "Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods." SIGIR 2009. It uses k = 60.\[83\]
- **RRF in bug localization.** BLAZE (TSE 2025) fuses dense and BM25 rankings with RRF.\[38\] "Retrieval-Oriented Code Representations in Agentic Bug Localization" (arXiv 2607.11046) fuses rankings from several code representations with RRF. "Fusing Code Searchers" (Wang et al., 2024) also combines code search rankers.\[21\]
- **Weighted score fusion in IRBL.** BugLocator (α-weighted sum), AmaLgam / AmaLgam+ (composer weights), BLIA (α, β), and Ye et al. (learned SVMrank weights).\[5\]\[84\] These are the "learned or tuned weights" precedents.
- **Regime-conditioned weighting.** We found no IRBL paper that switches fusion weights on an observable report property such as "names a file / does not." The nearest ideas are query-quality prediction and query reformulation in IRBL (Rahman et al.; KBL), and CraTer's "inside vs outside trace" classifier. **This is a plausible novelty point; say "to our knowledge."**

## Best Baseline Candidates

| Paper | Year | Inputs required | Granularity | Uses history? | Runnable without tests? | Code available? | Why fair for REMEMBER |
|---|---|---|---|---|---|---|---|
| BugLocator (rVSM + SimiScore) | 2012 | report, code, past fixed reports | file | yes (similar reports) | yes | Bench4BL (Java); easy to re-implement | Direct test of whether S4 beats the classic similar-report idea |
| BRTracer | 2014 | report with traces, code, past reports | file | yes | yes | sourceforge, Bench4BL | Classic stack-trace signal; best on Bench4BL new subjects |
| Pathidea | 2022 | report with logs, code | file | no | yes | check authors' package | Same input type (logs in Jira reports) |
| AmaLgam | 2014 | report, code, commits, past reports | file | yes (history + similar reports) | yes | Bench4BL | Multi-signal fusion with history |
| Locus | 2016 | report, commit history | hunk → file | yes (changes) | yes | Bench4BL | Strong history-only view |
| Ye et al. LR | 2014 | report, code, API docs, history | file | yes | yes | dataset public; code limited | Learned-fusion counterpart to your RRF |
| BLAZE | 2025 | report, code | file | no | yes | Hugging Face model | Cross-language incl. C++; dense + BM25 RRF |
| LLM-BL | 2025 | report, code | file | no | yes | check paper | Zero-shot LLM reranking; same inputs |
| Agentless (localization) | 2024 | issue, repo | file / function | no | yes | GitHub | De facto LLM localization baseline |
| LocAgent | 2025 | issue, repo | file / module / function | no | yes | GitHub (Python parser) | Strongest open agent; needs a parser port |
| Dense + BM25 hybrid (e.g., E5 or CodeSage + BM25, RRF) | n/a | report, code | file | no | yes | yes | Cheap "semantic" baseline LocAgent used |

**Recommended minimal set (realistic for an M.Sc. paper):** a BugLocator re-implementation (rVSM + SimiScore, α tuned on your dev split), a BRTracer-style trace boost, a BLAZE or dense+BM25 hybrid, and Agentless localization with one model, run on a sample (for example, 300–500 instances) if cost is a problem. Add Pathidea if its code runs on Java/Scala (Kafka); otherwise describe it and explain why it cannot run on C/C++.

## Novelty Threats

| Prior work | What it already does | What REMEMBER adds |
|---|---|---|
| BugLocator SimiScore (2012) | Similar past reports vote for their fixed files (sim / n_files) | Strict temporal firewall; duplicate-cluster and shared-commit exclusion; top-20 BM25 neighbors; rank-based votes; regime-conditioned RRF; provenance (which past issue voted); C/C++/Scala projects; module output |
| BRTracer / BLUiR+ / BLIA | Reuse SimiScore inside larger models | Same as above, plus explicit evaluation of the "hard" stratum where no fix file is named |
| AmaLgam / AmaLgam+ | Fuse history, similar reports, structure, traces, reporter | Leakage-controlled history; fusion weights depend on report regime; logs, not only stack traces |
| Ye et al. LR (collaborative filtering feature) | Learns weights including similar-report feature, chronological folds | No training; deterministic; under 1 s on CPU; provenance |
| ABLoTS (2018) | Similar-report score via Jira–commit trace links | Firewall that the 2026 ABLoTS replication shows is needed; duplicate exclusion; logs |
| RCACopilot (2024) / GPT-4 ICL RCA | Retrieve top-K similar past incidents (time-decay) | File and module output, not category; strict past-only; open data |
| LogFaultFlagger (2019) | kNN over historical failing logs | Localizes code files, not log lines; no test logs needed |
| Pathidea (2022) | Logs in Jira reports to code paths; dataset with logs and fixes | Multi-language; 5x more instances; time split; history signal; shows that logs often do *not* point to the fix |

**How to write it:** "Reusing similar past reports is an established IRBL signal [BugLocator, AmaLgam, Ye, ABLoTS]. Our contribution is not the signal itself but (i) a leakage-safe protocol for it, (ii) evidence of when it helps (the hard stratum), and (iii) a regime-conditioned fusion."

## Evaluation Methodology Precedents

- **Version matching and time.** Bench4BL: evaluate each report against the code version at report time.\[85\] REMEMBER's "parent of fix commit" choice matches the "before-fix version" practice that the deep-IRBL survey recommends.\[49\] Note one subtle point: the parent of the fix can be *later* than the report creation, so code may include changes made after the report. Mention this as a threat to validity.
- **Splits.** Ye et al. used chronological folds. The deep-IRBL survey recommends consecutive (chronological) validation.\[49\] Broccoli shows that time-aware results differ significantly.\[7\] The link-prediction leakage study shows that random splits inflate scores.\[11\]\[50\] Your 30/70 time split is in line with all of these.
- **Leakage through history.** The ABLoTS replication: use creation date, not fixed date. Bench4BL: duplicates help performance, so they must be controlled.\[5\] SWE-Bench+: issue text can contain the answer.\[8\]\[86\] This is why stratifying by "file named or not" is valuable.
- **Metrics and K.** IRBL papers report Top-1/5/10 (Acc@K), MAP and MRR (BugLocator, Ye, Bench4BL).\[5\]\[11\]\[18\]\[87\] Agent papers report Acc@1/3/5/10 at file, module and function level (LocAgent).\[88\] **Add MAP**, because the IRBL community expects it and you already have Recall@K.
- **Statistics.** IRBL and FL papers often use the Wilcoxon signed-rank test with an effect size (Cliff's delta or Vargha–Delaney A12). This norm is from general knowledge, since we did not find one survey that states it. Broccoli reports effect sizes.\[7\] Your paired bootstrap with Benjamini–Hochberg correction is stronger than the usual practice. Also report an effect size for the main comparisons.

## Methodology Weaknesses the Literature Exposes

1. **S4 vs SimiScore.** If you do not include a SimiScore baseline, reviewers will say S4 is BugLocator with BM25. SimiScore divides each vote by the number of fixed files. S4's 1/rank vote does not, so large refactoring commits can flood the votes. Run an ablation: S4 with sim/n_b weighting, and S4 with all neighbors vs top 20.
2. **Classic IRBL tools are Java-only.** BLUiR, BRTracer and Pathidea parse Java code and Java stack frames. For MariaDB, MongoDB and Qt you must re-implement them.\[3\]\[5\] State this clearly and run the original tools on Kafka (Java/Scala) as a sanity check.
3. **LLM baseline expectations.** For an ICSE 2026–2027 industry track, reviewers will likely expect one LLM localizer. Agentless or LLM-BL is enough. Report cost per issue and the risk of memorization on public projects.
4. **"First benchmark" claim.** Pathidea's dataset weakens it (see Section 6).
5. **Ground truth noise.** Fix commits often touch unrelated files (tangled changes).\[3\] Bench4BL and the IRBL survey discuss noisy links. Report how many instances have more than 10 changed files, and consider a filtered subset.
6. **Snapshot timing.** Parent-of-fix code may be newer than the report. Bench4BL's multi-version matching uses the version at report time.\[85\] Consider an ablation with the snapshot at issue creation time.

## Suggested Structure for the Related Work Section

1. **IR-based bug localization.** BugLocator, BLUiR, BRTracer, Moreno et al., AmaLgam/AmaLgam+, BLIA, Locus, Ye et al., DNNLoc, FBL-BERT, BLAZE; Bench4BL for reproducibility; the deep-IRBL survey.
2. **History and similar reports** (position S4 here). SimiScore, Ye's collaborative filtering, ABLoTS/TraceScore, Sisman and Kak; duplicate detection (Runeson, Wang, Sun REP); RCACopilot and GPT-4 ICL incident retrieval. End with what the firewall adds.
3. **Logs and stack traces for localization** (position S1 and the hard stratum). SherLog, Pathidea, Dao et al., LogFaultFlagger, CrashLocator, CraTer ("Does the fault reside in a stack trace?").
4. **LLM and agent localization.** Agentless, LocAgent, CoSIL, OrcaLoca, LLM-BL, GenLoc; test-based FL (AutoFL, AgentFL, Rafi et al.) and why they do not fit; SWE-Bench+ and memorization concerns.
5. **AIOps root cause analysis.** RCAgent, RCACopilot, Ahmed et al., OpenRCA, RCAEval; the granularity difference.
6. **Benchmarks and evaluation.** Defects4J, Bench4BL, Pathidea data, Long Code Arena, SWE-bench family, Loc-Bench/MULocBench, World of Logs, Public Jira Dataset; time-aware evaluation (Broccoli, ABLoTS replication, leakage study); RRF (Cormack et al.) and fusion in IRBL.

## Caveats

- Some details (DNNLoc venues, Sisman and Kak, duplicate-detection papers, CrashLocator, SherLog, Nezha/Eadro/DiagFusion, AutoFL authors, statistics norms) come from general knowledge, not from pages we opened. Check them in DBLP before adding them to BibTeX.
- The BugLocator formula and α come from papers that restate it, plus fragments of the original. We could not confirm whether the original evaluation used a per-query time cutoff.
- We could not verify "COLA" or "LinkCoM" incident-linking papers. Leave them out unless you find them yourself.
- Several 2025–2026 items are arXiv preprints (GenLoc, SHERLOC, BLAgent, GraphLocator, the ABLoTS replication). Cite them as preprints.
- SWE-bench localization numbers come from each paper's own setup (different models and metrics). Do not compare them directly with your Jira numbers.

## Sources

1. [(PDF) Where should the bugs be fixed? More accurate information retrieval-based bug localization based on bug reports](https://www.researchgate.net/publication/316921877_Where_should_the_bugs_be_fixed_More_accurate_information_retrieval-based_bug_localization_based_on_bug_reports)
2. [Singapore Management University Singapore Management University](https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=3432&context=sis_research)
3. [Evaluation of Cross-Lingual Bug Localization: Two Industrial Cases](https://arxiv.org/pdf/2310.01803)
4. [(PDF) Analyzing Requirements and Traceability Information to Improve Bug Localization](https://researchgate.net/publication/324227400_Analyzing_Requirements_and_Traceability_Information_to_Improve_Bug_Localization)
5. <https://www.darkrsw.net/papers/ISSTA2018.pdf>
6. [Bench4BL: reproducibility study on the performance of IR-based bug localization](https://dl.acm.org/doi/10.1145/3213846.3213856)
7. [Broccoli: Bug localization with the help of text search engines](https://arxiv.org/pdf/2109.11902)
8. [An Extensive Replication Study of the ABLoTS Approach for Bug Localization](https://arxiv.org/pdf/2605.11790)
9. <https://arxiv.org/pdf/2305.15778v4>
10. [\[PDF\] Where should the bugs be fixed? More accurate information retrieval-based bug localization based on bug reports](https://www.semanticscholar.org/paper/Where-should-the-bugs-be-fixed-More-accurate-bug-on-Zhou-Zhang/3f3816ca55d4681739f9dd920fdb7fe3d190b0b3)
11. [(PDF) Tracking Buggy Files: New Efficient Adaptive Bug Localization Algorithm](https://www.researchgate.net/publication/349905759_Tracking_Buggy_Files_New_Efficient_Adaptive_Bug_Localization_Algorithm)
12. [Table II from Where should the bugs be fixed? More accurate information retrieval-based bug localization based on bug reports](https://www.semanticscholar.org/paper/Where-should-the-bugs-be-fixed-More-accurate-bug-on-Zhou-Zhang/3f3816ca55d4681739f9dd920fdb7fe3d190b0b3/figure/6)
13. [Bug Localization by Learning to Rank and Represent Bug Inducing Changes](https://dl.acm.org/doi/abs/10.1145/3269206.3271811)
14. [Autom Softw Eng DOI 10.1007/s10515-017-0226-1](https://d-nb.info/1144407338/34)
15. [GitHub - TruX-DTF/Bench4BL · GitHub](https://github.com/TruX-DTF/Bench4BL)
16. [Engineering, Technology & Applied Science Research](https://etasr.com/index.php/ETASR/article/download/18559/6728)
17. [Boosting Bug-Report-Oriented Fault Localization with Segmentation and Stack-Trace Analysis](https://www.researchgate.net/publication/308495563_Boosting_Bug-Report-Oriented_Fault_Localization_with_Segmentation_and_Stack-Trace_Analysis)
18. [Researchgate](https://www.researchgate.net/publication/349905759_Tracking_Buggy_Files_New_Efficient_Adaptive_Bug_Localization_Algorithm/fulltext/6046d3df299bf1e078660749/Tracking-Buggy-Files-New-Efficient-Adaptive-Bug-Localization-Algorithm.pdf)
19. [BRTracer](https://brtracer.sourceforge.net/)
20. [Writing Bug Reports for Software Repair Agents: What Information Matters Most?](https://arxiv.org/pdf/2607.09553)
21. [Retrieval-Oriented Code Representations in Agentic Bug Localization](https://arxiv.org/pdf/2607.11046)
22. [(PDF) AmaLgam+: Composing Rich Information Sources for Accurate Bug Localization: Composing Rich Information Sources for Accurate Bug Localization](https://www.researchgate.net/publication/309145570_AmaLgam_Composing_Rich_Information_Sources_for_Accurate_Bug_Localization_Composing_Rich_Information_Sources_for_Accurate_Bug_Localization)
23. [(PDF) Version History, Similar Report, and Structure: Putting Them Together for Improved Bug Localization](https://www.researchgate.net/publication/261635117_Version_History_Similar_Report_and_Structure_Putting_Them_Together_for_Improved_Bug_Localization)
24. [Information Retrieval‐Based Techniques for Software Fault Localization](https://www.researchgate.net/publication/370201689_Information_Retrieval-Based_Techniques_for_Software_Fault_Localization)
25. [AmaLgam+: Composing Rich Information Sources for Accurate Bug Localization - Wang - 2016 - Journal of Software: Evolution and Process - Wiley Online Library](https://onlinelibrary.wiley.com/doi/10.1002/smr.1801)
26. [Composing rich information sources for accurate bug ...](https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=4577&context=sis_research)
27. [Bug Localization by Learning to Rank and Represent Bug Inducing Changes](https://www.researchgate.net/publication/328436590_Bug_Localization_by_Learning_to_Rank_and_Represent_Bug_Inducing_Changes)
28. [Structured information in bug report descriptions—influence on IR-based bug localization and developers](https://www.researchgate.net/publication/334426731_Structured_information_in_bug_report_descriptions-influence_on_IR-based_bug_localization_and_developers)
29. [High-Quality Automated Program Repair](https://arxiv.org/pdf/2104.07851)
30. [Towards Understanding the Challenges of Bug Localization in Deep Learning Systems](https://arxiv.org/html/2402.01021)
31. [LSTM Attention-Driven Similarity Learning for Effective Bug Localization](https://www.mdpi.com/2076-3417/15/3/1582)
32. [GitHub - logpai/bughub: A collection of free-text bug reports for duplicate issue identification · GitHub](https://github.com/logpai/bughub)
33. [(PDF) Learning to Rank Relevant Files for Bug Reports using Domain Knowledge](https://www.researchgate.net/publication/263469498_Learning_to_Rank_Relevant_Files_for_Bug_Reports_using_Domain_Knowledge)
34. [bugfiles](https://zenodo.org/records/268486)
35. [CMind: An AI Agent for Localizing C Memory Bugs](https://arxiv.org/pdf/2601.14434)
36. [Bug Localization from Bug Reports: A Multi-Objective Approach](https://arxiv.org/pdf/2608.27089)
37. [bug-localization/BLAZE · Hugging Face](https://huggingface.co/bug-localization/BLAZE)
38. [BLAZE: Cross-Language and Cross-Project Bug Localization via Dynamic Chunking and Hard Example Learning](https://arxiv.org/pdf/2407.17631)
39. [LLM-BL: Large Language Models are Zero-Shot Rankers for Bug Localization (ICPC 2025 - Research Track) - ICPC 2025](https://conf.researchr.org/details/icpc-2025/icpc-2025-research/36/LLM-BL-Large-Language-Models-are-Zero-Shot-Rankers-for-Bug-Localization)
40. [Leveraging Large Language Model for Information ...](https://arxiv.org/pdf/2508.00253)
41. [Improved Bug Localization with AI Agents Leveraging Hypothesis and Dynamic Cognition](https://arxiv.org/pdf/2601.12522)
42. [Reformulate, Retrieve, Localize: Agents for Repository-Level Bug Localization](https://arxiv.org/pdf/2512.07022)
43. [Large-Scale Evaluation of Method-LevelBug Localization with FinerBench4BL](https://arxiv.org/html/2302.14293v1)
44. [Bug-Report–Driven Fault Localization: Industrial Benchmarking](https://arxiv.org/pdf/2604.25700)
45. [Bench4BL: Reproducibility Study on the Performance of IR-Based Bug Localization](https://slideshare.net/darkrsw/bench4bl-reproducibility-study-on-the-performance-of-irbased-bug-localization)
46. [Where should the bugs be fixed?-more accurate information retrieval-based bug localization based on bug reports](https://www.researchgate.net/publication/316921797_Where_should_the_bugs_be_fixed-more_accurate_information_retrieval-based_bug_localization_based_on_bug_reports)
47. [Leveraging LLMs for Structured Information Extraction and Analysis from Cloud Incident Reports (Work In Progress Paper)](https://arxiv.org/pdf/2603.16818)
48. [\[PDF\] Automatic Root Cause Analysis via Large Language Models for Cloud Incidents](https://www.semanticscholar.org/paper/Automatic-Root-Cause-Analysis-via-Large-Language-Chen-Xie/47cae173d4618b32bf52f8b61b0a1051434d8b1f)
49. [When Deep Learning Meets Information Retrieval-based Bug Localization: A Survey](https://dl.acm.org/doi/10.1145/3734217)
50. [An Empirical Study on Data Leakage and Generalizability of Link Prediction Models for Issues and Commits](https://arxiv.org/html/2211.00381v2)
51. [Pathidea: Improving Information Retrieval-Based Bug ...](https://petertsehsun.github.io/papers/PathideaTSE2021.pdf)
52. [Crash Report Enhancement with Large Language Models: An Empirical Study](https://arxiv.org/pdf/2509.13535)
53. [How Does Execution Information Help with Information-Retrieval Based Bug Localization?](https://www.researchgate.net/publication/368117845_How_Does_Execution_Information_Help_with_Information-Retrieval_Based_Bug_Localization)
54. [No More Labelled Examples? An Unsupervised Log Parser with LLMs](https://dl.acm.org/doi/10.1145/3729377)
55. [Easy over Hard: A Simple Baseline for Test Failures Causes Prediction](https://arxiv.org/html/2405.02922v1)
56. [Failure Diagnosis in Microservice Systems: A Comprehensive Survey and Analysis](https://dl.acm.org/doi/10.1145/3715005)
57. [Does the fault reside in a stack trace? Assisting crash localization by predicting crashing fault residence - ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0164121218302401)
58. [The Impact Of Bug Localization Based on Crash Report Mining: A Developers' Perspective](https://doi.org/10.1145/3639477.3639730)
59. [Does the Fault Reside in a Stack Trace? Assisting Crash Localization by Predicting Crashing Fault Residence](https://www.researchgate.net/publication/328776689_Does_the_Fault_Reside_in_a_Stack_Trace_Assisting_Crash_Localization_by_Predicting_Crashing_Fault_Residence)
60. [Anchor: Locating Android Framework-specific Crashing Faults Pingfan Kong](https://arxiv.org/pdf/2008.01676)
61. [SBEST: Spectrum-Based Fault Localization Without Fault-Triggering Tests](https://arxiv.org/pdf/2405.00565)
62. [Defects4Log: Benchmarking LLMs for Logging Code Defect Detection and Reasoning](https://arxiv.org/pdf/2508.11305)
63. [A Survey on Automated Log Analysis for Reliability Engineering](https://ouci.dntb.gov.ua/en/works/4OOax6O4/)
64. [A Survey on Automated Log Analysis for Reliability Engineering](https://arxiv.org/pdf/2009.07237)
65. [Past, Present, and Future of Bug Tracking in the Generative AI Era](https://arxiv.org/pdf/2510.08005)
66. [SWE-Debate: Competitive Multi-Agent Debate for Software Issue Resolution](https://arxiv.org/pdf/2507.23348)
67. [GraphLocator: Graph-guided Causal Reasoning for Issue Localization](https://arxiv.org/pdf/2512.22469)
68. [LocAgent: Graph-Guided LLM Agents for Code Localization](https://www.researchgate.net/publication/389786036_LocAgent_Graph-Guided_LLM_Agents_for_Code_Localization/fulltext/67d24b227c5b5569dcba1302/LocAgent-Graph-Guided-LLM-Agents-for-Code-Localization.pdf)
69. [LocAgent: Graph-Guided LLM Agents for Code Localization](https://huggingface.co/papers/2503.09089)
70. [github.com](https://github.com/gersteinlab/LocAgent)
71. [\[2503.22424\] Issue Localization via LLM-Driven Iterative Code Graph Searching](https://arxiv.org/abs/2503.22424)
72. [OrcaLoca: An LLM Agent Framework for Software Issue Localization](https://arxiv.org/html/2502.00350)
73. [Issue Localization via LLM-Driven Iterative Code Graph Searching](https://arxiv.org/pdf/2503.22424)
74. [SHERLOC: Structured Diagnostic Localization for Code Repair Agents](https://arxiv.org/html/2606.24820v1)
75. [BLAgent: Agentic RAG for File-Level Bug Localization](https://arxiv.org/pdf/2605.17965)
76. [Reformulate, Retrieve, Localize: Agents for Repository-Level Bug Localization](https://www.arxiv.org/pdf/2512.07022)
77. [\[2410.06992\] SWE-Bench+: Enhanced Coding Benchmark for LLMs](https://arxiv.org/abs/2410.06992)
78. [A Benchmark for Localizing Code and Non-Code Issues in Software Projects](https://arxiv.org/html/2509.25242v1)
79. [From General Agents to RCA Experts: A Self-Evolving Harness for Root Cause Analysis](https://arxiv.org/pdf/2608.25661)
80. [A Multi-Dataset Benchmark for Evaluating LLM Agents in Microservice Failure Diagnosis](https://arxiv.org/html/2606.29193v1)
81. [arXiv:2406.11612v1 \[cs.LG\] 17 Jun 2024 Long Code Arena: a Set of Benchmarks](https://arxiv.org/pdf/2406.11612)
82. [JetBrains-Research/lca-bug-localization · Datasets at Hugging Face](https://huggingface.co/datasets/JetBrains-Research/lca-bug-localization)
83. [Retrieval-Enhanced Named Entity Recognition](https://arxiv.org/pdf/2410.13118)
84. [An Empirical Study of the Effects of Expert Knowledge on Bug Reports](https://sdf.org/~cmc/papers/huo_icsme14.pdf)
85. [Bench4BL: reproducibility study on the performance of IR-based bug localization](https://www.researchgate.net/publication/326363577_Bench4BL_reproducibility_study_on_the_performance_of_IR-based_bug_localization)
86. [SWE-Bench+: Enhanced Coding Benchmark for LLMs](https://arxiv.org/html/2410.06992v1)
87. [Two-Level Information-Retrieval-Based Model for Bug Localization Based on Bug Reports](https://www.mdpi.com/2079-9292/13/2/321)
88. [LocAgent: Graph-Guided LLM Agents for Code Localization](https://aclanthology.org/2025.acl-long.426.pdf)
