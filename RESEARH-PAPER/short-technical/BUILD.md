# How to build short-technical/main.tex

```bash
cd short-technical
pdflatex main.tex
pdflatex main.tex     # second pass for TOC + cross-references
```

No bibtex pass is needed --- there are no `\cite{}` calls (the project's references are quoted inline by name in the prose).

If `pdflatex` is missing, install TeX Live (Linux/macOS) or MiKTeX (Windows) and re-run.

## Sections

| File | Purpose |
|---|---|
| `sections/00-abstract.tex` | 1-page narrative summary |
| `sections/01-introduction.tex` | Problem framing, why custom dataset, why hybrid |
| `sections/02-dataset-construction.tex` | Workload, fault injection per scenario family, label semantics, humanizer, TAWOS, distractors, final stats |
| `sections/03-evaluation-setup.tex` | Splits, metrics in plain English, statistical envelope, pipeline panel |
| `sections/04-pipelines.tex` | Each of the seven models explained in technical depth |
| `sections/05-cascade.tex` | TCH four-layer cascade --- design, math, worked example, info flow |
| `sections/06-experiments.tex` | 13 baseline ablations + 8 G-series refinements + three cross-cutting findings |
| `sections/07-results.tex` | Headline tables, paired-bootstrap deltas, robustness summary, time-to-diagnose |
| `sections/08-industrial.tex` | Training cost, inference cost, deployment patterns, is-it-worth-it analysis |
| `sections/09-cross-app.tex` | External validity --- TAWOS-telemetry / new-app / OTel Demo options, recommended path |
| `sections/10-limitations.tex` | Dataset realism + methodological constraints + non-claims |
| `sections/11-conclusion.tex` | One-page final summary |

## Figures

All eight PDFs in `figures/` are copies of the artifacts produced by the
generation scripts in the main `technical-paper/figures/` directory. They are
embedded into the relevant sections (channel ablation, depth-stratified
retrieval, pipeline comparison, L1 stacker coefficients, G-series novelty
progression, G6 distractor robustness, G8 OOD F1, expected time-to-diagnose).
