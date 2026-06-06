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

### G5 run

| Stat | Value |
|---|---:|
| Windows judged | 1007 / 1008 (1 JSON parse failure) |
| Wall time | 2.6 hours |
| Avg per-window | 9.3 sec |
| Overrides suggested (best_idx ≠ 0) | 613 (61%) |

### Confidence distribution — uninformative

| Bucket | Count |
|---|---:|
| < 0.5 | 13 |
| 0.5-0.6 | 16 |
| 0.6-0.7 | 0 |
| 0.7-0.8 | 0 |
| **0.8-0.9** | **850 (84%)** |
| ≥ 0.9 | 128 |

The judge defaults to ~0.85 for the vast majority of calls. Confidence is essentially a constant; you can't usefully threshold it. This pattern is common with LLM "confidence" outputs unless explicitly post-trained for calibration.

### Threshold sweep — none improve Hit@1

| Threshold | Overrides applied | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| 0.00 (all) | 613 | 0.5891 | 0.9124 | 0.7258 |
| 0.50 | 613 | 0.5891 | 0.9124 | 0.7258 |
| 0.80 | 613 | 0.5891 | 0.9124 | 0.7258 |
| **0.90** | 90 | **0.6949** | 0.9124 | 0.7801 |
| 1.00 (none) | 0 | **0.7221** | 0.9124 | 0.7937 |
| **G4 baseline** | — | **0.7221** | **0.9124** | **0.7937** |

Every override level HURTS Hit@1 vs the cascade's existing overlap-rerank. The best case (threshold ≥ 0.9) loses 2.7pts. The worst case (apply all 613 overrides) loses 13pts.

Hit@5 stays constant at 0.9124 because we only reorder within the existing top-5 — we don't remove candidates.

## 6. Advantages

1. **Honest negative result** — we tested binary LLM "pick the best" as a reranker. It doesn't beat the cascade's existing logic.
2. **Confidence-output limitation surfaced.** Future LLM judges should either (a) train confidence calibration or (b) use a numeric score per candidate rather than picking one + asking for confidence.
3. **Compute cost is moderate.** 2.6 hrs LLM at 9.3 sec/window — could integrate at inference if it helped, but it doesn't.

## 7. Disadvantages

1. **Hurts Hit@1 in EVERY override scenario tested.** Same pattern as G2 cross-encoder and Phase E agent re-rank.
2. **Confidence output is uninformative** — clustered around 0.85, making threshold-gating useless.
3. **The cascade's overlap-rerank wins.** Multi-retriever consensus on top-1 beats a single LLM judgment.
4. **Hit@5 doesn't lift either** (would have required candidate filtering, which we deliberately didn't do — the schema only allows picking from the existing 5).

## 8. Decision

**SKIP G5 from the final cascade.** This is the THIRD reranking-style intervention (after G2 cross-encoder and Phase E agent re-rank) to underperform the cascade's existing overlap-rerank. The pattern is consistent: in this dataset, multi-retriever consensus beats any single LLM judgment for top-1 selection.

Final cascade going into G6 stays at **G1 + G4**.

The LLM judge predictions are preserved at `comparison/v2g-final-models/g5-llm-judge-reranker/llm_judge_outputs.jsonl` (with the original_top5, suggested_top5, confidence, reasoning per window) — useful as ablation data for the paper.

## 9. Open questions

- **Listwise LLM scoring** — instead of "pick best", ask the LLM for a score per candidate. Would this avoid the 0.85-everywhere problem? Out of scope.
- **Per-candidate calibration via probe** — Phase F's "ret_conf < 0.5" was an emergent calibration signal. Would the agent's verify confidence (Phase E) calibrate better? Could be checked retroactively.
- **Cart-redis specifically** — does G5 help that family even if it hurts overall? Worth a quick stratified check before final close-out.

## 10. Cross-references

- Code: `src/v2_advanced/tch/llm_judge.py` (new).
- Output: `data/derived/global/.../v2g-final-models/g5-llm-judge-reranker/`
- Commit pending.

---

*Generated 2026-06-06 after G5 completion. Third reranking-style intervention to underperform. Pattern is now publication-worthy.*

---

*Generated 2026-06-05 before G5 launch.*
