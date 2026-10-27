# New findings — results the submission did not contain

Candidate material for the rewrite. Several of these are more interesting than
what the submission led with.

---

## F1. Fusion is a trade-off, not a win

Seed-matched over 5 seeds: fusion **gains** +0.055 coarse Hit@5 and +0.274
strict Hit@5, and **loses** 0.041 Hit@1 (CI [−0.069, −0.013], excludes zero).
MRR is a wash (+0.009, CI includes zero).

The submission reported hybrid Hit@1 0.839 vs bi-encoder 0.856 and moved past
it. With five seeds it is a significant deficit. Fusing complementary retrievers
widens the candidate set and blunts the top rank — a mechanism worth stating.

**Why it matters for framing:** which end of the trade-off you want depends on
the consumer. A human scanning five candidates wants Hit@5; an automated
handoff wants Hit@1. That is a more useful claim than "fusion is better".

---

## F2. Fusion damps training-seed noise (5.4×)

| System | WoL coarse Hit@5 sd (5 seeds) |
|---|---|
| Dense bi-encoder | 0.0196 |
| Hybrid fusion | **0.0036** |

Two of three fused retrievers (SPLADE, graph) are untrained, so the trained
component's variance is diluted. This was not measured before and is a
*robustness* argument for fusion independent of accuracy — and a partial answer
to R3's reproducibility complaint from inside the method.

---

## F3. Fixed seeds do not make GPU fine-tuning reproducible

Seed 42, byte-identical config (same data, hyperparameters, 23,320 fine-tune
pairs; only path separators and timings differ):

| | published | re-run |
|---|---|---|
| coarse Hit@5 | 0.9050 | 0.8981 |
| strict Hit@5 | 0.5229 | 0.4805 |
| fit seconds | 79,568 | 8,562 |

The zero-shot baselines reproduced **exactly** (all five, to the reported
precision), so the non-determinism is confined to the trained component, not
the harness or the data.

R3 predicted this verbatim: *"The authors use GPUs and multicore CPUs so there's
no guarantee of determinism."* Worth reporting as a methodological finding for
the field, not just a threat to our validity.

---

## F4. The escalation gates are mis-calibrated, not mis-ranked

`paper-results-v2/escalation/`

| Dataset | Escalation changes the top-5 | Shipped gates escalate | An oracle needs |
|---|---|---|---|
| Online Boutique | **0.0%** of windows | 20.9% | 0% |
| OTel Demo | **0.0%** of windows | 17.4% | 0% |
| World of Logs | 6.2% helped / 0.3% hurt | **99.9%** | **6.2%** (16× reducible) |

On both telemetry datasets the controller pays for escalation on ~a fifth of
windows and it *provably never changes the ranking*. On WoL escalation is worth
+0.059 Hit@5 overall, but 6.2% of windows need it, not 99.9%.

**And a learned policy does not fix it.** Leave-project-out, using only features
available before escalating: ROC-AUC 0.924 (test Kafka) and 0.690 (test
MariaDB), but versus simply ordering by the confidence the controller already
computes, +0.0012 and −0.0012 — they cancel. The defect is the *threshold*, not
the ranking signal.

Threshold sweep confirms it: 0.477 reaches full-escalation quality (0.963) at
75% escalation; 0.362 retains 0.935 at 25%. The shipped 0.5 sits on the
saturated plateau at 85.4%.

**Untested:** the score-margin feature (top-1 minus top-2) is now persisted by
the v2 baseline rerun — mean 0.068, median 0.038, max 0.74, so real spread. It
was absent when the policy was first tried and is the obvious next feature. The
oracle reaches 0.9685 at 8% escalation where neither method gets close, so
headroom exists.

---

## F5. Evidence-gathering tools are non-load-bearing

With paired-bootstrap CIs (`paper-results-v2/tool-ablation-ci/`):
- **every** tool's Hit@5 effect is identically 0.000 on all three datasets
- the only significant Hit@1 effect is the extended-trace reader being
  *harmful*, −0.018 (CI [−0.033,−0.006]), and only in isolation; alongside the
  peer lookup it is −0.003 (n.s.)
- the peer lookup's apparent benefit (+0.015) has a CI including zero

This supports the controller's value being in *not* running them — but it also
means the evidence-gathering contribution should be demoted to a negative
result.

---

## F6. What the system returns is much better than the gold it is scored against

Only **6.3%** of coarse-gold pairs are rated ≥4 by the judge, but **39.0%** of
the system's actual top-1 results are, and 94% are rated ≥3.

A gold match is an arbitrary member of a large relevant set (mean ~288–410
items; see `05-open-issues.md` for the discrepancy); the system returns the
member it ranks highest. This partly rescues the retrieval claim without
rehabilitating the permissive relation — and it suggests the *metric* understates
the system more than it flatters it.

---

## F7. The coarse relation is very permissive, quantified

| Relation | Mean relevant items/query | % of memory | Random-ranker Hit@5 |
|---|---|---|---|
| coarse | ~288 | 0.75% | 0.036 |
| strict | ~34.5 | 0.09% | 0.0044 |

So 0.970 is 27× random under the permissive relation; 0.744 is 169× random
under the strict one. Reporting these reference points lets a reader calibrate
without taking our word for it.

---

## F8. Component metadata is load-bearing and uneven

- 75.3% of all 78,140 issues carry ≥1 component (80.5% on the test split)
- **1,621 of 6,773 held-out ticket-worthy queries (23.9%) have none** and are
  therefore dropped — this is why retrieval reports n=5,150, a conditioning
  step the submission never disclosed
- vocabularies are project-local and uneven: Camel 205 distinct components,
  IMPALA 9
- they are not a clean taxonomy: release numbers (`10.3`, `2.2.1`) appear as
  components, so two issues can share a "component" by sharing a version

---

## F9. No leakage from the labelling rule into the retrievers

Four independent checks (R2's central objection):
1. the indexed (humanized) corpus contains **no** `Components:` field — 0 of
   3,000 sampled docs; only 34.6% of gold component names appear anywhere in
   indexed text, 15.9% query-side
2. the graph's LLM-extracted component vocabulary (1,559 terms) overlaps the
   gold vocabulary (1,101 terms) by **109 terms = 9.9%**
3. the graph retriever is the **worst** system under both relations
   (coarse 0.308, strict 0.036); ±graph is non-significant everywhere
4. decisive: the component *trained on* coarse gold — our bi-encoder — degrades
   **most** under the strict relation (0.905 → 0.523, below zero-shot BGE),
   while fusion holds (0.970 → 0.744)

---

## F10. Our own end-to-end triage is at chance on real data, and that is fine

Agent triage accuracy vs majority baseline: 0.841 / 0.784 (OB),
0.846 / 0.725 (OTel), **0.506 / 0.506** (WoL).

Verified not to be a scoring artifact: suppression-on and suppression-off
classify exactly the same 6,769 of 13,388 windows correctly. Stating this
plainly strengthens the reframing rather than undermining it — it is the same
evidence that retrieval, not alert classification, is the transferable target.
