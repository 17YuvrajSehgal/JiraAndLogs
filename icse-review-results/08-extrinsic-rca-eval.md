# Extrinsic RCA evaluation — pre-registration and (eventually) results

**Status:** designed and pre-registered 2026-10-27 · results pending
**Code:** `scripts/v2/extrinsic_rca_generate.py`, `scripts/v2/extrinsic_rca_judge.py`,
`scripts/v2/trillium_v2_extrinsic.sbatch`
**Task:** #25 · **Output:** `paper-results-v2/extrinsic-rca/`

---

## Why we are running this

### The objection it answers

Every retrieval number in the paper is **intrinsic**: Hit@5 against a relevance
relation we defined (same project + shared component). R1's core objection —
the one that survived the whole rebuttal — is that this measures agreement with
our own rule, not usefulness:

> "two tickets can share project/component without being a genuinely helpful
> prior incident" (R1)
> "It does not show that they are the right or useful incidents an engineer
> would retrieve." (R1-Q1)

The hard-negative LLM judge improved on this (system top-1 beats a same-project
near-miss, +0.55, p≈1e-8) but is still a *rating* — an opinion about the
ticket, not a measurement of what the ticket is for.

### The novelty problem it fixes

All three reviewers scored Novelty = 2 on "we fused three known retrievers."
The extrinsic claim is categorically different: **retrieved prior-incident
context measurably improves a downstream LLM's root-cause diagnosis, on public
data** — unpublished anywhere, because nobody else has a public corpus pairing
38k incidents with engineer-recorded resolutions.

### The strategic purpose

ARISE is the investigation-context component of the author's larger RCA
framework (observability bundle → context builder → RCA agent). This experiment
produces exactly the sentence that framework needs to cite: *context built by
retrieving relevant prior incidents improves automated RCA by X*.

---

## Design (pre-registered — do not tune after seeing results)

### Data

- Queries: N = 500 held-out WoL `ticket_worthy` queries that have ≥1 coarse
  gold match (sampled seed 42 from the 5,150).
- Judge target: the query ticket's own recorded `root_cause` and `fix`
  (LLM-extracted from the resolved ticket; non-empty for 99.7% / 98.4% of
  memory; queries lacking either are excluded before sampling).
- Context documents: retrieved tickets rendered as `summary + root_cause + fix`
  (the fields an investigation-context builder would surface).

### Conditions — identical model, prompt, decoding; only the context differs

| | Context | Isolates |
|---|---|---|
| (a) `none` | — | what the model knows anyway (incl. pretraining leakage) |
| (b) `arise` | system's actual top-5 (hybrid fusion predictions, seed 42) | the contribution |
| (c) `hard` | 5 same-project non-gold tickets, most lexically similar | "is any plausible context as good?" |
| (d) `oracle` | 5 of the query's gold matches | ceiling |

**Firewall:** the query's own ticket AND every member of its Jira duplicate
cluster are excluded from all contexts (clusters from the v3 build's
union-find over `is duplicate of` / `Cloners` / `Cause` links).

### Generation

Qwen2.5-7B-Instruct, greedy, seed 42 (same model family as the judge work, but
a *different prompt role*). Output: a one-paragraph root-cause hypothesis and a
one-line proposed fix. 500 × 4 = 2,000 generations, persisted verbatim.

### Scoring

A blind judge rates each hypothesis against the recorded root cause on 1–5
("5 = identifies the same underlying cause"), conditions shuffled, judge never
told which condition produced a hypothesis. Primary metric: **fraction rated
≥4** per condition ("diagnosis matches"), with mean score secondary. Paired
bootstrap over queries for every pairwise delta; BH correction across the
family.

Human calibration: ~100 hypothesis/target pairs rated by annotators (folded
into study #5); report judge–human agreement.

### Pre-registered comparisons and readings

1. **(b) − (a)**: the headline. Positive and significant → retrieval-augmented
   context improves RCA.
2. **(b) − (c)**: ranking quality matters. If ≈0, any same-project text is as
   good — a finding *against* the system, reported as such.
3. **(d) − (b)**: headroom left in retrieval.
4. **(a) absolute level**: if high, pretraining leakage on old public Apache
   bugs — reported as a finding about evaluating RCA on public corpora, not
   hidden. The deltas remain interpretable since all arms share the baseline.

### Known limitations, stated up front

- The judge target is the root cause *as the resolving engineers recorded it* —
  occasionally thin or wrong. The human subset partly estimates this noise.
- Generator and judge are the same base model with different prompts; the
  human calibration is the check on self-grading bias.
- One retriever seed (42) for the main run; if budget allows, repeat (b) with a
  second seed to show the delta is not seed-specific.

---

## Results

*(to be filled when the run completes — do not edit the design above after
this section is populated)*

| Condition | n | mean score | ≥4 (%) |
|---|---|---|---|
| none | — | — | — |
| arise | — | — | — |
| hard | — | — | — |
| oracle | — | — | — |

Deltas: (b)−(a) = — · (b)−(c) = — · (d)−(b) = —

Interpretation: —
