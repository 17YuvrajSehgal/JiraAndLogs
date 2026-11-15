# When Deep Learning Meets Information Retrieval-based Bug Localization: A Survey

**Feifei Niu, Chuanyi Li (Nanjing U), Kui Liu (Huawei), Xin Xia (Zhejiang U), David Lo (SMU). ACM Computing Surveys 57(11), Art. 296 (2025); arXiv 2505.00144.**
PDF: `pdfs/deepirbl-survey-2025.pdf` — note: same first author (Niu) as the
ABLoTS replication; this group owns the leakage-aware IRBL agenda.

## What it is

Systematic survey of 61 DL-based IRBL studies (to Nov 2024), with the
three-generations framing: (1) 2004–2011 bag-of-words; (2) 2010–2016
BoW + auxiliary signals (similar reports, version history, structure,
stack traces — the BugLocator/AmaLgam/BLIA era); (3) 2015– DL semantic
representations (+ AST/CFG/PDG structure). The single umbrella citation
for the whole classic-through-deep IRBL family — lets our related work
cite BLUiR/AmaLgam/BLIA/Locus details through one source where originals
are paywalled.

## The protocol sections (what we cite)

- **Validation taxonomy**: "anachronistic" k-fold cross-validation
  (random folds; still the most common) vs **consecutive validation**
  (chronological split or k sequential folds, train on fold_i test on
  fold_i+1). Quotes Pendlebury et al.: training on future data to test on
  past "introduces bias". Their position: "we believe that consecutive
  validation provides a more accurate evaluation method." → our §4.1
  citation, from the survey of record.
- **Before-fix version**: single-revision evaluation "may already have
  been fixed towards the specific bug report, and thus contains future
  bug-fixing information"; credits Ye et al. for before-fix snapshots.
  → our snapshot-convention citation alongside Bench4BL RQ2 + Broccoli.

## Numbers and framings worth keeping

- **The lexical gap, quantified**: Yang et al.'s measurement — average
  TF-IDF similarity between bug reports and their FIXED methods is
  0.0153 vs 0.0149 for IRRELEVANT methods. At method granularity, raw
  lexical similarity is nearly uninformative. This both motivates
  semantic methods AND quietly supports our design: our S3 works at FILE
  granularity over a candidate pool (richer documents), and our hard
  stratum shows where lexical text runs out — memory steps in exactly
  there.
- Performance overview (their Table 9, self-reported numbers, explicitly
  "only a rough comparison"): 18/61 approaches reach MAP ≥ 50%; five
  approaches bold on all metrics (Coloc, bjXnet, Yan et al., bjEnet,
  MACL-IRFL). Method- and commit-level lag file-level; cross-project and
  cross-language lag within-project.
- Cold start still open: transfer approaches exist (TRANP-CNN etc.) but
  best results still need ~20% labeled target-project data.
- Open problems they list: sampling for extreme imbalance, the code-size
  problem (truncation in BERT-class models — BLAZE's chunking is the
  answer there), interpretability of DL rankings, Java-dominance of the
  literature.

## Relevance to us, distilled

1. §4 protocol: consecutive validation + before-fix version, cited to the
   survey of record (plus its named primary sources).
2. Related work: one-citation coverage of the DL-IRBL family; the
   interpretability complaint sets up our provenance output ("citations,
   not narrative") as the industrial answer.
3. The Java-dominance observation strengthens our multi-language
   (C/C++/Java/Scala) benchmark claim.
4. The 0.0153-vs-0.0149 statistic is a dramatic one-liner for why
   method-level lexical matching alone cannot carry localization — use
   with care (method-level, their citation chain).

## Weaknesses / notes

- Self-reported performance aggregation across incomparable setups (they
  say so).
- LLM-era coverage thin (cutoff Nov 2024; agents barely present) — pair
  with LocAgent/MULocBench for the current frontier.
- No treatment of similar-report leakage specifically (that's the same
  group's ABLoTS replication — cite both together).
