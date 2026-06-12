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

### G3 window extraction quality

| Stat | Value |
|---|---:|
| Windows extracted | 1008 / 1008 (100%) |
| Wall time | 133 minutes |
| Avg per-window | 7.92 sec |
| Failures / empty | 0 |
| Has services | 751 (74.5%) |
| Has error_classes | 414 (41.1%) |
| Has symptoms | 1008 (100%) |

Outstanding quality — every window got at least one symptom, 0 failures.

### Standalone retrieval lift (massive)

| Pipeline | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|
| kg_retrieval_rulebased | 0.0785 | 0.5559 | 0.2282 |
| **kg_retrieval_g3 (SYMMETRIC)** | **0.3958** | **0.6677** | **0.4960** |
| Δ rel | **+404%** | +20% | +117% |
| | | | |
| hybrid_rrf rule (baseline) | 0.5831 | 0.7976 | 0.6691 |
| hybrid_rrf LLM (asymmetric) | 0.4320 | 0.6677 | 0.5173 |
| **hybrid_rrf LLM (SYMMETRIC G3)** | **0.5438** | **0.7795** | **0.6334** |
| Δ rel vs asymmetric | +26% | +17% | +22% |

The symmetric extraction worked exactly as hypothesized — now both sides of the graph match use LLM-quality entities. kg_retrieval Hit@1 jumped 5x. hybrid_rrf LLM closed most of the gap to rule.

### Cascade integration (does NOT compose)

Three cascade modes tested, all worse than G1-only baseline:

| Config | Hit@1 | Hit@5 | MRR | PR-AUC inc | Novel prec | Novel rec |
|---|---:|---:|---:|---:|---:|---:|
| G1 cascade (baseline for G3) | 0.7221 | 0.9124 | 0.7937 | 0.8562 | 0.940 | 0.161 |
| G1 + G3 kg only | 0.7069 | 0.8671 | 0.7689 | 0.8231 | 0.919 | 0.168 |
| G1 + G3 hybrid_llm only | 0.6133 | 0.8308 | 0.7051 | 0.8444 | 0.911 | 0.182 |
| G1 + G3 kg + hybrid_llm | 0.7069 | 0.8671 | 0.7689 | 0.8222 | 0.868 | 0.272 |

Every G3 integration mode hurts Hit@5 by 5%+. The only metric that improves is novel recall — driven by score-scale shifts that make `max_ret_conf < 0.5` fire more often.

### Why doesn't G3 compose?

Two mechanisms identified:

1. **Overlap-rerank vote shifts.** L2 position 1 is picked by counting how many of `{hybrid_rrf rule, hybrid_rrf LLM, logseq2vec}` place each bi_encoder-top-3 candidate in their top-3. G3 hybrid_llm has different top-3 than asymmetric LLM hybrid → votes shift → position 1 changes on ~99% of windows. Some shifts are wins, some losses, but net negative.

2. **L4 stacker score-scale mismatch.** G3 has higher triage_scores than asymmetric LLM hybrid (because more confident retrieval). The L4 stacker retrains via 5-fold CV but still produces slightly different calibration. Plus the L3 free-novelty signal (`max_ret_conf < 0.5`) is using the NEW score distribution, which shifts more windows into the novel category at lower precision.

## 6. Advantages

1. **Confirmed the hypothesis.** Symmetric extraction does work — kg standalone lifted 5x at Hit@1.
2. **G3 artifacts are useful for downstream work.** The 1008 LLM window extractions live at `v2_kg_extractions_windows/` for any future graph-based experiments.
3. **Publishable negative result.** Supports the "cascade is at local optimum" claim from docs3/16 §12a — even when individual components improve massively, the cascade's RRF + overlap-rerank composition is fragile to score-distribution shifts.
4. **Novel recall lift available.** The G3 cascade configurations DO lift novel recall (0.161 → 0.272, +67% rel). If the paper prioritizes novelty over Hit@K, G3 has a niche use.

## 7. Disadvantages

1. **HURTS Hit@5 in all integration modes** by 5%+. Bound to the cascade's existing structure.
2. **HURTS Hit@1 modestly** when kg is integrated (-1.5pts to -10pts depending on config).
3. **HURTS novel precision** (-7.7% rel with full G3 config) because of the relaxed novelty trigger.
4. **High LLM cost** (133 min Qwen time + 33 min BiEncoder refit) for what amounts to a negative cascade result.
5. **Score-scale calibration** is a brittle pattern. Any new retriever added to the cascade would face the same composition issue.

## 8. Decision

**SKIP G3 from the final cascade headline.** G3 artifacts (window extractions + kg / hybrid predictions) are preserved at `v2g-final-models/g3-symmetric-llm-extraction/` for:
- Future researchers wanting to investigate score-scale recalibration of the cascade
- The novelty-recall-priority configuration (G3 lifts novel recall by 67% rel at cost of -5pts Hit@5)
- Standalone kg_retrieval / hybrid_rrf comparisons in the paper

Cascade going into G4 stays at **G1-only**.

The negative result is publishable and informative — it's one of the strongest single-pipeline lifts we've measured (kg Hit@1 +404% rel), yet the cascade structure can't absorb it. This says something interesting about composability of RRF cascades.

## 9. Open questions

- **Score-scale renormalization** — would per-pipeline z-score normalization before RRF fix the composition problem? Not tested.
- **L4 stacker without G3 features** — if we exclude hybrid_llm from L4_STACK_FEATURES when G3 is enabled, does it stop the regression? Not tested.
- **Could overlap-rerank skip G3 hybrid_llm in the vote pool** while still using it elsewhere? Quick test would clarify.
- **Per-family analysis** — does G3 help cart-redis (15 of 29 v2f failures)? Worth checking before final close-out.

## 10. Cross-references

- Code: `src/v2_advanced/proposal_d_knowledge_graph/extract_windows_cli.py` (new), pipelines extended with `window_extractions_subdir`.
- Output: `data/derived/global/.../v2g-final-models/g3-symmetric-llm-extraction/`
- Commits: `2c56b05` (infra), pending (negative cascade result + decision).

---

*Generated 2026-06-05 after G3 completion. Standalone wins, cascade integration fails.*

---

*Generated 2026-06-05 before G3 launch.*
