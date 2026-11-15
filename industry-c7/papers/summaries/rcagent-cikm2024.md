# RCAgent: Cloud Root Cause Analysis by Autonomous Agents with Tool-Augmented LLMs

**Zefan Wang, Zichuan Liu, Yingying Zhang, et al. (Tsinghua / Alibaba / ...). CIKM 2024, pp. 4966–4974. DOI 10.1145/3627673.3680016 (arXiv 2310.16340v3).**
PDF: `pdfs/rcagent-cikm2024.pdf`
**This is the challenge PDF's reference [2].**

## What it is

A ReAct-style autonomous agent for RCA of anomalous Apache Flink jobs on
Alibaba Cloud, deliberately running a LOCAL Vicuna-13B-16K (privacy: no
external APIs), hardened with a bag of engineering: OBSK (observations
stored in a key-value store, agent sees only heads + hash keys — their
answer to log volume), JsonRegen (JSON→YAML→JSON repair loop for parsable
actions), error-handling rules (duplicate calls, trivial inputs, premature
finalize), and Trajectory-level Self-Consistency (sample only at the
finalize step, share the greedy prefix). Two LLM "expert agents" as tools:
- **Code analysis tool**: given a class name, recursively reads files from
  the code repository, queues LLM-suggested related classes, summarizes.
  (So it DOES read code — but its output feeds a textual root-cause
  narrative, never a ranked list of code regions.)
- **Log analysis tool**: embeds log lines (GTE-LARGE), builds a line-graph
  weighted by cosine similarity × exp(−distance), Louvain-clusters it into
  semantic chunks, RAGs chunk-by-chunk, and — notably — **discards any
  analysis whose cited evidence cannot be fuzzy-matched back into the
  chunk** (Levenshtein filter), a concrete anti-hallucination mechanism.

## Evaluation

161 class-balanced anomalous Flink jobs (reduced from ~5,000 non-trivial
of 15,616 one-month anomalies; labels distilled from the Flink Advisor
rule base, SRE-proofread; ≤2 jobs per identical root cause). Outputs are
free text (root cause, solution, evidence, responsibility) scored with
semantic metrics + GPT-4 ("G-Correctness") + human evaluation. RCAgent
beats plain ReAct across the board (e.g., METEOR 15.15 vs 6.44); every
ablated component (expert agents, JsonRegen, OBSK) costs performance.

**Protocol point worth citing:** "only data before the detection time of
the anomaly can be retrieved, preventing the analysis of future
information" — they enforce a tool-level temporal constraint, and their
retrieval log database excludes the content used for labeling. Among the
AIOps agent papers this is the closest thing to our firewall, though it
governs telemetry access, not a similar-incident memory.

## Positioning against us (the sentence our related work needs)

RCAgent answers "what is the root cause of this failed JOB, in prose" from
live telemetry + code reading; granularity is the job/service and a
category/narrative. It does not produce a ranked list of defective source
files, does not use the project's resolved-incident history as a signal,
and is evaluated by text similarity to rule-derived labels — i.e., the
challenge's observation that log-based RCA "does not directly target
ranked localization of defective source-code regions" describes exactly
this paper. Our output granularity and external git-derived gold are the
delta.

## Weaknesses / gloss-overs

- 161 labeled jobs, one platform, labels derived FROM an existing rule
  base (the system is partly judged against distilled versions of the
  rules it complements); private data, irreproducible.
- Semantic-metric evaluation of free text (METEOR/BLEURT/BARTScore) is
  weak evidence of diagnostic correctness; G-Correctness is LLM-judging-
  LLM; the human eval is on their own platform.
- No ranked-output metrics at all (no Acc@K/MRR anywhere).
- The code analysis tool's recursive reading is unbounded in principle;
  cost/latency per incident is not clearly reported.

## Use in our paper

- Related work §5 (AIOps RCA): with RCACopilot, the pair of industrial
  precedents; one clause each — RCACopilot (category via similar
  incidents, time-decay), RCAgent (narrative via tool agent, local LLM).
  Both stop above code regions.
- §3/§6: their copied-evidence anti-hallucination filter is a nice
  independent echo of our "citations, not narrative" provenance stance —
  both designs force outputs to point at checkable evidence.
- Their detection-time data constraint can be cited as precedent that
  industrial RCA systems already accept temporal access control, so our
  firewall is deployable, not academic.
