# paper-results — fresh, publishable result set

Self-contained results for the ICSE submission, collected fresh (no mixing with
`data/` or the old `results/`). Categorized by the question each answers.
See `DOCS/review-sol.md` for the plan and `provenance/` for reproducibility.

| Dir | What it holds |
|---|---|
| `retrieval-cascades/` | Per-pipeline retrieval panel (Hit@1/5/10, MRR, CIs), per dataset |
| `baselines/` | Prior-art (SOTA dense, cross-encoder rerank, TF-IDF) + LLM-RAG |
| `agent-end-to-end/` | Full agent eval: Hit@K, triage acc, novelty, pages/incident |
| `agent-value/` | What the agent adds: cost@iso-accuracy, skill/tool ablations |
| `kg-usefulness/` | Is the KG helpful: ±graph ablation, complementarity, explanation judge |
| `robustness/` | Multi-seed variance, multiple-comparison correction, negative-results |
| `gold-validation/` | LLM-as-judge relevance + human-annotation kit |
| `provenance/` | git SHA, env freeze, seeds, run configs, LLM prompts |

Datasets: `online-boutique` (2026-05-25-dataset-v5-large-global),
`otel-demo` (2026-06-09-otel-demo-v1-global),
`wol-v3` (2026-06-17-wol-real-v3-global).
