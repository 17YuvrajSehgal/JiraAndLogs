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
| **No system / infrastructure faults**             | Every scenario is `kubectl scale` or pod restart. Zero DNS / network-partition / disk-pressure / clock-skew / kubelet / etcd faults. Real on-call is dominated by these. (Phase D11) |
| **No orphan / unreported faults**                 | Every `ticket_worthy` window has a paired Jira entry. We cannot tell whether the model is detecting genuine anomalies or just memorizing Jira patterns. (Phase D12) |

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
| System-level fault scenarios   | 0        | >=14      | inf    |
| Orphan ticket_worthy windows (no Jira) | 0 | >=200    | inf    |

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

## Phase D11 - System / infrastructure-level fault injection
**Goal:** v4-large faults are application-level - `kubectl scale to 0`,
pod restart, app config change. Real on-call queues are dominated by
infrastructure faults the application code never sees directly: DNS,
network partition, disk pressure, clock skew, kubelet, etcd, container
runtime. Without these, the model never learns the signature of an
infrastructure-class incident, and the dataset stays unrealistic.

### Tooling

- [ ] **D11.1** Install chaos-mesh in the kind cluster. It ships
      declarative CRDs (`NetworkChaos`, `IOChaos`, `StressChaos`,
      `TimeChaos`, `PodChaos`, `DNSChaos`, `KernelChaos`) and runs
      cleanly on kind. Litmus is the alternative; chaos-mesh has
      better tooling. Add `scripts/research-lab/install-chaos-mesh.ps1`.
- [ ] **D11.2** Authoring schema extension. Add an optional
      `system_fault` block to scenario YAML referencing a chaos-mesh
      experiment manifest (path or inline). Update `run-scenario.ps1`
      to apply the experiment at the same point in the lifecycle where
      app-level faults are currently applied, and clean it up at
      teardown. Keep the existing `fault` block for app-level scenarios;
      a scenario can have one or both.

### Network faults (NetworkChaos / DNSChaos)

- [ ] **D11.3** `dns-coredns-down-60s` (ticket_worthy). Kill CoreDNS
      pod for 60 seconds. Affects every service's DNS resolution -
      one of the most important infrastructure faults to recognize.
- [ ] **D11.4** `network-partition-cart-redis` (ticket_worthy).
      Partition `cartservice` from `redis-cart`. Mimics a real
      network split inside the cluster.
- [ ] **D11.5** `packet-loss-frontend-30pct-90s` (borderline).
      30% packet loss on frontend ingress; some users see retries,
      most don't.
- [ ] **D11.6** `network-latency-add-500ms-currency` (ticket_worthy).
      Inject 500ms latency on egress from `currencyservice`. Will
      ripple into checkout latency.

### Disk faults (IOChaos)

- [ ] **D11.7** `disk-read-latency-paymentservice-50ms` (borderline).
- [ ] **D11.8** `disk-full-frontend-pv` (ticket_worthy). Fill the
      PV to 100%; observe cascading write failures.

### Memory / CPU faults (StressChaos)

- [ ] **D11.9** `node-memory-pressure-eviction` (ticket_worthy).
      Pressure a node to trigger pod eviction.
- [ ] **D11.10** `cpu-throttle-recommendationservice-80pct` (borderline).
      Sustained CPU throttling.

### Time faults (TimeChaos)

- [ ] **D11.11** `clock-skew-cartservice-5min` (borderline).
      Skew system time forward 5 minutes; tests cert / token validation
      paths. Often produces strange-looking but recoverable errors.

### Pod-level faults (PodChaos beyond `kubectl scale`)

- [ ] **D11.12** `pod-kill-not-graceful-paymentservice` (ticket_worthy).
      SIGKILL instead of SIGTERM. Different log + trace signature than
      the existing `pod-restart-major` family.

### Control-plane faults (more invasive, optional stretch)

- [ ] **D11.13** `kubelet-restart-worker-node` (ticket_worthy).
      Restart kubelet on one worker. Brief API-server connectivity loss.
- [ ] **D11.14** `etcd-slow-100ms` (ticket_worthy). Inject latency into
      etcd. Affects every Kubernetes op cluster-wide.

### Dataset hygiene

- [ ] **D11.15** Two new scenario family slots in
      `SCENARIO_FAMILIES`: `network-fault` and `infra-fault`. Network
      faults cluster together (DNS, partition, packet loss, latency),
      infra faults cluster together (disk, memory, time, kubelet, etcd).
- [ ] **D11.16** Update `triage_labels.py` `FAULT_TYPE_COMPATIBILITY`
      to know that, e.g., a `network-latency` window is fault-compatible
      with an `application-latency` window (same observable symptom, but
      different root cause). This affects `window-memory-matchings`
      ground truth.

**Acceptance:**
- At least 10 of the 12+2 system-fault scenarios above run end-to-end
  on the kind cluster without breaking the rest of the lab.
- At least 800 windows in v5 carry system faults.
- System-fault windows are distinguishable from app-fault windows in
  feature space (e.g., `k8s_warning_event_count` distribution differs
  significantly, measured with KS test p < 0.05).

**Jira utilization:** these faults DO get Jira tickets - the on-call
team would file them. Same shadow-jira generator as app-faults. (D12
covers the case where they do NOT get tickets.)

**Status:** not started.
**Blocks:** D12 reuses these injectors for orphan-fault windows. Some
D11 scenarios (e.g., `node-memory-pressure-eviction`) benefit from
Phase D3 extended windows.

---

## Phase D12 - Unreported / orphan faults (real fault, no Jira ticket)
**Goal:** test whether the system catches genuine anomalies, or just
memorizes Jira-matched patterns. Inject real faults BUT gate the
shadow-jira generator OFF so no memory entry is produced for the
episode. The window is gold-labeled `ticket_worthy` (because a senior
engineer would file a ticket if they noticed), but has NO corresponding
Jira issue in the memory corpus.

This is the **inverse of D7.3** (false-alarm Jira: memory exists but
shouldn't match anything). Together they probe the two failure modes
of a Jira-as-memory system:

| Failure mode                       | What's wrong            | Probe          |
| ---------------------------------- | ----------------------- | -------------- |
| Retrieval over-fires on irrelevant memory | False-positive cite | D7.3 (false-alarm) |
| Detection under-fires on un-memoried fault | False-negative triage | D12 (this phase) |

Expected model behavior:
- A model that ONLY learned Jira patterns will **fail to flag** orphan
  faults (under-recall). The Jira-features (Phase 0.5) will all sit
  near zero on orphan windows; if those features carry the bulk of the
  decision weight, the model will stay silent.
- A model that learned genuine telemetry signal will **still flag**
  orphan faults, correctly mark them `is_novel=true`, and the
  citation field will say "novel pattern, no memory match".

### Design

- [ ] **D12.1** Scenario schema: new optional field
      `produces_jira_ticket: false` (default `true`). The collection
      script honors this and skips shadow-jira generation for the
      episode. The episode + telemetry windows are still recorded,
      but no row is added to `jira_shadow_issues.jsonl`.
- [ ] **D12.2** Author 8-12 orphan-fault scenarios mixing app-level
      (from D1 / D2 base catalog) and system-level (from D11). Roughly
      half should be **near-twin orphans** (the fault type and affected
      service ALSO appear in reported scenarios elsewhere in the
      corpus - tests pure generalization) and half **far orphans**
      (fault type and/or affected service never appears in any Jira
      ticket - tests truly out-of-distribution detection).
- [ ] **D12.3** Build-pipeline propagation. Set a new window field
      `expected_in_memory: false` on every window from an orphan
      episode. `build-window-memory-matchings.py` recognises this and
      forces `matched_memory_issue_ids = []` and `is_novel = true` in
      the ground truth.
- [ ] **D12.4** Triage labels for orphan windows are still computed
      the normal way: `ticket_worthy` for the active fault window,
      `noise` for `pre_fault_baseline`, etc. The whole point is that
      these LOOK ticket_worthy by signal even though no human filed.
- [ ] **D12.5** New evaluation slice: `orphan_ticket_worthy`. Reported
      via the comparison framework's stratified metrics, sliced on
      `expected_in_memory == false`.
- [ ] **D12.6** Headline metric: **orphan-detection recall gap** =
      (recall on reported ticket_worthy) - (recall on orphan
      ticket_worthy). Per pipeline. A gap > 20pts means the pipeline
      relies on Jira pattern matching; a gap < 10pts means the
      pipeline learned the underlying anomaly signal. This metric
      goes into the headline table for every Phase 0.5+ benchmark.
- [ ] **D12.7** Adversarial twin pairs. For at least 4 of the orphan
      scenarios, also collect a paired *reported* episode with the
      identical fault, identical service, identical timing, but
      `produces_jira_ticket: true`. This lets us compute the per-window
      delta directly: same fault, same telemetry, only difference is
      "Jira entry exists or not". Cleanest possible ablation of
      Jira-reliance.

### Orphan-fault catalog (initial)

Near-twin orphans (fault type already in corpus, just no ticket):
- `orphan-cart-redis-degradation-critical` (twin of `cart-redis-degradation-critical`)
- `orphan-paymentservice-pod-restart-major`
- `orphan-frontend-pod-restart-major`
- `orphan-productcatalog-latency-major`

Far orphans (fault type or service unseen in any Jira):
- `orphan-dns-coredns-down-60s` (system fault; nobody filed)
- `orphan-clock-skew-cartservice-3min`
- `orphan-disk-throttle-recommendationservice`
- `orphan-emailservice-flake-major` (new service that has no prior
  Jira tickets in the corpus at all)

### Expected research finding

If the orphan-detection recall gap is small (< 10pts), the system is
genuinely useful for catching unreported anomalies - a significant
product claim. If it is large (> 20pts), we have honest evidence that
the Jira-as-memory architecture is doing pattern matching rather than
detection, which is a useful negative finding worth publishing in its
own right.

**Acceptance:**
- v5 corpus contains at least **200 orphan `ticket_worthy` windows**
  across at least 8 orphan scenarios, with at least 4 adversarial
  twin pairs (D12.7).
- Every orphan window correctly produces `expected_in_memory = false`
  in the derived per-window matchings.
- Every orphan window correctly produces `is_novel = true` in any
  analyzer output.
- The comparison report includes the **orphan-detection recall gap**
  for every registered pipeline, headlined alongside PR-AUC.

**Jira utilization:** these windows have NO Jira entries by design.
Their `jira_*` features will all be near-zero. The system must triage
them on signal features alone. This is the most direct test of the
"memorization vs detection" question that the Jira-as-memory
principle implicitly raises.

**Status:** not started.

---

## Phase D13 - Production-realistic instrumentation (logs + traces + metrics)
**Goal:** today's Online Boutique services emit thin telemetry. cartservice
has zero OpenTelemetry coverage; the rest emit only auto-generated gRPC
RPC envelope spans with no internal structure, no `RecordError` on handler
failures, and zero application-level Prometheus metrics. This is the
single biggest dataset-quality lever we have not pulled.

Full design lives in `microservice-changes.md`. Actionable execution plan
lives in `microservice-changes-todo.md`. M0 decisions are recorded in
`docs/telemetry-implementation-decisions.md`.

- [x] **D13.1** Phase M0 decisions (interceptor placement, fork policy,
      registry, collector/Loki sizing, fidelity disclosure).
- [x] **D13.2** Phase M1.1: cartservice (.NET) OTel parity — packages,
      Startup.cs wiring, deployment patch entry, Redis instrumentation.
      This is the **highest-leverage single change in the entire D13**;
      it makes the cart-redis fault family (720 windows in v4-large)
      visible in traces for the first time.
- [x] **D13.3** Phase M1.2: adservice (Java) OTel agent in Dockerfile.
- [x] **D13.4** Phase M1.3: shippingservice (Go) OTel wiring.
- [x] **D13.5** Phase M2.1: shared per-RPC structured logging interceptor
      in Go, .NET, Node, and Python (Java covered by the agent's span
      output; manual Logback-encoder work deferred).
- [x] **D13.6** Phase M2.2: cartservice→Redis dependency-boundary error
      logs. Other services covered by M2.1 client interceptor.
- [x] **D13.7** Phase M3.1: RecordException + db.* tags fleetwide.
      Cartservice (Redis), checkoutservice (PlaceOrder + 6 dep helpers
      via recordDepError), frontend (renderHTTPError funnel),
      productcatalogservice (NotFound), shippingservice (item_count attr),
      paymentservice (invalid/unsupported/expired card paths via
      recordChargeError), currencyservice (Convert catch), recommendationservice
      (productcatalog dep call), emailservice (template + send errors).
- [x] **D13.8** Phase M3.4: documented the 100% sampling divergence in
      this doc, in `docs/dataset-v4-plan.md`, and in
      `docs/telemetry-implementation-decisions.md` M0.6.
- [x] **D13.9** Phase M4.1+M4.2+M4.3+M4.4 fleetwide:
      - Go shared rpclog package emits RED metrics + client metrics from
        the same interceptor (rpc_server_duration_seconds,
        rpc_server_requests_total, rpc_client_duration_seconds,
        rpc_client_errors_total).
      - `rpclog.InitMetrics()` helper installed in checkoutservice,
        frontend, productcatalogservice, shippingservice (port 9100).
      - cartservice exposes `/metrics` via OpenTelemetry.Exporter.Prometheus.AspNetCore.
      - paymentservice + recommendationservice: PrometheusMetricReader added.
      - Business-event counters: `orders_placed_total`+`order_value_units_total`
        (checkoutservice), `http_requests_total` (frontend),
        `catalog_lookups_total` (productcatalogservice),
        `cart_operations_total` (cartservice), `payments_total` (paymentservice),
        `recommendations_served_total` (recommendationservice).
- [x] **D13.10** Phase M5.1: validation script
      `scripts/research-lab/validate-cartservice-telemetry-upgrade.ps1`
      + companion Python evaluator. **User must run this before D13.11.**
- [x] **D13.11** Phase M2.3 business event logs: order_placed
      (checkoutservice), cart_size_changed (cartservice), payment_charged
      (paymentservice), recommendation_returned (recommendationservice),
      currency_conversion_completed (currencyservice).
- [x] **D13.12** Phase M3.3 span events: catalog.reload span event in
      productcatalogservice (the only real resilience-pattern code path
      in Online Boutique).
- [ ] **D13.13** Gate: M5.1 PASS required. Criterion: `trace_error_count`
      newly fires on cartservice active_fault windows (pilot nonzero_frac
      >= 0.5; baseline < 0.1). If FAIL, debug M1.1 wiring before continuing.
- [ ] **D13.14** Phase M5.2: collect v5 with the upgraded telemetry.
      Documented build-context fixes are in
      `docs/telemetry-implementation-build-notes.md`.
- [ ] **D13.15** Apply M0.4 collector capacity bumps (replicas=2,
      memory=2Gi, batch=16k) and M0.5 Loki sizing (120 GB PVC, 1 TB disk)
      before launching the full v5 sweep.
- [ ] **D13.16** Cherry-pick upstream Google microservices-demo changes
      from `master` into the fork per M0.2 quarterly cadence. First
      cherry-pick should land before D13.14.

**Acceptance:**
- D13.11 GATE passes.
- Every test-fixture RPC produces one L1 log line per direction.
- Every error path produces both an L2 log AND a `RecordException` span event.
- `curl <service>:<port>/metrics` returns RED + runtime metrics for every
  service.
- `promtool check metrics` clean — no unbounded cardinality.
- `validate-run-feature-distribution.py` shows no new feature column
  perfectly correlated with `scenario_id`, `scenario_family`, or
  `triage_label` (leakage canary).

**Status:** D13.1-D13.12 complete (all code changes); D13.13 (gate)
pending user run; D13.14-D13.16 pending gate result + cluster access.
**Blocks:** D4 (v5 collection) should use the upgraded telemetry; this
phase lands before D4.

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
| D-3.5  | **D11 tooling + D12 schema + D13 telemetry M1-M3** | 5-6 dev days | nothing (chaos-mesh install + scenario schema + cartservice OTel) |
| D-3.6  | **D13 M5.1 gate (cartservice validation)** | 0.5 VM day | D-3.5 done |
| D-4    | D4 pilot     | 1 VM day            | D1, D2, D3, D11.1-2, D13 gate PASS |
| D-5    | D4 full      | 4-5 VM days         | D-4 passes      |
| D-6    | D5, D11, D12 collection | 2 author + 2 VM days | D-5 done; D11 tooling ready |
| D-7    | D6           | 5 dev + 2 VM days   | D-5 done        |
| D-8    | D8           | 2 dev + 1 VM day    | D-5 done        |
| D-9    | D9           | 2 research days     | D-5 done        |
| D-10   | D10          | 1 dev day           | D-5 done        |

D-1, D-2 and D-3.5 are pure-thinking-and-writing-and-tooling sprints -
they can start today and run in parallel with the existing `todo.md`
Phase 1 (real embeddings) work, which doesn't need new data.

System-fault scenarios (D11) and orphan-fault scenarios (D12) are
collected together with D5 cascades in sprint D-6, because they all
require running chaos-mesh experiments alongside the existing
fault-injection pipeline.

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
- [ ] **D11.1 + D11.2: install chaos-mesh, extend scenario schema with
      a `system_fault` block** (pure setup; no collection yet)
- [ ] **D12.1 + D12.3: add `produces_jira_ticket: false` field and
      `expected_in_memory` plumbing through the build pipeline**
      (schema work; can validate end-to-end with a single test scenario)
- [ ] **D12.6: implement orphan-detection recall gap metric in
      `src/comparison/stratified.py`** (can be tested on v4-large by
      synthetically marking some ticket_worthy windows as orphan and
      verifying the metric is computed correctly)

The cleanest first step is **D0.2 + D0.3** (adjudication + LLM-first
review). It unlocks the v4 contract's promise that labels are
trustworthy, which the rest of the research story depends on.

The most **research-distinctive** pair of quick wins is **D12.1 + D12.6**:
even without collecting new orphan data, defining the `produces_jira_ticket`
schema and the orphan-detection recall gap metric is the foundation for
the central question "does our system memorize Jira or detect anomalies?",
which is what makes this work different from yet-another-log-classifier.
