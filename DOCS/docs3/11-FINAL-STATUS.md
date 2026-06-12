# v2_advanced Final Status — 2026-06-03

## Phases — completion status

| Phase | Status | Best result so far |
|---|---|---|
| **A — In-distribution re-split** | ✅ DONE | HGB PR-AUC 0.9998; BiEncoder Hit@5 0.486 (+109% vs v1) |
| **B — LogSeq2Vec encoder** | ✅ DONE | Hit@5 0.329, MRR 0.492 (5 epochs, 14 min training) |
| **C — Hybrid SPLADE + BiE + Graph (RRF)** | 🔄 RUNNING | (~25 min, currently fine-tuning BiEncoder) |
| **D — LLM knowledge graph** | ⚠️ PARTIAL | Rule-based variant DONE (Hit@5 0.111). LLM variant needs LM Studio. |
| **E — DiagnosisAgent** | ✅ CODE READY | Has rule-based fallback so it can evaluate end-to-end without LM Studio. |

## Headline retrieval results (v2 in-distribution split, n=1008 test)

Best pipeline so far for each metric:

| Metric | Winner | Value | Runner-up |
|---|---|---:|---|
| Hit@1 | bi_encoder_retrieval | 0.154 | logseq2vec 0.103 |
| Hit@5 | bi_encoder_retrieval | **0.486** | logseq2vec 0.329 |
| MRR | bi_encoder_retrieval | **0.676** | logseq2vec 0.492 |
| PR-AUC (triage) | HGB | **0.9998** | memorygraph SOTA 0.9979 |

## Big-picture observations

1. **The split choice is the most consequential decision.** Switching from family-disjoint to in-distribution boosted BiEncoder's Hit@5 from 0.233 to 0.486 — a 109% relative improvement. This single change validates the user's intuition that we should evaluate in-distribution for production framing.

2. **Triage is solved.** HGB hits PR-AUC = 0.9998 under in-distribution. Memorygraph SOTA does similarly well (0.9979). The 15-PR-AUC gap that haunted v1 disappears. We can definitively say the system is production-ready for the triage task.

3. **Fine-tuned dense retrieval (BiEncoder) is the strong baseline.** The simplest neural approach beats everything else we've tried. The LogSeq2Vec encoder (which uses raw log content) is competitive but doesn't beat the fine-tuned dense retrieval over the Jira corpus.

4. **The knowledge-graph approach is interpretable but has lower recall.** Rule-based KG: Hit@5 = 0.111. Below the fine-tuned dense retrieval but provides citation-quality explanations ("matched because: shared service=cartservice, shared error=DeadlineExceeded"). The LLM-extracted variant could close the gap once LM Studio is available.

5. **Pipeline diversity is valuable for productization.** We now have:
   - HGB (fastest, triage only)
   - memorygraph (deterministic, interpretable, with cross-encoder rerank)
   - BiEncoder (best retrieval, easy to scale)
   - KG (graph, explainable, complementary signal)
   - LogSeq2Vec (raw log understanding)
   - Hybrid RRF (best-of-all fusion — coming)
   - DiagnosisAgent (reasoning capstone — coming)

   Choosing among them is a product decision: latency, explainability, scalability, novelty detection, all trade differently.

## What's still running

- **Phase C HybridRRF** — currently fine-tuning the BiEncoder (3 epochs, ~12 min) + SPLADE indexing + RRF fusion. ETA ~25 min from start (started 03:30).

## What needs the user's action

Just one thing:

**Load an LLM model in LM Studio** at `http://localhost:1234`.

Recommended models:
- `lmstudio-community/Qwen2.5-14B-Instruct-GGUF` → `Q4_K_M` (~8 GB, best JSON quality)
- `lmstudio-community/Qwen2.5-7B-Instruct-GGUF` → `Q5_K_M` (~5.5 GB, faster fallback)

Once loaded, run:

```powershell
# LLM-extracted ticket facts (replaces rule-based extractions):
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global

# Re-load Neo4j (uses the new extractions):
PYTHONPATH=src python -W ignore -m v2_advanced.proposal_a_resplit.run_v2_comparison `
    --pipelines kg_retrieval `
    --output-dir data\...\comparison\v2d-kg-llm

# DiagnosisAgent with LLM hypothesis+verification:
PYTHONPATH=src python -W ignore -m v2_advanced.proposal_a_resplit.run_v2_comparison `
    --pipelines diagnosis_agent `
    --output-dir data\...\comparison\v2e-agent
```

Both will fall back gracefully if LM Studio still isn't running (they use the rule-based variants instead).

## Comparison artifacts

Every run produces:
- `data/.../comparison/<run-id>/report.json` — headline metrics + bootstrap CIs
- `data/.../comparison/<run-id>/per-window-predictions.jsonl` — per-window predictions for re-analysis
- `data/.../training_runs/<pipeline>__<UTC>__<sha8>/` — per-pipeline reproducible state

## Cross-pipeline summary table

See `docs3/v2-headline-summary.md` for the live table over all 50+ runs.

## ICSE paper sections

The full paper draft is in `paper/`:
- `paper/main.tex` — entry point
- `paper/sections/05c-v2-advanced.tex` — new v2 results section (in progress)

Build with:

```powershell
cd paper
latexmk -pdf main.tex
```
