# ICSE 2027 draft

Build: `pdflatex main && bibtex main && pdflatex main && pdflatex main`
(or `latexmk -pdf main.tex`). Format: IEEE two-column conference, double-blind.

## Open naming decisions (placeholders in main.tex macros)
- `\sys` — system name (currently "Remedy", placeholder).
- `\real` — real dataset short tag (currently "JiraInc", placeholder; repo codename is "WoL / World of Logs").
Confirm both before camera-ready; they are isolated in main.tex macros so renaming is one-line.

## Source of truth for all numbers
`../paper-results/` (+ per-category SUMMARY.md). Do not hand-edit numbers; cite from there.
