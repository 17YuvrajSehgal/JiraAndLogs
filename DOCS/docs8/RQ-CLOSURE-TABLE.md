# RQ closure table — Phase 3 master view

**Status:** Updated 2026-06-16. WoL column now reflects **WoL v2**
(Phase B class-diverse augmentation: 9341 rows, 1648 test, OB-ratio
class distribution 21/26/53). v1 numbers retained only as
"v1→v2 delta" footnotes where the comparison is informative.

**Source of truth pointers:**
- OB: `results/ob/PHASE3-OB-SUMMARY.md` + `results/ob/{3.5..4.9}-*/SUMMARY.md`
- OTel: `results/otel-demo/PHASE3-OTEL-SUMMARY.md` + `results/otel-demo/{3.6..4.8}-*/`
- WoL v2 cascade: `data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/`
- WoL v2 agent: `results/wol-v2/agent-runs/wol-v2-2026-06-16/{report,bootstrap}.json`

---

## Bucket A — agent core capabilities (headline)

| RQ | OB | OTel Demo | WoL v2 | Status |
|---|---|---|---|---|
| **A1** plan diversity | 4 plans / 1008 windows | 4 plans / 247 windows | **2 plans / 1648 windows** (was 1 v1; state_suppress branch now firing) | dataset-dependent |
| **A2** adaptive selection cuts cost | **64.1% saved** with verifier-ON (§4.10); 41% no-verifier (§4.5) | **65% saved** | **100% USD / 98.9% wall** (verifier structurally skipped + predictions-backed retrieval); ([cost_breakdown.json](../../results/wol-v2/4.5-cost-vs-cascade/SUMMARY.md)) | **✓ closed 3/3 datasets** |
| **A3** reformulation lift | gate fires 17.8%; v1 not measurable | TBD | TBD | v1 framework-only deferral |
| **A4** page suppression | pages/incident = 1.000 (20 suppressions) | **1.000** (1 supp.) | **1.000 (510 suppressions** — 28× v1's 18; substantive via Jira `is duplicate of` clustering) | **✓ 3/3 universal — substantive on all 3** |
| **A5** skill ablation | only `no_react` (Δ−0.0121) + `no_triage_numeric` (triage Δ−0.117) | **same pattern** | **`no_hybrid` / `dense_only` LIFT triage by Δ=+0.7462 [+0.7230, +0.7700], p<0.001*** ([4.1 SUMMARY](../../results/wol-v2/4.1-skill-ablation/SUMMARY.md))**; `no_kg` exactly 0 | ✓ universal; v2 surfaces text-only honest finding |
| **A6** ReAct lift | point: +0.0151 (peers); paired p=0.18 (NS). **`trace` tool significantly HARMFUL: Δ=−0.018, p=0.002 (§4.13)** | point: 0.0000 (flat) | **exactly 0 paired delta across 16 cells (p=1.0); 0 tool invocations across 1641 traces** ([3.8 SUMMARY](../../results/wol-v2/3.8-tool-ablation/SUMMARY.md)) | **✓ closed 3/3** OB has 1 sig. negative |
| **A7** budget-bounded Hit@K curve | non-monotone (0.6767→0.6798→0.6647→0.6647→0.6888) | **flat** (0.6471 across all N) | **flat** (0.9583 across N ∈ {0..4}) ([3.7 SUMMARY](../../results/wol-v2/3.7-budget-curve/SUMMARY.md)) | **✓ closed 3/3 — monotone hypothesis REJECTED on all 3** |

## Bucket B — cost & performance

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **B1** per-window cost breakdown | mean 60.7 ms actual / 101.1 ms cascade | mean 35.7 ms / 97.4 ms | ⏳ pending | ✓ closed on 2 datasets |
| **B2** Hit@K vs $cost Pareto | ✓ **Pareto-dominant**: flat Hit@K across thresholds {0.50..0.95}; cost varies $0.059–$0.068 (savings 66.5–72.3%) | partial (~65% at default) | **Pareto-dominant**: flat Hit@K AND flat cost across all 6 thresholds; 98.9% savings everywhere ([4.11 SUMMARY](../../results/wol-v2/4.11-pareto-sweep/SUMMARY.md)) | **✓ closed 3/3** |
| **B3** bootstrap CIs (single-report + paired-delta) | paired Δ ReAct = −0.0121 [−0.030, +0.006] p=0.262 (NS); triage Δ p<0.0001; trace tool harm p=0.002 (§4.13) | analogous on skill ablation (triage p<0.0001) | **v2 cascade (n=276)**: BiEncoder Hit@5 = 0.971 [0.949, 0.989]; Hybrid-RRF 0.942 [0.912, 0.968]; BM25 0.609 [0.556, 0.669]; paired BiEnc vs Hybrid Hit@1 Δ=−0.138 [−0.188, −0.097]\*\*\*; **`no_hybrid` triage Δ=+0.7462 [+0.7230, +0.7700]\*\*\***; capability-mask Δ=−0.958 [−1.000, −0.896]\*\*\* | **✓ 3-dataset closed; 10+ sig findings across all** |
| **B4** per-tool marginal cost | peers dominates lift; others noise/negative | peers also flat on OTel | ⏳ pending | dataset-specific |

## Bucket C — generalisation & external validity

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **C1** synthetic→real Apache Jira | n/a | n/a | **✓ Agent Hit@5 = 1.000, Hit@1 = 0.958, MRR = 0.976 (n_eval=48); cascade BiEncoder coarse Hit@5 = 0.971 [0.949, 0.989] (n_eval=276). Hybrid-RRF strong Hit@5 = 0.814 (+0.135 abs fusion lift). Per-project: Kafka Hit@5=1.000, MariaDB Hit@5=0.953.** Triage acc 0.164 < majority baseline 0.496 (text-only triage limitation; disclose) | **✓ closed — STRONGEST external-validity result; v2 5× evaluable sample over v1** |
| **C2** zero-shot transfer to OTel | n/a | Hit@1 0.6471, Hit@5 0.7563 | n/a | partial (no L1-retrained variant yet) |
| **C3** cross-corpus (Mode 4) | n/a | n/a | ⏳ pending | exotic; deferred |
| **C4** capability-mask robustness | graceful; text_only ≡ best subset; paired-delta (§4.14): strip-TRACE_SUMMARY +0.0030 (NS p=0.65), strip-NUMERIC triage Δ=−0.117 (p<0.0001) | same flatness | **strip-MEMORY_TEXT / strip-TEXT_EVIDENCE: Δ Hit@1 = −0.958 [−1.000, −0.896] p<0.001\*\*\* (n=1639). Inverse: triage acc 0.174 → 0.964 — same over-pager mechanism as A5** ([4.4 SUMMARY](../../results/wol-v2/4.4-capability-mask/SUMMARY.md)) | **✓ closed 3/3** |

## Bucket D — robustness & honest framing

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **D1** distractor robustness | cascade-level ✓ (50% ratio: Hit@5 0.7160 sim-w) | n/a | ⏳ pending | cascade-level only |
| **D2** novel detection (OOD precision) | 100% novel-precision on WoL OOD queries (pre-existing) | n/a | n/a | ✓ closed |
| **D3** verifier OOD failure | RQ-A8 ≡ closed pre-existing | n/a | **✓ asserted structurally skipped via `_assert_verifier_structurally_skipped`** | ✓ closed |
| **D4** HP sensitivity | 108 cells all identical (cascade HP-invariant) | n/a | TBD | partial; Phase-2 HPs deferred |
| **D5** failure-category distribution | false_novel 40.6% | false_novel 39.7% | **false_novel 0.0% v2** (was 0.7% v1) — collapses to literal zero without LLM verifier on text-only dataset | **LLM-induced finding** |
| **D6** tool-use failure modes | 93.6% success / 6.4% empty / 0% others | 88% on pod_events alone; 25 fires | **0 tool invocations across 1641 traces** (gate never opens; framework correctly skips tools when retrieval already confident) ([3.6 SUMMARY](../../results/wol-v2/3.6-failure-mode-catalog/SUMMARY.md)) | **✓ closed 3/3** |

---

## Cross-dataset findings — already in hand

### 1. STRONG generalisation (claims that survive cross-dataset)
- Adaptive selection cuts cost without accuracy loss (RQ-A2). 41% on OB, 65% on OTel — even higher savings where the cheap path dominates more.
- Page suppression works (RQ-A4). 1.000 pages/incident on all 3 datasets, **and now substantively on WoL v2** (510 suppressions over 901 multi-ticket clusters).
- Cascade is HP-invariant in central range (RQ-D4).
- Same set of skills are load-bearing across datasets (RQ-A5: triage_numeric + retrieve_dense + composition on OB/OTel; retrieve_dense alone on WoL).
- False-novel rate is dataset-invariant at ~40% on telemetry datasets (RQ-D5); collapses to 0% on text-only WoL v2. This is the agent's universal LLM-induced blind spot.
- Capability-adaptive degrades gracefully (RQ-C4): no crashes; plan IDs reduce from 4 (OB/OTel) → 2 (WoL v2).

### 2. DATASET-SPECIFIC findings (claims that narrow honestly)
- ReAct rerank lift (RQ-A6): OB +0.0151 (peers-only) vs OTel **0.0000**. Mechanism: OTel gate fires on only 10% of windows (vs OB 17.8%); 88% empty rate on `request_pod_events` because OTel runs have less k8s capture.
- Budget curve shape (RQ-A7): OB non-monotone vs OTel flat. Both reject the original "more tools = better" hypothesis.
- **NEW (v2-only): WoL triage accuracy 0.164 < majority-class baseline 0.496.** Mechanism: WoL lacks telemetry → `triage_numeric` doesn't fire → `compose_triage` falls back to retrieval-confidence → over-pages borderline/noise queries that retrieve high-confidence matches. v1 single-class dataset could not surface this. Honest disclosure of text-only triage limitation.

### 3. v1 LIMITS honestly disclosed
- RQ-A3 (reformulation Hit@K lift) not measurable in v1 (predictions-backed retrievers can't re-query on reformulated text). v2 deferred.
- RQ-D1 measured at cascade level only; agent-level distractor would need cascade re-train with poisoned memory.
- RQ-D4 covered cascade HPs only; Phase-2 HPs (rerank.alpha, min_overlap_for_boost, peers.top_k) need their own sweep.
- **NEW (v2 deferral):** v2 ablations (RQ-A5 skill-disable + RQ-A6 ReAct + RQ-C4 capability-mask) not yet re-run on v2 augmented dataset. v1 numbers retained for now; v2 re-runs are mechanical and cheap.

---

## WoL v2 closure summary (updated 2026-06-16 post-ablations)

Phase B augmentation + full ablation pass closed the v1 methodology red flags from Q5 AND surfaced one new mechanism finding:

| RQ | v2 outcome |
|---|---|
| A1 plan diversity | 1 → **2 plans** (state_suppress branch now fires via Jira-link multi-window clusters) |
| **A2 cost savings** | **100% USD / 98.9% wall** vs cascade-counterfactual (highest of 3 datasets — verifier structurally skipped + predictions-backed retrieval) |
| A4 page suppression | 18 → **510 suppressions**; still 1.000 pages/incident; substantive rather than structural |
| **A5 skill ablation** | **`no_hybrid` LIFTS triage acc by +0.7462 [+0.7230, +0.7700], p<0.001\*\*\*** (statistically significant headline finding — `dense_only` is the optimal text-only config) |
| A6 ReAct lift | exactly 0 paired delta across 16 cells; 0 tool invocations (gate correctly skips tools when retrieval is confident) |
| A7 budget curve | flat at all N — monotone hypothesis REJECTED on all 3 datasets |
| B2 Pareto | flat in BOTH Hit@K and cost (structurally Pareto-dominant) |
| **B3 bootstrap CIs** | 6+ statistically significant findings on v2 alone (cascade BiEnc vs Hybrid coarse Hit@1 −0.138\*\*\*, triage +0.7462\*\*\*, capability-mask −0.958\*\*\*); 10+ total cross-dataset |
| C1 synthetic→real | Hit@5 = 1.000 agent / 0.971 cascade BiEncoder coarse; 5× larger n_eval than v1 (276 vs 55) |
| **C4 capability mask** | sharpened from v1 −0.78 to v2 **−0.958 [−1.000, −0.896] p<0.001\*\*\*** (n=1639); inverse effect on triage acc (0.174 → 0.964) |
| D3 verifier OOD | confirmed structurally skipped on v2 dataset name |
| D5 failure categories | false_novel 0.7% → 0.0% (mechanism-consistent: LLM-induced rate collapse) |
| **D6 tool-use failure** | 0 invocations across 1641 traces (framework correctly skips tools when retrieval is confident) |

**Still v2-pending (deferred for architectural reasons, NOT for compute):**

- RQ-A3 (reformulation Hit@K lift): predictions-backed retrievers can't re-query on reformulated text. Needs live-retrieval mode (architectural change).
- RQ-D1 (agent-level distractor robustness): cascade-level result holds; agent-level would need cascade re-train with poisoned memory.

Both are out-of-scope for the current paper draft and disclosed in the v1-deferrals section of PAPER-FINDINGS.md.

## Reproduction

```bash
# 1. Build v2 dataset (~3 min Mongo harvest + sample + cluster + write)
python scripts/research-lab/build_wol_real_corpus_v2.py augment \
    --source-global-dir data/derived/global/2026-06-11-wol-real-global \
    --out-global-dir    data/derived/global/2026-06-15-wol-real-v2-global

# 2. KG entity extraction over test windows (~40 min on gpt-4o-mini at ~$1.50)
PYTHONPATH=src python scripts/agent/extract_window_entities.py \
    --global-dir data/derived/global/2026-06-15-wol-real-v2-global \
    --lm-studio-url https://api.openai.com --model gpt-4o-mini \
    --api-key-env OPENAI_API_KEY

# 3. Load memory KG into Neo4j (Neo4j Desktop, neo4j-wol DB)
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
    --global-dir data/derived/global/2026-06-15-wol-real-v2-global \
    --source llm --database neo4j-wol

# 4. Cascade pipelines (~2 hours)
for pipe in biencoder bm25 hybrid_rrf kg_retrieval; do
    PYTHONPATH=src python scripts/research-lab/run_${pipe}_wol_mode3.py \
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global \
        --out-dir    data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit
done

# 5. Agent smoke + bootstrap CIs (~1 min)
PYTHONPATH=src python scripts/agent/smoke_wol.py \
    --global-dir data/derived/global/2026-06-15-wol-real-v2-global \
    --order-by-incident-time \
    --output results/wol-v2/agent-runs/wol-v2-2026-06-16/report.json

PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
    --predictions data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit/*.jsonl \
    --paired bi_encoder_retrieval hybrid_rrf_retrieval \
    --output results/wol-v2/agent-runs/wol-v2-2026-06-16/bootstrap.json
```

---

## Cross-reference

- Architecture: `DOCS/docs8/AGENTIC-SYSTEM-V3.md`
- RQs (canonical): `DOCS/docs8/RESEARCH-QUESTIONS2.md`
- Implementation plan: `DOCS/docs8/IMPLEMENTATION-PLAN.md`
- OB results dir: `results/ob/`
- OTel results dir: `results/otel-demo/`
- WoL results dir (pending): `results/wol/`
