# paper-results — ICSE result set

Fresh, publishable results (clean of `data/` and the old `results/`). See `DOCS/collection-log.md` for provenance and `DOCS/audit-findings.md` for the correctness audit. Large per-window predictions/traces are shipped as a release archive (gitignored).

## Category summaries
- [`retrieval-cascades/SUMMARY.md`](retrieval-cascades/SUMMARY.md)
- [`baselines/SUMMARY.md`](baselines/SUMMARY.md)
- [`kg-usefulness/SUMMARY.md`](kg-usefulness/SUMMARY.md)
- [`gold-validation/SUMMARY.md`](gold-validation/SUMMARY.md)
- [`robustness/SUMMARY.md`](robustness/SUMMARY.md)
- [`agent-end-to-end/SUMMARY.md`](agent-end-to-end/SUMMARY.md)
- [`agent-value/SUMMARY.md`](agent-value/SUMMARY.md)
- [`triage-leaderboard/SUMMARY.md`](triage-leaderboard/SUMMARY.md)
- `agent-value/` — cost@iso-accuracy + skill/tool/budget ablations (per-dataset JSON)
- `provenance/` — env freeze, config (seeds/epochs/splits), git SHA

## Headline (WoL real data, coarse Hit@5)
Hybrid-RRF **0.970** > BiEncoder 0.905 > LLM-RAG 0.856 > BM25 0.727 — fusion of SPLADE+BiEncoder+graph wins on real Jira data and beats the LLM-RAG baseline.
