# Dataset v4 Plan (Jira-as-Memory)

Status: active. This is the canonical dataset plan for the current research
direction. It supersedes earlier dataset-version docs (v1, v2, v2.1, v3),
which have been removed from the repository. The triage task contract that
this plan satisfies lives in `docs/triage-task-contract.md`.

No collected data exists yet. The repository previously held v3 raw and
derived runs; those were removed in the cleanup that accompanied this plan.
The first v4 runs will be the first data on disk.

## The Product We Are Building For

The product is a **smart log analysis tool** that takes a stream of telemetry
windows and, for each window, decides:

1. is this window worth a Jira ticket?
2. if yes, which past Jira issues does this resemble?
3. if no past issues match but it still looks ticket-worthy, flag it as a
   novel incident.

The tool uses a **Jira memory corpus** as system memory. Past Jira issues are
the organizational record of what humans found important enough to track. The
tool retrieves matching memory entries to ground its decision and to provide
citations the engineer can act on.

This is fundamentally case-based: every "is this worth filing" decision is
grounded in similarity to past human decisions captured as Jira tickets. A
model that flags a window with "this looks like OBSRV-1042 from three weeks
ago, which was a Redis cart outage" is much more actionable than one that
outputs a probability.

## The Two Tasks

The dataset must support two tasks at once. They share the same telemetry
collection and Jira generation, but with additional label structure.

| Task | Question | Output |
| --- | --- | --- |
| **Triage** (primary) | Is this telemetry window worth a Jira ticket? | Calibrated probability and label decision |
| **Memory retrieval** (paired with triage) | Which past Jira issues does this window match, if any? | Ranked list of matched memory issues, plus an `is_novel` flag when nothing matches |

Both tasks are scored on every triage benchmark run.

## Dataset Structure

Every collected run produces three layers of data.

### Layer 1: Raw evidence

Lives under `data/runs/<DATASET_RUN_ID>/`. Treat as immutable evidence.

| File | Contents |
| --- | --- |
| `episodes.jsonl` | Incident or baseline episodes for this run. |
| `telemetry_windows.jsonl` | Per-window records with window type and time bounds. |
| `raw/loki/`, `raw/prometheus/`, `raw/tempo/`, `raw/kubernetes/` | Exported per-window evidence files. |
| `alerts.jsonl` | Alertmanager and Prometheus alert state. |
| `jira_shadow_issues.jsonl` | Generated Jira-shaped records for `jira_candidate` episodes. |
| `triage_window_labels.jsonl` | Per-window triage labels (the new file). Sourced from scenario YAML `triage` blocks and, where required, human adjudication. |
| `manifest.json` | Run metadata, collection timestamps, validation summary. |

### Layer 2: Derived per-run files

Lives under `data/derived/<DATASET_RUN_ID>/`. Rebuildable from raw.

| File | Contents |
| --- | --- |
| `triage_examples.jsonl` | One row per telemetry window: label, severity, components, hard-case flag, source, production-safe features. |
| `window_memory_matchings.jsonl` | One row per window with `matched_memory_issue_ids` (ground truth) and `is_novel` flag. |
| `windows.jsonl` | Window evidence summarized for model input. |
| `issues.jsonl` | Shadow Jira issues from this run, ready for the memory corpus. |

### Layer 3: Global derived files

Lives under `data/derived/global/<GLOBAL_DATASET_ID>/`. Stitches per-run data.

| File | Contents |
| --- | --- |
| `global-triage-examples.jsonl` | All triage examples across runs with scenario-family splits. |
| `jira-memory-corpus.jsonl` | Time-ordered Jira issues with `available_as_memory_from` timestamps. |
| `triage-split-manifest.json` | Train/validation/test split + leave-one-family-out folds. |
| `triage-feature-columns.json` | Production-safe numeric feature list. |
| `pipeline-input-schema.json` | Stable input contract for all pipelines. |

## The Jira Memory Corpus

The Jira memory corpus is the system memory the product retrieves from. It is
the same set of shadow Jira issues that the collection produces, indexed and
time-ordered.

Every issue in the corpus carries:

| Field | Meaning |
| --- | --- |
| `jira_shadow_issue_id` | Stable id. |
| `available_as_memory_from` | The issue's `created_at`. A window can only retrieve issues whose `available_as_memory_from` is before the window's `start_time`. This is the time-ordering rule. |
| `scenario_family` | Used for scoring memory-match quality. |
| `affected_service` | Used for scoring memory-match quality. |
| `fault_type` | Used for scoring memory-match quality. |
| `memory_text` | Text used as retrieval input. Includes summary, description, components, labels, comments, and a short telemetry summary that was attached when the issue was filed. |
| `linked_window_ids` | Telemetry windows that were on the issue when it was filed. |
| `resolution_notes` | The closing notes (synthetic but realistic — e.g. "Restarted paymentservice pods; cleared dependency outage"). |

The corpus grows monotonically. A window collected in v4 run #20 can
retrieve any issue created during v4 runs #1–#19, but not the issue from its
own run (own-run leakage is excluded).

For research with a fixed corpus (no streaming), the global corpus is the
union of all issues from all runs. Time-ordering is still enforced by the
`available_as_memory_from` field at evaluation time.

## Per-Window Memory Match Labels

Every telemetry window gets a memory-match label, computed during dataset
build, not during collection. The build script (`build_window_memory_matchings.py`)
applies these rules to compute ground truth:

| Window state | Memory match ground truth |
| --- | --- |
| Label `ticket_worthy`, scenario family seen in a prior issue | `matched_memory_issue_ids` includes all prior issues with the same scenario family AND affected service AND compatible fault type. `is_novel = false`. |
| Label `ticket_worthy`, no prior issue with matching family | `matched_memory_issue_ids = []`. `is_novel = true`. |
| Label `borderline` | `matched_memory_issue_ids` is best-effort — may include partial matches if any exist. `is_novel = false`. |
| Label `noise` | `matched_memory_issue_ids = []`. `is_novel = false`. (Noise should not retrieve anything; if a model does match noise to memory, that is a false positive cite.) |

These ground truths are not used as model inputs. They are evaluation targets
for the memory-retrieval task.

## Time-Ordering And Memory Visibility

Evaluation pipelines must respect time-ordering:

- A window queries the corpus for issues with `available_as_memory_from <
  window.start_time`.
- Issues from the same dataset run as the window are excluded from the
  visible corpus (own-run leakage).
- The visible corpus shrinks for early-run windows and grows for late-run
  windows. This is intentional: an early-run window sees a sparse memory
  (early product days); a late-run window sees a dense memory (mature
  product days). Both are evaluation conditions worth measuring.

A configuration flag `corpus_mode` controls this for ablations:

| Mode | Behavior |
| --- | --- |
| `time_ordered` | Default. Enforces time-ordering and own-run exclusion. |
| `flat` | Disables time-ordering. All issues from all runs visible. Use only as an ablation; reported scores are non-comparable with the default. |

## Scenario Families

A scenario family groups scenarios that share fault mechanism and affected
service. Used for triage holdouts and for memory-match ground-truth
computation.

The active family taxonomy (carried over from earlier scenario authoring):

| Family | Member scenarios (existing + new) |
| --- | --- |
| `payment-outage` | `paymentservice-unavailable-critical`, `paymentservice-pod-restart-major` |
| `cart-redis` | `cart-redis-degradation-critical`, `redis-cart-restart-major`, `redis-cart-intermittent-failure-major`, `redis-cart-restart-nearmiss` |
| `productcatalog-latency` | `productcatalog-latency-major`, `productcatalog-latency-nearmiss` |
| `productcatalog-outage` | `productcatalog-unavailable-critical`, `productcatalog-bad-config-critical` |
| `checkout-restart` | `checkoutservice-pod-restart-major`, `checkoutservice-partial-degradation-major` |
| `checkout-outage` | `checkoutservice-unavailable-critical` |
| `currency-outage` | `currencyservice-unavailable-major` |
| `shipping-outage` | `shippingservice-unavailable-major` |
| `recommendation-outage` | `recommendationservice-unavailable-major`, `recommendationservice-pod-restart-nearmiss` |
| `ad-outage` | `adservice-unavailable-nearmiss` |
| `frontend-restart` | `frontend-pod-restart-major` |
| `frontend-traffic-pressure` | `frontend-cpu-nearmiss`, `loadgenerator-traffic-spike-nearmiss`, `loadgenerator-noisy-high-traffic-nearmiss` |
| `baseline-normal` | `baseline-normal-traffic` |
| **New for v4** | |
| `post-deploy-churn` | rolling deploy produces brief errors and restarts without user impact |
| `recovered-in-window` | real fault that self-recovers before user impact |
| `single-pod-restart-healthy-replication` | one replica restarts, others serve traffic |
| `third-party-blip` | external dependency 5xx briefly, graceful degradation |
| `scheduled-job-spike` | cron job spike on shared resource |
| `latency-near-miss-partial-recovery` | latency exceeds soft SLO, stays under page-worthy |
| `flapping-pod` | pod restarts repeatedly, eventually customer-visible |
| `slow-leak-saturation` | memory or connection leak grows over minutes, eventually pages |

## Per-Window Triage Labels

Defined fully in `docs/triage-task-contract.md`. Summary:

| Label | Meaning |
| --- | --- |
| `ticket_worthy` | A senior engineer would file a Jira ticket. |
| `borderline` | Reasonable engineers disagree. |
| `noise` | A senior engineer would not file a Jira ticket. |

For v4, every `borderline` and `is_hard_case` window must carry
`source: human_adjudicated`. Other windows may use `scenario_authored` or
`derived` rules.

## Scenario-Family Holdouts

Default split:

| Split | Families |
| --- | --- |
| Train | 8+ families covering outages, restarts, latency, config, capacity, and false-alarm families. |
| Validation | 2 held-out families. |
| Test | 2 held-out families. |

Plus leave-one-family-out folds across every family.

Selection rules for the held-out families:

- Test must contain a mix of `ticket_worthy`, `borderline`, and `noise`.
- At least one held-out family must be noise-heavy (e.g. `post-deploy-churn`)
  to measure false-positive behavior.
- At least one held-out family must include `is_hard_case` windows.

## Label Adjudication

For every `borderline` and `is_hard_case` window:

1. Collection produces the window with `source: scenario_authored` or `derived`.
2. Reviewers open the actual telemetry exports without seeing the scenario id.
3. Reviewer records: chosen `triage_label`, severity, components, reason
   class, rationale, adjudicator id, `adjudicated_at`.
4. Two reviewers per borderline window minimum; disagreements kept as
   separate `human_adjudicated` entries.
5. Final label is majority decision; ties resolve to `borderline`.

Output of this process: a `reviewer_disagreement_rate` per scenario family.
Families above ~30% disagreement are inherently borderline and analyzed
accordingly.

## Calibration Set

A held-out collection run (not a held-out family) is reserved as the
calibration subset. It is used for:

- temperature scaling or Platt calibration of model probabilities,
- reliability-curve reporting,
- never for threshold selection (that happens on the validation split per
  the contract).

## Collection Phases

Phase A — scenario authoring (no collection):

- Author scenario YAML for the new v4 families above.
- Fill `triage` blocks for every existing scenario.
- Review the full scenario set with stakeholders.

Phase B — pilot collection (3 runs):

- Collect 3 pilot runs.
- Adjudicate every `borderline` and `is_hard_case` window.
- Iterate on scenarios that produce too-clean or too-noisy windows.

Phase C — full collection (target 24+ runs):

- Collect the full v4 corpus.
- Adjudicate borderline and hard-case windows.
- Build derived per-run files and the global dataset.

Phase D — benchmark and report:

- Run all triage pipelines on v4: rule, classical, lexical, embedding,
  language-model, hybrid.
- Run memory-retrieval pipelines: BM25, embedding kNN, hybrid.
- Publish v4 triage report with strict and inclusive borderline metrics,
  reliability curves, retrieval recall@k, and stratified metrics.

Phase order is firm. Skipping Phase A or B produces a dataset whose labels
are not trustworthy for product claims.

## Output File Inventory

After Phase C completes, the global directory will contain:

```text
data/derived/global/<GLOBAL_DATASET_ID>/
  global-triage-examples.jsonl       Per-window rows with labels and features
  jira-memory-corpus.jsonl           Time-ordered memory corpus
  window-memory-matchings.jsonl      Ground-truth match links and is_novel flags
  triage-split-manifest.json         Family-level splits and folds
  triage-feature-columns.json        Production-safe feature list
  pipeline-input-schema.json         Stable input contract
  README.md                          Dataset overview, sizes, contract pointers
  benchmarks/
    triage-baseline-v1/              First triage benchmark report
    ...
```

## Target Sizes

These are targets, subject to revision after Phase B.

| Item | Target |
| --- | ---: |
| Dataset runs | 24+ |
| Scenario families | 20+ |
| Telemetry windows | 2000+ |
| `ticket_worthy` windows | ~30% |
| `borderline` windows | 10–20% |
| `noise` windows | ≥50% |
| `is_hard_case` windows | ≥15% |
| Jira memory corpus entries | 400+ |
| `human_adjudicated` windows | 100% of borderline and hard cases |

## Current Limitations / Production Fidelity

These are known divergences from production telemetry, recorded so dataset
consumers can calibrate generalization expectations. The full draft list
lives in `docs/telemetry-implementation-decisions.md` M0.6 (added by Phase
M3.4 of `microservice-changes-todo.md`).

- **Trace sampling is 100% (`AlwaysSample`).** Real production deployments
  typically head-sample at 1-10% or tail-sample on errors/latency. Models
  trained here may over-rely on span fan-out features that would be partly
  missing under production sampling. We chose dataset density over sampling
  realism.
- Single-cluster, single-region; synthetic traffic patterns; synthetic Jira
  issues; one fault per run. See the linked decision doc for the full
  enumeration.

## Open Questions

These need answers before Phase A finalizes.

1. **Adjudication staffing.** Who reviews? At least two reviewers per
   borderline window is required. Options: rotate across team; bring in
   external on-call engineer; use an LLM as a tie-breaker reviewer (with
   sampled human spot-checks).
2. **Real-world reference traces.** Can we obtain anonymized production
   traces to validate that v4's noise families resemble production noise?
   Without this we calibrate against our own assumptions.
3. **Slow scenarios.** `slow-leak-saturation` may need windows much longer
   than 5–10 minutes. The collection pipeline currently assumes short
   windows.
4. **Cross-cluster scenarios.** v4 stays single-cluster; cross-cluster
   incidents deferred to v5.
5. **LM cost.** v4 is sized so an LM zero-shot baseline over the full
   dataset is affordable. Confirm cost before committing to final size.
6. **Memory text shape.** What exactly goes into `memory_text` for each
   Jira issue? Summary + description + first comment is a reasonable start;
   adding the closing comment leaks "this was a real incident" signal that
   wouldn't be available at decision time in production. Pilot in Phase B.
