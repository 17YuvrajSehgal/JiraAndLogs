# G3 — Symmetric LLM Extraction (Tickets AND Windows)

**Status:** 🟡 In progress (started 2026-06-05, ~13:50)

## 1. Goal

Close the entity-mismatch gap discovered in Phase D's "RRF density paradox":
LLM-extracted tickets emit specific entities (e.g. `RedisConnectionException`, `CPUThrottlingHigh`) while rule-extracted windows emit generic entities (`Unavailable`, `pod`, `high latency`). The strings don't overlap, so the LLM-graph `kg_retrieval` and `hybrid_rrf (LLM graph)` underperform.

Symmetric extraction = LLM-extract the 1008 test windows too, using the same Qwen 35B + strict JSON schema as Phase D. Then both sides of the graph match use LLM-quality entities.

## 2. Hypothesis

If symmetric extraction works:
- `kg_retrieval (LLM)` Hit@5 should recover from current 0.28 → 0.50-0.60 (closer to rule-based 0.46 or better).
- `hybrid_rrf (LLM graph)` Hit@5 might recover from 0.69 → 0.78-0.85.
- If LLM-graph hybrid_rrf becomes competitive, it can re-enter TCH's L2 fusion (it was dropped in Phase F because it hurt Hit@5).
- Final cascade Hit@5: could lift from 0.912 → 0.92-0.94.

If symmetric extraction doesn't work:
- The LLM-graph would still be a precision-heavy precision/recall trade-off, but at least now we know it's not just the asymmetry.

## 3. Setup

- **Schema:** `WINDOW_EXTRACTION_SCHEMA` (already exists in `src/v2_advanced/shared/json_schemas.py` — fields: affected_services, components, error_classes, symptoms).
- **Model:** Qwen 3.6 35B-A3B via LM Studio (currently loaded, server on `localhost:1234`).
- **Thinking mode:** OFF (fast extraction, matching Phase D ticket extraction).
- **max_tokens:** 600 per call.
- **Window scope:** 1008 test windows (the v2 in-distribution test set). NOT train/val — we don't need to LLM-extract those because they don't drive metric computation.
- **Throughput target:** ~14 sec/window (same as Phase D tickets) → ~4 hours total wall time for 1008 windows.

## 4. Plan

1. Create `src/v2_advanced/proposal_d_knowledge_graph/extract_windows_cli.py` (analog to `extract_tickets_cli.py`).
2. For each test window: build the same window evidence text used by `kg_retrieval`, call Qwen with `WINDOW_EXTRACTION_SCHEMA`.
3. Cache outputs to `v2_kg_extractions_windows/all_extractions.jsonl` (one row per window).
4. Reload Neo4j with the combined graph: all 347 tickets + all 1008 test windows as `Incident` nodes connected to LLM-extracted Symptom/Service/Component nodes.
5. Re-run `kg_retrieval` pipeline against the new graph — now both sides use LLM entities.
6. Re-run `hybrid_rrf_retrieval` with the new LLM graph.
7. Build TCH cascade with `TCH_OVERRIDE_HYBRID_LLM` pointing at the new hybrid_rrf output. Try re-adding LLM hybrid_rrf to L2 fusion.
8. Compute deltas vs G1 cascade baseline.

## 5. Observations

_(To be filled in.)_

## 6. Advantages

_(To be filled in.)_

## 7. Disadvantages

_(To be filled in.)_

## 8. Decision

_(To be filled in.)_

## 9. Open questions

- Does symmetric extraction restore LLM-graph to competitive Hit@5?
- If yes — does it help when re-added to L2 RRF fusion?
- Are there windows where the LLM extraction times out or produces invalid JSON? (Phase D had 0 failures over 347 tickets; expecting similar for 1008 windows but the schema is slightly different.)

---

*Generated 2026-06-05 before G3 launch.*
