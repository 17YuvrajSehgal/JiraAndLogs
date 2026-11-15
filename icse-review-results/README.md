# ICSE review response — consolidated results reference

Everything produced while addressing the ICSE 2027 reviews, in one place, so the
rewrite does not have to re-derive any of it.

**Status:** paper rejected (2/2/3, all three Novelty=2). 26 commits on
`v2-research`. Reviews in `ICSE/reviewers-comments/R{1,2,3}.txt`.

| File | Contents |
|---|---|
| `README.md` (this) | index + how to use |
| `01-headline-results.md` | what we can claim, with numbers and intervals |
| `02-retractions.md` | claims removed or changed, and why |
| `03-methods-changed.md` | protocol changes, with rationale |
| `04-new-findings.md` | results the submission did not contain |
| `05-open-issues.md` | known gaps, unverified items, things to check |
| `06-reviewer-coverage.md` | every reviewer point → status → evidence |

## How to use this when rewriting

1. **Never quote a number from memory.** Every figure here names its source
   file. `python scripts/v2/verify_claims.py` re-checks the headline set
   against those files and fails on mismatch — run it before submitting.
2. `02-retractions.md` lists text that must not survive into the new draft.
3. `05-open-issues.md` has one genuine numeric discrepancy still unresolved
   (coarse gold set size) — settle it before it reaches a table.

## Where the data lives

```
paper-results-v2/
  baselines/wol-v3/           5 baselines re-run WITH per-candidate scores
  multiseed/wol-v3/           bi-encoder, seeds 42,1,2,3,4
  multiseed/{online-boutique,otel-demo}/   seeds 42,1,2,3,4
  multiseed-hybrid/wol-v3/    hybrid fusion, seeds 42,1,2,3,4
  strict-leaderboard.json     9-system panel, both relations, BH-corrected
  triage-text/wol-v3/         text classifiers (replaces zero-feature result)
  gold-validation/wol-v3/     hard-negative LLM judge
  tool-ablation-ci/           Fig 4 confidence intervals
  escalation/                 headroom, threshold sweep, learned-policy result
  cost/                       measured vs modelled cost decomposition
```

Analysis scripts: `scripts/v2/` (v2 work) and `scripts/rebuttal/` (first-pass
diagnostics). Cluster jobs: `scripts/v2/trillium_*.sbatch`, driven by
`scripts/v2/tri`.
