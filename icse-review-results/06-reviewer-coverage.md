# Reviewer coverage map

Every point raised, its status, and where the evidence is.
✅ addressed · ⚠️ partially · ❌ open

---

## R1 (#5913A) — weak reject, Novelty 2, Rigor 2, Artifact "partially satisfactory"

| # | Point | Status | Evidence |
|---|---|---|---|
| Q1 | Human judgments that matches are *useful*, not just better than random | ⚠️ | Hard-negative LLM judge built and run: system top-1 3.65 vs same-project hard negative 3.10, +0.55, p≈1e-8. **Still a model, not people** — the human study is not done. `04-new-findings.md` F6 |
| Q2 | Justify telemetry-reasoning claims when telemetry is synthetic and real data is text-only | ❌ | We narrowed the claim rather than fixing it. Either collect real telemetry or cut the claim. `05-open-issues.md` |
| Q3 | Is Jira resolution a valid proxy for page-worthiness? | ⚠️ | Split into its own construct threat and stated as a limitation; the *empirical* answer needs the human page-worthiness axis, not run |
| Q4 | Compare incident-level systems (FLASH, Triangle, DeepCT, COMET) | ⚠️ | DeepCT + Triangle from primary sources, with a task/capability table. FLASH and COMET could not be obtained |
| — | Word the 97% carefully | ✅ | Always labelled "under an inferred project–component relation"; strict 0.744 co-headlined |
| — | Report component metadata quality | ✅ | 75.3% coverage; 23.9% of held-out TW queries dropped (why n=5,150). `04-new-findings.md` F8 |
| — | Qualify "triage collapses to chance" | ✅ | Retracted entirely; replaced with measured 0.57–0.70. `02-retractions.md` R1 |
| — | Artifact ships WoL-v2, not v3 | ⚠️ | Bundler fixed and dry-run verified (54 files, 2.07 GB); **not yet published** |

---

## R2 (#5913B) — weak reject, Novelty 2, Rigor 2

| # | Point | Status | Evidence |
|---|---|---|---|
| Q1a | Does the relevance rule favour ARISE (graph uses component overlap)? | ✅ | Four independent checks, no leakage found. `04-new-findings.md` F9 |
| Q1b | How do other methods do under the stricter rule? | ✅ | Full 9-system panel, 23/24 significant after BH. `01-headline-results.md` §2 |
| Q2 | What is `MAXCONF(R)`, and how were its thresholds set? | ✅ | Own numbered equation, explicitly *not* the RRF score; two gates separated; sensitivity table. `03-methods-changed.md` |
| Q3 | What inputs did the Jira classifiers use? | ✅ | Zero-filled telemetry columns — the defect. Replaced with text classifiers. `02-retractions.md` R1 |
| — | Synthetic-vs-real comparison overstated | ✅ | Reframed as a contrast between two operationalizations, not a transfer experiment |
| — | Controller/cost evaluation lacks detail | ✅ | Measured vs modelled separated, cost table published, robustness shown. `01-headline-results.md` §6 |
| — | Novelty detection + evidence gathering not evaluated on real data | ✅ | Both demoted to negative/unvalidated results. `04-new-findings.md` F5 |
| — | "Engineers evaluating top-ranked results against hard same-project alternatives" | ⚠️ | Done with an LLM judge; the *engineers* part is the open human study |

---

## R3 (#5913C) — weak accept, Verifiability 2, Presentation 2

| # | Point | Status | Evidence |
|---|---|---|---|
| Q1 | Why not multiple runs? | ✅ | 5 seeds × 3 datasets (bi-encoder) + 5 seeds hybrid on WoL; seed-aware intervals; variance decomposition. `01-headline-results.md` §5 |
| Q2 | Why no CIs on Figure 4? | ✅ | Added; one claim withdrawn as a result. `02-retractions.md` R4 |
| — | What is an incident? Where does it come from? | ✅ | Stated concretely before any notation; symbols grounded per dataset |
| — | Why windowed, not continuous? | ✅ | Justified: the window is the unit at which the *label* exists |
| — | Where do labels come from? "human-annotation kit"? | ✅ | All three sources documented; stated outright that no human annotated anything; misleading phrasing corrected |
| — | Hybrid-RRF never defined | ✅ | Unified to "hybrid fusion" across text, figures, captions |
| — | When does fine-tuning happen? Is it per-incident? | ✅ | Offline, once per dataset, frozen at eval; no state between incidents |
| — | Fixed seed insufficient for GPU work | ✅ | Confirmed empirically — R3 was right. `04-new-findings.md` F3 |
| — | "Not replicable by a research assistant" | ✅ | 8 exact reproductions; every claim traceable via `verify_claims.py` |
| — | Both flagged sentences unparseable | ✅ | Rewritten |

---

## The unlisted blocker

**All three reviewers scored Novelty = 2 and none raised it as a question**, so
the rebuttal structurally could not address it. We answered the rigor questions
well and were rejected anyway. ICSE 2027 accepted 119 of 2,375 (5.0%) with 300
major revisions (12.6%) — at 2/2/3 we were below the revision line too.

Fixing rigor was necessary and is now largely done. The contribution itself is
the open problem: see `todo-list.md` P0-2.

**And the metareview we received is for a different paper**, so we do not have
the AC's actual reasoning. Query sent to the PC chairs.
