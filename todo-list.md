# ARISE — plan v3 (post-rejection, reframed 2026-10-27)

**Branch:** `v2-research` · **Status:** rejected at ICSE; rebuilding for resubmission
**Framing (FINAL):** system paper — *retrieval-augmented investigation context*.
ARISE retrieves relevant prior incidents from observability data; the paper
proves that component so it can anchor the author's larger RCA framework
(observability bundle → investigation context builder → RCA agent).
This OVERRIDES the brief measurement-paper pivot; rigor work all transfers.

**Why this framing survives Novelty=2:** the contribution is no longer "we
fused three retrievers" but "retrieved prior-incident context measurably
improves downstream RCA" — an extrinsic evaluation nobody has published on
public data, runnable with data in hand (99.7% of memory tickets carry a
recorded root cause, 98.4% a fix). The reviewers pointed here themselves:
R2 called the focus on retrieving past resolutions "practical and
complementary to work on root-cause analysis"; R1's requested comparison class
is RCA-support systems.

Reviews: `ICSE/reviewers-comments/` · Evidence: `icse-review-results/` ·
Results: `paper-results-v2/` · Claim tracing: `scripts/v2/verify_claims.py`

---

## P0 — The experiment the resubmission hinges on

### Extrinsic RCA evaluation (task #25) — NEW
Does ARISE's retrieved context improve a downstream LLM's root-cause diagnosis?
~500 held-out WoL queries; four context conditions (none / ARISE top-5 /
hard-negative / oracle gold), same model and prompt otherwise; output a
root-cause hypothesis; judge against the ticket's own recorded root cause
(blind, shuffled; human-rated subset calibrates the judge via task #5).
Firewall: the query's own ticket and its duplicate cluster never appear in any
context. Headline: the (ARISE − none) delta; (ARISE − hard-negative) shows
ranking quality matters; (oracle − ARISE) bounds headroom.

Risks designed in: distinct generator/judge prompts; report the no-context
condition honestly (pretraining leakage on old Apache bugs is itself a
finding); persist prompts + generations so `verify_claims.py` rows can be added.

### Reframe the paper around it (task #21)
Title/abstract/intro redone for "retrieval-augmented investigation context";
RQ2 becomes the extrinsic result. §11 recommendations survive as evaluation
methodology; the triage-saturation finding becomes the *motivation* (why
context-building should be retrieval-based, not classification-based).
**Do not write the abstract until #25 produces its delta.**

---

## P1 — Reviewer asks still open

- **Human study (#5)** — relevance + page-worthiness + NEW RCA-usefulness axis
  that calibrates #25's judge. Longest lead; recruit now.
- **RCA-systems positioning (#26)** — rewrite the comparison around outputs
  (team / category / retrieved context); obtain FLASH + COMET or footnote the
  omission. Add the ops-RAG literature sweep.
- **R1-Q2 scope cut (#23)** — scope telemetry-reasoning claims to the synthetic
  corpora; real telemetry + real tickets stays future work feeding the parent
  framework. Priority lowered: the "so what" now comes from #25.
- **Artifact publish (#4)** — ready, needs user sign-off (public DOI).
- **Cost microbenchmark (#3)** — optional; result already shown insensitive.

---

## P2 — Write and verify

- Section work per `icse-review-results/07-restructure-plan.md`, adapted to the
  system framing (most of the evidence map is framing-independent).
- Verification pass (#24): every number traces to a result file;
  `scripts/v2/verify_claims.py` green; add rows for #25's outputs.
- Final editing pass (#17) last.

---

## Already fixed (24 commits, do not redo)

| | Reviewer ask | What changed |
|---|---|---|
| ✅ | R2-Q3, R1-Q3 | "Triage collapses to chance" was an artifact of a zero-filled feature matrix. Re-run on text: ROC-AUC 0.572–0.601 (paper binarization), 0.704 (strict). Retracted paper-wide. |
| ✅ | R2-Q1 | Strict-relation panel, all 9 systems, 23/24 comparisons significant. Non-leakage analysis: indexed corpus has no `Components` field, KG vocabulary overlaps gold by 9.9%, graph retriever is worst, and the component trained on coarse gold degrades most. |
| ✅ | R2-Q2 | `maxconf` defined as its own equation, two gates separated, threshold sensitivity table. |
| ✅ | R3-Q2 | Figure 4 CIs. Withdrew "peer lookup is the only clearly beneficial tool" — its interval includes zero. |
| ✅ | R3-Q1 (part) | 5 seeds on both telemetry sets + WoL bi-encoder. Seed contributes 1% of variance on OTel, 28% on OB. |
| ✅ | R1 metadata | 75.3% component coverage; disclosed that 23.9% of held-out queries are dropped (why n=5,150 not 6,773). |
| ✅ | R3 clarity | Incident defined concretely, windowing justified, label provenance documented, "human-annotation kit" corrected, naming unified. |
| ✅ | R1-Q4 (part) | DeepCT + Triangle comparison table from primary sources. |
| ✅ | R2 cost | Reframed as counts × modelled table, with a robustness argument. |

**Also worth keeping:** eight exact reproductions of published baseline numbers
(tfidf, mpnet, bge, e5, ce + 3 seeds) — a Verifiability answer the submission
could not have claimed.
