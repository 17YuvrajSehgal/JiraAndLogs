# ICSE 2027 — Submission Draft

**Target venue:** ICSE 2027 Research Track
**Page limit:** 10 pages + unlimited references (acmart `sigconf`)
**Review mode:** double-blind (`anonymous` option)
**Status:** scaffolding only — section structure + templates; no content yet

This directory holds the ICSE submission draft. It is a **distinct, parallel** document from `technical-paper/`, which is the comprehensive ~40-page technical report. The ICSE paper is the conference-formatted, page-limited, anonymous version of the same work — distilled to what fits in 10 pages.

## Working relationship to `technical-paper/`

| Aspect | `technical-paper/` | `ICSE/` (this dir) |
|---|---|---|
| Audience | Institutional / advisor | ICSE reviewers (double-blind) |
| Style | Comprehensive narrative | Compressed; experimental focus |
| Length | ~40 pages, 14 sections | 10 pages, 10 sections |
| Anonymity | Authored | Anonymous (for review) |
| Citation density | Lower | Higher |
| Status | Locked baseline | First draft |

The ICSE paper draws on `technical-paper/` for content but is a separate document; do not `\input` across the two.

## Directory layout

```
ICSE/
├── README.md                 (this file)
├── main.tex                  paper entry point — preamble + section \input{}s
├── references.bib            bibliography (BibTeX)
├── Makefile                  `make` to build PDF; `make clean` to wipe
├── sections/
│   ├── 00-abstract.tex
│   ├── 01-introduction.tex
│   ├── 02-background.tex
│   ├── 03-approach.tex
│   ├── 04-evaluation.tex
│   ├── 05-results.tex
│   ├── 06-cross-app.tex
│   ├── 07-discussion.tex
│   ├── 08-threats-to-validity.tex
│   ├── 09-related-work.tex
│   └── 10-conclusion.tex
├── figures/                  (PDF / PNG figures; empty for now)
└── tables/                   (standalone .tex tables if any; empty for now)
```

## Building

```bash
# Requires pdflatex + bibtex (e.g. via texlive-full on Ubuntu, MiKTeX on Windows)
make            # builds main.pdf
make clean      # removes .aux/.log/.bbl/.blg/.toc/etc.
```

The build sequence is `pdflatex → bibtex → pdflatex → pdflatex` to resolve all references and the ToC.

## Section structure rationale

Sized for the 10-page limit. Approximate budgets:

| § | Section | Pages | Headline content |
|---|---|---:|---|
| Abstract | — | 0.25 | Problem, contribution, key numbers |
| 1 | Introduction | 1.0 | Diagnosis bottleneck; system overview; claims |
| 2 | Background | 0.75 | OB, V2 corpus, what was settled in prior work |
| 3 | Approach (TCH) | 2.0 | 4-layer cascade math + worked example |
| 4 | Evaluation setup | 0.75 | Splits, metrics, bootstrap envelope |
| 5 | Results | 2.0 | Headline table + per-stratum + G-series synthesis |
| 6 | Cross-app generalization | 1.0 | OTel Demo zero-shot + L1-retrained + L1–L4 graded |
| 7 | Discussion | 0.5 | Composition vs. component fragility; what transfers |
| 8 | Threats to validity | 0.5 | Sampling, synthetic Jira, feature-population gap |
| 9 | Related work | 0.75 | IR/RAG, AIOps, log anomaly, microservices benchmarks |
| 10 | Conclusion | 0.5 | Recap + future work pointer |
| References | — | (unlimited) | |
| **Total body** | | **~10.0** | |

## Headline numbers to weave in (locked from `technical-paper/`)

These are the numbers the paper proves; populate from `data/derived/global/.../comparison/v2g-final-models/final/headline-final.json`:

- **Hit@5 = 0.912** on the v2 in-distribution test split (1,008 windows)
- **Hit@1 = 0.722**
- **MRR = 0.794**
- **Strict PR-AUC = 0.9998**
- **Inclusive PR-AUC = 0.8562**
- **Novel precision = 0.940**, **Novel recall = 0.793** (+388% rel over the v2f baseline at preserved precision)
- **Inference cost = 16 μs / window** after caching
- Robustness: Hit@5 drops only 2% rel at 50% distractor ratio; LOFO novelty F1 within 11% rel of in-distribution
- Cross-app: TBD pending GCP collection — placeholders in `06-cross-app.tex`

## Anonymization checklist before submission

- [ ] `\author` block uses anonymous placeholders
- [ ] No self-citations expose authors (use "this paper" not "our prior work")
- [ ] No URL / repo hostnames that identify the lab
- [ ] No acknowledgments section in the review version
- [ ] No identifying figure metadata (PDF properties)
- [ ] Memo: `\acmConference`, `\copyrightyear` set per ICSE 2027 instructions when known

## Open questions for the lead author

Tracked here so they don't get lost during drafting:

1. **Title** — current placeholder: "Memory-Augmented Incident Triage with Cross-App Generalization". Iterate before finalizing.
2. **Position of the cross-app section (§6)** — separate section vs. folded into §5? Currently separate for emphasis.
3. **Page-budget tension** — preliminary section budgets sum to 10 exactly. If cross-app GCP results expand §6, something else gets compressed (most likely §2 or §9).
4. **Whether to include the G-series at all** — it's the strongest evidence the cascade is at a local optimum, but takes space. Currently in §5 as a sub-section.
5. **Reference padding strategy** — references are unlimited, but the bib should focus on IR/RAG + AIOps + microservices benchmarks rather than padding with adjacent work.

## What to fill in next

Per the user's direction, the scaffold is complete; content authoring is the next step. Recommended order:

1. **§5 Results** — the numbers are locked; this is the easiest to write and anchors everything else.
2. **§3 Approach** — port the math from `technical-paper/sections/05-tch-cascade.tex`, compress to 2 pages.
3. **§1 Introduction** — written last in conference papers, often; but the headline is locked.
4. **§4 Evaluation setup** — locked methodology; mostly copy/compress.
5. **§6 Cross-app** — waits for GCP collection results.
6. **§2 Background, §7 Discussion, §8 Threats, §9 Related, §10 Conclusion** — fill as space allows.
