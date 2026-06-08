# META-ANALYSIS — Cross-Phase Synthesis and Model-Change Recommendations

**Date:** 2026-06-06
**Scope:** All eight G-phases (G1–G8) on `master-final-models`.
**Question this answers:** Given everything we just learned, do we need to change the hybrid model?

---

## TL;DR

**No structural changes to the hybrid model are required to lock the headline.** The G1+G4+G7 cascade is the right configuration to publish.

**Three discretionary follow-ups exist** that could lift specific metrics if pursued — none are blocking, all carry asymmetric ROI:

1. **G3 score-scale renormalization** (untested) — could rescue the negative result and lift Hit@5 from 0.912 → ~0.94 if z-score-before-RRF fixes the composition problem. **Highest expected value, ~3 hours work.**
2. **Per-window-type novelty thresholds** (untested) — could close most of the G8 OOD recall gap (currently active_fault-dominated families lose 30–50 pts recall). **Medium value, ~1 hour work.**
3. **Free vs learned novelty redundancy audit** — the cascade currently OR's the agent signal, the `ret_conf < 0.5` free signal, AND the G7 learned signal. If learned subsumes free, we can drop free for simpler downstream reasoning. **Low value, ~30 minutes.**

**The model itself does not need to change to claim the headline. These are model-improvement options, not bug fixes.**

---

## 1. What worked

| Phase | Mechanism | Headline lift | Cost |
|---|---|---|---|
| **G1** | BiEncoder fine-tune w/ BM25 hard negs + random negs | Hit@1 +2.1% rel | 14 min GPU |
| **G4** | Agent Phase 3 — full 1008-window coverage | Novel recall +119% rel | 6 hours LLM |
| **G7** | LogReg over per-window features for L3 novelty | **Novel recall +388% rel** | <1 sec |

Two patterns inside the KEEPs:

- **G1 and G7 are nearly free.** Both are training-time interventions with negligible inference cost. They contribute the bulk of the lift.
- **G4's value is shrinking in light of G7.** G4 lifts novel recall +119% rel (0.163 → 0.356). G7 lifts the same metric +388% rel on top of G4 (0.356 → 0.793). The G7 features include `triage_score` and `tch_max_retrieval_conf`, both of which are partly correlated with agent eligibility. The question worth checking: **how much of G7's lift remains if we drop G4?** This is a publication-narrative question — if G7 alone delivers ~80% of the win, the paper can frame it as "learned-threshold beats LLM-agent at zero LLM cost." (See Follow-up #3.)

## 2. What didn't work — and why it's still publishable

| Phase | Intervention | Failure mode |
|---|---|---|
| **G2** | Cross-encoder as 5th retriever or reranker | Hurts Hit@1 by 4.5–5.4 pts in both modes |
| **G3** | Symmetric LLM extraction (kg + hybrid_llm) | Standalone Hit@1 +404% rel — cascade integration breaks (overlap-rerank vote shifts + L4 score-scale mismatch) |
| **G5** | LLM judge picking best top-1 | Confidence clusters at 0.85 (uninformative); every threshold hurts Hit@1 |

**The pattern is consistent across all three:** any single-component intervention that tries to OUTSCORE the cascade's existing L4 overlap-rerank loses to it. This is the strongest evidence so far that the cascade's multi-retriever consensus is at a non-trivial local optimum, not a coincidence.

This is the **publishable negative-result narrative**. Three independent reranker designs (cross-encoder w/ BCE, symmetric LLM-graph retrieval, LLM judge w/ strict JSON) underperform a 5-fold-CV LogReg stacker + RRF + overlap-rerank composition. Worth a section in the paper.

## 3. Robustness evidence

| Phase | Test | Result |
|---|---|---|
| **G6** | Hit@5 vs distractor ratio (simulated, 0%–50%) | −2% rel at 50% noise — graceful degradation |
| **G8** | LOFO novelty F1 vs in-distribution | −11.4% rel at threshold 0.30 — generalizes, but recall splits by family structure |

Both are publishable robustness claims with the caveats already documented in their respective docs.

## 4. Cross-cutting insights (what the eight phases together teach us)

### 4.1 The cascade is COMPOSITION-FRAGILE, not COMPONENT-FRAGILE

G3 is the cleanest demonstration: `kg_retrieval` standalone Hit@1 went from 0.078 → 0.396 (5×), `hybrid_rrf LLM` standalone Hit@5 went from 0.668 → 0.780. Both are massive component-level wins. **Yet adding either to the cascade hurt Hit@5 by 5%+.**

The reason is two specific composition mechanisms identified in `docs4/G3-symmetric-llm-extraction.md` §5:

1. **Overlap-rerank vote shifts.** L2 position 1 is determined by counting how many retrievers vote each bi_encoder top-3 candidate into their own top-3. Changing one retriever's top-3 shifts 99% of votes.
2. **L4 stacker score-scale mismatch.** The 5-fold-CV LogReg re-fits, but the underlying score distribution shift breaks the L3 free-novelty trigger (`max_ret_conf < 0.5`).

**Direct implication for the model:** the cascade has structural assumptions about score normalization that aren't currently exposed as hyperparameters. Z-score-normalizing each pipeline's triage scores before RRF/stacker would likely unblock future retrievers (including G3). This is **Follow-up #1** below.

### 4.2 Where the lift actually came from

| Source of lift | Phase | Contribution to headline |
|---|---|---|
| BiEncoder negatives | G1 | Hit@1 +2.1% rel |
| Agent coverage | G4 | Novel recall: 0.163 → 0.356 (+119% rel) |
| Learned threshold | G7 | Novel recall: 0.356 → 0.793 (+123% rel on top of G4) |
| **Total** | — | **Hit@1 +2.1% rel, Novel recall +388% rel** |

**Retrieval did not improve materially.** Hit@5 stayed at 0.9124 across the whole G-series — the v2f baseline was already at the cascade's local Hit@5 ceiling. **The story of master-final-models is that we found a +388% rel novelty-recall win where the original plan was looking for a retrieval win.**

This shifts the paper framing: the headline is no longer "TCH improves retrieval" (it doesn't, materially) but "TCH's L3 novelty channel was underexploited — a learned-threshold classifier lifts novel recall 4.9× at preserved precision while the cascade's retrieval channel was already optimal."

### 4.3 Three independent rerankers failing is a pattern, not a coincidence

| Reranker design | Outcome |
|---|---|
| Cross-encoder w/ BCE (G2) | Hit@1 −5.4 pts |
| Phase E agent rerank (pre-G-series) | net −5 wins |
| LLM judge w/ strict JSON (G5) | Hit@1 −2.7 to −13 pts |

Three different mechanisms, three negative results. The cascade's overlap-rerank is empirically dominant for top-1 selection on this dataset. The paper should explicitly claim this as a finding — it's worth a paragraph.

### 4.4 The G7 win is partially explained by the L3 channel being under-engineered, not by clever features

The G7 LogReg has 46 features (mostly one-hot family + window_type). The top coefficients are:
- `window_type=pre_fault_baseline` (+2.90) — pre-incident windows have no gold by construction
- `window_type=recovery_window` (−2.28) — post-incident windows have recent gold

These are **trivially recoverable from window metadata**. The fact that a 46-feature LogReg lifts recall 4.9× over a fixed `ret_conf < 0.5` heuristic suggests the previous L3 design was wasting easy signal. **This is a finding about the original cascade's blind spots, not about the cleverness of G7.**

Worth being honest about in the paper: G7 is not deep ML. It's exploiting structural metadata the original L3 ignored.

## 5. Open follow-ups (untested, ranked by expected value)

### Follow-up #1 — Score-scale renormalization for G3 (HIGHEST VALUE)

**What:** Add per-pipeline z-score normalization to triage scores before L2 RRF fusion and L4 stacking. Re-test G3 (symmetric LLM extraction) under this normalization.

**Why:** G3 had the largest standalone component lift of the entire G-series (kg Hit@1 +404% rel). If the cascade currently can't absorb it because of score-scale mismatch, fixing the normalization could finally close part of the 0.912 → 0.976 Hit@5 ceiling gap.

**Cost:** ~3 hours implementation + cascade rerun. Already have the G3 predictions; we just need to renormalize and re-fuse.

**Risk:** Normalization might break G1's existing lift via the same mechanism, or might require re-tuning the L3 free-novelty trigger threshold. Both are tractable.

**Verdict:** **Worth doing.** Either it rescues G3 (publishable retrieval win) or it confirms the cascade's score-scale assumption (publishable structural finding). Asymmetric upside.

### Follow-up #2 — Per-window-type novelty thresholds (MEDIUM VALUE)

**What:** Instead of a single G7 threshold for all windows, train a separate G7 threshold per `window_type` (active_fault, observation_window, pre_fault_baseline, recovery_window).

**Why:** G8 OOD analysis showed recall splits sharply by family structure — active_fault-dominated families lose 30–50 pts recall when held out. A lower threshold for active_fault windows would likely close most of that gap.

**Cost:** ~1 hour. Train 4 LogReg models on data subsets; emit per-window-type thresholds; modify `build_cascade.py` to look up the threshold based on `window_type`.

**Risk:** Overfits per window_type if some buckets are small. Mitigatable with shared regularization across heads.

**Verdict:** **Worth doing IF** publishing an OOD-robustness claim. Optional otherwise.

### Follow-up #3 — Free / learned / agent novelty redundancy audit (LOW VALUE)

**What:** Currently `is_novel = agent_novel OR (max_ret_conf < 0.5) OR (learned_p >= 0.5)`. Measure how often each disjunct fires alone vs together; if learned subsumes free, simplify the cascade.

**Why:** Cleaner published architecture. May also reveal that the learned signal alone matches the OR for less downstream complexity.

**Cost:** ~30 minutes. Compute pairwise agreement and per-disjunct contribution.

**Risk:** None.

**Verdict:** **Nice-to-have for paper clarity.** Won't change headline metrics.

### Follow-up #4 — G7 lift attribution (LOW VALUE)

**What:** Re-run G7 cascade with and without G4 (agent Phase 3). Measure how much of the +388% rel novel recall lift is from G7 alone vs G4+G7.

**Why:** Paper-narrative question. If G7 alone delivers most of the win, the cleaner story is "free learned-threshold beats expensive LLM-agent."

**Cost:** ~5 minutes (rerun cascade with TCH_EXTRA_AGENT_FILES unset).

**Risk:** None.

**Verdict:** **Should do before writing the paper.** Quick, informative, frames the headline.

### Untested ideas the docs flag but we should DROP

- G2 listwise loss / larger cross-encoder backbone — low ROI, already three rerankers failed
- G5 listwise LLM scoring — same pattern as above
- G1 `n_random_negs` sweep — marginal expected lift, not on critical path
- Real-Jira corpus, smaller LLM — explicitly out of scope per the original plan

## 6. Does the hybrid model need to change?

**For locking the headline: NO.** G1+G4+G7 at threshold 0.50 is the right final cascade. The metrics in `headline-final.json` are real and reproducible. The paper can be written from this configuration.

**For maximizing the paper's claims: MAYBE.** Follow-ups #1 (G3 score-scale fix) and #4 (G7 lift attribution) are high-information, low-cost experiments that would either lift the headline further or sharpen its framing. They're optional but recommended.

**For long-term system health: ONE small structural change worth considering** — expose score normalization as an explicit hyperparameter in `build_cascade.py`. Even if we don't change the default behavior now, this would let future retriever additions test their own normalization without recompiling the cascade.

## 7. Recommended action sequence

If pursuing the optional follow-ups:

1. **Follow-up #4 first (5 min).** Quick rerun of G7 cascade without G4 to attribute lift. Updates the paper narrative.
2. **Follow-up #3 (30 min).** Audit novelty-signal redundancy. Updates the architecture diagram.
3. **Follow-up #1 (3 hrs).** Score-scale renormalization + G3 retry. Highest upside.
4. **Follow-up #2 (1 hr).** Per-window-type thresholds. Optional, depends on whether paper claims OOD robustness as a primary contribution.

If NOT pursuing the follow-ups: **commit `b7557c4` is the publication artifact.** Start writing.

---

## 8. Bottom line

The G-series produced one massive win (G7, +388% rel novel recall), one solid win (G4, +119% rel novel recall), one small retrieval win (G1, +2.1% rel Hit@1), three publishable negative reranker results (G2, G3, G5), and two robustness validations (G6, G8). The hybrid model in its current G1+G4+G7 configuration is correct as-is — no required structural changes. Optional follow-ups exist with clear cost/benefit tradeoffs.

**Recommendation: lock the current cascade as the publication artifact, do Follow-up #4 (5 min) and #3 (30 min) before writing for narrative sharpness, and decide on Follow-up #1 based on whether the team wants one more attempt at a retrieval win.**

---

*Generated 2026-06-06 from cross-reading of all eight G-phase docs.*
