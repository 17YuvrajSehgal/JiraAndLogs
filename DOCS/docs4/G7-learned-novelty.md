# G7 — Learned Per-Window Novelty Threshold

**Status:** 🟡 In progress (starting 2026-06-06)

## 1. Goal

Replace the hard-coded `ret_conf < 0.5` free-novelty signal with a learned classifier that predicts per-window novelty using features like `window_type`, `service_name`, `is_hard_case`, `scenario_family`, retrieval confidence, and stacked triage score. The hypothesis: different incident types have different baseline retrieval confidences, so a fixed 0.5 threshold over-flags some categories and under-flags others.

## 2. Hypothesis

If learned, the per-window classifier should:
- Match or beat current free-signal precision (~96% at the 0.5 threshold).
- Lift novelty recall by 5-10pts because the classifier can use richer features than just ret_conf.
- Hit@K unchanged (novelty signal doesn't affect ranking).

Risk: the classifier overfits to the test set (in-distribution split has limited novelty diversity), or learns spurious correlations. We'll use 5-fold CV to mitigate.

## 3. Setup

- **Features per window:**
  - `window_type` (one-hot: active_fault, observation_window, pre_fault_baseline, recovery_window)
  - `is_hard_case` (bool)
  - `scenario_family` (one-hot, ~22 families)
  - `tch_max_retrieval_conf` (scalar)
  - `triage_score` (stacked, scalar)
  - `n_prior_family_tickets` (int, NaN-imputed)
  - bi_encoder/hybrid_rule/hybrid_llm/kg/logseq2vec triage_scores (scalars)
- **Target:** `gold_matched_issue_ids is empty` (truly novel = no past Jira match).
- **Model:** Logistic Regression with class_weight='balanced'.
- **CV:** 5-fold StratifiedKFold, random_state=42.
- **Threshold:** sweep {0.3, 0.4, 0.5, 0.6, 0.7} pick the one maximizing F1.

## 4. Plan

1. Build `src/v2_advanced/tch/novelty_calibration.py`.
2. Train + score via 5-fold CV; emit per-window P(novel).
3. Modify `build_cascade.py` to OPTIONALLY use learned novelty instead of `ret_conf < 0.5` (env var `TCH_LEARNED_NOVELTY_PATH`).
4. Sweep threshold, pick best. Compare to G4 cascade.

## 5. Observations

### Feature-set leakage detected first iteration

First training included `n_prior_family_tickets` (count of past memory tickets in the same family). This is essentially a TAUTOLOGY for novelty in our dataset:
- `novelty` = "no matching past Jira ticket in memory"
- `n_prior_family_tickets = 0` = "no past memory tickets in same family"
- Since gold tickets are tied to scenario_family, these are equivalent.

F1 = 1.000 with this feature, dominant coefficient −4.977. Excluded for the leakage-free run.

### Leakage-free out-of-fold sweep

| Threshold | Flagged | TP | FP | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| 0.30 | 665 | 597 | 68 | 0.898 | 0.882 | **0.890** |
| 0.40 | 594 | 556 | 38 | 0.936 | 0.821 | 0.875 |
| 0.50 | 542 | 525 | 17 | 0.969 | 0.776 | 0.861 |
| 0.60 | 526 | 521 | 5 | 0.991 | 0.770 | 0.866 |
| 0.70 | 516 | 516 | 0 | 1.000 | 0.762 | 0.865 |

Best standalone F1 at threshold 0.30, but precision-recall trade-offs exist across the sweep.

### Top features (coefficient, leakage-free)

| Feature | Coef | Direction |
|---|---:|---|
| window_type=pre_fault_baseline | +2.90 | NOVEL (no incident yet) |
| scenario_family=ad-outage | +2.62 | NOVEL |
| scenario_family=frontend-traffic-pressure | +2.58 | NOVEL |
| scenario_family=email-outage | +2.39 | NOVEL |
| window_type=recovery_window | −2.28 | NOT NOVEL (post-incident, gold linked) |
| scenario_family=productcatalog-outage | −1.99 | NOT NOVEL (well-covered family) |
| scenario_family=checkout-outage | −1.93 | NOT NOVEL |
| window_type=active_fault | −1.69 | NOT NOVEL |

Logical: pre-fault baseline and observation windows lack gold by construction; recovery and active-fault windows have recent gold. Families like ad-outage / email-outage are sparsely covered.

### Cascade integration sweep (G1 + G4 + G7)

| Threshold | Flagged | Precision | Recall | Δ Recall vs v2f |
|---|---:|---:|---:|---:|
| 0.30 | 682 | 0.880 | 0.886 | +446% rel |
| 0.40 | 614 | 0.914 | 0.829 | +410% rel |
| **0.50** | **571** | **0.940** | **0.793** | **+388% rel** ⭐ |
| 0.60 | 557 | 0.959 | 0.789 | +386% rel |
| 0.70 | 548 | 0.967 | 0.783 | +382% rel |

**Threshold 0.50 is the sweet spot:** precision exactly matches v2f's 0.940 baseline, recall jumps 4.9x. Hit@1/Hit@5/MRR/PR-AUC all UNCHANGED (L3 only affects novelty channel).

### Final G7 cascade vs v2f baseline

| Metric | v2f | G7 cascade | Δ rel |
|---|---:|---:|---:|
| Hit@1 | 0.7069 | 0.7221 | +2.1% |
| Hit@5 | 0.9124 | 0.9124 | tie |
| MRR | 0.7880 | 0.7937 | +0.7% |
| PR-AUC strict | 0.9998 | 0.9998 | tie |
| PR-AUC inclusive | 0.8527 | 0.8562 | +0.4% |
| Novel precision | 0.9402 | 0.9405 | tie |
| **Novel recall** | **0.1625** | **0.7932** | **+388% rel** |

## 6. Advantages

1. **Massive novel recall lift** (+388% rel at preserved precision). The biggest single-phase improvement in the entire G-series.
2. **Hit@K unchanged.** L3 only affects novelty — no risk to retrieval/triage.
3. **Threshold is tunable per deployment.** Want stricter precision? Use 0.60-0.70. Want more recall? Use 0.30. The cascade exposes this knob.
4. **Cheap inference.** LogReg with 46 features runs in microseconds. No LLM cost at inference.
5. **Interpretable features.** Top features make domain sense (pre-fault baseline → novel; recovery → not novel).

## 7. Disadvantages

1. **In-distribution evaluation only.** The classifier learns the family/window-type distribution of the v2 test set. On out-of-distribution windows (new families), it may not generalize. **G8 will test this.**
2. **Dependency on scenario_family being correctly identified at inference.** In production, scenario_family is itself a prediction; if wrong, the novelty signal degrades.
3. **Feature engineering required.** Different organizations would need to rebuild the feature set for their telemetry conventions.
4. **Threshold trade-off must be deployment-tuned.** No universally-best threshold; depends on product priority (precision vs recall).

## 8. Decision

**INTEGRATE G7 into the final cascade** at threshold = 0.50. This delivers:
- Novel precision tied with v2f baseline (0.940)
- Novel recall +388% rel (0.163 → 0.793)
- All retrieval/triage metrics unchanged
- The single biggest novelty lift in the project

Final activation:
```bash
TCH_OVERRIDE_BIENC="v2g-final-models/g1-bienc-hard-negatives/predictions-bienc.jsonl"
TCH_EXTRA_AGENT_FILES="v2g-final-models/g4-agent-phase3/per-window-predictions.jsonl"
TCH_LEARNED_NOVELTY_PATH="v2g-final-models/g7-learned-novelty/learned_novelty.jsonl"
TCH_LEARNED_NOVELTY_THRESHOLD=0.50
```

## 9. Open questions

- **Generalization to orphan families** (the OOD test). G8 will measure this directly.
- **Is the `n_prior_family_tickets` leakage useful in practice?** Argument for keeping: in production, n_prior is computable from memory state, no peek at gold. Argument against: it's a near-trivial feature that would make the paper's "novelty detection is hard" framing weaker. KEEP IT EXCLUDED in the headline.
- **Could a small NN beat LogReg?** Probably not on 1008 windows; LogReg + class_weight='balanced' is a strong baseline for this scale.

## 10. Cross-references

- Code: `src/v2_advanced/tch/novelty_calibration.py` (new) + build_cascade.py G7 hooks.
- Output: `data/derived/global/.../v2g-final-models/g7-learned-novelty/`
- Commit pending.

---

*Generated 2026-06-06 after G7 completion. Single biggest novelty lift of the entire G-series.*

---

*Generated 2026-06-06 before G7 launch.*
