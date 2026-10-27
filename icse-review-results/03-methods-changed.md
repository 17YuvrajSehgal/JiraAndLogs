# Methods and protocols changed

What we now do differently, and why. These are the methodological commitments
the rewrite should describe.

---

## Triage evaluation on text-only corpora

**Was:** standard classifiers over the 94 `triage_feature_*` telemetry columns,
applied uniformly to all three datasets.

**Now:** on a text-only corpus the classifiers take the input the corpus
actually has. TF-IDF (200k features, 1–2 gram, min_df=3, sublinear) feeding
logistic regression, a linear SVM, and HGB over a 256-dim truncated-SVD
projection. Five seeds. Both binarizations reported (TW vs {borderline,noise} to
match the submission; TW vs noise as a robustness check).

**Why:** feeding zero-filled columns to a classifier produces a constant
predictor whose 0.500 says nothing. Any dataset-specific feature set must be
checked for degeneracy before its output is interpreted —
`wol_text_triage_panel.py` now prints that audit as its first output.

---

## Relevance validation

**Was:** LLM judge rates the *gold* match against a control sampled uniformly
from the full 38,642-item memory; report the gap.

**Now:** three conditions per query, each an independent single-blind call with
shuffled call order:
- the system's **actual top-1 retrieved** incident
- a **hard negative**: same project, outside the gold set, chosen as the most
  lexically similar such ticket
- the uniform control, retained only for comparability with the old number

Report per-condition mean and ≥4 fraction, the paired system-vs-hard comparison,
and both gaps.

**Why:** a uniform control from a 38k memory is an easy negative, so a large gap
shows the relation is non-random, not useful. And the operationally meaningful
object is what the system returns, not the gold. R1 and R2 both said this.

**Caveat to carry:** still a model judging. It gives the human study a
pre-registered quantity to validate against; it does not replace it.

---

## Uncertainty reporting

**Was:** paired bootstrap over test queries at a single training seed.

**Now:** five training seeds per system per dataset, and intervals that combine
both sources, `sqrt(sd_seed² + sd_sample²)`, wherever a *trained* component is
compared. For system-vs-system comparisons, the paired per-seed difference with
a t-interval (df=4), plus the range-separation statement, which is
distribution-free.

**Why:** the seed contributes ~28% of Hit@5 variance on Online Boutique and
~1% on OTel Demo. A query-only interval understates uncertainty on at least one
dataset, and it is what made the +0.065 margin look tighter than it is.

**Also established:** GPU fine-tuning does not reproduce at fixed seed across
environments. Seed 42 re-run with byte-identical config gave coarse Hit@5
0.8981 vs the published 0.9050 (strict 0.4805 vs 0.5229). The zero-shot
baselines *did* reproduce exactly, so the non-determinism is confined to the
trained component. R3 predicted this explicitly; the paper should state it as a
property of the setting rather than an accident.

---

## Cost accounting

**Was:** presented as measured wall-clock and token usage.

**Now:** counts are measured (invocations, gate skips, per-skill durations);
unit costs are modelled from a published table. Reported as an estimated
counterfactual, with a sensitivity check that recomputes using measured
durations as unit costs.

**Why:** the harness is predictions-backed, so its measured end-to-end time
(43 ms/window) is the cost of replaying a decision rather than making one.
Reporting that would overclaim far worse than the estimate does. The honest
defence is structural: every gated skill sits behind the same gate, so the
saving ≈ that gate's closure rate, nearly independent of unit costs.

---

## Gate definition and reporting

**Was:** `MAXCONF(R)` undefined; two gates described as one; thresholds
asserted.

**Now:** `maxconf` is its own numbered equation — max over retrievers of each
retriever's calibrated ticket-worthiness probability in [0,1] — with an explicit
note that it is *not* the fused RRF score (whose ceiling is ~0.049, which is why
R2 read the 0.5 comparison as meaningless). The escalation gate (numeric < 0.90
or no dense match) and the reformulation gate (maxconf < 0.5) are described
separately. A sensitivity table shows what other thresholds buy.

Observed `maxconf` range on WoL: 0.177–0.862, median 0.510, 74.3% ≥ 0.5. The
0.90 cheap-path gate **never fires** on a text-only corpus — intended
degraded-mode behaviour that the paper never stated.

---

## Artifact packaging

**Was:** bundler pinned to the v2 corpus (paper reports v3), hardcoded to a
Windows path, and would have shipped 117,153 files / 4.84 GB.

**Now:** v3, path-portable with `--dry-run`, and three exclusions:
- `.pool_cache` (2.8 GB) — *unsampled* source-corpus pools including buckets
  never drawn into the dataset. Shipping them would exceed the "derived subset"
  our Data Availability section says we redistribute: a licensing boundary, not
  just size.
- the two per-item KG caches — exactly redundant with the consolidated JSONLs
  (38,600 files vs 38,600 rows; 78,139 vs 78,140).
- `jira-memory-corpus.jsonl` — quarantined. Its `memory_text` embeds a literal
  `Components: X, Y` line, i.e. the field that *defines* the coarse relation.
  It is **not** what the retrievers index (the humanized corpus is), but
  shipping it unlabelled lets a reproducer index it by mistake.

Result: 54 files / 2.07 GB, with every reproduction-essential file verified
present.

---

## Pre-submission verification

**New.** `scripts/v2/verify_claims.py` maps each headline number to its source
file and JSON path and fails on mismatch. 19/19 passing, including an explicit
assertion that the zero-filled-feature count is 0 so that specific defect cannot
return silently. Five claims are traceable to a script but have no stored
artifact — listed in the script output; persisting their output would close the
gap.
