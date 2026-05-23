# Dataset Expansion Plan (v5 and beyond)

**Created:** 2026-05-23
**Owner:** Yuvraj
**Status doc:** complements `docs/dataset-v4-plan.md` (canonical v4 spec)
and `docs/triage-task-contract.md` (metrics contract). This file is the
**actionable plan for growing the dataset past v4-large**, so ML/AI models
in `todo.md` Phases 1+ have enough signal to train without overfitting.

---

## Why we need a bigger dataset

v4-large landed at:

- 3,216 windows, 208 Jira memory issues, 40 runs, 13 scenario families.

That's enough to make a triage model look respectable, but not enough for the
ML/AI agenda in `todo.md`. Specific overfitting / coverage risks:

| Risk                                              | Evidence on v4-large                               |
| ------------------------------------------------- | -------------------------------------------------- |
| Test split has only 6 families (of 13)            | `productcatalog-latency` is the only latency-type family in test; can't generalize to other latency shapes |
| Many families have only 1-2 scenario YAMLs        | `checkout-outage`, `currency-outage`, `ad-outage`, `frontend-restart` each have 1 scenario - the model memorizes the scenario, not the family |
| 8 v4-plan families were never collected           | `post-deploy-churn`, `recovered-in-window`, `single-pod-restart-healthy-replication`, `third-party-blip`, `scheduled-job-spike`, `latency-near-miss-partial-recovery`, `flapping-pod`, `slow-leak-saturation` |
| Memory corpus undersized for retrieval research   | 208 < target of 400+ from `dataset-v4-plan.md` |
| Zero human adjudication                           | Every borderline + hard-case label is `scenario_authored` / `derived`. v4 contract demands `human_adjudicated` for these. |
| Single application (Online Boutique only)         | No cross-app generalization signal |
| Fault duration capped at ~2 min                   | `slow-leak-saturation` and similar gradual faults can't be expressed |
| No temporal / continuous context                  | Each run is a discrete burst, no day/night / deploy / business-hour patterns |
| No real-world anchoring                           | We're calibrating noise families against our own assumptions only |

Each of these is a phase below.

---

## Sizing targets for v5

Compared to v4-large (3,216 windows / 208 issues / 40 runs / 13 families):

| Asset                          | v4-large | v5 target | x-fold |
| ------------------------------ | -------: | --------: | -----: |
| Dataset runs                   | 40       | 100       | 2.5x   |
| Scenario families              | 13       | 21        | 1.6x   |
| Distinct scenarios (YAMLs)     | 24       | 45        | 1.9x   |
| Telemetry windows              | 3,216    | 8,000     | 2.5x   |
| Jira memory issues             | 208      | 500       | 2.4x   |
| `borderline` (% of windows)    | 22%      | 15-20%    | -      |
| `is_hard_case` (% of windows)  | 0%       | >=15%     | inf    |
| `human_adjudicated` windows    | 0        | 100% of borderline + hard | inf |
| Reviewer disagreement labels   | 0        | every borderline + hard | inf |
| Distinct microservice apps     | 1        | 2         | 2x     |
| Long-window (>=10 min) episodes | 0       | >=100     | inf    |
| Cross-service cascade episodes | ~0       | >=80      | inf    |

The 100-run target is sized for a 4-5 day cloud VM at the same `e2-standard-8`
profile that ran v4-large in ~24 hours. Doubling the disk to 1TB covers the
extra log volume.

---

## Phase D0 - Squeeze v4-large dry first (no new collection)
**Goal:** before spending more compute on a v5 collection, extract more
research value from the v4-large bits we already have.

- [ ] **D0.1** Per-family minimum window check. Run a validator across the
      v4-large global directory that fails if any family has < 30 windows
      in any split. If train has weak families, document which.
- [ ] **D0.2** Adjudication tooling. New module `src/adjudication/` with:
      `adjudicate.py` - loads a borderline / hard-case window, blanks out
      `scenario_id`, presents trace + log + metric + Jira-memory hits to
      a reviewer, captures `{label, severity, components, reason, rationale}`
      back into `triage_window_labels.jsonl` with `source: human_adjudicated`.
- [ ] **D0.3** LLM-as-first-reviewer pass (one of `dataset-v4-plan.md`
      open questions). Prompt: "given this evidence text and these top-5
      similar past Jira issues, would you file a ticket?". Compare LLM
      label to scenario_authored label - log every disagreement. This is
      the labour-saving way to make 100% adjudication feasible.
- [ ] **D0.4** Pull at least 1 human reviewer (Yuvraj + optionally a
      second) over the LLM-flagged disagreements + a random 10% audit
      sample. Yields `reviewer_disagreement_rate` per family - critical
      for the paper.
- [ ] **D0.5** Calibration-run carve-out. Pick one v4-large run (the
      one with the most diverse family coverage) and reserve it as the
      calibration set per `dataset-v4-plan.md` Section "Calibration Set".
      Should NOT be used for threshold selection downstream.
- [ ] **D0.6** `is_hard_case` backfill. Currently 0 windows are flagged
      hard. Apply a rules-based heuristic + LLM second opinion to set
      `is_hard_case=true` on windows where (a) borderline label, OR
      (b) `triage_score` near threshold from any pipeline in
      `comparison/phase0.5-full/`. Target: 15%+ of windows flagged.

**Acceptance:** 100% of borderline + hard-case windows on v4-large carry
`source: human_adjudicated`. Per-family disagreement rate reported.
Calibration run identified.
**Status:** not started.
**Blocks:** every later phase consumes adjudicated labels.

---

## Phase D1 - Author the 8 deferred v4 scenario families
**Goal:** `docs/dataset-v4-plan.md` explicitly lists 8 new families that
were planned but never collected. Authoring them costs nothing (YAML)
and immediately gives v5 a much richer test surface.

For each new family, target **2-3 scenarios** so the family is not a
single-point-of-failure:

- [ ] **D1.1** `post-deploy-churn` (noise-heavy). Rolling deploy produces
      brief errors and restarts WITHOUT user impact. Critical false-positive
      family. Scenarios: `deploy-rolling-cart-graceful`,
      `deploy-rolling-frontend-graceful`, `deploy-canary-rollback-quick`.
- [ ] **D1.2** `recovered-in-window` (borderline). Real fault that
      self-recovers before user impact. Scenarios: `redis-blip-30s-recovery`,
      `paymentservice-flake-recovers`, `currency-timeout-recovers`.
- [ ] **D1.3** `single-pod-restart-healthy-replication` (noise). One
      replica restarts, others serve traffic. Scenarios: `frontend-1-of-3-restart`,
      `cartservice-1-of-3-restart`.
- [ ] **D1.4** `third-party-blip` (borderline). External dependency
      5xx briefly, graceful degradation. Scenarios: `currency-api-blip-major`,
      `recommendation-model-blip-minor`.
- [ ] **D1.5** `scheduled-job-spike` (noise). Cron job spike on shared
      resource. Scenarios: `analytics-job-burst`, `cleanup-job-burst`.
- [ ] **D1.6** `latency-near-miss-partial-recovery` (borderline). Latency
      exceeds soft SLO, stays under page-worthy. Scenarios:
      `productcatalog-slow-recovers`, `recommendation-slow-recovers`.
- [ ] **D1.7** `flapping-pod` (ticket_worthy after N flaps). Pod
      restarts repeatedly, eventually customer-visible. Scenarios:
      `cart-redis-flap-5x`, `paymentservice-flap-3x-30min`.
- [ ] **D1.8** `slow-leak-saturation` (ticket_worthy, long-running).
      Memory/connection leak grows over minutes, eventually pages.
      Scenarios: `frontend-memory-leak-15min`, `redis-connection-leak-20min`.
      Requires Phase D3 (extended window support) to express properly.

**Acceptance:** All 8 families have >= 2 authored YAMLs in
`deploy/research-lab/scenarios/faults/`. Each scenario YAML carries a
filled `triage` block per the v4 schema. Family taxonomy in
`scripts/research-lab/triage_labels.py` (constant `SCENARIO_FAMILIES`)
extended to cover them.
**Status:** not started.
**Blocks:** Phase D4 (v5 collection) - we don't collect without scenarios.

---

## Phase D2 - Existing-family densification
**Goal:** families with only 1 scenario (`ad-outage`, `checkout-outage`,
`currency-outage`, `frontend-restart`, `shipping-outage`) are
single-point-of-failure for the model. Each needs at least one more
scenario to make the family "real".

- [ ] **D2.1** Add `adservice-pod-restart-nearmiss` and `adservice-bad-config-major`.
- [ ] **D2.2** Add `checkoutservice-redis-dependency-major` and
      `checkoutservice-payment-dependency-major`.
- [ ] **D2.3** Add `currencyservice-bad-config-major` and `currencyservice-slow-recovers`.
- [ ] **D2.4** Add `frontend-bad-rollout-major`, `frontend-cdn-blip-nearmiss`.
- [ ] **D2.5** Add `shippingservice-pod-restart-major` and `shippingservice-slow-major`.

**Acceptance:** every family in `SCENARIO_FAMILIES` has at least 2
distinct scenario YAMLs.
**Status:** not started.

---

## Phase D3 - Extended-window / long-running scenarios
**Goal:** the collection pipeline (`run-scenario.ps1`,
`export-telemetry-window.ps1`) currently assumes ~2-minute episodes. The
slow-leak-saturation family and similar gradual faults need 10-30
minute episodes with finer-grained intra-episode sub-windows.

- [ ] **D3.1** Schema change: add `episode_duration_minutes` and
      `sub_window_seconds` fields to the scenario YAML. Default to current
      behavior (2 min episode, 75 sec windows).
- [ ] **D3.2** Update `run-scenario.ps1` to honor the new fields. Episode
      runs long; the exporter slices it into N sub-windows so the model
      sees the same kind of per-window structure it sees today.
- [ ] **D3.3** Memory-leak fault injector: a sidecar that runs `stress-ng`
      or a tiny Python script which leaks memory linearly inside a target pod.
- [ ] **D3.4** Connection-leak injector: opens TCP / DB connections without
      closing them; targets Redis client connections.
- [ ] **D3.5** Slow-disk injector: cgroup-based io throttling on a pod.

**Acceptance:** at least 5 long-running scenarios run end-to-end and
produce >= 8 sub-windows each with `window_type` values including
`active_fault_t+5min`, `active_fault_t+10min`, etc.
**Status:** not started.
**Blocks:** D1.8 (slow-leak-saturation) needs this.

---

## Phase D4 - v5 collection itself (multi-day VM)
**Goal:** the actual production-scale v5 collection. Sizing assumes D0-D3
are done.

- [ ] **D4.1** New corpus manifest
      `deploy/research-lab/corpora/dataset-v5-large.json`. 100 runs:
      8 control + 30 compact-a + 30 compact-b + 12 new-families-a + 12
      new-families-b + 8 long-running. Each new-families plan uses the
      Phase D1 + D2 scenario inventory.
- [ ] **D4.2** New run plans
      `deploy/research-lab/run-plans/dataset-v5-new-families-a.json` and
      `-b.json` mixing the 8 new families across the 100-run budget.
- [ ] **D4.3** Update `docs/gcp-production-dataset-vm-runbook.md` for
      v5: 1TB disk, ~4-5 day budget, double the Loki retention.
- [ ] **D4.4** Pilot collection: 3 runs from each new plan family,
      validate every window passes `validate-run-feature-distribution.py`,
      check borderline ratios match v4-large expectation. If a new
      family produces 100% noise or 0% noise, iterate before launching
      the full 100-run sweep.
- [ ] **D4.5** Launch full 100-run sweep on cloud VM.
- [ ] **D4.6** Re-run the Phase 0 + Phase 0.5 comparison reports against
      the v5 global directory. Diff the headline numbers vs v4-large to
      quantify the dataset-scale lift.

**Acceptance:** `data/derived/global/2026-05-??-dataset-v5-large-global/`
exists with >= 8,000 windows, >= 500 Jira memory issues, and per-family
size >= 60 windows.
**Status:** not started.
**Blocks:** D5-D8 use v5 as their base, not v4-large.

---

## Phase D5 - Cross-service cascading faults
**Goal:** v4-large faults are single-service (one fault, one affected
service). Real outages cascade: redis blip -> cartservice errors ->
checkout failures -> frontend timeouts. The current dataset has
near-zero cascade signal.

- [ ] **D5.1** New scenario schema field `cascade_chain` listing
      [(service, fault_type, t_offset_sec), ...].
- [ ] **D5.2** Author cascading-fault scenarios:
      `cart-redis-into-checkout-cascade`,
      `paymentservice-into-frontend-cascade`,
      `productcatalog-into-recommendation-into-frontend`.
- [ ] **D5.3** Each cascade scenario generates ONE Jira ticket but
      MULTIPLE ticket_worthy windows (one per affected service). The
      memory-retrieval ground truth must include all affected services'
      windows in `linked_window_ids`.

**Acceptance:** at least 80 telemetry windows in v5 carry a cascade
scenario. Memory-retrieval ground truth correctly links cross-service
windows to the same Jira ticket.
**Status:** not started.

---

## Phase D6 - Topology diversity (second microservice application)
**Goal:** Online Boutique is the only app. A model trained on one app's
service names and log shapes won't generalize. Adding a second app
tests cross-app transfer and stresses the family taxonomy.

- [ ] **D6.1** Pick a complementary OSS demo. Top candidates:
      - **Sock Shop** (https://microservices-demo.github.io/) - mature,
        Go + Java + Node mix, different fault surface than Boutique.
      - **TrainTicket** (academic favourite, 41 services, rich fault
        catalog) - most cited in microservice fault research.
      - **Hotel Reservation** (DeathStarBench) - heavy DB + Memcached
        usage; complements Boutique's Redis focus.
      Recommend Sock Shop (lowest setup cost) for v5.1, TrainTicket as
      a stretch for v6.
- [ ] **D6.2** Bring up the picked app in the same kind cluster, with
      the same observability overlay (Loki + Tempo + Prometheus + Alloy).
- [ ] **D6.3** Translate the Phase D1 + D2 scenario families onto the new
      app. The fault TYPES are the same (latency, restart, outage); the
      affected services change.
- [ ] **D6.4** Collect 20-30 runs on the new app. Add to v5 corpus as
      `dataset-v5.1-cross-app`.
- [ ] **D6.5** Cross-app evaluation: train on Boutique, test on Sock
      Shop. If PR-AUC holds within 10pts, the model generalizes; if it
      collapses, the model was memorizing service names and the report
      should disclose this.

**Acceptance:** 600+ windows on Sock Shop covering >= 6 of the v5
families. Cross-app PR-AUC measured.
**Status:** not started.

---

## Phase D7 - Memory corpus diversity (Jira side)
**Goal:** every Jira issue is currently auto-generated from one template.
The retrieval models can't generalize across writing styles. v5 should
inject realistic variation.

- [ ] **D7.1** Multi-author style templates. Author 4-5 distinct
      `summary_template` / `description_template` styles in
      `deploy/research-lab/scenarios/`. Rotate templates per run so the
      same fault family yields differently-worded tickets.
- [ ] **D7.2** Sparse-info issues. For 10% of generated issues, drop
      half the description fields. Tests retrieval robustness to thin
      memory_text.
- [ ] **D7.3** **False-alarm issues** (unique research contribution).
      For 5% of `noise`-labeled windows, generate a Jira ticket that
      gets closed-as-not-an-issue. This creates "memory entries that
      should NOT match anything", which the retriever should learn to
      down-rank. Add `is_false_alarm: true` to memory_corpus rows.
- [ ] **D7.4** Resolution-notes variation. Some tickets get "Rolled back
      deploy. Closed as fixed." Others get a multi-paragraph postmortem.
      Variation drives the upper bound on resolution-keyword features.

**Acceptance:** memory_text length distribution shifts from "all 600
chars" to long-tail (100-3000 chars). At least 5% of memory entries
flagged `is_false_alarm`.
**Status:** not started.

---

## Phase D8 - Continuous / temporal-context collection
**Goal:** every v4 run is a discrete fault burst. Real production has
constant background noise, weekly traffic cycles, deploy events,
business-hour fluctuations. A model that only sees burst-isolated
windows misses the temporal-context signal.

- [ ] **D8.1** Continuous-cluster mode. New script
      `scripts/research-lab/run-continuous.ps1` that keeps the cluster
      up for 24+ hours and sprinkles faults at irregular times.
- [ ] **D8.2** Background-load schedule. Implement a synthetic
      day/night traffic curve (lower at "night", higher at "day") via
      the loadgenerator. 24 simulated hours can compress to ~4 real
      hours.
- [ ] **D8.3** Deploy events. Schedule N rolling deploys per simulated
      day; some have errors (post-deploy-churn), some are clean.
- [ ] **D8.4** Continuous-window slicing. Slice the 24h timeline into
      75-second windows END TO END, not just around fault episodes. Most
      windows will be `noise`; that's the point - the model sees the
      base rate properly for the first time.

**Acceptance:** at least one 24h continuous run captured, producing
~1100 windows of which >= 90% are noise. False-positive rate of any
v5 pipeline drops by at least 30% after including this run in training.
**Status:** not started.

---

## Phase D9 - Real-world anchoring
**Goal:** open question from `dataset-v4-plan.md`. Right now we
calibrate noise families against our own assumptions. Anchoring to
public production data validates the realism of the noise distribution.

- [ ] **D9.1** Pull public incident postmortems (Google, AWS,
      Cloudflare, GitHub status archives). Convert to Jira-shaped
      memory entries with synthetic linked-window ids (or mark
      `linked_window_ids=[]`). Tests retrieval against real human-written
      incident text.
- [ ] **D9.2** LogHub corpus (https://github.com/logpai/loghub) - public
      log datasets from HDFS, Spark, Hadoop, BGL, Apache. Use as noise
      anchor: train a noise classifier on LogHub; verify our synthetic
      noise looks like real noise in template-space.
- [ ] **D9.3** Optional, stretch: secure an NDA-signable production
      slice from a friendly company. Anonymize service / user / request
      IDs. Use as held-out test set.

**Acceptance:** at least 50 real-world Jira-shaped memory entries
ingested. Synthetic noise distribution overlaps real noise distribution
on the top-50 template-frequency rank ordering with Spearman rho > 0.6.
**Status:** not started.

---

## Phase D10 - Reproducibility hardening
**Goal:** the v4 manifest captures tool versions and builder hashes,
but the scenarios themselves can drift. v5 should be byte-deterministic.

- [ ] **D10.1** Pin all docker image digests in the kind manifests.
- [ ] **D10.2** Snapshot the Online Boutique commit SHA into every
      manifest.
- [ ] **D10.3** Add `docs/dataset-v5-reproducibility.md` with the exact
      commands to reproduce the dataset bit-for-bit from a fresh VM.

**Acceptance:** a second researcher can produce a byte-identical (modulo
timestamps and trace IDs) dataset from the same git SHA on a clean VM.
**Status:** not started.

---

## Suggested execution order (sprints)

Adjudication and scenario authoring can run before any new collection.
Topology diversity and continuous mode are higher-effort and best after
v5 has validated the bigger-corpus hypothesis.

| Sprint | Phases       | Cost                | Depends on      |
| ------ | ------------ | ------------------- | --------------- |
| D-1    | D0           | 3-5 reviewer days   | nothing         |
| D-2    | D1, D2       | 2 author days       | nothing         |
| D-3    | D3, D7       | 3 dev days          | D2 (templates)  |
| D-4    | D4 pilot     | 1 VM day            | D1, D2, D3      |
| D-5    | D4 full      | 4-5 VM days         | D-4 passes      |
| D-6    | D5           | 2 author + 1 VM day | D-5 done        |
| D-7    | D6           | 5 dev + 2 VM days   | D-5 done        |
| D-8    | D8           | 2 dev + 1 VM day    | D-5 done        |
| D-9    | D9           | 2 research days     | D-5 done        |
| D-10   | D10          | 1 dev day           | D-5 done        |

D-1 and D-2 are pure-thinking-and-writing sprints - they can start
today and run in parallel with the existing `todo.md` Phase 1 (real
embeddings) work, which doesn't need new data.

---

## Decision points

These should be resolved before D-4:

1. **Adjudication staffing.** Yuvraj solo, or pull in a second
   reviewer? Single-reviewer is fine for v5 if we explicitly say so in
   the paper; two reviewers strengthen the disagreement-rate story.
2. **Second app choice** (D6.1): Sock Shop (low cost), TrainTicket
   (academic credibility), or Hotel Reservation (DB stress)?
3. **VM size for v5.** e2-standard-8 + 1TB disk for ~4-5 days, or step
   up to e2-standard-16 + 1TB to halve wall time at +50% cost?
4. **Cost ceiling.** v5 collection estimate is $80-120 GCP. Acceptable?
5. **Continuous mode scope** (D8): one 24h run, or multiple to cover
   weekday/weekend patterns?

---

## What this plan DOES NOT solve

Things that need their own future plans, not on the critical path for
v5:

- **GPU-scale training.** None of the v5 models in `todo.md` Phase 1-5
  need GPUs. If we move to fine-tuning a 7B+ LLM in Phase 4 or 5,
  separate compute plan needed.
- **Real production deployment.** A pilot at a real company with
  real on-call data is the only way to remove "synthetic-incident"
  caveats. Out of scope for v5.
- **Multi-cluster / cross-region.** Deferred to v6 per
  `dataset-v4-plan.md`.

---

## Quick wins available right now

These do not block on any cloud VM or new collection:

- [ ] D0.2: build adjudication tooling and run it on v4-large
- [ ] D0.3: LLM-as-first-reviewer pass over borderline + hard-case windows
- [ ] D1: author the 8 deferred v4 scenario families (YAML only)
- [ ] D2: author densification scenarios for single-scenario families
- [ ] D7.3: design false-alarm Jira generation (huge differentiator
      vs other public datasets - nobody else has "memory entries that
      should be ignored")

The cleanest first step is **D0.2 + D0.3** (adjudication + LLM-first
review). It unlocks the v4 contract's promise that labels are
trustworthy, which the rest of the research story depends on.
