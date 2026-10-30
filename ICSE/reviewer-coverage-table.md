# Reviewer coverage — what is answered, what is not (2026-10-30)

Every point from the three ICSE 2027 reviews (`reviewers-comments/R1-R3.txt`),
with its status **after** the v2 rigor work AND the Challenge #7 results.
Two deliverables carry the answers:

- **C7** = the Industry Challenge #7 solution paper (due Nov 13) —
  incident-memory-augmented fault localization, 7,775-instance benchmark.
- **Main** = the main ARISE paper resubmission (FSE/EMSE track, paused).

✅ answered · ⚠️ partially · ❌ open

## R1 (#5913A, weak reject — Novelty 2, Rigor 2)

| Point | Status | How it is answered | Still open |
|---|---|---|---|
| Q1: show retrieved incidents are *genuinely useful*, not just better than random | ✅ via C7 | Usefulness is now measured against **external ground truth**: retrieved past incidents' fix files improve localization of the true fix (hard stratum +0.080/+0.242/+0.165/+0.153 acc@5 on 4 projects, all SIG after BH). No self-defined relevance rule anywhere. | Human study (#5) still unrun; needed for main paper's relevance claims |
| Q2: telemetry-reasoning claims rest on synthetic telemetry; real corpus is text-only | ⚠️ | C7 claims nothing about telemetry reasoning; its inputs are real reporter-logs per the challenge spec. Planned complement: OTel flag-fault mini-benchmark (real runtime bundles → 9 known code sites). | Real production telemetry (Ciena) remains the long-term fix for main |
| Q3: is Jira resolution a valid proxy for page-worthiness? | ✅ for C7 / ❌ for main | C7 does not use triage labels at all — gold = the fix commit engineers actually shipped. | Main paper still needs human page-worthiness labels to make triage claims |
| Q4: compare against incident-level systems (FLASH, Triangle, DeepCT, COMET) | ⚠️ | Task/capability table for DeepCT + Triangle done (v2). For C7 the comparison class legitimately becomes FL baselines: trace-grep, path/content BM25, memory ablations are in; **LLM-only and agentic-FL baselines (challenge's own citations) still to add**. | FLASH/COMET unobtainable; LLM baselines pending token |
| Word 97% carefully (inferred relation) | ✅ | Done in v2; moot in C7 (no inferred relation exists) | — |
| Report project/component metadata quality | ✅ | 75.3% coverage measured; drop accounting published (v2) | — |
| Qualify "triage collapses to chance" | ✅ | Retracted; measured 0.57–0.70 on text (v2) | — |
| Artifact ships WoL-v2 not v3 | ⚠️ | Bundler fixed + dry-run verified (v2). C7 benchmark gets its own Zenodo release with datasheet. | Publish both artifacts |

## R2 (#5913B, weak reject — Novelty 2, Rigor 2)

| Point | Status | How it is answered | Still open |
|---|---|---|---|
| Q1a: relevance rule shares features with the graph retriever — does evaluation favor ARISE? | ✅ | v2: four independent leakage checks, none found. **C7 dissolves the concern structurally**: gold is git-derived, no overlap with any retrieval feature is possible. | — |
| Q1b: other methods under the stricter rule | ✅ | Full 9-system strict panel, 23/24 significant after BH (v2) | — |
| Q2: MAXCONF undefined; 0.5 threshold vs RRF scale | ✅ | Own equation, gates separated, sensitivity table (v2) | — |
| Q3: what inputs did Jira classifiers use? | ✅ | The zero-filled-features defect — found, retracted, re-run on text (v2) | — |
| Synthetic-vs-real framed as transfer failure | ✅ | Reframed as two operationalizations (v2); C7 does not make the claim | — |
| Controller / cost evaluation lacks detail | ⚠️ | v2: measured vs modelled separated, robustness shown. Cost remains **estimated**, not fully measured (confirmed defect from the review response). | Measured cost pass if main paper keeps the cost claim |
| Novelty detection + evidence gathering not evaluated on real data | ⚠️ | v2: demoted to negative/unvalidated results. C7's evidence-selection stage is still thin; the OTel raw-bundle complement is the test. | Evidence selection on noisy bundles |
| Engineers rating top-ranked vs hard same-project alternatives | ✅ via C7 (model-free) | The hard-negative LLM judge (v2) is superseded by C7's external gold: no rating needed when the fix commit decides. | Engineer study still valuable for main |

## R3 (#5913C, weak accept — Verifiability 2, Presentation 2)

| Point | Status | How it is answered | Still open |
|---|---|---|---|
| Why not multiple runs? | ✅ | v2: 5 seeds × 3 datasets + seed-aware intervals. C7: pipeline is deterministic end to end — re-runs reproduced every table line-identically and all 64 bootstrap tests with zero mismatches. | — |
| No CIs on Figure 4 | ✅ | Added; one claim withdrawn as a result (v2) | — |
| What exactly is an incident / where does it come from? | ✅ | Defined concretely (v2). C7 instances are maximally concrete: issue key + logs + snapshot sha + fix sha. | — |
| Why windowed, not continuous? | ✅ | Justified: the window is the unit the label exists at (v2); C7 has no windows | — |
| Where do labels come from? "human-annotation kit"? | ✅ | All label sources documented, phrasing corrected (v2). C7 labels are git facts with a per-filter funnel datasheet. | — |
| Hybrid-RRF never defined | ✅ | Naming unified (v2); C7 paper is written fresh | — |
| When does fine-tuning happen? | ✅ | Documented offline/frozen (v2). C7 core uses no fine-tuned component (BM25/RRF only). | — |
| Fixed seed insufficient on GPUs | ✅ | Confirmed empirically — R3 was right (v2). C7 avoids the issue by construction. | — |
| "Not replicable by a research assistant" | ✅ | 8 exact baseline reproductions + verify_claims.py (v2); C7 adds bit-identical re-runs. | C7 numbers not yet wired into verify_claims.py |
| Two unparseable sentences | ✅ | Rewritten (v2) | — |

## The blocker no rebuttal could fix: Novelty = 2 (all three)

The rigor answers above were necessary but not sufficient — the paper was
rejected on contribution. Status:

- **C7 paper:** novelty is structural, not incremental — first use of
  incident memory as a fault-localization signal, first public benchmark of
  issue + logs + snapshot + ground-truth faulty files (7,775 instances,
  4 organizations), and a density finding (memory value scales with linked
  history) that no baseline in the challenge's own citation list touches.
- **Main paper:** still needs its redesigned extrinsic evaluation
  (option A, telemetry-query variant) after Nov 13; it can now also cite
  the C7 result as external evidence that retrieved incidents carry
  actionable signal.

## Open-items shortlist (ordered by deadline relevance)

1. LLM-only / agentic-FL baselines for C7 (needs API token) — R1-Q4's modern form
2. Wire C7 headline numbers into `verify_claims.py` — R3's replicability standard
3. OTel raw-bundle complement — R1-Q2/R2's "real noisy input" in miniature
4. Publish C7 benchmark (Zenodo, datasheet) — R1's artifact standard
5. Human study (#5) — main paper only, after Nov 13
6. Measured (not estimated) cost — main paper only, if the cost claim stays
