# Real-Data Evaluation Plan — World of Logs (WoL) as a Real-Jira Corpus

**Status.** Plan v3 (drafted 2026-06-11). Supersedes v2 (2026-06-11) and v1 (2026-06-10) — see §1.2 below for the changelog.

**Owner.** Yuvraj Sehgal.

**Parent claim being supported.** The ICSE submission's §8 (Threats to Validity) and §10 (Conclusion) both call out the synthetic humanized memory corpus as a real external-validity gap. WoL is the right instrument for closing *part* of that gap. With the addition of TCH-Lite as a log-only deployment configuration of the cascade (see [`docs7/TCH-Lite.md`](TCH-Lite.md)), WoL gains a genuine end-to-end role rather than only a distractor / novelty stand-in.

**Companion documents.** [`docs7/TCH-Lite.md`](TCH-Lite.md) for the log-only cascade configuration this plan now relies on; [`docs4/X_FINAL_TCH_CASCADE.md`](../docs4/X_FINAL_TCH_CASCADE.md) for the full cascade we contrast against; [`docs6/pipeline-2-BiEncoder.md`](../docs6/pipeline-2-BiEncoder.md) and [`docs6/pipeline-6-KGRetrieval.md`](../docs6/pipeline-6-KGRetrieval.md) for the pipelines whose inputs we're constructing; the WoL paper at `data/17569722/Xiaohui_MSR_2026.pdf` for the source dataset.

---

## Table of contents

1. [Executive summary and what changed across versions](#1-executive-summary-and-what-changed-across-versions)
2. [The validity problem v1 missed (preserved for reference)](#2-the-validity-problem-v1-missed-preserved-for-reference)
3. [What WoL can and cannot supply](#3-what-wol-can-and-cannot-supply)
4. [The four evaluation modes](#4-the-four-evaluation-modes)
5. [Mode 1 — WoL as a real distractor pool](#5-mode-1--wol-as-a-real-distractor-pool)
6. [Mode 2 — Cross-domain novelty validation](#6-mode-2--cross-domain-novelty-validation)
7. [Mode 3 — TCH-Lite end-to-end on self-contained WoL retrieval (PROMOTED)](#7-mode-3--tch-lite-end-to-end-on-self-contained-wol-retrieval-promoted)
8. [Mode 4 — Bookmarked: WoL Kafka × OTel Demo Kafka](#8-mode-4--bookmarked-wol-kafka--otel-demo-kafka)
9. [Project selection for each mode](#9-project-selection-for-each-mode)
10. [Semantic mapping — WoL fields to our schemas](#10-semantic-mapping--wol-fields-to-our-schemas)
11. [Priority normalization table](#11-priority-normalization-table)
12. [Directory layout under `data/`](#12-directory-layout-under-data)
13. [The extraction pipeline](#13-the-extraction-pipeline)
14. [Phased delivery plan](#14-phased-delivery-plan)
15. [Evaluation matrix and acceptance criteria](#15-evaluation-matrix-and-acceptance-criteria)
16. [Risks and explicit limitations](#16-risks-and-explicit-limitations)
17. [Reproducibility and provenance](#17-reproducibility-and-provenance)
18. [Decision gates](#18-decision-gates)

---

## 1. Executive summary and what changed across versions

### 1.1 Plan summary in one paragraph

We use WoL JIRA in three methodologically valid ways. (1) **WoL records from off-topic projects become a real-language distractor pool** for the §13.1 robustness sweep — they are real, engineer-written, and *unambiguously not gold* for any of our synthetic windows. (2) **WoL records' extracted log messages become out-of-distribution query windows** for the cascade's L3 novelty layer — every such query has a structurally correct gold answer (`is_novel=true`). (3) **WoL JIRA becomes the memory-and-query corpus for an end-to-end TCH-Lite retrieval evaluation** under an inferred match relation — both sides of the retrieval are real engineer-written text, the input modality matches TCH-Lite's expectations (log-only, no telemetry channels), and the cascade is in its intended deployment configuration. Mode 3 is the load-bearing real-data result; Modes 1 and 2 are reinforcement. A fourth mode (WoL Apache Kafka × OTel Demo Kafka) is bookmarked and blocked on the GCP cross-app collection.

### 1.2 Changelog across plan versions

**v1 (2026-06-10).** Headlined "Mode A: replace 347 synthetic memory tickets with 350 WoL tickets, keep synthetic windows, measure Hit@K." Retired in v2 because no semantic match exists between synthetic Online Boutique windows and WoL Apache Spark/Cassandra tickets; Hit@K against WoL memory would have measured fabrication rather than retrieval correctness.

**v2 (2026-06-11).** Replaced Mode A with three smaller modes (distractor pool, cross-domain novelty, deferred self-contained WoL→WoL retrieval). Removed the false-headline retrieval transfer claim. Modes 1 and 2 critical path; Mode 3 deferred; Mode 4 bookmarked.

**v3 (2026-06-11, current).** Promotes Mode 3 to critical path **because the introduction of TCH-Lite ([`docs7/TCH-Lite.md`](TCH-Lite.md)) makes it methodologically clean.** TCH-Lite is the cascade configuration designed for log-only deployments — WoL is a log-only dataset — so TCH-Lite × WoL is a natural fit where TCH-Combined × WoL was not. Mode 3 becomes the strongest real-data headline in the paper. Modes 1 and 2 stay as reinforcement.

The v2 directory layout (§12), schema mapping (§10), priority normalization (§11), and reproducibility discipline (§17) are preserved without change — those parts of the plan were not affected by the v2→v3 reframe.

### 1.3 The relationship with TCH-Lite

This plan and `TCH-Lite.md` are siblings, not nested. TCH-Lite specifies *how to construct a log-only deployment configuration of the cascade*; this plan specifies *what we do with WoL data*. They intersect at Mode 3: TCH-Lite is the cascade configuration we evaluate on the WoL-self-contained retrieval task. If TCH-Lite is not built, Mode 3 stays deferred (returning to the v2 framing). If TCH-Lite is built, Mode 3 becomes the critical-path real-data headline.

---

## 2. The validity problem v1 missed (preserved for reference)

To make sure this does not repeat downstream, the problem is worth stating in one place precisely.

The cascade's retrieval task is: *given a telemetry window, return the past Jira tickets that describe a recurring incident with the same root cause*. The "correct" output is defined by the dataset's gold-match list, which our synthetic pipeline constructs by tying each window to the synthetic ticket(s) emitted by the same scenario taxonomy.

If we swap the memory corpus for WoL, the gold-match list becomes meaningless: a synthetic `payment-outage` window's gold was a synthetic payment-outage ticket, which is no longer in the corpus. There is no WoL ticket that describes the same incident, because WoL is about completely different software systems. Two consequences:

1. **Hit@K against WoL memory is undefined.** Every retrieval is technically a "miss" by the dataset's own gold definition, regardless of how plausible-looking the retrieval is.

2. **The cascade has no chance to produce a "correct" output and so the test is biased toward whatever the cascade does *anyway*.**

The honest move is to ask different questions of WoL — questions where there *is* a correct answer that does not require a synthetic-to-real ground-truth join. Modes 1, 2, and 3 do that.

---

## 3. What WoL can and cannot supply

### 3.1 What WoL has

Confirmed by the local-MongoDB inventory:

| Collection | Documents | High-confidence (`pred_uncertainty ≤ 0.05`) |
|---|---:|---:|
| `WoL_v1.JIRA` | 360,778 | 268,966 |
| `WoL_v1.SO` | 585,304 | 392,413 |
| `WoL_v1.GitHub` | 114,679 | 74,629 |
| `WoL_v1.CommonCrawl` | 773 | 107 |

WoL JIRA records carry: the full Atlassian REST API field set (`fields.project.*`, `fields.priority.*`, `fields.issuetype.*`, `fields.components`, `fields.summary`, `fields.description`, `fields.created`, `fields.comments`, `fields.resolution`), plus the extracted `log_msgs` array (the cleaned per-ticket log lines from the WoL paper's three-stage extractor), plus the convenience flags (`log_msg_count`, `has_log_msg`, `pred_uncertainty`).

### 3.2 What WoL does NOT have

WoL is **log-and-ticket-context only**. It carries no traces, no metrics, no Kubernetes events, no per-handler latency histograms, no error-rate time series, no co-collected telemetry of any kind. Two consequences for the cascade:

1. **The triage gate (HGB) cannot be evaluated against WoL** because HGB consumes the 94-column numeric feature vector that WoL records do not have. **This is exactly why TCH-Lite exists:** TCH-Lite drops HGB by design and reads only log-derived text. WoL is the dataset TCH-Lite was designed for.

2. **TCH-Combined's full input modality cannot be exercised against WoL** because Hybrid-RRF, LogSeq2Vec, and the agent expect evidence text that includes a trace-anomaly summary and alert names alongside log lines. WoL's `log_msgs` give us only the log component. Modes 1 and 2 use this honestly — log-only stand-ins or non-retrieval evaluations. Mode 3 sidesteps it entirely by running TCH-Lite instead of TCH-Combined.

### 3.3 What WoL has at low quality

The CommonCrawl subset is out of scope (14% pass the uncertainty bar; high-confidence examples are noisy WAF block messages, not incident-style logs). Stack Overflow is question-and-answer prose around code questions; not a Jira-ticket analogue, so we use it only as a Mode 1 distractor source where relevant. The JIRA and GitHub subsets are the genuinely useful pools.

---

## 4. The four evaluation modes

Each mode answers a question the synthetic-only evaluation cannot, with a well-defined correct answer that does not require a synthetic-to-real semantic join.

| Mode | Question | Cascade variant | Critical-path? | Effort |
|---|---|---|---|---|
| **1 — Real distractor pool** | Does the cascade's retrieval consensus survive when the noise floor is real-language Jira text from unrelated software systems? | TCH-Combined | Yes | ~3 hours |
| **2 — Cross-domain novelty validation** | Does the cascade's L3 novelty layer correctly identify queries from a completely different software ecosystem as novel? | TCH-Combined (primary), TCH-Lite (secondary) | Yes | ~half day |
| **3 — TCH-Lite end-to-end on WoL** *(PROMOTED in v3)* | Does TCH-Lite produce meaningful Hit@K on real engineer-written Jira corpora under an inferred match relation, both sides log-only? | TCH-Lite | **Yes** (once TCH-Lite is built) | ~3 days |
| **4 — WoL Kafka × OTel Demo Kafka** | When memory and query are from the same real software ecosystem (Kafka), does TCH-Combined transfer? | TCH-Combined | Blocked on GCP collection | ~1 day after blocker clears |

Each mode is specified in its own section below.

---

## 5. Mode 1 — WoL as a real distractor pool

### 5.1 The claim this supports

Reinforces §13.1's distractor robustness finding. Currently the distractor sweep mixes *synthetic* distractor tickets into the memory at varying ratios and measures Hit@5 degradation. Synthetic distractors are by construction lower-overlap with synthetic queries than real distractors would be. **Real distractors are a stronger test**: real Jira text shares vocabulary with real incident description (every Jira ticket mentions "error", "timeout", "exception", "pod restart", etc.) but never carries the right answer for our synthetic scenarios. If the cascade's retrieval consensus survives this stronger noise, the §13.1 conclusion is reinforced.

### 5.2 Why it is methodologically valid

- **Gold is unambiguous:** the synthetic memory's own gold list is unchanged.
- **WoL is unambiguously not gold:** no WoL ticket about Apache Spark or Apache Cassandra describes an Online Boutique incident.
- **The metric (Hit@5 vs distractor ratio) is well-formed**, with a baseline (synthetic distractors) to compare against.

### 5.3 Setup

Sample 200–500 WoL JIRA records from explicitly-off-topic projects (Qt, Minecraft, Confluence Server, Sakai, JBoss EAP — desktop GUI, game-client, wiki-authoring, learning-management, and Java-EE-container domains, all real engineer-written tickets with extracted logs but with no semantic overlap with our 27-family microservice taxonomy). Map each WoL record into the humanized-timeline schema (§10.2) with `is_distractor=true`. Mix them into the synthetic memory at ratios $r \in \{0, 10, 25, 50\}\%$.

### 5.4 Evaluation

Re-run `src/v2_advanced/tch/distractor_sweep.py` with the new distractor pool against **TCH-Combined**. Produce the same table as §13.1 of the paper (Hit@1 / Hit@5 / MRR vs distractor ratio) with a new column showing the synthetic-distractor baseline alongside the real-distractor result.

### 5.5 Expected outcome

Hit@5 degradation at 50% real-distractor ratio should be in the range −3% to −6% relative (versus synthetic's −2%). Real distractors are higher vocabulary-overlap with queries, so we expect a slightly larger drop. Anything beyond −10% would be a finding worth its own paragraph; anything within −6% reinforces the existing §13.1 conclusion.

---

## 6. Mode 2 — Cross-domain novelty validation

### 6.1 The claim this supports

The cascade's L3 novelty layer is currently evaluated only on synthetic windows that are novel-by-construction. **Mode 2 tests a stronger form of novelty: query windows that are out of the cascade's training distribution entirely.**

If we feed the cascade a query whose evidence text is a WoL Apache Spark ticket's `log_msgs` (joined as if it were a window's characteristic log lines), the only correct answer is `is_novel=true`. The cascade's L3 disjunction should fire on every such query.

In v3 we run Mode 2 against **both TCH-Combined and TCH-Lite**. TCH-Combined gets the primary result (it's the paper's headline cascade); TCH-Lite gets a secondary result that tells us whether the log-only deployment configuration's novelty layer is equally OOD-robust.

### 6.2 Why it is methodologically valid

- **The correct answer is the same for every query: `is_novel=true`.** No ambiguity.
- **The metric (novel precision on WoL queries) is well-formed.**
- **The OOD shift is real and not constructible synthetically.**
- **The negative result is informative.**

### 6.3 Setup

Sample 500–1000 WoL JIRA records (high-confidence, Bug-type, ≥1 `log_msg`) from a deliberately diverse set of projects. For each, construct a synthetic `TriageWindow`-shaped record where:
- `window_id = "wol-novelty-<wol-id>"`
- `evidence_text = "\n".join(wol_record.log_msgs[:50])`
- `service_name = "wol-real"` (sentinel, not any Online Boutique service)
- `scenario_family = "wol-novelty"` (sentinel family the L3 classifier has never seen)
- `window_type = "active_fault"`
- Numeric features: zero-vector.
- Gold-match list: empty (`is_novel = true` is the ground truth).

Feed this through TCH-Combined first; then through TCH-Lite. Report novel precision on the WoL-derived queries for each.

### 6.4 Evaluation

| Metric | Definition | Expected |
|---|---|---|
| **Novel precision on WoL queries (TCH-Combined)** | Fraction of WoL queries the cascade flags `is_novel=true` | ≥ 0.95 if L3 generalizes |
| **Novel precision on WoL queries (TCH-Lite)** | Same, evaluated against the TCH-Lite cascade | ≥ 0.90 (slightly looser because TCH-Lite's L1 score is a less sharp anchor) |
| **L3-signal contribution breakdown** | Per-WoL-query, which of the three L3 disjuncts (agent / free / learned) caused the novel flag | All three should fire frequently |

### 6.5 Expected outcome

If novel precision ≥ 0.95 for TCH-Combined and ≥ 0.90 for TCH-Lite, the cascade's novelty layer is OOD-robust in both configurations. Publishable positive result.

If TCH-Combined > TCH-Lite by more than 5pts, that is itself a reportable finding: the L3 layer's OOD robustness is partly carried by the HGB triage anchor, and a log-only deployment loses some of that robustness. Honest in either direction.

---

## 7. Mode 3 — TCH-Lite end-to-end on self-contained WoL retrieval (PROMOTED)

This was deferred in v2; v3 promotes it to the critical path because **TCH-Lite ([`docs7/TCH-Lite.md`](TCH-Lite.md)) makes the evaluation methodologically clean**.

### 7.1 The claim this supports

> *TCH-Lite achieves Hit@5 = [X] on the WoL JIRA self-contained retrieval task under match relation R, demonstrating that the cascade's structural design transfers to real engineer-written Jira corpora in log-only deployments.*

This is the **strongest real-data result the paper can carry without the OTel Demo cross-app collection** (which remains Mode 4). Both sides of the retrieval are real; the cascade is in its intended deployment configuration; the match relation is disclosed transparently.

### 7.2 Why TCH-Lite (and not TCH-Combined) is the right cascade for this mode

TCH-Combined's input modality assumes log lines + trace summary + alert names + numeric features. WoL provides only log lines. Running TCH-Combined against WoL means feeding it zero-vectors for the 94 numeric features and stripping the trace/alert parts of evidence text. That is a TCH-Lite *by accident*, with no L1 retuning, no L3 refit. The result is uninterpretable.

**TCH-Lite is the configuration whose input modality matches WoL's content.** Both sides of the retrieval consume log-only text; the L1 stacker is fit on log-only triage signals; the L3 learned classifier is fit on the log-only L1 score distribution. The cascade is operating in the regime it was designed for.

### 7.3 Setup

**Partition WoL JIRA into a query split and a memory split.** Use a 2000-ticket subset from microservice-adjacent projects (per §9.3 below). Split 70/15/15 (train / val / test) with stratification by `fields.project.name`.

**For each ticket A in the test split:**
- Construct a synthetic `TriageWindow`-shaped record with `evidence_text = "\n".join(A.log_msgs[:50])`.
- The cascade's task: retrieve tickets B from the memory split such that A and B match under the chosen relation.

**Map each ticket into both the `JiraMemoryIssue` and the humanized-timeline schemas** so the existing cascade loaders can consume them without code changes (per §10).

**The match relation.** Disclosed in the paper. Two candidates evaluated:
- *Coarse:* tickets A and B match if they share `fields.project.name` AND at least one `components` entry.
- *Strong:* same as coarse PLUS symptom-string Jaccard overlap > 0.5 between their `log_msgs`.

The paper reports both numbers. The delta between them reveals how much of the cascade's retrieval signal is structural (entities) vs textual (log similarity).

### 7.4 Cascade reconfiguration steps (one-time per WoL split)

1. **Refit TCH-Lite's L1 stacker** on the WoL train split. Same protocol as the synthetic L1 stacker (5-fold CV LogReg, `class_weight="balanced"`, `random_state=42`). The fit uses the five retrieval pipelines' triage scores on WoL train; the "triage label" for L1 is `1` if the ticket is a Bug (it always is in our subset; effectively the stacker is fitting to retrieval-score-to-novelty correlations).
2. **Refit TCH-Lite's L3 learned classifier** on the WoL train split. Match-positive vs match-negative labels; same feature set; same sweep over thresholds {0.3, 0.4, 0.5, 0.6, 0.7}; pick F1-max.
3. **Lock both refit artifacts** in `data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/` for reproducibility.

### 7.5 Evaluation

Run TCH-Lite on the WoL test split with the refit L1 and L3 artifacts. Report:

| Metric | Definition |
|---|---|
| Hit@1, Hit@5, MRR | Under each match relation (coarse, strong) |
| Per-project Hit@5 | Stratified by `fields.project.name` to see which projects the cascade does best/worst on |
| Match-relation delta | Hit@5 (strong) − Hit@5 (coarse), revealing the structural-vs-textual signal contribution |
| Novelty precision | Fraction of test queries the cascade correctly flags as novel when the memory genuinely has no match-relation peer |
| Novelty recall | Fraction of truly-novel test queries the cascade flags |

### 7.6 Expected outcome

| Outcome | Hit@5 under coarse match | Interpretation |
|---|---:|---|
| Excellent | ≥ 0.70 | The cascade's retrieval mechanism generalizes to real Jira text under a structural match relation |
| Acceptable | 0.50–0.70 | Real Jira retrieval is harder than synthetic but the cascade does meaningfully better than random; honest publishable result |
| Reportable | 0.35–0.50 | Modest result; the paper reports it as the magnitude of the synthetic-to-real gap |
| Concerning | < 0.35 | Cascade is barely above random; investigate whether the inferred match relation is the issue or the cascade itself |

Random baseline for Hit@5 with ~300 visible memory tickets and ~10 true matches per query: ~0.10–0.15. Anything substantially above that floor is a real signal.

---

## 8. Mode 4 — Bookmarked: WoL Kafka × OTel Demo Kafka

### 8.1 The opportunity

Cross-application validation against OpenTelemetry Demo is already in the project plan (`docs5/`). OTel Demo has a Kafka-mediated communication path between checkout-service and the downstream accounting/fraud-detection services; the cross-app collection includes five Kafka-specific scenario families (broker outage, consumer lag, consumer crash, partition rebalance, dead-letter spike).

**WoL JIRA contains the Apache Kafka project's bug tickets.** A WoL Kafka ticket about a broker outage *could plausibly be the right answer* for an OTel Demo `kafka-broker-outage` window. Both sides are about the same software system. This is the only mode where memory and query share an actual semantic relationship.

### 8.2 Why TCH-Combined (not TCH-Lite) for Mode 4

OTel Demo *will* have full telemetry — that's the whole point of the OpenTelemetry Demo. Mode 4's query side has traces, metrics, k8s events, *and* log lines. The cascade configuration that matches this input modality is TCH-Combined, not TCH-Lite. **Mode 4 evaluates TCH-Combined** against a memory corpus consisting of WoL Apache Kafka tickets.

### 8.3 Why it is bookmarked, not on the critical path

Mode 4 requires (a) the OTel Demo collection to complete on GCP (currently in progress per `docs5/02-implementation-status.md`), (b) WoL's Apache Kafka tickets to actually be in the corpus and pass our quality filters (TBC), and (c) a Kafka-specific gold-match construction that maps an OTel Demo Kafka window to one-or-more candidate WoL Kafka tickets. The construction is feasible — Kafka has a small canonical vocabulary (broker, partition, consumer-group, lag, rebalance, ISR, leader-election) that the rule extractor can match against — but it is its own week of work.

This is the path that *would* let us claim full-modality real-data Hit@K honestly. Bookmark for post-submission.

---

## 9. Project selection for each mode

### 9.1 Mode 1 distractor pool — OFF-topic WoL projects

Selected for *no* semantic overlap with our 27-family Online Boutique taxonomy.

| WoL project | Logged tickets | Domain | Why it's an unambiguous distractor |
|---|---:|---|---|
| Qt | 18,298 | C++ desktop GUI framework | Failure modes are GUI rendering, signal/slot, QML — no microservice analogue |
| Minecraft: Java Edition | 13,302 | Game client | Player-side, single-process — no distributed-services analogue |
| Confluence Server | 4,902 | Wiki + authoring | UI workflows, page rendering — no service-outage analogue |
| Sakai | 4,749 | Learning management system | Education domain |
| JBoss EAP | 3,979 | Java EE container | Container-internal failure modes, not service-mesh |
| Tools (JBoss Tools) | 4,926 | IDE plugin | Tooling, not runtime |

Sampling target: 300 records, stratified by project. Quality filters: `pred_uncertainty ≤ 0.05`, `issuetype = Bug`, `≥1 log_msg`.

### 9.2 Mode 2 cross-domain novelty queries — diverse source projects

Mix from both microservice-adjacent and unrelated projects, so that the cross-domain shift exercises both adjacent-vocabulary shifts and complete shifts. Sampling target: 800 records.

| WoL project | Sample size | Why included |
|---|---:|---|
| Apache Spark | 100 | Adjacent domain (distributed compute) |
| Apache Cassandra | 100 | Adjacent domain (distributed datastore) |
| Apache Flink | 100 | Adjacent domain (stream processing) |
| Apache HBase | 100 | Adjacent domain |
| MariaDB Server | 100 | Database engine |
| Qt | 100 | Unrelated — full domain shift |
| Minecraft: Java Edition | 100 | Unrelated — full domain shift |
| Confluence Server | 100 | Unrelated — wiki authoring |

### 9.3 Mode 3 (PROMOTED) — TCH-Lite WoL self-contained subset

A separately-sampled **2000-record WoL JIRA subset from microservice-adjacent projects**. Split 70/15/15 train/val/test.

| WoL project | Sample size | Used for |
|---|---:|---|
| Apache Spark | 350 | Memory + queries |
| Apache Cassandra | 350 | Memory + queries |
| Apache HBase | 300 | Memory + queries |
| Apache Flink | 300 | Memory + queries |
| Apache Ambari | 250 | Memory + queries |
| MariaDB Server | 250 | Memory + queries |
| Apache Kafka (if present) | 200 | Memory + queries (also feeds Mode 4 if pulled) |
| **Total** | **2000** | |

Quality filters: same as Modes 1 and 2 (`pred_uncertainty ≤ 0.05`, `issuetype = Bug`, `≥1 log_msg`), plus `fields.description ≥ 200 chars`.

---

## 10. Semantic mapping — WoL fields to our schemas

The mapping is shared by Modes 1, 2, and 3 — the difference is the target file (distractor timeline, novelty-query window, or self-contained memory + query record).

### 10.1 Mode 1 target: humanized distractor schema

Output file: `data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl`. Each row maps a WoL JIRA record to the humanized-timeline schema that `load_humanized_corpus` reads when `extra_distractor_path` is set.

| Target field | Source / value |
|---|---|
| `ticket_id` | `wol-d-<first-16-of-_id>` |
| `source_episode_id` | same as `ticket_id` |
| `source_dataset_run_id` | `wol-distractor-2026-06-11` |
| `source_injection_id` | empty string |
| `affected_services_seen` | `["wol-distractor"]` |
| `severity_seen` | normalized from `fields.priority.name` via §11 |
| `components_seen` | `[c.name for c in fields.components]` |
| `is_misattributed` | `false` |
| `closed_as_noise` | `false` |
| `is_distractor` | **`true`** |
| `is_followup_of` | `null` |
| `description_code` | joined `log_msgs` (first 50 lines) |
| `resolution` | `fields.resolution.name` or empty |
| `resolution_time_s` | `fields.resolutiondate - fields.created` in seconds; `0` if unresolved |
| `log_signature_source` | `"wol-extracted"` |
| `evidence_bundle_hash` | SHA-256 of `description_code` |
| `generator_version` | `"wol-bridge-v3"` |
| `sanitizer_version` | `"none"` |
| `symptom_map_version` | `"none"` |
| `timeline` | one synthetic step (see §10.4) |

### 10.2 Mode 2 target: synthetic-window schema

Output file: `data/derived/global/2026-06-11-wol-real-global/novelty-queries/windows.jsonl`.

| Target field | Source / value |
|---|---|
| `window_id` | `wol-novelty-<first-16-of-_id>` |
| `dataset_run_id` | `wol-novelty-2026-06-11` |
| `incident_episode_id` | same as `window_id` |
| `scenario_id` | `wol-novelty-<wol-project-slug>` |
| `scenario_family` | `wol-novelty` (sentinel) |
| `service_name` | `wol-real` (sentinel) |
| `window_type` | `active_fault` |
| `start_time`, `end_time` | now, now + 5 min |
| `triage_label` | `ticket_worthy` |
| `triage_severity` | from `fields.priority.name` via §11 |
| `triage_components` | `[c.name for c in fields.components]` |
| `triage_reason_class` | from §13.4's heuristic on `fields.summary` |
| `is_hard_case` | `false` |
| `source` | `"wol-novelty-queries"` |
| `evidence_text` | `"\n".join(wol.log_msgs[:50])` |
| `raw.triage_feature_*` | all zeros |
| `matched_memory_issue_ids` | `[]` |
| `is_novel` | `true` (gold) |
| `fault_compatibility_class` | `"wol-novelty"` |
| `expected_in_memory` | `false` |

### 10.3 Mode 3 target: both memory and query schemas

Output files:
- Memory side: `data/derived/global/2026-06-11-wol-real-global/self-contained/memory.jsonl` (humanized-timeline schema, `is_distractor=false`, with `scenario_family=<wol-project-slug>` so per-project stratification works)
- Query side: `data/derived/global/2026-06-11-wol-real-global/self-contained/queries.jsonl` (TriageWindow schema, `evidence_text` from query ticket's `log_msgs`)
- Gold relations: `data/derived/global/2026-06-11-wol-real-global/self-contained/gold-relations.json` (per-query list of matching memory ticket IDs under each match relation)

The field mappings reuse §10.1 (memory side) and §10.2 (query side) but with the sentinel values replaced by per-WoL-record values (real `scenario_family = <wol-project-slug>`, real `service_name = <wol-component-name>`).

### 10.4 The single synthetic timeline step (Modes 1 and 3 memory side)

```json
{
  "step_kind": "report",
  "persona_role": "real-engineer",
  "persona_avatar": "WoL",
  "t_offset_s": 0,
  "context_window_s": 0,
  "evidence": {
    "log_quotes": <wol.log_msgs>,
    "metric_observations": [],
    "k8s_observations": [],
    "trace_observations": [],
    "alert_names": [],
    "trace_id_quoted": null,
    "symptom_phrase": <first 200 chars of fields.summary>
  },
  "text": "<fields.summary>\n\n<fields.description (first 1500 chars)>",
  "body_code": "<\\n.join(log_msgs[:50])>",
  "prompt_hash": "wol-<mode>"
}
```

---

## 11. Priority normalization table

WoL JIRA has 50+ distinct priority strings across projects. They collapse cleanly into our three-class severity vocabulary plus a fallback. Applies to Modes 1, 2, and 3.

| WoL priority strings (case-insensitive) | Our `severity` |
|---|---|
| `Blocker`, `Highest`, `P0`, `P0: Blocker`, `Showstopper`, `1 - Blocker`, `Blocker - P1`, `Critical`, `Critical - P2`, `2 - Critical`, `P1: Critical`, `Urgent`, `P1`, `P1-Urgent`, `Severe` | **critical** |
| `Major`, `High`, `Major - P3`, `3 - High`, `P2-High`, `P2: Important`, `P2`, `Important`, `Should Have` | **major** |
| `Minor`, `Low`, `Medium`, `Normal`, `Trivial`, `Trivial - P5`, `P3`, `P3: Somewhat important`, `P3-Medium`, `P4`, `P4: Low`, `P4-Low`, `Minor - P4`, `4 - Normal`, `5 - Minor`, `Lowest`, `Optional`, `P5: Not important` | **minor** |
| `Not Evaluated`, `Unknown`, `Undefined`, `TBD`, `Unprioritized`, `Unset`, `Not a Priority`, `Level 2`, `Level 3`, `Level 4`, `Complex Fast-Track`, `(null)` | **minor** (fallback; `severity_uncertain=true` in raw) |

A single JSON file `wol-priority-mapping.json` codifies the mapping. Coverage report flags fallback bucket size; if >5%, revisit.

---

## 12. Directory layout under `data/`

```
data/
├── runs/                                              # existing synthetic runs (UNTOUCHED)
├── derived/
│   ├── global/
│   │   ├── 2026-05-25-dataset-v5-large-global/        # synthetic (UNTOUCHED)
│   │   ├── smoke-otel-pilot-global/                    # OTel pilot (UNTOUCHED)
│   │   │
│   │   └── 2026-06-11-wol-real-global/                 # NEW — Modes 1, 2, 3
│   │       ├── distractors/                            # Mode 1
│   │       │   ├── timeline.jsonl
│   │       │   └── source-mapping.csv
│   │       ├── novelty-queries/                        # Mode 2
│   │       │   ├── windows.jsonl
│   │       │   └── source-mapping.csv
│   │       ├── self-contained/                         # Mode 3 (PROMOTED in v3)
│   │       │   ├── memory.jsonl                        # WoL records, humanized-timeline schema
│   │       │   ├── queries.jsonl                       # WoL records as TriageWindow
│   │       │   ├── gold-relations.json                 # per-query gold lists per match relation
│   │       │   ├── split-manifest.json                 # 70/15/15 train/val/test
│   │       │   └── source-mapping.csv
│   │       ├── tch-lite-refit/                         # Mode 3 refit artifacts
│   │       │   ├── stacker_lite.pkl                    # refit L1 stacker (5-feature)
│   │       │   ├── learned_novelty_lite.jsonl          # refit L3 classifier predictions
│   │       │   └── refit-manifest.json
│   │       ├── wol-extraction-manifest.json            # provenance
│   │       ├── wol-priority-mapping.json               # §11
│   │       ├── wol-coverage-report.json                # per-mode per-project counts
│   │       ├── retired-v1-mode-A-notes.md              # v1's Mode A retirement
│   │       └── README.md                               # rerun instructions
│   │
│   └── wol/                                            # raw WoL extracts (per-query cache)
│       └── extraction-cache/
│           ├── apache-spark-bugs.jsonl
│           ├── apache-cassandra-bugs.jsonl
│           ├── ...
│           ├── qt-bugs.jsonl
│           └── minecraft-bugs.jsonl
```

**Two principles enforced by this layout:**

1. **No synthetic file is modified.**
2. **The cascade evaluator is pointed at the new directory** via the same `extra_distractor_path` (Mode 1) or via small evaluator wrappers (Modes 2 and 3). No new code paths in the cascade itself; the TCH-Lite configuration is a flag, not a new module (per [`docs7/TCH-Lite.md`](TCH-Lite.md) §6).

---

## 13. The extraction pipeline

A single script, `scripts/research-lab/build_wol_real_corpus.py`, produces all artifacts deterministically. Subcommands per mode:

```bash
# Mode 1: distractor pool
python -m scripts.research-lab.build_wol_real_corpus distractors \
    --out-dir data/derived/global/2026-06-11-wol-real-global/distractors \
    --n-per-project 50

# Mode 2: novelty queries
python -m scripts.research-lab.build_wol_real_corpus novelty-queries \
    --out-dir data/derived/global/2026-06-11-wol-real-global/novelty-queries \
    --n-per-project 100

# Mode 3: self-contained memory + query + gold relations
python -m scripts.research-lab.build_wol_real_corpus self-contained \
    --out-dir data/derived/global/2026-06-11-wol-real-global/self-contained \
    --n-total 2000 \
    --split 70:15:15 \
    --match-relation coarse strong

# All-modes single run
python -m scripts.research-lab.build_wol_real_corpus all \
    --out-root data/derived/global/2026-06-11-wol-real-global
```

### 13.1 Common pipeline steps

1. Connect to MongoDB at `mongodb://localhost:27017`; verify collections.
2. Query candidate pool per project. Project out `log_blks` field. Cache to `data/derived/wol/extraction-cache/<project>.jsonl`.
3. Filter by mode-specific quality criteria.
4. Stratified-sample per project at seed 42.
5. Map fields per §10.
6. Normalize priority per §11.
7. Heuristic `triage_reason_class` (Mode 2; §13.4) and `fault_type` (Mode 3 memory side).
8. (Mode 3 only) Compute gold relations under each match definition.
9. Atomic write (`.tmp/` → final paths).
10. Coverage report.

### 13.2 (Mode 3 only) The match-relation computation

For each ticket pair $(A, B)$ in the test queries × memory cross-product, compute:

- **Coarse match:** `A.project == B.project AND len(A.components ∩ B.components) ≥ 1`
- **Strong match:** coarse match AND jaccard(symptom_tokens(A.log_msgs), symptom_tokens(B.log_msgs)) > 0.5

`symptom_tokens` = lowercased non-stopword tokens from the joined `log_msgs`. Stopword list is fixed (the standard English stopword set plus `error`, `info`, `warning`, `debug`, `at`, `line`, `file` to remove generic log boilerplate).

The result is `gold-relations.json` keyed by query `ticket_id`, with one list per match relation.

### 13.3 (Mode 3 only) TCH-Lite refit on the WoL training split

A separate subcommand:

```bash
python -m scripts.research-lab.refit_tch_lite \
    --memory data/derived/global/2026-06-11-wol-real-global/self-contained/memory.jsonl \
    --train-queries data/derived/global/2026-06-11-wol-real-global/self-contained/queries.jsonl \
    --train-split train \
    --gold-relations data/derived/global/2026-06-11-wol-real-global/self-contained/gold-relations.json \
    --match-relation coarse \
    --out-dir data/derived/global/2026-06-11-wol-real-global/tch-lite-refit
```

Refits the L1 stacker and L3 learned classifier per [`docs7/TCH-Lite.md`](TCH-Lite.md) §5. Wall time: minutes.

### 13.4 `triage_reason_class` heuristic

Same keyword matcher as in v2; reproduced here for completeness:

| Keyword | Class |
|---|---|
| `outage`, `down`, `unavailable`, `cannot connect`, `not responding` | `outage` |
| `slow`, `latency`, `timeout`, `hangs`, `freezes` | `latency_regression` |
| `restart`, `crash`, `oom`, `out of memory`, `killed`, `crashloop` | `restart_with_impact` |
| `network`, `partition`, `packet loss`, `connection refused`, `dns` | `network` |
| (no match) | `other` |

### 13.5 Determinism

Same seed + same MongoDB content + same git SHA → bit-identical outputs.

---

## 14. Phased delivery plan

| Phase | Deliverable | Effort | Blocks |
|---|---|---|---|
| **P1 — Mongo setup** | 4-collection MongoDB populated and reachable. | DONE. | — |
| **P2 — Extraction script** | `scripts/research-lab/build_wol_real_corpus.py` producing Mode 1, 2, and 3 artifacts in §12. | ~1.5 days. | P1. |
| **P3a — TCH-Lite implementation** | `--lite` flag on `build_cascade.py` per [`docs7/TCH-Lite.md`](TCH-Lite.md) §6. ~80-line diff. | ~half day. | None (independent of P2). |
| **P3b — Channel-ablation table on synthetic data** | Re-run TCH-Combined with channel masks; report table. | ~1 day. | P3a (for the TCH-Lite row). |
| **P4 — Sanity validation** | Pilot run on 50 Mode 1, 50 Mode 2, and 100 Mode 3 records. | ~3 hours. | P2 + P3a. |
| **P5 — Mode 1 evaluation** | TCH-Combined run with WoL distractors at 10/25/50% ratios. Reproduce §13.1 table with real-distractor column. | ~3 hours. | P4. |
| **P6 — Mode 2 evaluation** | TCH-Combined + TCH-Lite runs against the 800-record novelty query set. | ~4 hours. | P4. |
| **P7 — Mode 3 TCH-Lite refit** | Refit L1 stacker + L3 classifier on the WoL train split (per [`docs7/TCH-Lite.md`](TCH-Lite.md) §5). | ~half day. | P4. |
| **P8 — Mode 3 evaluation** | TCH-Lite run on the WoL test split under both match relations. Per-project stratified Hit@5 table. | ~half day. | P7. |
| **P9 — Paper integration** | Add `§5.X Real-Data Validation` to `ICSE/sections/05-results.tex` with Mode 1 table, Mode 2 result, Mode 3 headline + per-project table, and the channel-ablation table from P3b. Update §8 and §10 accordingly. | ~half day. | P5, P6, P8. |
| **P10 (blocked)** | Mode 4 WoL Kafka × OTel Demo Kafka with TCH-Combined. | ~1 day after blocker clears. | OTel Demo GCP collection complete. |

Critical-path total: P2/P3a (parallel) → P4 → P5/P6/P7 (parallel) → P8 → P9 ≈ **3–4 days** of focused work.

---

## 15. Evaluation matrix and acceptance criteria

### 15.1 Mode 1 acceptance — real-distractor robustness (TCH-Combined)

| Outcome | Hit@5 degradation at 50% ratio | Interpretation |
|---|---|---|
| Excellent | better than −5% rel | Cascade survives real-language noise as well as synthetic noise |
| Acceptable | between −5% and −10% rel | Slight additional drop; still publishable |
| Reportable | between −10% and −20% rel | Measurable real-language gap |
| Concerning | worse than −20% rel | Investigate before publication |

### 15.2 Mode 2 acceptance — cross-domain novelty precision (TCH-Combined and TCH-Lite)

| Outcome | TCH-Combined novel precision | TCH-Lite novel precision | Interpretation |
|---|---|---|---|
| Excellent | ≥ 0.97 | ≥ 0.93 | L3 layer is OOD-robust in both configurations |
| Acceptable | 0.90–0.97 | 0.85–0.93 | Mostly robust; per-signal breakdown is the headline |
| Reportable | 0.80–0.90 | 0.75–0.85 | Measurable OOD weaknesses |
| Concerning | < 0.80 | < 0.75 | L3 is confabulating across OOD |

### 15.3 Mode 3 acceptance — TCH-Lite WoL self-contained retrieval

| Outcome | Hit@5 (coarse match) | Hit@5 (strong match) | Interpretation |
|---|---|---|---|
| Excellent | ≥ 0.70 | ≥ 0.55 | Cascade generalizes to real Jira retrieval |
| Acceptable | 0.50–0.70 | 0.35–0.55 | Real retrieval is harder than synthetic; honest result |
| Reportable | 0.35–0.50 | 0.25–0.35 | Modest result; reports the synthetic-to-real gap magnitude |
| Concerning | < 0.35 | < 0.25 | Barely above random; investigate |

### 15.4 What lands in the paper

A new `§5.X Real-Data Validation` subsection with:
- **Channel-ablation table (from P3b)** — TCH-Combined, four mask configurations, TCH-Lite. Synthetic data.
- **Mode 1 table:** Hit@1 / Hit@5 / MRR vs distractor ratio under synthetic and real-WoL distractor distributions.
- **Mode 2 numbers:** overall novel precision for TCH-Combined and TCH-Lite, plus a small per-source-project table.
- **Mode 3 table:** TCH-Lite Hit@1/Hit@5/MRR on the WoL self-contained retrieval task under each match relation. Per-project stratification. **This is the load-bearing real-data headline.**
- **Honest scope statement:** TCH-Combined is the headline cascade; TCH-Lite is for log-only deployments; cross-modality real-data retrieval (TCH-Combined × real telemetry) is future work via Mode 4.

---

## 16. Risks and explicit limitations

1. **Triage gate is not evaluated against WoL.** WoL has no numeric features. TCH-Combined's triage PR-AUC = 0.9998 is reported only against synthetic. TCH-Lite's triage PR-AUC (substantially lower) is reported on synthetic data and is the deployability cost of going log-only.
2. **TCH-Combined retrieval transfer (synthetic-to-real) is not in scope.** v1's mistake. Mode 4 is the eventual answer.
3. **Mode 2's "WoL ticket as a window" is a log-only stand-in for TCH-Combined.** Fine for TCH-Lite (whose input is log-only by design); a known simplification for TCH-Combined.
4. **WoL extraction F1 = 0.70.** Even on the high-confidence sub-pool, some log_msgs may have minor extraction artifacts. The cascade sees these as noise.
5. **Mode 3's match relation is inferred, not labeled.** Paper has to defend the choice. Both relations (coarse, strong) are reported transparently.
6. **Mode 3 ground-truth depth is bounded by the match relation, not by real engineering judgment.** A reviewer could argue that real Jira tickets that share project + components are not necessarily recurrences of one another. We acknowledge and report under both relations to bracket the answer.
7. **Mode 2's TCH-Lite secondary result requires TCH-Lite to be built first.** If P3a slips, Mode 2 reports TCH-Combined only.
8. **Mode 3's L3 evaluation does not test the full L3 layer end-to-end** because the DiagnosisAgent is expensive (~30 sec/query); we may cap the agent runs at 200 queries to stay under 2 hours of LLM time. The free signal and learned classifier still run on the full query set.

---

## 17. Reproducibility and provenance

Every artifact in `2026-06-11-wol-real-global/` carries provenance:

- `wol-extraction-manifest.json`: WoL archive SHA-256, MongoDB query per project, count before/after each filter, random seed, script git SHA, timestamps, priority-mapping checksum.
- `wol-coverage-report.json`: per-mode per-project per-severity counts, fallback-priority bucket size, `triage_reason_class` distribution.
- `source-mapping.csv` per mode: maps every output row to its WoL `_id` and project.
- `tch-lite-refit/refit-manifest.json`: source split, sample counts, refit training time, refit feature coefficients (so anyone can verify the L1 stacker's reweighting after HGB is dropped).
- The script writes to `.tmp/` then renames. Deterministic with seed 42.

The directory's `README.md` documents the exact rerun commands.

---

## 18. Decision gates

**Gate 1 — after P2 extraction.** Eyeball 20 random Mode 1 distractors, 20 random Mode 2 queries, and 40 random Mode 3 memory/query pairs. Do they look like real Jira tickets and real log lines respectively? Do the Mode 3 gold relations under each match definition look semantically reasonable on a 10-pair spot check? If yes, proceed.

**Gate 2 — after P4 pilot.** For Mode 1: does TCH-Combined produce non-trivial BiEncoder cosines against WoL distractors? For Mode 2: does the cascade's L3 layer fire? For Mode 3: does TCH-Lite's pilot retrieval against WoL memory produce non-zero scores above the random floor? If all yes, proceed.

**Gate 3 — after P5, P6, P8.** Mode 1 degradation within the acceptable bar? Mode 2 novel precision within the acceptable bar for both cascades? Mode 3 Hit@5 (coarse) at or above the random floor + meaningful margin? If all yes, proceed to paper integration. If any concerning, discuss remediation before P9.

After Gate 3 passes, the paper integration in P9 is mechanical.

---

## Appendix A — Three-paragraph version, for a quick reader

We use WoL JIRA in three methodologically valid ways. (1) WoL records from off-topic projects (Qt, Minecraft, Confluence, Sakai, JBoss EAP) become a **real-language distractor pool** for the §13.1 robustness sweep — they are real engineer-written tickets that are unambiguously not gold for any synthetic Online Boutique window, which is what a stronger distractor test needs. (2) WoL records' extracted log messages become **out-of-distribution query windows** for the cascade's L3 novelty layer — every such query has a structurally correct gold answer (`is_novel=true`), and we measure novel precision for both TCH-Combined and TCH-Lite.

(3) **WoL JIRA becomes the memory-and-query corpus for an end-to-end TCH-Lite retrieval evaluation** (the v3 promotion of what was deferred in v2). TCH-Lite is the log-only deployment configuration of the cascade documented in [`docs7/TCH-Lite.md`](TCH-Lite.md); WoL is a log-only dataset; their input modalities match. The match relation is inferred (project + components, plus a stronger version with symptom Jaccard); both relations are reported transparently. **This is the load-bearing real-data headline the paper now carries.** A fourth mode (TCH-Combined × WoL Apache Kafka × OTel Demo Kafka, where memory and query are from the same real software ecosystem) remains bookmarked and blocked on the GCP cross-app collection.

Critical-path effort is approximately three to four days, dependent on the parallel TCH-Lite implementation finishing in P3a. The paper integration in P9 adds a `§5.X Real-Data Validation` subsection with a channel-ablation table, three result tables (Modes 1/2/3), and an explicit scope statement that TCH-Combined cross-modality real-data retrieval is future work via Mode 4.

---

*Generated 2026-06-11. This plan v3 supersedes v2 and v1. The extraction script (`scripts/research-lab/build_wol_real_corpus.py`) implements §10–§13 against this spec; the new dataset directory (`data/derived/global/2026-06-11-wol-real-global/`) is the artifact; the cascade configuration that consumes Mode 3 is documented in [`docs7/TCH-Lite.md`](TCH-Lite.md).*
