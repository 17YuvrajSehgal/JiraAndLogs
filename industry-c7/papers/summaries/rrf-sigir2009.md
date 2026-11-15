# Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods

**G. V. Cormack, C. L. A. Clarke, S. Büttcher. SIGIR 2009 (short paper, 2 pages).**
PDF: `pdfs/rrf-sigir2009.pdf`

## What it is

The origin of RRF, the fusion rule our weighted variant extends:
RRFscore(d) = Σ_r 1/(k + r(d)) over rankings r, with **k = 60 fixed in a
pilot and never re-tuned**. Unsupervised: no training data, no score
calibration, rankings combined one system at a time with no global state.

## Their justification of the formula (useful to quote/paraphrase)

- 1/(k+rank) decays slower than an exponential: low-ranked documents keep
  nonzero influence.
- k mitigates "outlier systems that rank something absurdly high" — one
  rogue ranking cannot dominate.
- Their conjecture for why RRF beats Condorcet voting: "one or two systems
  that rank a document highly can substantially improve its rank", i.e.,
  RRF harnesses DIVERSITY among rankers, while majority-style voting lets
  many weak preferences overrule one strong one. This is precisely the
  property our fusion needs: on hard instances only S4 knows the answer,
  and RRF lets a single confident signal push a file up.

## The numbers and what they mean

- Pilot (Table 1): MAP nearly flat for k in 10..100 (0.2123–0.2147), falls
  at k=0 and k=500. Meaning: **k is not a sensitive hyperparameter**; our
  reuse of k=60 without tuning is standard and defensible with this table.
- TREC fusion (Table 2): RRF beats the best individual run on 3 of 4
  collections (loses only to a human-in-the-loop run on TREC 9) and beats
  Condorcet everywhere, CombMNZ in 3 of 4. Overall 4–5% over the
  alternatives; sign-test significant (p ≈ 0.008–0.04).
- LETOR 3 (Table 3): fusing seven learning-to-rank baselines with RRF
  (MAP 0.6051) beats every individual learned ranker (ListNet 0.5846,
  RankSVM 0.5737, RankBoost 0.5622; all p ≤ .003) — fusion of learners
  beat each learner. CombMNZ edges RRF insignificantly (p ≈ .2) there.

## Weaknesses / scope notes

- Two-page paper: no analysis of WEIGHTED RRF, no conditioning, no
  treatment of rankings with very different list lengths (our lists are
  truncated at 50 — a deviation to keep documented).
- Document-retrieval collections only; transfer to code retrieval is
  assumed by later work (BLAZE et al.), not shown here.
- "Not altered during subsequent validation" is the original
  tune-once-then-freeze discipline — matches our dev-only tuning story.

## Use in our paper

- §3 fusion: the citation for the formula and for k = 60.
- The diversity-harnessing sentence supports why fusion is the right
  combiner for four signals with disjoint strengths.
- Our additions relative to this paper, stated plainly: per-signal weights,
  tuned on a time-based dev split, conditioned on an observable regime —
  the survey found no prior IRBL work that conditions fusion weights on a
  report property ("to our knowledge" novelty point).
