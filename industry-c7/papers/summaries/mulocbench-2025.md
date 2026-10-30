# MULocBench: A Benchmark for Localizing Code and Non-Code Issues in Software Projects

**Zejun Zhang, Jian Wang, Qingyun Yang, Yifan Pan, Yi Tang, Yi Li, Zhenchang Xing, Tian Zhang, Xuandong Li, Guoan Zhang. arXiv 2509.25242 (2025).**
PDF: `pdfs/mulocbench-2025.pdf` · Data: huggingface.co/datasets/somethingone/MULocBench

## What it is

A localization benchmark built to break the SWE-bench monoculture: 1,100
issues from the top-50 starred Python projects (46 survive filtering),
locations extracted from merged PRs (716), commits (63), or — new —
explicit RESOLUTION COMMENTS (321, manually extracted). It covers issue
types beyond bugs (execution failures, unexpected results, enhancements,
usage questions) and non-code locations (configs, docs, requirements.txt).

## The numbers (Table 1, Python-code subset; Acc@5 file-level)

- BM25: 9.4 — far below LocAgent's 61.7 BM25-on-Lite figure, showing how
  population choice swings even the dumb baseline.
- Agentless (Claude-3.5): 23.9
- OpenHands (Claude-3.5): 33.5
- **LocAgent (Claude-3.5): 35.2 file Acc@5 / 25.9 class / 21.9 function**

The same systems score 80/70/60+ (file/class/function Acc@5) on SWE-bench
Lite. The collapse (≈45–50 points at file level) on a fresh, broader
population is the third leg of the LLM-caveat argument (with SWE-Bench+
leakage and the Illusion memorization gap). Also: usage questions localize
BEST (54% file Acc@5 — concrete descriptions), enhancements/unexpected
results worst (~30%) — description concreteness drives localization, the
same gradient as our easy/hard stratum.

## Relevance to us

- Baseline expectation management: if our LLM baseline lands in the
  20s–30s file Acc@5 on our hard stratum, that is CONSISTENT with fresh-
  data LLM performance, not a misconfiguration — cite this.
- Their comment-derived gold (321 issues) is a creative alternative gold
  source but manual; our git-derived gold scales 20× with filters instead.
- The non-code-location observation (configs, docs) is a real scope note
  for us: our gold excludes non-source files by design — one sentence in
  §2 limitations acknowledging that some fixes land outside source code
  (our no_source_gold funnel bucket actually QUANTIFIES this: 147–1,475
  per project).

## Weaknesses / notes

- Python-only, top-starred projects, 200 sampled issues per project —
  diversity by issue type but not by language or tracker.
- Mixed gold provenance (PR vs comment-extracted) with different noise
  profiles, analyzed only lightly.
- No time-awareness, no history signal; strictly an LLM/agent testbed.

## Use in our paper

- Related work §6 (benchmarks): one sentence with the 80→35 file-Acc@5
  collapse; together with SWE-Bench+ and Illusion it justifies why our
  LLM baseline protocol is stratified and post-cutoff-separable.
- §2: cite as the only other recent localization benchmark that reports
  WHERE fixes land beyond code — next to our no_source_gold yield.
