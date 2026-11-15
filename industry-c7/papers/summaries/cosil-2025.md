# CoSIL: Issue Localization via LLM-Driven Iterative Code Graph Searching

**Zhonghao Jiang, Xiaoxue Ren, Meng Yan, Wei Jiang, Yong Li, Zhongxin Liu (Zhejiang U / Chongqing U / Ant Group). arXiv 2503.22424v3 (2025).**
PDF: `pdfs/cosil-2025.pdf`

## What it is

Function-level issue localization WITHOUT training or indexing: two-phase
search over DYNAMICALLY built call graphs — broad file-level exploration
over a module call graph, then iterative function-level search over an
expanded function call graph — with a PRUNER that filters irrelevant
search directions and a REFLECTION mechanism that fixes malformed tool
calls via short independent queries (their Fig. 1 shows the failure modes:
type-mismatched tool args, hallucinated file keys).

## Numbers

Top-1 function-level accuracy 43.3% (SWE-bench Lite) / 44.6% (Verified)
with Qwen2.5-Coder-32B — claimed +96% average over SOTA; plugging CoSIL's
locations into Agentless improves issue resolution by 2.98–30.5%.

## Why it's in our library (related-work tier)

- Their diagnosis ❶ is a crisp statement of our problem framing: "issue
  description usually describes the symptoms rather than the essence of
  the problem," which makes description-anchored search spaces too
  narrow — the LLM-agent community's independent arrival at
  symptom≠cause.
- Three engineering failure modes of LLM localizers (breadth/depth
  balance, direction control, format failures) — useful when we argue the
  deterministic-pipeline advantage in §6 (our failure modes are none of
  these).
- Python-only, no tests needed (fair input regime), no memory/history.

## Use in our paper

- Related work (LLM localization group cite with LocAgent/OrcaLoca/
  GenLoc); optionally quote the symptoms-vs-essence sentence next to our
  53% statistic.
