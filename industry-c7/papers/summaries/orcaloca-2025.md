# OrcaLoca: An LLM Agent Framework for Software Issue Localization

**Zhongming Yu, Hejia Zhang, Yujie Zhao, Hanxian Huang, Matrix Yao (Intel), Ke Ding (Intel), Jishen Zhao (UCSD). ICML 2025 (arXiv 2502.00350v2).**
PDF: `pdfs/orcaloca-2025.pdf` · Code: github.com/fishmingyu/OrcaLoca

## What it is

An LLM-agent localizer with three systems ideas: priority-based scheduling
of LLM-guided actions, action decomposition with relevance scoring, and
distance-aware context pruning. Function match rate 65.33% on SWE-bench
Lite (open-source SOTA at submission); +6.33pp resolved rate when wired
into a patch-generation framework.

## Useful facts

- Their leaderboard analysis: across ALL submitted SWE-bench Lite agents,
  average file match is 72.08% but **function match only 53.5%** and
  resolve 33.1% — the community-wide gap between file- and function-level
  success, good context for our function-stage expectations.
- SWE-bench codebases average 3,010 files / ~438K LOC — scale context.
- CAVEAT from CoSIL's authors (noted in our cosil summary source): OrcaLoca
  uses traceback from REPRODUCTION TESTS — i.e., not a strictly
  no-execution baseline; classify accordingly (closer to the test-based
  family for our purposes).

## Use in our paper

- Related work, LLM-agent group cite; the 72-vs-53.5 file/function gap as
  one sentence when introducing our (planned) function level.
- Not a fair baseline candidate for us (reproduction-test dependency).
