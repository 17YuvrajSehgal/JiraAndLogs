# BugLocator: Where Should the Bugs Be Fixed? (ICSE 2012)

**Jian Zhou, Hongyu Zhang, David Lo. ICSE 2012, pp. 14–24. DOI 10.1109/ICSE.2012.6227210.**

> **PROVENANCE NOTE:** the original PDF is paywalled (IEEE; the SMU and
> institutional mirrors block automated access). This summary is assembled
> from sources read IN FULL that restate BugLocator's mechanics and
> numbers: Bench4BL (ISSTA'18, §3.1 configs + tables), the ABLoTS
> replication (2026, §2), the survey document's verified fragments, and
> BLAZE/LocAgent's descriptions. Every statement below is cross-checked
> against at least one of those; items we could NOT verify are flagged.
> Before quoting formulas verbatim in the paper, obtain the original
> through the university library.

## Why it matters to us

The 2012 origin of the similar-report signal ("SimiScore") — the direct
ancestor of our S4 and the paper the reviewer said we must cite and
baseline against, or be accused of reinventing it.

## Mechanics (as needed for our re-implementation)

- **rVSM**: a revised Vector Space Model over report/source text whose
  revision favors LARGER files via a length function (Bench4BL runs it
  with "a logistic function as the length function"). File score =
  rVSM cosine similarity adjusted by the length factor.
- **SimiScore** (from the survey's verified fragments + ABLoTS §2):
  SimiScore(q, f) = Σ over past fixed reports b that touched f of
  sim(q, b) / n_b, where sim is cosine similarity between reports and
  n_b = number of files changed by b's fix. No top-k cutoff is described
  — ALL past linked reports contribute.
- **Combination**: FinalScore = (1−α)·N(rVSM) + α·N(SimiScore), min-max
  normalized; α tuned around 0.2–0.3 (Bench4BL uses α = 0.3 as default).
- Granularity: file. Inputs: report text, snapshot, past fixed reports
  with fixed files. No tests, no execution.

## Evaluation (as reported by the replications)

Four Java projects — Eclipse 3.1, AspectJ, SWT, ZXing; 3,000+ bugs.
Headline: for 62.60% of Eclipse 3.1 bugs a buggy file ranks in the top 10
among 12,863 files; MAP ~0.22–0.55 across projects (survey-verified
range). Under Bench4BL's harmonized re-run on 46 new subjects: MAP 0.305
/ MRR 0.422 (single-version), rising to 0.371 MAP with correct version
matching.

**UNVERIFIED (flagged by the survey too):** whether the original
evaluation enforced a per-query time cutoff on "similar bugs fixed
before". The paper's text says it uses previously-fixed bugs, but no
replication confirms a strict creation-time cutoff, and no duplicate or
shared-fix-commit exclusion is described anywhere. Do NOT claim it leaks;
say its protocol "does not describe" these controls — and measure the
effect ourselves (the planned SimiScore-with/without-firewall experiment).

## Differences from our S4 (for the related-work positioning)

| BugLocator SimiScore | Our S4 |
|---|---|
| all past reports vote, weight sim/n_b | top-20 BM25 neighbors vote, weight 1/rank |
| no described time cutoff | strict creation-time firewall (blocks 67–71% of votes) |
| no duplicate handling | duplicate-cluster exclusion (PJD links) |
| no shared-fix-commit rule | shared-fix-commit exclusion |
| fixed α blend with rVSM | regime-conditioned weighted RRF over four signals |
| Java, snapshot per release | C/C++/Java/Scala, parent-of-fix snapshot |

Also worth implementing as an S4 ablation (reviewer's suggestion): the
sim/n_b vote weighting — it divides credit across large fixes, which our
1/rank votes do not; large refactoring commits can flood our votes.

## Use in our paper

- Related work §2 (history/similar reports): first sentence of the
  paragraph; the "established IRBL signal" citation.
- §4 baselines: rVSM+SimiScore re-implementation with Bench4BL's default
  α = 0.3, tuned variant on our dev split.
- The firewall experiment: SimiScore with firewall on/off = the headline
  methodological measurement the reviewer called potentially "the paper's
  strongest contribution".
