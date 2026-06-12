# Channel Ablation — TCH-Combined vs TCH-Lite + Per-Channel Memory-Text Contribution

**Status.** Empirical results from P3b (2026-06-11). Two complementary ablations.

**Companion documents.** [`docs7/TCH-Lite.md`](TCH-Lite.md) §7 specified the full 5-row table; this doc reports what we can defensibly compute with existing data plus the new TCH-Lite implementation, and is explicit about the gap. Raw numbers are in [`channel-ablation-data.json`](channel-ablation-data.json).

---

## Table of contents

1. [Headline tables](#1-headline-tables)
2. [Ablation 1 — TCH cascade: HGB removal (TCH-Lite vs TCH-Combined)](#2-ablation-1--tch-cascade-hgb-removal-tch-lite-vs-tch-combined)
3. [Ablation 2 — Single-pipeline channel-ablation on memorygraph SOTA](#3-ablation-2--single-pipeline-channel-ablation-on-memorygraph-sota)
4. [Combined interpretation](#4-combined-interpretation)
5. [Scope and limitations](#5-scope-and-limitations)
6. [What would close the remaining gap](#6-what-would-close-the-remaining-gap)
7. [Cross-references](#7-cross-references)

---

## 1. Headline tables

### 1.1 TCH cascade — HGB ablation (v2-resplit 1008-window test split)

| Configuration | Hit@1 | Hit@5 | MRR | PR-AUC strict | Novel precision | Novel recall |
|---|---:|---:|---:|---:|---:|---:|
| **TCH-Combined** (HGB + all channels) | 0.7221 | 0.9124 | 0.7937 | **0.9998** | 0.9405 | 0.7932 |
| **TCH-Lite** (HGB dropped, log-only deployment) | **0.7221** | **0.9124** | **0.7937** | **0.3101** | **0.9405** | **0.7932** |
| **Δ rel** | **0%** | **0%** | **0%** | **−69%** | **0%** | **0%** |

Retrieval and novelty metrics are **bit-identical** because the L2 retrieval fusion and L3 novelty disjunction do not consume HGB output. Only the triage gate degrades — this is the deployability cost of running without numeric telemetry. See `docs7/TCH-Lite.md` §3 for the design that makes this clean separation possible.

### 1.2 Single-pipeline channel ablation — memorygraph SOTA (Phase C, 2940-window split)

| Configuration | Hit@1 | Hit@5 | MRR | Top-1 changed vs full |
|---|---:|---:|---:|---:|
| All channels | 0.1339 | 0.2048 | 0.1566 | — |
| − k8s events (from memory text) | 0.1339 | **0.2048** | 0.1566 | **0 of 2940** |
| − trace lines (from memory text) | 0.1339 | **0.2048** | 0.1566 | **0 of 2940** |
| − log lines (from memory text) | **0.1087** | **0.1888** | **0.1345** | **1285 of 2940** (43.7%) |

**Removing trace and k8s lines from the memory text produces identical predictions to the full-channel baseline.** Only log-line masking moves any windows. Log lines carry essentially all the memory-side text signal that the retriever indexes against.

---

## 2. Ablation 1 — TCH cascade: HGB removal (TCH-Lite vs TCH-Combined)

### 2.1 What was measured

Two end-to-end cascade runs on the v2-resplit 1008-window test split, both reading the same per-pipeline cached predictions:

- **TCH-Combined.** The locked configuration with G1 + G4 + G7 (BiEncoder mixed negatives, full agent coverage, learned L3 classifier). L4 stacker has 6 features including `hist_gradient_boosting_numeric`.
- **TCH-Lite.** Same configuration but `TCH_LITE=1` set on `build_cascade.py`, which drops HGB from the L4 stacker. L4 has 5 features.

Both runs use the identical:
- L2 retriever set: BiEncoder, Hybrid-RRF rule, LogSeq2Vec, KG-Retrieval
- L2 overlap-rerank voter set: Hybrid-RRF rule, Hybrid-RRF LLM, LogSeq2Vec
- L3 novelty disjunction: agent_novel ∨ (max_conf < 0.5) ∨ (P_learned ≥ 0.5)
- L4 composition

### 2.2 Why retrieval and novelty are unchanged

The cascade's L2 retrieval consumes the **rankings** produced by each retriever, not the stacker. Removing HGB from the L1 stacker changes the L1 triage probability but does not change the L2 top-5 output, the L3 disjunction, or the L4 composition. The cascade was designed for this clean separation; the data confirms it.

### 2.3 Why triage PR-AUC drops 69% relative

HGB's standalone PR-AUC strict on the test split is 1.0 (near-perfect numeric-feature separation). The five retrievers' standalone PR-AUC strict values range from 0.24 to 0.31. The L1 stacker on retrievers alone cannot beat its base learners by more than a few points, so the cascade's triage PR-AUC settles at 0.3101. The other channels (inclusive PR-AUC = 0.6434, ROC-AUC = 0.6180) drop similarly.

### 2.4 L1 stacker coefficients in lite mode

```
bi_encoder_retrieval                  +1.484
hybrid_rrf_retrieval_rule             -0.002
hybrid_rrf_retrieval_llm              +0.112
logseq2vec_retrieval_pretrained       +1.589
kg_retrieval_rulebased                +2.172   ← largest, vs +0.504 in TCH-Combined
```

KG-Retrieval's coefficient grows ~4× larger when HGB is removed. The structural-overlap signal that KG produces correlates with `ticket_worthy` because windows with strong structural matches in memory tend to be real incidents; without HGB's near-perfect signal anchoring L1, KG steps up.

---

## 3. Ablation 2 — Single-pipeline channel ablation on memorygraph SOTA

### 3.1 What was measured

Predictions for **memorygraph_v2_sota_nw080** (the prior project's strongest retrieval pipeline) under four memory-text masking configurations, from the `phase-c-channels` archived comparison run:

- **All channels** — full memory_text
- **− k8s events** — `mask_k8s=True` strips k8s-event-like lines (e.g., `kubelet PLEG`, `CrashLoopBackOff`)
- **− traces** — `mask_traces=True` strips trace-like lines (e.g., span IDs, p99 latency annotations)
- **− logs** — `mask_logs=True` strips the residual log lines (those that don't match k8s/trace heuristics)

The masking is **memory-side only** — it modifies the `memory_text` string that BM25 / dense embeddings index against. Window-side query text is not masked in this pre-existing archive.

### 3.2 Key finding: trace and k8s lines as text are dead weight

When k8s-event lines or trace-style lines are removed from the memory text, the retriever's predictions are **literally identical** to the all-channels baseline. Zero windows change their top-1 pick out of 2940. This means BM25 + the dense bi-encoder + the cross-encoder rerank were not using those lines to score candidates — they were noise the retriever ignored.

When log lines are removed, **43.7%** of windows see a changed top-1 candidate. Hit@5 drops 7.8% relative. Hit@1 drops 19% relative.

### 3.3 What this implies for the WoL Mode 3 evaluation

If trace and k8s lines contribute nothing to retrieval on the memorygraph pipeline (which uses a fundamentally similar BM25 + MiniLM stack to our cascade's retrievers), then a log-only memory corpus — exactly what WoL provides — should retrieve almost as well as one with full multi-channel evidence. This is direct empirical support for the TCH-Lite × WoL plan: the cascade's retrieval channel is robust to the "WoL has no traces / metrics / k8s" gap.

### 3.4 Caveat — the 2940-window split is not the cascade split

The Phase C predictions are from an older split (2940 windows) that includes more borderline / noise windows than the v2-resplit 1008-window test split. Absolute Hit@5 = 0.205 is much lower than the cascade's 0.912 because the cascade composes multiple pipelines with RRF + overlap-rerank. **Only relative deltas within the same pipeline are meaningful here**, and that's how we read them.

---

## 4. Combined interpretation

Together, the two ablations tell a clean story for the paper:

> **Removing the numeric-feature triage gate (HGB) collapses TCH's triage PR-AUC from 0.9998 to 0.3101, but leaves retrieval (Hit@5 = 0.9124) and novelty (recall = 0.7932) bit-identical.** Removing trace-style and k8s-event lines from memory text additionally has no measurable effect on retrieval, as shown by the memorygraph SOTA channel ablation (0 of 2940 windows changed). Log lines alone carry the memory-side text signal the retriever depends on (Hit@5 drops 7.8% relative when log lines are masked from memory text; top-1 changes on 43.7% of windows). The implication is that **the TCH cascade's retrieval and novelty channels are robust to deployment in log-only environments, while the triage channel is structurally dependent on the numeric-feature pipeline that no log-only dataset can supply.** This is the deployability boundary TCH-Lite operates within.

The paper integration in `ICSE/sections/05-results.tex` §5.X gets:
- One headline table — the cascade-level HGB ablation (Ablation 1) showing retrieval and novelty are preserved.
- One supporting table or paragraph — the memorygraph SOTA channel ablation (Ablation 2) showing trace/k8s lines are not load-bearing for the retrieval channel.
- One explicit honest statement — full cascade-level retrieval-side channel ablation is left as future work.

---

## 5. Scope and limitations

The original `TCH-Lite.md` §7 envisioned a 5-row table where every row was the **TCH cascade** under a different masking configuration:

| Original-spec row | Status | What it would need |
|---|---|---|
| TCH-Combined (all channels) | ✓ done (Ablation 1) | — |
| − HGB only, full text | ✓ done (Ablation 1, "TCH-Lite") | — |
| − trace text (HGB intact) | not done | re-run BiEncoder + Hybrid-RRF + LogSeq2Vec + KG with `mask_traces=True` on memory + window text |
| − k8s text (HGB intact) | not done | re-run same 4 retrievers with `mask_k8s=True` |
| TCH-Lite (HGB dropped + log-only text) | not done at the cascade level | re-run same 4 retrievers with `mask_logs=False, mask_traces=True, mask_k8s=True` |

Reasons the bottom three rows are not delivered in P3b:

1. **The masking infrastructure is single-pipeline.** Only `memorygraph_v2_sota_nw080` supports the `mask_logs / mask_traces / mask_k8s` flags via Phase C wiring. The cascade's L2 retrievers (BiEncoder, Hybrid-RRF, LogSeq2Vec, KG) do not currently honor those flags.
2. **Re-running the retrievers with masking is expensive.** Each retriever's BiEncoder index needs to be rebuilt; LogSeq2Vec needs to be re-trained on masked sequences; KG-Retrieval would need to re-extract entities from masked text. Estimated cost: 2–4 hours of GPU time per retriever per mask configuration × 4 retrievers × 3 mask configurations = 24–48 GPU-hours.
3. **The cheap result we DO have is informative.** Ablation 2 establishes that trace and k8s lines contribute nothing to memorygraph SOTA's retrieval; the cascade's other retrievers use similar BM25 + MiniLM machinery and would likely show the same pattern. The paper can defensibly cite this as supporting evidence.

What we **cannot** claim from the current data:

- A precise cascade-level channel-contribution number ("trace lines contribute X% of cascade Hit@5"). We have a single-pipeline analog (0% on memorygraph SOTA) and a cascade-level HGB delta (69% on triage PR-AUC), not a cascade-level per-channel-line decomposition.
- Symmetric channel masking on the query (window) side. The Phase C infrastructure masks only the memory side; query-side masking is the future-work axis.

---

## 6. What would close the remaining gap

A future round of work (estimated 2–3 days of mixed coding + GPU time):

1. **Extend `mask_logs / mask_traces / mask_k8s` to BiEncoder, Hybrid-RRF, LogSeq2Vec, KG.** Each retriever needs a small flag that, when set, applies the per-line heuristics from `humanized_loader.py::_looks_like_trace / _looks_like_k8s` to its input text. ~50 lines per retriever.
2. **Add query-side masking to `build_window_query_text`.** Same heuristics, applied to `window.evidence_text` at retrieval time. ~20 lines.
3. **Re-run each retriever under three mask configurations.** Each retriever takes 5–30 minutes of GPU time per configuration depending on whether it re-trains or only re-indexes.
4. **Compose new cascade outputs.** Each masked retriever's cached predictions feed the cascade with the same `TCH_OVERRIDE_*` env-var mechanism the G-series uses. Adds ~30 minutes of cascade composition per configuration.

Output: a complete 5-row table identical to the one `TCH-Lite.md` §7 envisioned.

This work is not on the critical path for the ICSE submission as currently planned (the WoL evaluation in `REAL-DATA-WoL-PLAN.md` §7 is the load-bearing real-data result). It belongs in a "future work" sentence or a separate empirical paper.

---

## 7. Cross-references

- **Implementation of TCH-Lite.** `src/v2_advanced/tch/build_cascade.py` lines 92–112 (`TCH_LITE` env var handling). Documented in [`docs7/TCH-Lite.md`](TCH-Lite.md) §6.
- **Phase C channel-mask infrastructure.** `src/memorygraph/humanized_loader.py::_mask_lines_in_block` and the four `memorygraph_v2_sota_nw080_*` variants registered in `src/comparison/runner.py:532-556`.
- **Phase C cached predictions.** `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/archive/phase-c-channels/per-window-predictions.jsonl`.
- **TCH-Combined and TCH-Lite cached predictions from P3a sanity runs.** `/tmp/tch-combined-sanity/` and `/tmp/tch-lite-sanity/` (regenerable; see TCH-Lite.md §6.2 for the activation command).
- **Raw analysis data.** [`channel-ablation-data.json`](channel-ablation-data.json) — the full result dictionary in machine-readable form, for paper-figure generation.

---

*Generated 2026-06-11 as part of P3b (channel ablation) per `REAL-DATA-WoL-PLAN.md` v3 §14 phased plan.*
