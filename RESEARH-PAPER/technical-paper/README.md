# Technical Report — Memory-Augmented Incident Triage

A comprehensive technical narrative of the project: dataset construction, microservice instrumentation, methods evolution (V1 → V2 → V2-advanced → TCH → G-series), the final hybrid cascade, results, and discussion. Intended for institutional / advisor review.

## Layout

```
technical-paper/
├── main.tex                            entry point (article class, 11pt, A4)
├── README.md                           this file
├── figures/                            PDF + PNG figures
│   ├── anchor_combined.pdf             depth-scaling characteristic (reused from results/)
│   ├── channel_ablation.pdf            per-channel ablation (reused from results/)
│   ├── diagnosis_time.pdf              time-to-diagnose simulation (reused from results/)
│   ├── g_series_novelty.pdf            NEW: G-series novelty progression
│   ├── pipeline_comparison.pdf         NEW: TCH vs each single pipeline
│   ├── g6_distractor_robustness.pdf    NEW: G6 simulator results
│   ├── g8_ood_f1.pdf                   NEW: G8 OOD vs ID
│   ├── l1_stacker_coefs.pdf            NEW: stacker weights bar chart
│   └── generate_extra_figures.py       script that produced the 5 NEW figures
└── sections/
    ├── 00-abstract.tex
    ├── 01-introduction.tex
    ├── 02-dataset-construction.tex      microservice mods, scenarios, telemetry, Jira corpus
    ├── 03-evaluation-setup.tex          splits, metrics, statistical envelope, pipeline panel
    ├── 04-methods-evolution.tex         V1 → V2 → V2-advanced; Pareto-incomparable observation
    ├── 05-tch-cascade.tex               L1+L2+L3+L4 specification with worked example
    ├── 06-g-series-improvements.tex     13 baseline ablations + 8 G-phases
    ├── 07-results.tex                   headline tables, progression, robustness, cost
    ├── 08-discussion.tex                cross-cutting findings, composition fragility, framing
    ├── 09-limitations.tex               dataset realism, methodological constraints, non-claims
    ├── 10-future-work.tex               4 ranked follow-ups from META-ANALYSIS
    ├── 11-conclusion.tex
    ├── A-hyperparameters.tex            appendix: every hyperparameter
    └── B-reproducibility.tex            appendix: how to regenerate every artifact
```

## Build

Requires a TeX distribution (TeX Live, MikTeX, or MacTeX) with the following packages: `geometry`, `microtype`, `lmodern`, `amsmath`, `booktabs`, `tabularx`, `longtable`, `graphicx`, `xcolor`, `subcaption`, `listings`, `hyperref`, `cleveref`, `titlesec`, `enumitem`, `makecell`.

```bash
cd technical-paper
pdflatex main.tex
pdflatex main.tex   # second pass for cross-references
```

Or with `latexmk`:

```bash
latexmk -pdf main.tex
```

## Regenerating the figures

The 5 NEW figures are produced by `figures/generate_extra_figures.py`. From the project root:

```powershell
.venv\Scripts\python.exe technical-paper\figures\generate_extra_figures.py
```

Requires `matplotlib`, `numpy` (already in the project's `.venv`). All numerical values are hardcoded from the locked artifacts (the figures are deterministic, not regenerated from raw cascade output).

The 5 REUSED figures (`anchor_*`, `channel_ablation`, `distractor_curve`, `diagnosis_time`) come from `results/figures/` and were produced by earlier project scripts:

- `scripts/figures/anchor_depth_curve.py` (depth-scaling figures)
- `scripts/figures/channel_ablation.py` (per-channel ablation)
- `scripts/figures/distractor_curve.py` (distractor sweep)
- `scripts/figures/diagnosis_time.py` (time-to-diagnose)

## Number provenance

Every numerical claim in the report traces to a specific artifact:

| Claim | Source |
|---|---|
| Hit@K, MRR, PR-AUC headline | `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/tch_metrics.json` |
| Novel precision / recall headline | same `tch_metrics.json` |
| G1–G8 phase results | `docs4/G1-…md` through `docs4/G8-ood-eval.md` |
| 13 baseline ablations | `docs3/16-TCH-CASCADE.md` |
| Cross-phase synthesis | `docs4/META-ANALYSIS.md` |
| L1 stacker coefficients | output of `python -m v2_advanced.tch.build_cascade` (last lines) |
| G7 threshold sweep | `data/.../v2g-final-models/g7-learned-novelty/best_threshold.json` |
| G8 OOD per-family table | `data/.../v2g-final-models/g8-ood-eval/ood_per_family.json` |
| Dataset sizes (1008 / 4701 / 1011 / 347) | `data/derived/global/.../triage-split-manifest.json` |

The locked commit hashes for each phase are in `sections/B-reproducibility.tex`.

## Audience and scope

This document is a **comprehensive technical report**, not a conference paper. It covers the full project narrative (data collection through final cascade through future work) at greater length than a 10-page submission would allow. A future conference submission could be derived from Sections 4–8 with substantial trimming.

## Status

All sections drafted as of 2026-06-06 after the G-series completion. Numbers locked from cascade build `b7557c4` (final TCH lock) and meta-analysis `e485149`.
