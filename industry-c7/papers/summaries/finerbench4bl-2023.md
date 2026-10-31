# FinerBench4BL: Large-Scale Evaluation of Method-Level Bug Localization

**Shizuka Tsumita, Shinpei Hayashi (Tokyo Tech), Sousuke Amasaki (Okayama Pref. U). arXiv 2302.14293 (2023); SANER-track lineage.**
PDF: `pdfs/finerbench4bl-2023.pdf`

## What it is

Bench4BL transformed to METHOD level: a "repository transformation" turns
each file-level repo version into a repo of method-sized documents, the
same bug→commit linking then yields oracle METHODS, and five file-level
IRBL implementations (BugLocator, BLUiR, BRTracer, AmaLgam, BLIA lineage)
are mechanically retargeted. 37 projects.

## Findings

- **Method-level IRBL DECREASES accuracy but REDUCES debugging effort.**
  Accuracy drops because method documents are short (sparser term
  statistics); effort drops because recommended units are tiny. Their
  motivating example (CODEC-221): file-level ranks the 729-line
  `HmacUtils.java` first; method-level surfaces all three buggy methods
  within the top-4, total 82 LOC to read (−11% reading effort even in a
  favorable file-level case).
- Relative ordering of techniques is similar across levels — level choice
  changes absolute numbers, not the winners.
- Background stat (via Hata et al.): a buggy file typically contains 1–2
  buggy methods out of 8–22 — file-level output leaves most of the
  reading work undone.

## Relevance to us (reviewer W4: "code regions, not files")

- The honest framing for our function-level stage: expect LOWER Acc@K at
  function level than file level (sparser documents) but a better
  effort story. We should report both, not promise accuracy gains.
- Their transformation design (treat methods as documents, reuse the same
  gold-linking machinery) is exactly the cheap second stage the reviewer
  sketched: tree-sitter functions as documents, gold functions from fix
  diff hunks, rank within top-N files. Java-only here; our C++ port is
  the new part.
- Effort-based metrics (LOC-to-read) are a nice complementary number we
  can compute nearly for free (sum LOC of ranked units until first gold).

## Weaknesses / notes

- Java only; method extraction from files via transformation can mangle
  edge cases (they call it semi-automatic).
- No new technique — evaluation infrastructure paper; absolute numbers
  depend on Bench4BL's known linkage noise (see BLAZE's 44% citation).
- No time-awareness (inherits Bench4BL's protocol).

## Use in our paper

- §Related work (granularity): cite with LocAgent for the file/module/
  function reporting convention, and for the accuracy-vs-effort trade-off
  sentence when we introduce our function-level stage.
- §4 metrics: justification for reporting module AND file (AND function
  if built) rather than claiming one true granularity.
