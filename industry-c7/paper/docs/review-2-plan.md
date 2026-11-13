# Review-2 response plan — C7 (ICSE 2027 Industry Challenge)

**Verdict to beat:** Borderline / Weak Reject, 6.8/10, 35–45% accept.
**Deadline:** 2026-11-13 AoE. **Today:** 2026-11-02 → **11 days**.

## The one sentence that matters

> "Your strongest evidence is that REMEMBER identifies files associated with
> eventual fixes. Your challenge asks for identifying the underlying root
> cause. Those are related, but they are not interchangeable."

Everything below is ordered by how directly it closes that gap. The reviewer
says this single change could make the biggest difference to acceptance, and
they are right: four of the eight "other weaknesses" are downstream of it.

## Resource facts (checked, not assumed)

| | |
|---|---|
| All four git repos | local, full history (`data/c7-repos/*-full.git`, 4.8 GB) |
| vLLM server | **DOWN** — job 1211031 walltime ended 2026-11-01 20:05 ET |
| Agent throughput | 232 s/instance; 50.9 GPU-hours serial |
| Full split (4,508) | ~15 h at 20 workers, ~21 h at 14 → **fits one 24 h job** |
| 790-instance rerun | ~2.5–4 h |

**Everything in P0 is CPU-only and needs no cluster.** Start it today; queue
GPU work in parallel.

---

## P0 — Establish causal ground truth (reviewer Priority 1)

The reviewer's core objection: fix-modified files conflate four different
things — the file holding the defect, the file that detected/reported the
failure, a file changed to prevent recurrence, and incidental refactoring.

### T1. Build the annotation kit
Stratified sample of **150 instances**: 4 projects, hard/easy balanced, and
*including* instances REMEMBER gets wrong (no cherry-picking). KAFKA-6624 is
in by construction. For each, render: issue report + logs, the fix diff from
the local repo, the fix commit message, and the snapshot tree.

### T2. Annotate — two independent annotators
Per instance, label:
1. the causal function/region (where the defect was),
2. the symptom-producing function (where it surfaced),
3. the logging / stack-trace location,
4. the relation between 1 and 2 (same location / caller-callee / state
   producer / config / unrelated),
and **per gold file a role**: `causal` | `symptom-handling` | `preventive` |
`refactor` | `test`.

Report Cohen's κ. **Decision needed:** is a second human annotator available?
If not, the honest fallback is one human plus an independent model as a
second rater, reported as such — weaker, but disclosable. Do not report a
single annotator's labels as "ground truth".

### T3. The headline measurement
What fraction of fix-modified gold files are actually `causal`? That number
either defends the benchmark or quantifies its limit. Either outcome is
publishable and both are better than the current silence.

### T4. Re-score every system against causal gold
Build `causal-gold` = gold files labelled causal, re-run the whole Table III
comparison on the annotated subset, and report fix-gold and causal-gold side
by side. Expect a drop; the question is whether the *ordering* survives.

### T5. Scope the claim precisely
Define "root-cause localization" in §1 before using it, state that the
ground truth is fix-modified files, and point to the annotation study as
validation. The title keeps "root-cause" (it is the challenge's own name),
but the paper must say exactly what it has and has not shown.

---

## P1 — Expand the agent evaluation (reviewer Priority 2)

### T6. Run REMEMBER on the full 4,508 evaluation split
One 24 h SLURM job at ~20 workers. The harness is already restart-safe. This
retires "limited to 790" outright rather than negotiating it.
**Blocked on:** a fresh vLLM job (needs MFA'd SSH; ask the user to open it).

### T7. Multiple seeds
3 seeds on the 790 sample (~8 h total). Report mean ± CI. Currently one seed,
which the reviewer rates Medium–high severity.

### T8. Project-level and stratum-level breakdown
Per-project Acc@1/Acc@5/MRR for the agent, easy vs hard. Pure re-analysis of
T6 output, no extra GPU.

### T9. Document the sampling procedure
State the seed, that the sample was drawn before any system ran, and the
test-only-gold removal with its conservative-direction evidence (already in
§V-B; needs to be visible from the agent section too).

---

## P2 — Make the investigation actually causal (reviewer Priority 3)

The reviewer: "do not simply add more tools … introduce a structured
investigation strategy that requires the agent to establish a chain of
evidence between the observed symptom and the suspected causal code."

### T10. Agent v3: required evidence chain
Add a `causal_chain` field to `submit_ranking`: ordered steps from symptom
location to causal location, each citing a tool result. Schema-required, in
the same way `evidence` was made required in v2 — that change was worth
+14.0 points of hard Acc@1, so the mechanism is proven on this system.

### T11. Make backward reachability structural
`callers_of` sits at 0.01 calls/issue — the model never asks. Auto-run it on
the top stack-trace symbol during Phase 0 and hand the result over, exactly
as incident memory is handed over now. Add `data_flow_back(symbol)`: where
the bad value came from.

### T12. Measure causal lift, not retrieval lift
Evaluate v3 against **causal-gold from T4**, not just fix-gold. This is the
measurement the reviewer explicitly asks for. If the chain does not improve
causal localization, report that — it is a finding either way.

---

## P3 — Realistic noise (reviewer Priority 4)

Current perturbations (dup / generic / foreign / drop) are a reasonable start
but do not reproduce production bundles. All CPU-only.

### T13. Mixed-incident interleaving
Time-order log lines from *k* concurrent incidents of the same project.
Distinct from the current `foreign` arm, which splices lines without
temporal structure.

### T14. Cascading failures
Append downstream timeout/retry/circuit-breaker errors caused by the primary
fault, so the decisive line is buried under consequences rather than noise.

### T15. Missing decisive evidence
Delete the single highest-signal line (largest BM25 contribution to a gold
file) rather than all file mentions. A sharper and more realistic test than
the current `drop` arm.

---

## P4 — Evaluate the explanations (reviewer Priority 5)

The challenge asks for an explanation connecting symptoms, log events, and
code regions. We produce one and never evaluate it.

### T16. Mechanical checks
Does the cited path exist in the snapshot? Does the cited line exist? Does
the cited symbol occur there? Fully automatic, no judge needed.

### T17. Correctness of the reasoning
LLM judge (different model from the one under test) on whether the evidence
genuinely links report symptom → log event → code region, calibrated against
~50 human-rated examples.

### T18. Report the "right answer, wrong reason" rate
Of top-1 rankings that are correct, what share carry a *correct*
explanation? Cheap to compute once T16/T17 exist, and it is exactly the
honest-negative style the paper already uses.

---

## P5 — Generalization and remaining gaps

### T19. Second model
Run REMEMBER on a second model (GLM-5.3-Flash was already staged on the
cluster) to show the gain is architectural, not a quirk of one model.
~4–6 h GPU. Reviewer severity: Medium–high.

### T20. Function-level stage
Acc@1 13.2–25.9% is weak and the reviewer flags it as High, because it is
the paper's only "code region" result. Either improve it (the agent already
reads functions — rank the functions it actually read instead of BM25 over
the top-10 files) or reframe it explicitly as a reported baseline with the
oracle ceiling as the headline. **Recommend: try the agent-read-function
ranker first; it is nearly free given T6's transcripts.**

### T21. Engineer-facing walkthrough
One subsection: what an engineer sees during triage, what the ranked list
plus evidence gives them, and how it changes the investigation. The reviewer
says industrial *relevance* is essential (unlike deployment, which is not),
and we already have the cost numbers to anchor it.

### T22. (Optional) Developer study
Explicitly not required by the CFP. Skip unless the schedule frees up.

---

## Recommended cut for 11 days

If everything cannot land, this is the order I would hold:

**Must:** T1–T5 (causal ground truth), T6+T8+T9 (full split), T10–T12 (causal
chain), T21 (relevance framing). These four blocks answer every "Very high"
and "High" severity row.

**Should:** T13–T15 (realistic noise, CPU-only so they parallelize with GPU
work), T16+T18 (mechanical explanation checks, cheap).

**Nice:** T7 (seeds), T17 (judged explanations), T19 (second model), T20
(function stage).

**Drop:** T22.

The binding constraint is not compute, it is **annotation effort in T2 and a
decision on the second annotator**. That decision gates the paper's single
most valuable experiment, so it should be made today.

## Verification discipline

Every number produced here goes into `verify_claims.py` as an exact check
(currently 266). No ranges, no `or` fallbacks — the earlier `0.3 or 0.4`
check is why a wrong number survived to review.
