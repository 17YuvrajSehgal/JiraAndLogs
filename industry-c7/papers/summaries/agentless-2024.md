# Agentless: Demystifying LLM-based Software Engineering Agents

**Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, Lingming Zhang (UIUC). arXiv 2407.01489v2 (Oct 2024); FSE 2025.**
PDF: `pdfs/agentless-2024.pdf` · Code: github.com/OpenAutoCoder/Agentless

## What it is

The "no-agent" answer to SWE-bench agents: a fixed three-phase pipeline —
hierarchical LOCALIZATION, repair (sampled diffs), patch validation
(generated reproduction tests + regression tests + majority voting). No
tool use, no autonomous planning. 32.00% resolve rate on SWE-bench Lite
(96/300) at ~$0.70/issue, best open-source at the time; adopted by OpenAI
to showcase GPT-4o/o1. For us only the LOCALIZATION phase matters — it is
the de-facto LLM file-localization baseline the challenge PC will expect.

## The localization mechanics (what we would re-implement for a baseline)

Step 1 — files: give the LLM the repository TREE (paths only, no content)
plus the issue; ask for top-N suspicious files. In parallel, an
embedding-retrieval route: LLM first filters irrelevant folders, remaining
files are chunked and embedded, issue embedding retrieves nearest chunks.
Merge both lists (top-N most common).
Step 2 — elements: per file, a "skeleton" (declaration headers only); LLM
picks classes/functions.
Step 3 — edit locations: full code of the selected elements; LLM emits
final locations (sampled 4×, each sample repaired separately).

Localization ablation (their Table 2, "contains ground-truth file"):
prompting-only 78.7%, embedding-only 67.7%, **merged 81.7%** — the two
routes are complementary. Full-file content instead of skeletons makes
localization WORSE and costlier ("LLMs cannot handle long context well") —
independent support for our compact-evidence design and for RCACopilot's
same finding.

## Other numbers that matter

- Patch selection ablation: majority voting alone 77 fixes; + regression
  tests 81; + generated reproduction tests 96. Upper bound if any sampled
  patch counts: 126 (42%) — selection, not generation, is the bottleneck.
- Cost: ~$0.29 repair + $0.25 validation; total ≈ $0.70/issue.

## The SWE-bench Lite audit (ammunition for our §4/§6)

Manual classification of all 300 problems:
- **4.3% contain the exact ground-truth patch in the issue description**;
  another 9.7% give the complete steps in natural language; 5.0% contain a
  MISLEADING proposed solution; 10.0% lack information needed to pass the
  hidden tests at all. They build SWE-bench Lite-S by removing these
  (OpenAI's SWE-bench Verified followed).
- Location-information analysis (their Fig. 8c, read from the figure): most
  issues carry no line-level location (~90% none) and no function-level
  location (~73% none); file-level hints are present in roughly a third.
  This is the same phenomenon as our easy/hard stratification, measured on
  Python GitHub issues — ours is stricter (we test whether a GOLD file is
  named, not whether any location hint exists).

## Weaknesses / gloss-overs for our purposes

- Python-only tooling (tree building, skeletons via Python parsing);
  porting step 2–3 to C++/Scala needs tree-sitter work. A fair C7 baseline
  can keep step 1 (repo tree + issue → files), which is language-agnostic.
- Localization is never evaluated as a RANKING task with Acc@K/MRR in this
  paper — only "contains GT" within the working set and end-to-end resolve
  rate. LocAgent later reports Agentless file Acc@1 ≈ 67–73% on Lite.
- Memorization risk unaddressed: SWE-bench repos are in LLM training data
  (SWE-bench Illusion later quantifies this). For our benchmark the same
  caution applies to Kafka/MongoDB/Qt — if we run an LLM baseline, report
  post-cutoff issues separately.
- No history/similar-report signal anywhere — the memory axis is simply
  absent from this entire line of work.

## Use in our paper

- §Related work (LLM localization): the representative baseline; one
  sentence on hierarchical localization + its merged-retrieval 81.7%.
- §4 baselines: the design to follow if we run the LLM baseline on a
  sample (their step 1 is directly portable; ~200 instances/project keeps
  cost near $30–50 per model at their per-issue cost).
- §6: the exact-patch/solution-leakage audit supports evaluating on
  reports where the answer is NOT in the text — our hard stratum is the
  log-world version of SWE-bench Lite-S's motivation.
