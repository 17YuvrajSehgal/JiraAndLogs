# Threats to Validity (draft for the paper)

*Honest scoping of claims. Drafted 2026-06-28; paste/adapt into the manuscript.*

## Construct validity
- **Gold relevance labels.** Window↔ticket gold is derived, not human-adjudicated.
  We mitigate with an **LLM-as-judge** validation (Qwen2.5-7B): on a seeded sample
  per dataset, the judge rates the gold ticket vs a random control; we report the
  gold/random mean-score gap and agreement (see `paper-results/gold-validation/`).
  This is a stopgap, **not** a multi-annotator human study; we ship a
  human-annotation kit for a later Cohen's/Fleiss' κ. *Threat:* the judge shares
  failure modes with LLM components elsewhere; the random-control gap partially
  guards against trivial "everything-relevant" bias.
- **Retrieval metrics.** Hit@K/MRR are computed only over windows with non-empty
  gold; triage metrics over all windows. Coarse and strong-relation gold are
  reported separately where available (strong gold exists for WoL only).

## Internal validity
- **Temporal leakage.** All retrievers enforce time-ordered visibility
  (`visible_to(window)`); a pre-collection audit found and fixed a leak in the
  standalone KG retriever (it had returned post-window tickets). Re-run results
  are leak-free.
- **Split integrity.** OB/OTel use the fixed per-window resplit
  (`triage-split-manifest-v2-resplit.json`); WoL uses its native split. An audit
  caught and fixed pipelines that had ignored the resplit (OTel test was empty).
- **Train/serve consistency.** The hybrid's internal triage head has a known
  feature-availability skew on two-class datasets (OB/OTel) that affects the
  hybrid's *triage* PR-AUC — **not** Hit@K, and not WoL (single-class). The
  headline triage number comes from the agent's compose_triage, not this head.
- **Determinism.** Seed 42 throughout; bootstrap CIs are paired (same resample
  indices across compared systems) with Benjamini–Hochberg correction across the
  family of RQ tests.

## External validity (the central scope limit)
- **Synthetic vs real telemetry.** OB and OTel are synthetic fault-injection
  datasets; **WoL is real** (Apache Jira text, 24 projects, 38.6k memory tickets,
  13.4k test windows). The retrieval/triage claims are therefore demonstrated on
  real data, not only synthetic.
- **What is real-data validated:** ticket retrieval (Hit@K/MRR), the page-
  suppression / cost-gating controller behavior (run over WoL's real
  multi-incident clusters), and the hybrid-fusion result (Hit@5 0.970 on WoL).
- **What remains synthetic-only:** the telemetry-*diagnosis* path and the ReAct
  evidence tools depend on injected fault structure; we **do not** claim those
  generalize to production telemetry. This is the primary external-validity
  threat and the main direction for future work (a real-telemetry agentic study).
- **LLM baseline + judge scale.** LLM-RAG and LLM-as-judge run on seeded subsets
  (500 / 300 windows) for compute tractability — standard for LLM baselines, but
  not full-corpus.
- **Seed variance.** Multi-seed variance is reported for the BiEncoder on OB/OTel;
  WoL is reported single-seed (seed 42) due to compute cost (~hours/run). We note
  this rather than implying full-scale multi-seed coverage.

## Conclusion validity
- **Multiple comparisons.** With many pipelines × datasets × metrics, per-test
  significance is corrected via Benjamini–Hochberg; we report q-values.
- **Negative results reported, not hidden.** Cross-corpus transfer and KG-alone
  retrieval are weak (and the KG's marginal contribution in fusion is mixed —
  it aids Hit@1 more than Hit@5); we report these explicitly in
  `paper-results/robustness/` and `kg-usefulness/` rather than omitting them.
