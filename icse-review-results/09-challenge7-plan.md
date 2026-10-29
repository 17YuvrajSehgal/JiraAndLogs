# ICSE 2027 Industry Challenge — Challenge #7 solution plan

**Decided 2026-10-29:** primary target = solution paper for Challenge #7,
*"Log-Guided Root-Cause Code Localization from Production Issues"*
(`icse2027-challenge7-log-guided-rca-localization.pdf`).
Submission: HotCRP `icse2027-industry-challenge.hotcrp.com`, **5–10 pages IEEE**,
**double-anonymous** (Ciena cannot be named in the submission), deadline
**Nov 13, 2026 AoE**. The FSE-2027/EMSE track for the main ARISE paper is
paused, not cancelled.

---

## What the challenge demands (from the PDF, verbatim anchors)

- **Input:** "a natural-language issue description, logs and source code snapshot"
- **Output:** "(i) the affected module, (ii) a ranked list of suspicious code
  regions and (iii) an explanation linking issue symptoms, selected log events
  and candidate code regions"
- **Evaluation:** "a benchmark containing issue descriptions, logs, source code
  and groundtruth faulty code regions… Recall@K, MRR and Acc@K", improving over
  "the strongest available baseline"
- Its three named difficulties: evidence-to-code semantic retrieval; noisy and
  incomplete logs; root-cause code vs symptom-reporting code.

## Our solution concept — incident-memory-augmented fault localization

The challenge's own references localize via retrieval over the *codebase*
(multi-agent FL, Rafi et al.) or tool-augmented agents (RCAgent). Nobody uses
**retrieval over resolved past incidents** as a localization signal. That is
our differentiator, and it keeps ARISE as the core:

1. **Evidence selection** — ARISE's existing machinery picks salient log events
   from the noisy issue bundle.
2. **Log-to-code retrieval** — index the code snapshot (files + their logging
   statements and identifiers); match selected log events against logging
   templates and code vocabulary (BM25/SPLADE + dense).
3. **Incident-memory prior (NEW, ours)** — ARISE retrieves similar resolved
   incidents; their fixing commits' touched files vote for candidate regions.
   Rationale: recurring failure modes concentrate in the same code.
4. **Fusion** — RRF over (2) and (3), exactly the machinery we have.
5. **Output** — ranked files (module = top-level dir; method-level if time),
   plus the explanation chain: symptom → selected log events → candidates.

**The paper's headline ablation:** localization with vs. without the incident
memory. If memory adds nothing, that is reported — but the Kafka linkage
density (below) makes a real contribution plausible.

## The benchmark — WoL × git history (feasibility VERIFIED 2026-10-29)

Every WoL issue carries its Jira key (38,642/38,642); Apache commits reference
keys in subjects. Measured on Kafka (treeless clone, 18,542 commits):

| | |
|---|---|
| WoL KAFKA ticket-worthy issues | 1,147 |
| with ≥1 fixing commit in history | **800 (69.7%)** |
| with exactly one fixing commit | **743 (64.8%)** |
| split of linked issues | all `test` (Kafka is a held-out family) |

Ground truth = files modified by the fixing commit. Code snapshot = repo at
the fix commit's **parent** (the code as it was when broken). Target projects:
Kafka + MariaDB (`MariaDB/server`, MDEV keys) = the WoL test split; more
Apache projects if yield holds and time permits.

## Pre-registered design guards (lessons from the circularity episode)

1. **Snapshot = parent of fix commit** — the fix must not be in the code shown.
2. **Memory firewall** — the query issue, its duplicate cluster, and any issue
   resolved AFTER the query's creation are excluded from incident memory
   (time-aware visibility, as in ARISE).
3. **Linkage noise controls** — prefer single-commit issues; drop reverts;
   flag test-only diffs; report yield at every filter.
4. **Symptom-vs-cause stratification** — measure how often a stack-trace-named
   file differs from the fix-touched file. When the trace names the fixed file,
   localization is easy by construction; report performance on both strata.
   (This directly addresses the challenge's third difficulty, and is a
   publishable statistic on its own.)
5. Every number traces to a result file; extend `verify_claims.py`.

## Evaluation plan

Metrics: Recall@K, MRR, Acc@K (K = 1, 5, 10) at file level, per the PDF.
Baselines: BM25 issue-text→file; dense retrieval; LLM-only localization
(no retrieval); ours without memory; ours full. Paired bootstrap + BH as
always. Stratified by trace-present / trace-absent.

## Deliverables

- `benchmark/` — mined dataset (issue, logs, snapshot ref, gold files), with
  a datasheet and the mining script
- the localizer (ARISE + log-to-code layer + fusion)
- the solution paper (new paper, not a rewrite of the ARISE draft)
- new architecture figure (the current one shows incident retrieval only)

## What this reuses from the existing work

Hybrid retrieval + RRF, evidence extraction, time-aware memory discipline,
the extrinsic-eval harness pattern (conditions + firewall + blind scoring),
seed discipline, claim verification. The ARISE paper's intrinsic results
become supporting evidence that the memory component retrieves well.
