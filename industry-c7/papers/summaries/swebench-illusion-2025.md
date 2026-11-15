# The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason

**Shanchao Liang (Purdue), Spandan Garg, Roshanak Zilouchian Moghaddam (Microsoft). arXiv 2506.12286v4 (2025).**
PDF: `pdfs/swebench-illusion-2025.pdf`

## What it is

A memorization probe for SWE-bench Verified via three diagnostic tasks
plus cross-benchmark comparison: (1) **file-path identification from the
issue description ALONE** — no repository structure, no code, the model
just names the buggy file path; (2) function reproduction without the
needed specification; (3) verbatim prefix completion. Logic: genuine
skill should transfer across comparable benchmarks; a benchmark-specific
spike indicates contamination.

## The findings (for citation)

- SoTA models (e.g., o3) reach **up to 76% accuracy naming the buggy FILE
  PATH from the issue text alone** on SWE-Bench Verified — with zero
  repository context. The same task on repositories NOT in SWE-bench:
  **up to 53%**. The ~23-point gap is the memorization signature.
- Function reproduction: consecutive 5-gram overlap with the gold fix up
  to **35% on SWE-Bench Verified/Full vs up to 18%** on comparable
  external benchmarks — models partially regurgitate the actual patches.

## What this means for our paper

Two distinct implications:

1. **For any LLM baseline we run** (Agentless-style on Kafka/MariaDB/
   MongoDB/Qt — all public, all in training corpora): a strong LLM score
   may partly be recall of these very bug fixes. Mitigations we can apply
   cheaply: report post-cutoff issues separately (our eval split is
   time-ordered), and/or run the Illusion-style probe ourselves — ask the
   model to name the fixed file from the report alone and compare against
   our trace-grep baseline, which bounds what the TEXT gives away. If the
   LLM beats trace-grep by a wide margin WITHOUT code access, that margin
   is memory (theirs), not reasoning.
2. **A subtle parallel to own our framing**: the LLM's "remembered
   issue→file association" is functionally an UNDISCLOSED incident
   memory, learned from the same history our S4 uses — but without a
   firewall, without provenance, and without the ability to update. Our
   memory signal is the auditable version of what these models do
   covertly. This positioning sentence could be valuable in §6 or related
   work.

## Weaknesses / notes

- Contamination is inferred from performance gaps, not shown directly in
  training data (impossible with closed corpora) — the authors are candid
  about this; the cross-benchmark design is the best available proxy.
- The 53% "clean" number still includes any public-GitHub memorization of
  the external repos; the gap is a lower bound on contamination.
- File-path identification accuracy conflates memorization with genuine
  text-only localization (reports often NAME the file — SWE-bench's own
  solution leakage). They partially control by comparing like-for-like
  across benchmarks, but a leakage-stratified analysis (as we do) would
  have been sharper.

## Use in our paper

- §4 baselines / §6 threats: cite with SWE-Bench+ as the pair of
  LLM-benchmark caveats (leakage + memorization) that motivate our
  stratified, time-ordered, post-cutoff-separable evaluation.
- Possible cheap experiment: the no-context file-naming probe on our
  benchmark as an "LLM memory disclosure" baseline.
