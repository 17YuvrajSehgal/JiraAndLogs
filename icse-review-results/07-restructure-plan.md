# Restructure plan — measurement paper, journal target

**Decided 2026-10-27:** contribution = measurement/benchmark-validity paper.
Target = journal (EMSE/TOSEM). ARISE is the instrument, not the claim.

**Thesis.** Incident-triage research is largely evaluated on alert
classification over injected faults. We show that target is saturated by
construction and does not transfer, that incident-memory retrieval does
transfer, and that several standard protocol choices materially change which
method appears to win. We release the datasets and a protocol that makes these
comparisons honest.

**Why this framing:** every finding we have becomes an asset. In the system
framing they read as hedges ("no tool is load-bearing", "fusion is harmful on
small corpora", "our own triage is at chance") — in the measurement framing
they are the results. It also answers Novelty=2 directly: the contribution is
no longer "we fused three retrievers".

---

## New structure

| § | Section | Source | Status |
|---|---|---|---|
| 1 | Introduction — the measurement problem | rewrite from `01-introduction.tex` | **new framing** |
| 2 | Background: how incident triage is evaluated today | `02-background` + `09-related` | merge |
| 3 | Study design: RQs, datasets, protocol | `05-setup` | reframe |
| 4 | **Datasets** (contribution 1) | `04-datasets` | promote, expand |
| 5 | ARISE as instrument | `03-approach` | **demote + compress** |
| 6 | F1: classification saturation is an artifact | `06-results` RQ4 | promote to finding |
| 7 | F2: retrieval transfers; rankings flip with scale | `06-results` RQ1 | promote to finding |
| 8 | F3: protocol choices change the answer | new, from seed/CI/determinism work | **new** |
| 9 | F4: what adaptive execution actually buys | `06-results` RQ3 + escalation | reframe |
| 10 | **Recommendations** (contribution 3) | new | **new** |
| 11 | Threats | `08-threats` | expand (journal length) |
| 12 | Conclusion | `10-conclusion` | rewrite |

---

## Research questions (replacing RQ1–RQ4)

- **RQ1** Does ticket-worthiness classification — the dominant benchmark target
  — transfer from injected faults to real incidents?
- **RQ2** Does incident-memory retrieval transfer, and do method rankings hold
  across corpora of different scale and realism?
- **RQ3** How sensitive are reported results to evaluation-protocol choices:
  training seed, relevance relation, cost model, feature construction?
- **RQ4** What does adaptive execution actually buy, and is it calibrated?

---

## Evidence map (every finding has a home)

| Finding | § | Key numbers | Source |
|---|---|---|---|
| Classification saturates on injected faults, weak on real text | 6 | ROC 1.00 → 0.57–0.70 | `01-headline-results` §3 |
| ...and the original 0.500 was a degenerate all-zero design matrix | 6 | 0 / 78,140 rows | `02-retractions` R1 |
| Our own end-to-end triage is also at chance, verified not an artifact | 6 | 0.506 vs 0.506 majority | `04-new-findings` F10 |
| Retrieval transfers; fusion significantly best on the real corpus | 7 | +0.055 Hit@5, 23/24 sig | `01-headline-results` §1–2 |
| Fusion is a **trade-off**: Hit@5 up, Hit@1 down | 7 | −0.041, CI excludes 0 | F1 |
| Method rankings **flip** with corpus scale | 7 | harmful on OB, decisive on WoL | `robustness/negative-results.md` |
| Relevance relation choice moves Hit@5 by 0.23 | 7 | 0.970 → 0.744 | §2 |
| Calibrate against random: 19× / 116× | 7 | 0.051 / 0.006 | `05-open-issues` |
| What the system returns ≫ the gold it is scored against | 7 | 39.0% vs 6.3% rated ≥4 | F6 |
| Single-seed intervals understate uncertainty | 8 | seed = 28% of variance (OB) | §5 |
| GPU fine-tuning irreproducible at fixed seed | 8 | 0.9050 → 0.8981, identical config | F3 |
| Fusion damps seed noise 5.4× | 8 | sd 0.0196 → 0.0036 | F2 |
| Zero-shot baselines reproduce exactly | 8 | 5/5 exact | §5 |
| Evidence tools are non-load-bearing | 9 | all Hit@5 effects 0.000 | F5 |
| Gates mis-calibrated 16× | 9 | 99.9% vs 6.2% needed | F4 |
| A learned policy does not beat the existing signal | 9 | ±0.0012, cancels | F4 |
| Cost saving tracks gate closure, not unit costs | 9 | 79.0% vs 77.9% | §6 |
| Metadata quality is load-bearing; 23.9% of queries dropped | 4 | 75.3% coverage | F8 |
| No leakage from the labelling rule | 7 | four checks | F9 |

---

## §10 Recommendations — the actionable half

A measurement paper is only useful if it tells people what to do instead.

1. **Report retrieval, not just classification**, on real corpora; classification
   saturation on injected faults certifies the dataset, not the method.
2. **Seed-matched comparison with seed-aware intervals** whenever a trained
   component is compared. Query-bootstrap alone understated our own uncertainty
   by ~2.6×.
3. **Report ≥2 relevance relations** when ground truth is inferred, plus a
   random-ranker reference so readers can calibrate.
4. **Audit features for degeneracy** before interpreting a classifier's output —
   our own 0.500 came from an all-zero design matrix with a CI of exactly
   [0.5000, 0.5000].
5. **Separate measured from modelled** in cost claims, and state which is which.
6. **Evaluate on >1 corpus scale** — our fusion conclusion reverses between a
   347-item and a 38,642-item memory.

---

## What gets cut or demoted

- "Capability-gated telemetry reasoning" as a contribution → §9 negative result
- Novelty detection as a validated capability → auxiliary, unvalidated
- Duplicate-page suppression as a headline → one paragraph (only meaningfully
  exercised on one corpus: 29.0% vs 5.3% / 0.9%)
- Algorithm 1 in full → compress; the controller is instrument, not contribution
- Any claim that telemetry evidence-gathering transfers to production (R1-Q2) →
  cut, pending real telemetry

---

## Execution order

1. §10 Recommendations + §3 RQs — these fix the paper's spine
2. §6/§7/§8 findings — mostly reorganising text that already exists
3. §1 Introduction — write last, once the findings are settled
4. §5 compress ARISE
5. §4 expand datasets
6. §11 threats, §12 conclusion
7. Re-run `verify_claims.py`; rebuild figures; build with pdflatex

**Not blocking:** the human study (§7 will cite the LLM judge and flag the study
as in progress), FLASH/COMET, artifact publication.
