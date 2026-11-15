# BLAZE: Cross-Language and Cross-Project Bug Localization via Dynamic Chunking and Hard Example Learning

**Partha Chakraborty, Mahmoud Alfadel, Meiyappan Nagappan. IEEE TSE 2025. DOI 10.1109/TSE.2025.3579574 (arXiv 2407.17631v3).**
PDF: `pdfs/blaze-tse2025.pdf` · Model: huggingface.co/bug-localization/BLAZE · Dataset: BeetleBox

## What it is

File-level IRBL that needs NO per-project training: a CodeSage (GPT-style
code embedding) model fine-tuned once with contrastive learning on hard
examples, fused with an ElasticSearch BM25 lexical retriever via
**reciprocal rank fusion** — the published precedent for RRF in bug
localization and the strongest "dense + lexical hybrid" baseline candidate
for us (covers C++ and Java, zero-shot on new projects).

## Method mechanics

- **Dynamic chunking**: tree-sitter finds component boundaries
  (class/method); a DP picks split points minimizing "continuity loss"
  (splitting inside a component costs most) under the embedding window
  size. Beats static chunking by 5.5–16% and sliding windows by 2–7.4%
  while using 3% fewer TFLOPS than sliding (static 201k chunks, sliding
  274k, dynamic 209k).
- **Hard example learning**: contrastive NT-Xent loss with multipliers
  α,β>1 on pairs on the wrong side of the batch-median similarity
  (positives below median, negatives above). Mined in embedding space, so
  language-agnostic.
- **Hybrid retrieval**: Milvus (dense) + ElasticSearch BM25 (lexical, which
  also indexes FILENAMES AND PATHS "to match logs and stack traces in bug
  reports" — their lexical side is roughly our S1+S2+S3 in one index);
  rankings combined with RRF (citing Cormack).

## BeetleBox and evaluation

23,782 bugs / 29 projects / 5 languages (C++ 8.1k, Java 4.6k, Python 5.2k,
JS 4.7k, Go 1.1k), train/test split BY PROJECT (zero-shot on unseen
projects). Also evaluated on SWE-bench (2,294) and Ye et al. (16,314).
Ground-truth linkage: they apply Kim et al.'s correction method and claim
only 0.06% incorrect mappings vs "up to 44%" in Bench4BL — a useful
citation that naive issue–commit linking is noisy (our funnel filters are
our answer). They also EXCLUDE bug reports that explicitly mention the
modified files — i.e., they evaluate roughly on our HARD stratum only, and
admit residual answer-revealing reports remain.

## Numbers and what they mean (BeetleBox test, Table V)

| retriever | Top1 | Top5 | Top10 | MAP | MRR |
|---|---|---|---|---|---|
| Lexical (BM25) | 0.07 | 0.12 | 0.19 | 0.11 | 0.13 |
| Deep (fine-tuned) | 0.12 | 0.25 | 0.31 | 0.14 | 0.18 |
| Hybrid (BLAZE) | 0.18 | 0.37 | 0.45 | 0.22 | 0.27 |

Meaning: on mention-free, cross-project bugs, even the best 2025 hybrid
gets Top5 = 0.37 — strikingly close to our hard-stratum numbers (cond_ours
0.33–0.54 acc@5), which supports that our hard stratum is the
representative difficulty, not an artifact. Fusion gain (+45–57% over deep
alone) is large — same qualitative story as our RRF gains. The headline
"up to 120%/144%/100%" improvements are vs the weakest baselines
(TRANP-CNN/CooBa/FBL-BERT); vs OpenAI embeddings the margin is 14–17%
Top-1 (and it loses to OpenAI on Go and on Ye-et-al Top-1 by 5%).

## Weaknesses / gloss-overs

- Needs GPU fine-tuning + Milvus + ElasticSearch infrastructure; "no
  per-project training" ≠ cheap (fine-tuned on 11.8k BeetleBox training
  bugs). As OUR baseline, the honest cheap form is: their public HF model
  for embeddings + BM25 + RRF, zero-shot — flag as "BLAZE-style hybrid".
- No history/similar-report signal; no time-awareness anywhere (their
  snapshot is "the repository version where the bug exists" — good — but
  nothing constrains cross-bug information flow in training vs test time
  beyond the project split).
- Mention-excluding filter makes their numbers incomparable to easy+hard
  mixes — when citing their Top5 0.37 next to ours, say both are
  "no-file-named" populations.
- Chunk/embedding cost on big C++ repos is nontrivial (our blob-cache
  trick would be needed to make it tractable across 6,437 snapshots).

## Use in our paper

- Related work (deep IRBL + fusion): RRF-in-IRBL precedent; dense+lexical
  complementarity (their precision/recall analysis mirrors our S-signal
  complementarity).
- §4 baselines: the designated "dense retriever" baseline the reviewer
  demanded (W1) — BLAZE HF model or CodeSage zero-shot + our BM25 via RRF.
- §2: Kim-et-al 44%-bad-mappings citation motivates our linkage filters;
  their mention-exclusion motivates our stratified reporting instead of
  population surgery.
