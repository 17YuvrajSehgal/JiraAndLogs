# Retractions — text that must not survive into the new draft

Each entry: what the submission said, why it was wrong, what replaces it.

---

## R1. "Triage classification collapses to chance on real incidents"

**Where:** abstract, introduction, §VII-D, §VIII (threats), conclusion.

**Why wrong:** the WoL classifiers were fitted on the 94 `triage_feature_*`
columns, which `build_wol_real_corpus_v3.py` zero-fills unconditionally for a
text-only corpus. **0 of 78,140 rows has a non-zero feature.** The reported
ROC-AUC 0.500 was a constant predictor forced by an all-zero design matrix, not
a measurement of learnability. Our own artifact printed the bootstrap CI as
exactly [0.5000, 0.5000], which should have caught it.

**Replacement:** real-incident triage from text reaches ROC-AUC 0.57–0.70
(binarization-dependent), CI excluding 0.500 — weakly learnable, far below the
1.00 of injected telemetry, and not beating majority at the operating
threshold. The qualitative reframing survives; the word "chance" does not.

**Severity:** this is the rejection-grade defect. A reviewer who re-ran the
pipeline would have found it.

---

## R2. "Pages per incident = 1.0"

**Where:** Table III, §VII-B.

**Why wrong:** tautological. `n_incidents == n_pages_emitted` by construction in
the harness (7,505 == 7,505 on WoL), so the ratio is 1.0 regardless of
behaviour. It carries no information.

**Replacement:** share of would-be pages suppressed — **5.3% / 0.9% / 29.0%**
(OB / OTel / WoL). Note honestly that OTel fires the mechanism once in 106
pages, so suppression is only meaningfully exercised on the real corpus.

---

## R3. Cost described as "measured"

**Where:** §VI-C ("measured per window as wall-clock time and language-model
token usage"), Table III caption.

**Why wrong:** it is counts × a hardcoded per-skill cost table.

**Replacement:** describe as an estimated counterfactual, publish the cost
table, and give the robustness argument (measured-unit recomputation differs by
1.1 points because the saving tracks gate-closure rate). See
`01-headline-results.md` §6.

---

## R4. "The peer-incident lookup is the only clearly beneficial tool"

**Where:** Figure 4 caption.

**Why wrong:** with paired-bootstrap CIs, +0.015 with CI [−0.006, +0.033] —
includes zero.

**Replacement:** no evidence tool has a demonstrable benefit. The only
significant effect is the extended-trace reader being *harmful* (−0.018,
CI [−0.033,−0.006]) and only in isolation; added alongside the peer lookup it
is −0.003 (n.s.). On OTel and WoL every tool effect is identically 0.000.

---

## R5. "+0.065 Hit@5 for fusion, 95% CI [+0.058, +0.073]"

**Where:** §VII-A, abstract framing.

**Why wrong:** one hybrid run vs one bi-encoder run, with a query-bootstrap CI
that ignored training-seed variance. The bi-encoder draw used (0.9050) sits near
the **low end** of its 0.898–0.946 seed range; seed sd (0.0196) is ~2.6× the
quoted CI half-width.

**Replacement:** seed-matched **+0.0553, 95% CI [+0.0353, +0.0752]**, plus the
stronger non-overlap statement and the Hit@1 trade-off. See
`01-headline-results.md` §1.

---

## R6. Claim drafted but never published — record it anyway

"The controller emits a third `borderline` decision on 3,061 windows that the
binary gold can never score correct, so ARISE's 0.506 triage accuracy is partly
self-inflicted."

**Why wrong:** `harness.py::_score` computes `effective_triage`, mapping
suppressed windows back to `ticket_worthy` before comparing, specifically so a
paging action is not charged as a triage error. Proof: suppression-OFF (0
borderline) and suppression-ON (3,061 borderline) classify **exactly the same
6,769 of 13,388** windows correctly. Had the bug been real the number would read
0.399, not 0.506.

**Why it matters:** this claim came from a rebuttal draft and was propagated
into the paper without checking the scoring path — the same failure mode as R1.
It was caught, but only because someone looked. Recorded here as the reason
`scripts/v2/verify_claims.py` exists.

---

## Also soften / re-scope

| Claim | Problem | Action |
|---|---|---|
| "97% Hit@5" unqualified | inferred relation, not usefulness | always label "under an inferred project–component relation"; co-headline the strict 0.744 |
| capability-gated **telemetry** reasoning transfers | telemetry is synthetic, real data is text-only (R1-Q2) | fix with real telemetry, or cut the claim — narrowing was not enough |
| on-demand evidence-gathering as a contribution | our own data shows no tool helps | demote to a reported negative result |
| novelty detection as a validated capability | confounded with retrieval uncertainty on text-only corpora | report as auxiliary, unvalidated on real data |
| "the saving grows with scale" | it tracks gate-closure rate, not scale | restate mechanically |
| synthetic-vs-real as a *transfer* experiment | task AND input both change (R2) | present as a contrast between two operationalizations |
