# ICSE Readiness Review

*An honest, thorough self-review of the agentic incident-triage work toward an
ICSE submission. Written 2026-06-28.*

> **STATUS (2026-06-28): all identified gaps addressed.** The fix plan and its
> completed outcomes are in [`review-sol.md`](review-sol.md); the resulting fresh
> results are in [`paper-results/`](../paper-results/README.md). Summary of
> closure: prior-art + LLM-RAG baselines ✅, agent marginal-value (cost@iso-acc)
> ✅, KG-usefulness (±graph ablation + complementarity) ✅, gold validation
> (LLM-as-judge) ✅, multi-seed + multiple-comparison (BH) + negative-results ✅,
> triage leaderboard (PR-AUC/ECE/precision@FPR) ✅. Synthetic-only agentic
> validation (gap #3) remains a scoped limitation, partially mitigated on real
> WoL data + documented in [`threats-to-validity.md`](threats-to-validity.md).

> **Caveat on scope of this review.** The actual paper draft (`RESEARH-PAPER/`,
> `DOCS/docs7`, `DOCS/docs8`) is not present in the repository at review time, so
> this critique is grounded in the *system design* (`DOCS/agentic-system.md`),
> the *datasets* (`DOCS/dataset.md`, `DOCS/WoL-v3-dataset.md`), the *RQ list and
> status* (`todo.md`), and the *measured results*. It does **not** reflect the
> paper's contribution framing or related-work section, which materially affect
> the verdict. Adjust anywhere these assumptions are wrong.

---

## Bottom line

This is a **substantial, methodologically careful empirical study** — but as
currently scoped it is at real risk of an ICSE reject on **novelty framing +
missing prior-art baselines + the synthetic-data validity gap**, *not* on rigor.
Re-collecting the existing result matrix strengthens **reproducibility** but does
not close those gaps; they require *new* experiments.

---

## What is genuinely strong (keep & foreground)

- **Real data at scale.** WoL: 78,140 queries / 38,642 memory tickets / 24
  Apache projects. Strong external validity, rare in this space.
- **Leakage discipline.** Time-ordered visibility, own-run exclusion, lab-leakage
  label stripping, and an explicit field-policy contract. This pre-empts the #1
  reviewer attack on retrieval papers — foreground it.
- **Statistical hygiene.** Paired bootstrap CIs (seed-locked, 1,000 resamples),
  ablation grid, per-family / per-project stratification.
- **Capability-adaptive controller.** A clean, defensible systems idea: the same
  agent degrades gracefully from full-telemetry (Online Boutique) to text-only
  (WoL) based on observed capability flags.

---

## Gaps that would draw a reject (priority order)

### 1. No comparison to published prior art
Baselines are internal (BM25 vs BiEncoder vs hybrid vs agent). ICSE reviewers
will almost certainly say "no comparison to state of the art." Need ≥1 *published*
method from incident triage / duplicate-issue detection / log-based retrieval,
run on the same data. **Single most likely reject driver.**

### 2. Missing strong end-to-end LLM-RAG baseline
A 2026 reviewer will immediately ask "why not feed the window + retrieved tickets
to GPT-4 / Claude directly?" `verify_with_llm` exists but is calibrated *off* for
WoL. An honest end-to-end LLM-RAG comparison is needed to justify the engineered
cascade/agent.

### 3. The full agentic story is validated only on synthetic data
The deepest issue. Online Boutique and OTel Demo are synthetic, and their Jira
tickets are LLM-"humanized." The only **real** dataset (WoL) is **text-only**, so
telemetry diagnosis, the 4 ReAct evidence tools, numeric triage, log-sequence
retrieval, and state-based page suppression are **never exercised on real
telemetry**. The most novel capabilities are synthetic-only. Either (a) obtain
some real telemetry+incident data (even small), or (b) explicitly and prominently
scope the claims and anchor the contribution on what WoL *does* validate
(real-world text-retrieval generalization).

### 4. Ground truth is automatic / LLM-derived, with no human validation
Gold matchings are derived; "strong relation" is Jaccard > 0.15 of symptom
tokens; OB/OTel tickets are LLM-generated; KG extraction is via gpt-4o-mini.
No human-annotated subset or inter-annotator agreement is apparent. Reviewers
will question whether retrieval is being measured against a *valid* target. A
small human-validated gold subset (with inter-annotator agreement) plus a
qualitative utility study of matched tickets + memorygraph explanations would
substantially de-risk acceptance.

### 5. The agent's marginal contribution is not cleanly isolated
Because skills are predictions-backed, the agent's retrieval ≈ the best cascade's.
The agent's real value is the *controller*: gating → cost savings at iso-accuracy,
graceful degradation, page suppression. That should be the crisp thesis, shown
with cost/latency + CIs across all three datasets and an explicit
"agent vs always-run-everything at equal accuracy" comparison.

---

## Lower-priority but reviewer-flaggable

- **Single learned model, single seed (42).** Bootstrap CIs capture sampling
  noise but not *training* variance. Re-fit the BiEncoder over ≥3 seeds and
  report mean ± std, or "is 0.905 a lucky fine-tune?" is fair game.
- **Multiple-comparison correction** across the many RQ bootstrap tests (none
  apparent).
- **Negative results need framing, not burying.** Cross-corpus Hit@5 = 0.05 and
  KG-retrieval Hit@5 ≈ 0.31 (leak-free WoL) are weak; turn them into honest
  analysis of *when and why* graph/cross-corpus retrieval fails. *(Done — see
  `paper-results/robustness/negative-results.md`.)*
- **LLM reproducibility caveat** (gpt-4o-mini drift). Already noted by the team;
  reviewers will want extracted artifacts + prompts shipped (mostly done).

---

## On the current task (re-collecting all three datasets)

Worth doing for a clean reproducibility story, **but** it reproduces *existing*
numbers — it does not touch gaps #1–#4. If effort is limited before the deadline,
rank **prior-art baseline + LLM-RAG baseline + a human-validated gold subset**
*above* re-running numbers already trusted.

---

## Recommended next steps (concrete)

1. **Pick the venue framing first.** Is the contribution (a) the
   *capability-adaptive agent* (systems), (b) the *dataset/benchmark* (WoL at this
   scale is a real asset), or (c) the *empirical study* ("does Jira-as-memory help
   triage")? Each implies different required experiments. A **benchmark/dataset
   framing may be the strongest, lowest-risk path** given the real-data asset.
2. Add the two baselines (published prior art + end-to-end LLM-RAG).
3. Human-validate a ~150–200 window gold subset (+ inter-annotator κ).
4. Re-fit the BiEncoder over ≥3 seeds; report variance.
5. Then re-collect the full result matrix (the run already in progress).
