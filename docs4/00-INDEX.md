# `docs4/` — Per-Phase Observation Log (master-final-models)

One document per G-phase capturing **what we did, what we observed, advantages, and disadvantages**. Written immediately before / during / after each phase. The intent is that at the end of the 8-phase work, anyone reading `docs4/` end-to-end has the full narrative of what changed and why.

## Convention

Each phase has its own file: `Gn-<short-name>.md`. Structure:

1. **Goal** — one-sentence summary
2. **Hypothesis** — what we predicted before running
3. **Setup** — exact config / params / inputs
4. **What we did** — concrete actions
5. **Observations** — measured results
6. **Advantages** — what's better
7. **Disadvantages** — what's worse or unchanged
8. **Decision** — keep / discard / integrate into final cascade
9. **Open questions** — things to revisit

## Index

| Phase | File | Status | Headline result |
|---|---|---|---|
| G1 | [G1-bienc-hard-negatives.md](G1-bienc-hard-negatives.md) | ✅ done | Hit@1 +2.1% rel, novelty unchanged |
| G2 | G2-crossencoder-rerank.md | pending | — |
| G3 | G3-symmetric-llm-extraction.md | pending | — |
| G4 | G4-agent-phase3.md | pending | — |
| G5 | G5-llm-judge-reranker.md | pending | — |
| G6 | G6-distractor-sweep.md | pending | — |
| G7 | G7-learned-novelty.md | pending | — |
| G8 | G8-ood-eval.md | pending | — |
| FINAL | FINAL-summary.md | pending | — |

Cross-reference: full plan is in `docs3/20-Final-plan.md`. The locked baseline (`v2f-tch-phase1`) is documented in `docs3/16-TCH-CASCADE.md` and `docs3/17-FINAL_HYBRID.md`.
