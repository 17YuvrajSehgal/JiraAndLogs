# SWE-Bench+: Enhanced Coding Benchmark for LLMs

**Reem Aleithan, Haoran Xue, Mohammad Mahdi Mohajer, Elijah Nnorom, Gias Uddin, Song Wang (York University). arXiv 2410.06992v2 (2024).**
PDF: `pdfs/swebenchplus-2024.pdf` · Data: zenodo.org/records/13879453

## What it is

A manual audit of SWE-bench through the patches that SWE-Agent+GPT-4
"successfully resolved" (251 instances with all tests passing), three
authors independently comparing generated vs gold patches, plus a repaired
dataset (SWE-bench+: issues collected 2023-11..2024-08, post-cutoff, with
leaked-solution issues removed).

## The findings (exact numbers for citation)

Of the 251 "resolved" patches (Table 1):
- **Solution leak: 82 (32.67%)** — the fix is spelled out in the issue
  description or comments (both fed to the model as `hints_text`).
- **Weak tests: 31.08%** total — incorrect fixes passing anyway (12.75%),
  different files/functions changed yet tests pass (3.59%), incomplete
  fixes (14.74%).
- Correct fixes: different-but-valid (30.27%) + more comprehensive than
  gold (5.98%).
- **94% of SWE-bench issues predate the models' training cutoffs** —
  memorization risk on top of leakage.
- After filtering suspicious instances: SWE-Agent+GPT-4's resolution rate
  falls **12.47% → 3.97%**; on post-cutoff, leak-free SWE-bench+ it falls
  to **0.55%** (AutoCodeRover+GPT-4o: 18.83% → 3.83%).

Meaning: roughly two-thirds of the celebrated leaderboard success either
copied the answer from the input or slipped past inadequate tests, and
post-cutoff performance collapses by an order of magnitude. The
"different files changed yet tests pass" pattern is also a quiet warning
about TEST-BASED gold itself.

## Relevance to us

- The strongest citation for evaluating localization on reports where the
  answer is NOT in the text. Our hard stratum (53% of reports name no
  fixed file) is the log-world analogue of removing solution leakage —
  but as a reported stratification rather than population surgery, which
  lets us also show the easy stratum honestly.
- If we run an LLM baseline on Kafka/MariaDB/MongoDB/Qt (all surely in
  training data), this paper mandates reporting post-cutoff issues
  separately; our benchmark's time-ordered eval split makes that cut easy
  (issues by creation date).
- Related work §6 (benchmarks): one sentence with the 32.67% and the
  12.47→3.97 collapse.

## Weaknesses / notes

- Audit covers one agent (SWE-Agent+GPT-4) at one time point; patterns
  could differ for other systems, though the dataset properties (leakage,
  weak tests, cutoff dates) are system-independent.
- "Weak tests" judgments are manual (three raters, discussion-resolved);
  no kappa reported in the sections we read.
- SWE-bench+ keeps the weak-test problem partially (lowest, not zero).
