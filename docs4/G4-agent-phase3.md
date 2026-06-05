# G4 — DiagnosisAgent Phase 3 (Remaining 658 Windows)

**Status:** 🟡 In progress (starting 2026-06-05, ~17:05)

## 1. Goal

Run the DiagnosisAgent on the 658 test windows it hasn't seen yet (Phase 1 covered 200 random, Phase 2 covered 150 hard-case). After G4, agent coverage = 1008/1008 (100%) and the cascade has the agent's `is_novel` signal on every window.

## 2. Hypothesis

The agent has ~94% novelty precision at the current threshold (0.4) and consistent ~37% recall on the windows it's seen. If extrapolation holds, applying it to 658 more windows should:
- Catch ~37% × 543 (truly novel in unseen) = ~200 additional truly-novel windows.
- At 94% precision = ~13 false-novel windows added.
- Combined with G1's existing 117 novel flags → ~310 total flagged.
- Novel recall: 0.162 → ~0.30-0.35 (a +85-115% rel lift).
- Hit@K, MRR, PR-AUC: unchanged (agent doesn't rerank in TCH design).

This is the cleanest "more LLM = more novelty recall" experiment. Low risk of regression.

## 3. Setup

- **Model:** Qwen 3.6 35B-A3B via LM Studio (already loaded post-G3 ejection cycle).
- **Stages:** hypothesize (thinking=OFF, ~1 sec) + verify (thinking=ON, ~25-30 sec).
- **max_tokens:** 1500 for verify (allows ample thinking budget).
- **Window scope:** 658 windows = 1008 test − 200 Phase 1 − 150 Phase 2.
- **Cached hybrid predictions:** reuse `v2c-hybrid-llm/per-window-predictions.jsonl` so no BiEncoder refit needed (same trick as Phase 2).
- **Window-ID filter:** explicitly enumerate the 658 not-yet-seen windows.
- **Expected wall:** 658 × ~30 sec/window = ~5.5 hours.

## 4. Plan

1. Compute the set of windows already covered: Phase 1 (`v2e-agent-llm/`) + Phase 2 (`v2e-agent-phase2/`) = 350 windows.
2. The 1008 test set − 350 = 658 windows. Write IDs to `phase3_window_ids.txt`.
3. Launch `diagnosis_agent` pipeline with `V2_AGENT_WINDOW_IDS_PATH=phase3_window_ids.txt` and `V2_AGENT_HYBRID_PREDICTIONS_PATH=v2c-hybrid-llm/per-window-predictions.jsonl`.
4. Monitor progress per 25-window batch.
5. After completion, update cascade's `EXTRA_AGENT_FILES` (or use `TCH_EXTRA_AGENT_FILES` env) to include the new agent predictions.
6. Rebuild cascade with G1 + G4 (agent everywhere) → compute deltas.

## 5. Observations

_(To be filled in.)_

## 6. Advantages

_(To be filled in.)_

## 7. Disadvantages

_(To be filled in.)_

## 8. Decision

_(To be filled in — expected POSITIVE based on linear extrapolation.)_

## 9. Open questions

- Does novelty precision drop with the larger sample? (Agent's confidence may be miscalibrated on certain subpopulations.)
- Are there windows where agent's novel flag conflicts with the free signal? Which one wins more often when they disagree?
- Does the per-family novelty recall improve uniformly, or is it concentrated on certain families?

---

*Generated 2026-06-05 before G4 launch.*
