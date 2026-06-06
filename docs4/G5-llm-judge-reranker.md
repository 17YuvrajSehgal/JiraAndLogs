# G5 — Per-Window LLM Judge Reranker

**Status:** 🟡 In progress (starting 2026-06-05, ~23:30)

## 1. Goal

After L2 produces the top-5 candidate Jira tickets, ask Qwen 35B (with thinking enabled): "Given this window evidence, which of these 5 candidates is the best match?". Use the answer to confidence-gate-override position 1.

This is the **last** ablation that can plausibly push Hit@1 above the current 0.722 (matching bi_encoder's standalone 0.722, no statistically significant lift). The theoretical union-of-retrievers ceiling on Hit@5 is 0.976 — Hit@1's ceiling is bound by whether SOMEONE has gold at position 1 in their top-5, which is around 0.91 (most retrievers have gold somewhere). An LLM judge could close some of that gap.

## 2. Hypothesis

For each test window:
- L2 cascade produces top-5 candidates.
- Send window evidence + 5 candidates (with titles + root_cause from extractions) to Qwen.
- Strict JSON schema: `{best_idx: 0-4, confidence: 0-1, reasoning: string}`.
- Thinking ON, max_tokens=1500.

If `confidence > threshold` (sweep 0.5, 0.6, 0.7, 0.8) and `best_idx != 0`, swap top-1 and final_top[best_idx]. Otherwise keep L2's order.

Expected outcome:
- Hit@1 lift: +1-3pts (best case to ~0.74-0.75).
- Hit@5 unchanged (we only reorder existing top-5).
- MRR slight lift if Hit@1 improves.
- Novel precision/recall unaffected (judge doesn't see novelty).
- Cost: 1008 × ~15 sec/window (smaller prompt than verify) = ~4.2 hours.

Risks:
- Same issue as G2 cross-encoder: LLM judge may be NOISIER at top-1 than the cascade's overlap-rerank. Phase E showed agent's top-1 override hurt by net -5 wins.
- Confidence threshold needs to be tuned. Too low → judge overrides too often (hurts). Too high → judge never overrides (no lift).

## 3. Setup

- **Model:** Qwen 3.6 35B-A3B via LM Studio (already loaded).
- **Thinking:** ON.
- **max_tokens:** 1500 (thinking budget).
- **Prompt:** window evidence (truncated to ~2000 tokens) + 5 candidates with `{ticket_id, title (from G3 extractions if available, else from humanized memory), root_cause, affected_services}`.
- **Schema:** strict JSON `{best_idx: int 0-4, confidence: float 0-1, reasoning: string}`.
- **Candidate source:** the L2 top-5 from the G1+G4 cascade (the new locked baseline).
- **Threshold sweep:** 0.5, 0.6, 0.7, 0.8. Pick the one that maximizes Hit@1 without hurting Hit@5.

## 4. Plan

1. Build `src/v2_advanced/tch/llm_judge.py`:
   - Loads G1+G4 cascade outputs.
   - For each window, calls LM Studio with the judge schema.
   - Writes `llm_judge_outputs.jsonl` with (window_id, best_idx, confidence, reasoning, original_top5, new_top5).
2. Run on 1008 windows (~4-5 hours).
3. Modify `build_cascade.py` to optionally apply the judge override (env var: `TCH_LLM_JUDGE_PATH`).
4. Sweep confidence threshold {0.5, 0.6, 0.7, 0.8} — pick best.
5. Compute deltas vs G4 cascade.

## 5. Observations

_(To be filled in.)_

## 6. Advantages

_(To be filled in.)_

## 7. Disadvantages

_(To be filled in.)_

## 8. Decision

_(To be filled in — risk: agent re-rank precedent suggests this may HURT like G2.)_

## 9. Open questions

- Does LLM judge see information bi-encoder doesn't (e.g., semantic relationships between fault types)? If yes → lift. If just consolidating same signals → no lift.
- Is the optimal threshold high (judge only acts when very confident) or low (judge acts often)?
- Does the judge help specifically on cart-redis (the family with most v2f failures)?

---

*Generated 2026-06-05 before G5 launch.*
