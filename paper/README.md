# ICSE 2027 paper — Retrieval-Augmented Incident Triage

LaTeX source for the ICSE 2027 submission. All numbers locked from comparison runs through 2026-06-01; reproducible from the `data/derived/global/.../comparison/{phase-a-anchor,phase-b-finetune,phase-c-channels,phase-d-distractors}/` artifacts.

## Build

Requires the ACM `acmart` LaTeX class. On TeX Live / MikTeX:

```
cd paper
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Or with `latexmk`:

```
cd paper
latexmk -pdf main.tex
```

## Layout

```
paper/
├── main.tex                  # entry point — sets ACM template, includes sections
├── references.bib            # bibtex
├── README.md                 # this file
├── figures/                  # PDF figures (copied from results/figures/)
│   ├── anchor_combined.pdf       # the headline 3-panel depth-scaling figure
│   ├── anchor_depth_{hit1,hit5,mrr}.pdf   # per-metric depth curves
│   ├── channel_ablation.pdf      # Phase C
│   ├── distractor_curve.pdf      # Phase D
│   └── diagnosis_time.pdf        # Phase E utility
└── sections/
    ├── 00-abstract.tex
    ├── 01-introduction.tex
    ├── 02-related-work.tex
    ├── 03-system.tex
    ├── 04-methodology.tex
    ├── 05-results.tex
    ├── 06-discussion.tex
    ├── 07-limitations.tex
    └── 08-conclusion.tex
```

## Submission-blocking TODOs

1. **Bibliography verification.** `references.bib` has placeholders for some venues, page numbers, and DOIs. Verify each entry against the official ACM/IEEE listing before submission.
2. **Figure quality.** Current figures use matplotlib defaults; for camera-ready, switch to ACM-template-compatible serif fonts (`matplotlib.rcParams['font.family'] = 'serif'`).
3. **Architecture figure.** Section 3.1 references Figure 1 (architecture) which is currently a TODO. Either draw it (TikZ) or remove the forward reference.
4. **Page budget.** ICSE research track allows 10+2 pages (10 main + 2 references). Verify final layout fits.
5. **Anonymization.** The `acmart` template is set to `anonymous` mode; verify all self-references and code-repository URLs are redacted in review-time builds.
6. **Camera-ready commit.** Remove `\setcopyright{none}`, replace with ACM/IEEE-supplied copyright code, drop `anonymous` from `\documentclass` options.
