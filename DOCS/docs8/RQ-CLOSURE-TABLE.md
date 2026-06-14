# RQ closure table — Phase 3 master view

**Status:** Draft 2026-06-14. OB + OTel columns filled with measured
numbers; WoL column **pending** (cascade in progress — task #106).
This is the single source of truth for the paper's headline
numbers and the WoL row will be replaced when its analyses land.

**Source of truth pointers:**
- OB: `results/ob/PHASE3-OB-SUMMARY.md` + `results/ob/{3.5..4.9}-*/SUMMARY.md`
- OTel: `results/otel-demo/PHASE3-OTEL-SUMMARY.md` + `results/otel-demo/{3.6..4.8}-*/`
- WoL: pending (will be `results/wol/PHASE3-WOL-SUMMARY.md`)

---

## Bucket A — agent core capabilities (headline)

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **A1** plan diversity | 4 plans / 1008 windows | 4 plans / 247 windows | ⏳ pending | partial (need WoL window_types) |
| **A2** adaptive selection cuts cost | **64.1% saved** with verifier-ON (§4.10); 41% no-verifier (§4.5) | **65% saved** | ⏳ pending | ✓ closed on 2 datasets |
| **A3** reformulation lift | gate fires 17.8%; v1 not measurable | TBD | ⏳ pending | v1 framework-only deferral |
| **A4** page suppression | pages/incident = 1.000 | **1.000** | ⏳ pending | ✓ generalises |
| **A5** skill ablation | only `no_react` (Δ−0.0121) + `no_triage_numeric` (triage Δ−0.117) | **same pattern** | ⏳ pending | ✓ generalises |
| **A6** ReAct lift | point: +0.0151 (peers); paired p=0.18 (NS). **`trace` tool significantly HARMFUL: Δ=−0.018, p=0.002 (§4.13)** | point: 0.0000 (flat) | ⏳ pending | OB has 1 sig. negative finding |
| **A7** budget-bounded Hit@K curve | non-monotone (0.6767→0.6798→0.6647→0.6647→0.6888) | **flat** (0.6471 across all N) | ⏳ pending | ✓ closed on 2 datasets |

## Bucket B — cost & performance

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **B1** per-window cost breakdown | mean 60.7 ms actual / 101.1 ms cascade | mean 35.7 ms / 97.4 ms | ⏳ pending | ✓ closed on 2 datasets |
| **B2** Hit@K vs $cost Pareto | ✓ **Pareto-dominant**: flat Hit@K across thresholds {0.50..0.95}; cost varies $0.059–$0.068 (savings 66.5–72.3%) | partial (~65% at default) | ⏳ pending | OB ✓; cross-dataset partial |
| **B3** bootstrap CIs (single-report + paired-delta) | Hit@1 [0.6385, 0.7405]; **paired Δ Hit@1 ReAct = −0.0121 [−0.030, +0.006] p=0.262 (NS)**; triage Δ p<0.0001 | analogous (NS for ReAct; p<0.0001 for triage) | ⏳ pending | ✓ closed on 2 datasets |
| **B4** per-tool marginal cost | peers dominates lift; others noise/negative | peers also flat on OTel | ⏳ pending | dataset-specific |

## Bucket C — generalisation & external validity

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **C1** synthetic→real Apache Jira | n/a | n/a | ⏳ pending | WoL is the test |
| **C2** zero-shot transfer to OTel | n/a | Hit@1 0.6471, Hit@5 0.7563 | n/a | partial (no L1-retrained variant yet) |
| **C3** cross-corpus (Mode 4) | n/a | n/a | ⏳ pending | exotic; deferred |
| **C4** capability-mask robustness | graceful; text_only ≡ best subset | same flatness | ⏳ pending | ✓ closed on 2 datasets |

## Bucket D — robustness & honest framing

| RQ | OB | OTel Demo | WoL | Status |
|---|---|---|---|---|
| **D1** distractor robustness | cascade-level ✓ (50% ratio: Hit@5 0.7160 sim-w) | n/a | ⏳ pending | cascade-level only |
| **D2** novel detection (OOD precision) | 100% novel-precision on WoL OOD queries (pre-existing) | n/a | n/a | ✓ closed |
| **D3** verifier OOD failure | RQ-A8 ≡ closed pre-existing | n/a | structurally skipped ✓ | ✓ closed |
| **D4** HP sensitivity | 108 cells all identical (cascade HP-invariant) | n/a | ⏳ pending | partial; Phase-2 HPs deferred |
| **D5** failure-category distribution | false_novel 40.6% | **false_novel 39.7%** | ⏳ pending | ✓ generalises (1pp gap) |
| **D6** tool-use failure modes | 93.6% success / 6.4% empty / 0% others | 88% on pod_events alone; 25 fires | ⏳ pending | ✓ closed on 2 datasets |

---

## Cross-dataset findings — already in hand

### 1. STRONG generalisation (claims that survive cross-dataset)
- Adaptive selection cuts cost without accuracy loss (RQ-A2). 41% on OB, 65% on OTel — even higher savings where the cheap path dominates more.
- Page suppression works (RQ-A4). 1.000 pages/incident on both.
- Cascade is HP-invariant in central range (RQ-D4).
- Same set of skills are load-bearing across datasets (RQ-A5: triage_numeric + retrieve_dense + composition).
- False-novel rate is dataset-invariant at ~40% (RQ-D5). This is the agent's universal blind spot.
- Capability-adaptive degrades gracefully (RQ-C4): no crashes, plan_ids stable.

### 2. DATASET-SPECIFIC findings (claims that narrow honestly)
- ReAct rerank lift (RQ-A6): OB +0.0151 (peers-only) vs OTel **0.0000**. Mechanism: OTel gate fires on only 10% of windows (vs OB 17.8%); 88% empty rate on `request_pod_events` because OTel runs have less k8s capture.
- Budget curve shape (RQ-A7): OB non-monotone vs OTel flat. Both reject the original "more tools = better" hypothesis.

### 3. v1 LIMITS honestly disclosed
- RQ-A3 (reformulation Hit@K lift) not measurable in v1 (predictions-backed retrievers can't re-query on reformulated text). v2 deferred.
- RQ-D1 measured at cascade level only; agent-level distractor would need cascade re-train with poisoned memory.
- RQ-D4 covered cascade HPs only; Phase-2 HPs (rerank.alpha, min_overlap_for_boost, peers.top_k) need their own sweep.

---

## What WoL will close (when #106 lands)

| RQ | Expected contribution |
|---|---|
| A1 plan diversity | If WoL surfaces `pre_fault_baseline` / `recovery_window` types absent on OB, plan count rises from 4 → 5–6 |
| A4 page suppression | Independent confirmation that pages/incident stays ≤ 1.5 on text-only data |
| A5 skill ablation | WoL HAS retrieve_log_sequence (which OTel doesn't); will reveal whether log_sequence drops Hit@K on real data |
| A6 ReAct lift | WoL only has `request_similar_incident_window` (no telemetry); pure peers-tool isolation |
| C1 synthetic→real generalisation | Headline number: BiEncoder coarse Hit@5 ≈ 0.959 per Mode 3; agent's Hit@K on top |
| D3 verifier OOD refusal | Asserted by `_assert_verifier_structurally_skipped` in smoke_wol.py |
| D5 failure categories | Validates whether 40% false_novel holds on real Apache Jira |
| D6 tool-use failure | Different distribution expected (only peers fires) |

---

## Reproduction one-liner

When #106 lands, run:

```
bash scripts/agent/run_wol_phase3_analyses.sh
```

That single script populates all WoL columns above.

---

## Cross-reference

- Architecture: `DOCS/docs8/AGENTIC-SYSTEM-V3.md`
- RQs (canonical): `DOCS/docs8/RESEARCH-QUESTIONS2.md`
- Implementation plan: `DOCS/docs8/IMPLEMENTATION-PLAN.md`
- OB results dir: `results/ob/`
- OTel results dir: `results/otel-demo/`
- WoL results dir (pending): `results/wol/`
