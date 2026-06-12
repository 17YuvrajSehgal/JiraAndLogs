# Triage Task Contract

The triage task is the primary product task for this project. Given a telemetry
window, the system must decide whether the window is worth a Jira ticket, and
if so, draft a ticket-shaped record explaining the decision.

This document defines the input, the label space, the metrics, the split
rules, and the production-safe field policy. It is the stable contract that
dataset builders, schemas, and pipelines must agree on.

For project background, read `docs/research-project-onboarding-guide.md` first.
For the secondary retrospective-ranking task, see
`docs/ml-ai-pipeline-benchmark-plan.md`.

## What Problem We Are Solving

Large companies generate continuous telemetry. Engineers cannot read every
log line, alert, or trace. Existing tools (Datadog, PagerDuty, Splunk) surface
anomalies, but the decision "is this worth tracking in Jira" still falls on
humans. That decision is the bottleneck. A useful product must:

- accept a telemetry window as input,
- output a calibrated decision: ticket-worthy, borderline, or noise,
- explain the evidence that drove the decision,
- on ticket-worthy windows, draft a Jira-shaped record (summary, components,
  severity, affected service, evidence links).

The triage task is harder than alerting because it must absorb the false
positives that current alerting systems push to humans.

## The Jira-as-Memory Architecture

The dataset is designed to support a product architecture where past Jira
issues are the **system memory**. The model does not learn a fixed mapping
from telemetry to "ticket-worthy" in isolation; it grounds each decision in
similarity to past tickets the organization actually filed.

At decision time, for a new telemetry window, the product:

1. retrieves matching past Jira issues from a time-ordered memory corpus,
2. uses the matches as evidence for its triage decision,
3. when it decides ticket-worthy, cites the matches the engineer can review,
4. when nothing in memory matches but it still decides ticket-worthy, flags
   the window as a novel incident.

This means the dataset must provide three things on top of standard triage
labels:

- a **time-ordered Jira memory corpus** with `available_as_memory_from`
  timestamps,
- per-window **ground-truth memory-match labels** (`matched_memory_issue_ids`
  and `is_novel`),
- evaluation metrics for both classification quality and retrieval quality.

See `docs/dataset-v4-plan.md` for how the corpus and match labels are built.

The retrieval is not the task — it is the architecture. The task remains
"decide whether this window is worth a Jira ticket". Architecture-free
classifiers (no retrieval, just features) are valid baselines and must be
reported as such.

## Task Definition

Input:

- one telemetry window with logs, metrics, traces, and Kubernetes state,
- optional preceding baseline window evidence for delta computation,
- production-safe features only (see "Field Policy" below).

Output:

- a calibrated probability `p_ticket_worthy` in `[0, 1]`,
- a label decision at one or more operating points,
- ranked evidence references that explain the decision,
- on ticket-worthy windows, a draft ticket structure following
  `schemas/jira_shadow_issue.schema.json`.

The first benchmark only requires the probability and label decision. The
ticket draft is a secondary task scored separately.

## Label Space

Every telemetry window receives one of three labels.

| Label | Meaning | Examples |
| --- | --- | --- |
| `ticket_worthy` | A senior engineer would file a Jira ticket if they saw this. | Payment service outage during checkout, Redis cart degradation, customer-visible latency regression, bad config causing failures. |
| `borderline` | Reasonable engineers would disagree. The fault recovered before user impact, or impact is small enough that filing is judgement-dependent. | Single-pod restart with healthy replication, brief latency spike that self-recovered, partial degradation under low traffic. |
| `noise` | A senior engineer would not file a Jira ticket. Includes normal behavior and near-miss patterns. | Baseline normal traffic, post-deploy churn that settled, high traffic without user impact, transient third-party blip. |

Three label classes — not two — are intentional. A binary task forces every
edge case into a wrong bucket. `borderline` lets us measure how a model handles
uncertainty without penalizing it for refusing to commit on genuinely
ambiguous windows.

## Severity And Components

For windows labeled `ticket_worthy`, the dataset additionally records:

| Field | Meaning |
| --- | --- |
| `triage_severity` | `minor` / `major` / `critical` — matches the existing scenario severity vocabulary. |
| `triage_components` | List of Jira components the ticket would carry (e.g. `paymentservice`, `checkoutservice`). |
| `triage_reason_class` | One of `outage`, `latency_regression`, `restart_with_impact`, `bad_config`, `capacity`, `dependency_failure`, `data_consistency`. |

These fields enable secondary tasks (severity classification, component
prediction, ticket drafting) without requiring a new dataset pass.

For windows labeled `borderline` or `noise`, these fields are `null`.

## Hard Case Flag

Each window also carries:

- `is_hard_case` (boolean): true when the window is intentionally designed
  to confuse simple models (e.g. restart vs. outage, near-miss vs. real
  incident, root-cause service vs. downstream symptom service).

`is_hard_case` is for analysis and stratified metrics. It must not be used as
a model input.

## Label Sources

Every label has a recorded source:

| Source | Meaning |
| --- | --- |
| `scenario_authored` | Label comes from the scenario YAML — the scenario author declared the expected per-window triage outcome. |
| `human_adjudicated` | Label was reviewed and possibly overridden by a human reviewer after looking at the actual collected telemetry. |
| `derived` | Label was generated by a deterministic rule from existing scenario fields (`jira_candidate`, `severity`, `window_type`). Used as the v3 default until scenarios are extended. |

For v3, most labels will be `derived` from the existing scenario fields. The
contract permits this. For v4, every `borderline` and `is_hard_case` window
must be `human_adjudicated`.

## Where Labels Live

| Location | Purpose |
| --- | --- |
| `deploy/research-lab/scenarios/**/*.yaml` | Source of truth for `scenario_authored` labels (see Scenario YAML section). |
| `data/runs/<run>/triage_window_labels.jsonl` | Per-window labels recorded during collection, including any human adjudication. |
| `data/derived/<run>/triage_examples.jsonl` | Per-window rows with labels and production-safe features for model training. |
| `data/derived/global/<global>/global-triage-examples.jsonl` | Global triage corpus across runs. |
| `schemas/triage_window_label.schema.json` | JSON Schema for the label record. |

## Scenario YAML Extension

Scenarios add an optional top-level `triage` block:

```yaml
triage:
  schema_version: 1
  per_window:
    pre_fault_baseline:
      triage_label: noise
      triage_severity: null
      triage_components: null
      triage_reason_class: null
      is_hard_case: false
      rationale: "Pre-fault baseline; no injected fault."
    active_fault:
      triage_label: ticket_worthy
      triage_severity: critical
      triage_components: [paymentservice, checkoutservice]
      triage_reason_class: dependency_failure
      is_hard_case: false
      rationale: "Customer-visible checkout failures during payment outage."
    recovery_window:
      triage_label: borderline
      triage_severity: minor
      triage_components: [paymentservice]
      triage_reason_class: dependency_failure
      is_hard_case: true
      rationale: "Recovery may still show residual errors depending on rollout speed."
```

Scripts that do not understand `triage:` must ignore it. The block is purely
additive.

For baseline and near-miss scenarios, all per-window labels default to
`noise` unless the scenario author explicitly marks otherwise.

## Field Policy

The same production-safety rules from the ranking benchmark apply here.

Production-facing models must not consume:

- `scenario_id`,
- `incident_type`,
- `root_cause_category`,
- `severity` (the lab-authored one),
- `jira_candidate` (the lab-authored one),
- `triage_label` (this is the target, not a feature),
- `triage_severity`, `triage_components`, `triage_reason_class` (also targets),
- `is_hard_case`,
- any field under `ground_truth`.

These fields are eval-only.

Allowed inputs include logs, metrics, traces, Kubernetes events, deployment
state, alert state, and any deterministic features derived from them.

Label-aware sanity-check models are permitted but must be flagged in
`benchmark-report.md` and excluded from product claims.

## Split Rules

Triage benchmarks must hold out scenario families, not individual runs.

A scenario family groups scenarios that share fault mechanism and affected
service. Examples:

| Family | Member scenarios |
| --- | --- |
| `payment-outage` | `paymentservice-unavailable-critical`, `paymentservice-pod-restart-major`. |
| `cart-redis` | `cart-redis-degradation-critical`, `redis-cart-restart-major`, `redis-cart-intermittent-failure-major`, `redis-cart-restart-nearmiss`. |
| `productcatalog-latency` | `productcatalog-latency-major`, `productcatalog-latency-nearmiss`. |

Default split:

- train on at least three families,
- validate on one held-out family,
- test on one held-out family,
- additionally report leave-one-family-out macro metrics for every family.

Per-run holdout (the ranking benchmark's split rule) is too easy for triage
because a model can memorize fault signatures across runs of the same family.

## Metrics

The triage task is a calibrated classification, not a ranking. Required
metrics:

| Metric | Why |
| --- | --- |
| Precision@FPR=1% | Headline metric. Models a low-false-alarm operating point. Direct measure of "would this product page engineers for nothing". |
| Precision@FPR=5% | Secondary operating point. Useful for less critical environments. |
| Recall@FPR=1% | What fraction of real tickets we catch at the headline operating point. |
| PR-AUC | Calibration- and threshold-free quality. Robust to class imbalance, which matters because `ticket_worthy` is the minority class. |
| ROC-AUC | Comparable across datasets with different base rates. |
| Reliability curve | Plot of predicted probability vs. observed positive rate, with Expected Calibration Error. Required for ticket-worthy probabilities to be usable downstream. |
| Cost-weighted F-beta (β=2) | F-beta with β=2 weights recall over precision, matching the cost asymmetry: missing a real incident is worse than one false alarm. |

Borderline handling:

- A strict metric variant counts `borderline` as negative and computes
  precision against `ticket_worthy` only.
- An inclusive metric variant counts `borderline` as positive and rewards
  models that surface anything human-interesting.
- Both variants must be reported. The strict variant is the headline.

Stratified metrics (recommended):

- by scenario family,
- by `is_hard_case` (true / false),
- by `triage_reason_class`,
- by affected service,
- by `is_novel` (true vs false) — novel-incident behavior is a distinct
  product axis.

## Memory-Retrieval Metrics

For pipelines that use the Jira memory corpus, the following retrieval
metrics are required alongside the classification metrics above.

| Metric | Why |
| --- | --- |
| Recall@k of matched issues | For `ticket_worthy` windows with a non-empty `matched_memory_issue_ids` ground truth, did the system retrieve at least one correct match in the top k? Report for k in {1, 3, 5}. |
| Cite precision | Of the issues the model cited for a ticket-worthy window, what fraction share scenario family + affected service + fault type with ground truth? |
| Novel-incident detection rate | For windows with `is_novel = true`, did the system correctly decline to cite memory issues? A model that always cites something fails this. |
| Time-ordering compliance | Audit metric: did the model only retrieve issues with `available_as_memory_from < window.start_time` and from a different `dataset_run_id` than the window? |

For pipelines that do not consume the memory corpus (pure classifiers, the
baseline track), the retrieval metrics are reported as `n/a`. This is a
valid baseline approach and must be reported as such.

## The Ticket Draft Subtask

For windows scored `ticket_worthy`, models may additionally produce a draft
ticket. Scoring:

| Field | Metric |
| --- | --- |
| `summary` | ROUGE-L vs. scenario `summary_template`, plus optional human eval. |
| `components` | Set-F1 against `triage_components`. |
| `severity` | Accuracy and macro-F1 against `triage_severity`. |
| `triage_reason_class` | Accuracy against `triage_reason_class`. |

The ticket draft task is optional in the first triage benchmark. It becomes
required when triage classification metrics plateau and we shift focus to
ticket quality.

## Operating Point Selection

Pipelines must report metrics at thresholds chosen on the validation set, not
the test set. Recommended procedure:

1. Train the pipeline on train splits.
2. On the validation split, sweep thresholds and record FPR-vs-precision.
3. Pick the smallest threshold whose validation FPR is at or below 1%.
4. Apply that threshold to the test split.
5. Report test-split precision, recall, and F-beta at that threshold.

Threshold leakage from test back to threshold selection is a common error.
The benchmark harness must enforce this.

## Reproducibility

Build the per-run triage dataset:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-triage-dataset.ps1 `
  -DatasetRunId "<DATASET_RUN_ID>" `
  -Force
```

Build the global triage dataset:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-global-triage-dataset.ps1 `
  -DatasetRunPrefix "<CORPUS_PREFIX>" `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -Force
```

Run the triage benchmark:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\run-triage-benchmark.ps1 `
  -GlobalDatasetId "<GLOBAL_DATASET_ID>" `
  -BenchmarkId "triage-baseline-v1" `
  -Force
```

These scripts are part of Phase 2 of the triage rollout (see
`docs/dataset-v4-plan.md`). They do not yet exist; this contract defines what
they must produce.

## Acceptance Gates For The First Triage Benchmark

A triage benchmark report is acceptance-ready when:

- All windows in the global triage dataset have a label and a label source.
- At least 20% of windows are `noise` and at least 5% are `borderline`.
- At least three scenario families exist in train, one in validation, one in
  test, and no family appears in more than one split.
- Operating-point thresholds are selected on the validation split only.
- Strict and inclusive borderline metrics are both reported.
- Reliability curve and Expected Calibration Error are reported for every
  pipeline.
- Stratified metrics by `is_hard_case` are reported.
- No production-facing model consumes any field listed in "Field Policy" as
  eval-only.

## Out Of Scope

The triage task explicitly does not:

- write to real Jira,
- trigger pages,
- close existing tickets,
- act on production systems without human approval.

Those actions are downstream of triage and live in later product phases.