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

| Phase | File | Status | Verdict | Headline result |
|---|---|---|---|---|
| G1 | [G1-bienc-hard-negatives.md](G1-bienc-hard-negatives.md) | ✅ done | KEEP | Hit@1 +2.1% rel, novelty unchanged |
| G2 | [G2-crossencoder-rerank.md](G2-crossencoder-rerank.md) | ✅ done | SKIP | Cross-encoder rerank hurts cascade (−5pt Hit@5 in fusion mode) |
| G3 | [G3-symmetric-llm-extraction.md](G3-symmetric-llm-extraction.md) | ✅ done | SKIP | Standalone kg +404% Hit@1, but cascade integration breaks (overlap-rerank shift) |
| G4 | [G4-agent-phase3.md](G4-agent-phase3.md) | ✅ done | KEEP | Novel recall +119% rel, retrieval/triage all tied or up |
| G5 | [G5-llm-judge-reranker.md](G5-llm-judge-reranker.md) | ✅ done | SKIP | LLM judge confidence uninformative (84% = 0.85); applying overrides drops Hit@1 by 2.7-13pts |
| G6 | [G6-distractor-sweep.md](G6-distractor-sweep.md) | ✅ done | KEEP (analysis) | Hit@5 only drops 2% at 50% distractor ratio (simulated); cascade is robust |
| G7 | [G7-learned-novelty.md](G7-learned-novelty.md) | ✅ done | **KEEP** | **Novel recall +388% rel at preserved precision** (largest single-phase lift) |
| G8 | G8-ood-eval.md | pending | TBD | — |
| FINAL | FINAL-summary.md | pending | — | — |

## Cumulative cascade as of G7

| Metric | v2f baseline | Current (G1+G4+G7) | Δ rel |
|---|---:|---:|---:|
| Hit@1 | 0.7069 | 0.7221 | +2.1% |
| Hit@5 | 0.9124 | 0.9124 | tie |
| MRR | 0.7880 | 0.7937 | +0.7% |
| PR-AUC strict | 0.9998 | 0.9998 | tie |
| PR-AUC inclusive | 0.8527 | 0.8562 | +0.4% |
| Novel precision | 0.9402 | 0.9405 | tie |
| **Novel recall** | **0.1625** | **0.7932** | **+388%** |

Activation:
```bash
TCH_OVERRIDE_BIENC="v2g-final-models/g1-bienc-hard-negatives/predictions-bienc.jsonl"
TCH_EXTRA_AGENT_FILES="v2g-final-models/g4-agent-phase3/per-window-predictions.jsonl"
TCH_LEARNED_NOVELTY_PATH="v2g-final-models/g7-learned-novelty/learned_novelty.jsonl"
TCH_LEARNED_NOVELTY_THRESHOLD=0.50
```

## Notable bug fixed mid-G4

Earlier today the bi_encoder G1 predictions file was OVERWRITTEN by a cascade output (both wrote to `per-window-predictions.jsonl` in the same dir). The cascade silently produced Hit@5 = 0.83 instead of 0.91. **Restored from `training_runs/bi_encoder_retrieval_g1__.../predictions.jsonl` to `predictions-bienc.jsonl` (separate filename).** Future G-phases should write their pipeline outputs to filenames distinct from `per-window-predictions.jsonl` to avoid the same trap.

Cross-reference: full plan is in `docs3/20-Final-plan.md`. The locked baseline (`v2f-tch-phase1`) is documented in `docs3/16-TCH-CASCADE.md` and `docs3/17-FINAL_HYBRID.md`.
