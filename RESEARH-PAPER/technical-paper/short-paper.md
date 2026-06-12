# From Telemetry to Triage — Short Version

**A Memory-Augmented Hybrid Cascade for Incident Diagnosis with Past-Ticket Citation**

Yuvraj Sehgal · 17yuvraj.sehgal@gmail.com · June 2026

> *This is the short, professor-friendly version of the comprehensive report at `technical-paper/main.tex`. It explains the problem, the dataset, the models, the cascade, the headline numbers, and the path to ICSE submission in roughly 10 pages of plain English. Acronyms and model names are spelled out the first time they appear.*

---

## 1. What problem are we solving?

When something breaks in a production microservice system, an on-call engineer is paged. Today's monitoring stacks are excellent at the first question — **"is something wrong?"** — but they are poor at the next three:

1. **Is this real, or noise?** (Brief blips, post-deploy artifacts, and test traffic look like incidents but aren't worth a ticket.)
2. **Have we seen this before?** Past Jira tickets carry the resolution. If today's incident matches one, the engineer can act in seconds instead of hunting through Jira for tens of minutes.
3. **Is this something new?** If nothing matches, the failure is genuinely novel and deserves careful investigation rather than a stale runbook.

Our system answers all three at once. Given a 5-minute window of telemetry (logs, traces, metrics, Kubernetes events), it returns:

* a calibrated **triage probability** (real or noise),
* a ranked **top-5 list of past Jira tickets** that look similar, and
* an **`is_novel` flag** when no good past match exists.

The novelty channel turned out to be where the largest improvement of the project lives.

---

## 2. Why we had to build the dataset ourselves

No public corpus contains the joint information we need: rich telemetry *and* the Jira ticket that engineers eventually filed for it, with both the pre-incident trigger and the post-incident resolution.

* **Open log datasets** (HDFS, BGL, Thunderbird) lack ticket-side ground truth.
* **Public Jira corpora** like TAWOS (458K real issues across 39 OSS projects, loaded locally for us) carry ticket text but no co-collected telemetry — we use TAWOS only as a length/style reference, never as labeled training data.
* **Real production data** from cooperating companies is rarely shareable and almost never reproducible.

A controlled lab solves both: we pay the cost of synthetic-but-realistic data and get full provenance — every test number can be traced back to a fault-injection script.

---

## 3. The dataset we built

### 3.1 The workload — Google's Online Boutique

We forked **Online Boutique**, Google's 10-service e-commerce microservices demo (Go, C#/.NET, Node.js, Python, Java) and added production-realistic instrumentation in five sequential phases (M0–M5) over ~3 weeks.

Every change obeyed one hard rule: **anything a real production service would not emit was not added.** No scenario IDs in span attributes, no fault labels in log fields. If we leak scenario labels into the telemetry stream, the resulting numbers measure an unrealistic surrogate task. This made debugging harder but the dataset defensible.

**What we added:**

| Channel | What was instrumented |
|---|---|
| **Logs** | Per-RPC structured JSON via shared interceptors in every language. Dependency-boundary error context (Redis, gRPC, HTTP). Business events (`cart_size_changed`, `order_placed`). |
| **Traces** | OpenTelemetry instrumentation for all 10 services — including the Redis-StackExchange auto-instrumentation on cartservice, which alone gave us a 3× lift in cart-Redis trace signal. `RecordError` on every failure handler. Manual child spans with semantic-convention attributes. |
| **Metrics** | OpenTelemetry Meter with Prometheus exporter on every service. RED metrics per RPC handler. Business-event counters. Standard runtime gauges. |

### 3.2 The fault library — 27 scenario families

We grouped the operationally interesting failure modes into seven categories:

* **Hard service outage** (8 families): payment-outage, checkout-outage, currency-outage, shipping-outage, recommendation-outage, ad-outage, productcatalog-outage, email-outage.
* **Dependency degradation** (2): cart-redis, productcatalog-latency.
* **Pod restart / churn** (5): checkout-restart, frontend-restart, single-pod-restart, flapping-pod, post-deploy-churn.
* **Capacity pressure** (4): traffic-pressure, scheduled-job-spike, resource-saturation, slow-leak.
* **Near-misses** (3): latency-near-miss-partial-recovery, recovered-in-window, third-party-blip.
* **Network / system** (4): network-latency, network-packet-loss, network-partition, dns-outage.
* **Baseline** (1): baseline-normal.

Each family runs by one of four primitives: `SetEnv` (patch environment variables), `ScaleDeployment` (scale to zero, restore), `RestartPods` (kill, wait, replace), or `RecordOnly` (passive baseline).

### 3.3 The collection pipeline

One **dataset run** = a sequence of scenarios against a freshly-deployed cluster. Each run produces raw evidence in three layers:

1. **Layer 1 (raw)** — Loki logs, Tempo traces, Prometheus metrics, Kubernetes events, alerts, and shadow Jira issues per window.
2. **Layer 2 (per-run derived)** — `triage_examples.jsonl` (one row per window with label + 94 numeric features), `window_memory_matchings.jsonl` (ground-truth past-ticket links with `is_novel`), model-ready evidence summaries.
3. **Layer 3 (global)** — `global-triage-examples.jsonl` across all runs, `jira-memory-corpus.jsonl` (time-ordered tickets with `available_as_memory_from`), and the train/val/test split manifest.

### 3.4 The humanized Jira corpus

Generating realistic Jira tickets was harder than generating telemetry. We went through two voice profiles:

* **V1 (customer-service voice):** friendly, descriptive, ~800 chars per ticket. Useful baseline but unrepresentative.
* **V2 (engineer voice, current):** anchored to length / content distributions measured directly on TAWOS. ~2,400 chars per ticket; **90.2% include a leading `description_code` block** (the engineer's first paste of the relevant logs); per-step prose interleaves additional log/trace fragments; resolution notes read like postmortem closure.

We also have a 110-ticket **distractor pool**: 60 TAWOS real-Jira (PII-stripped, cross-architecture), 25 in-architecture-but-irrelevant, 25 cross-architecture (DB, mobile, infra). Used in robustness experiments at memory-noise ratios of {0, 10, 25, 50}%.

### 3.5 Final numbers

| Item | Count |
|---|---:|
| Dataset runs | 100 |
| Scenario families | 27 |
| Total telemetry windows | 6,720 |
| Train / val / test (v2 in-distribution split) | 4,701 / 1,011 / 1,008 |
| Test windows with at least one gold-match past ticket | 331 |
| Test windows truly novel (no match exists) | 677 |
| Jira memory corpus (V2 engineer-voice) | 347 |
| Distractor pool | 110 |
| Derived numeric features per window | 94 |
| Raw evidence size | ~10 GB compressed |

The split is chronological and **family-stratified**: every scenario family appears in train, val, and test, but from *different* fault-injection runs. (A complementary leave-one-family-out evaluation tests the harder "orphan family" regime — see §10.)

---

## 4. How we evaluate (metrics in plain English)

Three groups of metrics, all computed on the 1,008-window test split with 95% paired-bootstrap confidence intervals (1,000 resamples, seed 42):

**Triage** — should this window become a ticket?
* `PR-AUC strict` and `PR-AUC inclusive`: area under the precision-recall curve. Strict counts only `ticket_worthy` windows as positive; inclusive also counts borderline windows.
* `F1 @ FPR ≤ 5%`: operating-point F1 for a fixed alert budget.

**Retrieval** — does the gold past ticket appear in our suggestions?
* `Hit@5`: fraction of windows whose gold ticket appears in our top-5 — our **primary headline**.
* `Hit@1`: stricter — gold is the very first pick.
* `MRR (Mean Reciprocal Rank)`: average of 1/rank, with 0 if no hit.

**Novelty** — when no past ticket matches, do we say so?
* `Novel precision` and `Novel recall`. The latter became the headline win of the project.

**Robustness** — how does the system degrade under stress?
* `Distractor confusion rate`: relative Hit@1 drop as we mix in irrelevant tickets.
* `LOFO F1`: novelty F1 under leave-one-family-out (a harder test of generalization).

---

## 5. The seven pipelines we tried (and what each one actually is)

Over the project we trained seven independent pipelines. Each one is a different bet about which signal in the telemetry matters most. Plain-language description for each:

| Pipeline (short name) | What it actually is | Where it wins |
|---|---|---|
| **HGB** — Histogram Gradient Boosting | A gradient-boosted decision-tree classifier (sklearn) fit on 94 numeric features (log counts, trace error counts, latency percentiles, k8s restarts, business-event rates, plus delta-from-baseline columns). | **Triage** — PR-AUC = 0.9998. Cannot retrieve. |
| **BiEncoder** — fine-tuned dense retriever | A 22M-parameter sentence-transformer (`all-MiniLM-L6-v2`) fine-tuned with `MultipleNegativesRankingLoss` on (window, gold ticket) pairs. Encodes window evidence and each Jira ticket into the same vector space; similarity = cosine. | **Top-1 retrieval** — Hit@1 = 0.695. |
| **HRRF-rule** — Hybrid Reciprocal Rank Fusion (rule-graph) | Internally fuses three retrievers (BM25 keyword search, the dense bi-encoder, and a rule-extracted entity-graph score) via RRF, a standard formula `score(c) = Σ 1/(60 + rank_r(c))`. | **Top-5 coverage** — Hit@5 = 0.798. |
| **HRRF-LLM** — same fusion, LLM-extracted graph | Same as above but the entity graph is populated by an LLM (Qwen 35B) extracting `{services, components, error_classes, root_cause, fix, symptoms}` per ticket into Neo4j. | Precision-heavy but sparse — illustrates the *RRF density paradox*. |
| **logseq2vec** — small log-sequence transformer | A 4-layer transformer (d=128, 4 heads) trained for 5 epochs on raw sequences of templated log lines. | Family-specialist (Hit@5 = 1.000 on productcatalog-outage). |
| **KG-retrieval** | A Neo4j Cypher retriever that traverses the LLM-extracted knowledge graph (347 incidents + ~1,500 nodes for services / components / symptoms / root-causes / fixes / error-classes) to find structurally similar incidents. | Interpretable retrieval; explains *why* a ticket matched. |
| **DiagnosisAgent** | A three-stage LLM chain. **Hypothesize** (Qwen 35B, thinking=OFF, ~1 sec): guess the root cause from the window evidence. **Retrieve** (no LLM call): fetch top-5 from the existing cascade. **Verify** (thinking=ON, ~25–30 sec): given hypothesis + top-5, output `{best_idx, confidence, is_novel, reasoning}`. | The **only** pipeline that emits an `is_novel` flag. ~94% novelty precision. |

### The key observation — no single pipeline wins

| Pipeline | Hit@1 | Hit@5 | MRR | PR-AUC strict | Novel detect? |
|---|---:|---:|---:|---:|---|
| HGB | — | — | — | **0.9998** | no |
| BiEncoder | **0.695** | 0.789 | **0.729** | 0.287 | no |
| HRRF-rule | 0.583 | **0.798** | 0.669 | 0.236 | no |
| HRRF-LLM | 0.432 | 0.667 | 0.517 | 0.292 | no |
| logseq2vec | 0.483 | 0.531 | 0.498 | 0.313 | no |
| KG-retrieval | 0.079 | 0.556 | 0.228 | — | no |
| DiagnosisAgent | 0.386 | 0.436 | 0.405 | 0.243 | **yes (94% prec)** |

Every column has a *different* winner. **No pipeline Pareto-dominates any other.** A single bigger model could in principle learn the union of these signals, but HGB on numerics already saturates triage (PR-AUC = 0.9998), so the marginal value of replacing it with a transformer is essentially zero. Instead, we built a cascade that uses each pipeline for the sub-task it is best at.

---

## 6. The TCH cascade — four layers, one for each sub-task

**TCH = Tiered Cascade Hybrid.** Four layers, each consuming the previous layer's output plus the per-pipeline predictions cached upstream. Ordering is driven by per-call cost — cheap-and-broad first, expensive-and-narrow last.

```
INPUT: one 5-minute telemetry window
        |
   [six pipelines pre-computed]
        |
   +----+----+----+----+
   v    v    v    v    v
  L1   L2   L3   L4   (optional LLM path on hardest windows)
TRIAGE RETRIEVAL NOVELTY COMPOSE
```

**L1 — Triage gate.** A class-balanced logistic regression *stacker* trained via 5-fold cross-validation on six pipeline triage scores. HGB dominates the learned weights (coefficient +8.221, ~30× the next largest); removing HGB collapses PR-AUC from 0.9998 to 0.303. The other five pipelines contribute on borderline windows, adding +3.2 points absolute on inclusive PR-AUC. Threshold τ = 0.5.

**L2 — Retrieval fusion.** Two different rules for two different jobs:
* **Position 1 (the top pick): anchor + overlap rerank.** Start with the BiEncoder's top-3 (its strongest move). For each candidate, count how many of the other retrievers also vote it into their top-3 (weighted by rank). The candidate with the highest consensus wins. *Why this works:* multi-retriever agreement is a stronger signal than any single retriever's top-1.
* **Positions 2–5: Reciprocal Rank Fusion** across four retrievers (BiEncoder + HRRF-rule + logseq2vec + KG-retrieval — we found by ablation that HRRF-LLM hurts this fusion by 2.1 points and dropped it). Standard RRF formula with k=60.

**L3 — Novelty check.** Three independent novelty signals combined with logical OR:
* the agent's own `is_novel` output (when the agent ran),
* a *free* signal: max retrieval confidence < 0.5 (empirically 96% precise),
* a *learned* signal added in late-stage refinement (G7 below): a logistic regression over 46 features (`window_type` one-hot, `scenario_family` one-hot, `service_name` one-hot, `is_hard_case`, `max_retrieval_conf`, `triage_score`).

L3 deliberately does **not** reorder L2's top-5. We tested letting the agent override L2's top-1 on 200 windows: the agent was right 3 times, L2 was right 8 times, net −5 wins. On this dataset multi-retriever consensus dominates single-LLM judgment.

**L4 — Composition.** Dict assembly: `{triage_score, matched_issue_ids[5], is_novel}`.

**Inference cost:** **16 microseconds per window** once the pre-computed pipelines are cached. The DiagnosisAgent is heavy (~30 sec/window) and runs once at training time over the test set; it only feeds the L3 novelty channel.

---

## 7. How we landed on this design (refinement experiments)

The cascade was the result of two rounds of experimentation.

### Round 1 — Thirteen baseline ablations

Each ablation tested one design dimension. Outcomes that hurt the cascade were rejected; outcomes that helped were kept. Highlights:

* Dropping HRRF-LLM from the L2 RRF added +2.1 points Hit@5.
* Score-weighted RRF, confidence-weighted RRF, learned per-candidate ranker — all hurt; uniform RRF wins.
* An *oracle* that always picked the best retriever per family scored Hit@5 = 0.888, *worse* than uniform RRF at 0.912.
* Letting the agent override L2's top-1: net −5 wins; disabled.
* LogReg beats GBM as the L1 stacker (0.9998 / 0.853 vs 0.985 / 0.739 on PR-AUC strict / inclusive).
* Multi-seed stability check (seeds 1, 7, 42, 100, 1000): PR-AUC std = 0.0000; not a lucky seed.

We also computed the **theoretical ceiling**: the union of the four L2 retrievers' top-5 sets contains the gold ticket on 97.6% of windows. The cascade at Hit@5 = 0.912 is at 93.5% of that ceiling. **Closing the remaining 6.4-point gap requires a new retriever, not more fusion tuning.**

### Round 2 — Eight targeted refinements (G1–G8)

The G-series tried to close the ceiling gap and/or improve the other axes. Outcomes:

| Phase | Intervention | Verdict |
|---|---|---|
| G1 | BiEncoder fine-tune with BM25 hard-negs + random negs | **KEEP** — Hit@1 +2.1% rel |
| G2 | Fine-tuned cross-encoder as 5th retriever / reranker | SKIP — Hit@1 −5.4 pts |
| G3 | Symmetric LLM extraction (windows too, not just tickets) | SKIP — standalone +404% rel, cascade integration breaks |
| G4 | DiagnosisAgent complete coverage on remaining 658 windows | **KEEP** — novel recall +119% rel |
| G5 | LLM judge reranker (Qwen picks best of top-5) | SKIP — confidence uninformative; net negative |
| G6 | Distractor robustness sweep (simulated, 0%, 10%, 25%, 50%) | KEEP-analysis — Hit@5 −2% at 50% noise |
| G7 | Learned per-window novelty threshold (LogReg, 46 features) | **KEEP — novel recall +388% rel (the headline win)** |
| G8 | Out-of-distribution eval (leave-one-family-out) | KEEP-analysis — F1 within 11% rel of in-distribution |

Three findings transcended any single experiment:

1. **The cascade is composition-fragile, not component-fragile.** G3's symmetric LLM extraction gained +404% rel on the KG-retrieval component standalone but broke cascade integration through two specific mechanisms: (a) the overlap-rerank vote-tally shifted on 99% of windows; (b) the underlying score-scale shift broke the L3 free-novelty trigger. The cascade's internal RRF + stacker math assumes specific score distributions, and we never made that an explicit hyperparameter.
2. **Three independent rerankers failed.** The G2 cross-encoder, the earlier agent-rerank attempt, and the G5 LLM judge are three orthogonal designs with three negative results in the same direction. Multi-retriever consensus on top-1 is empirically dominant on this dataset; single-LLM judgment cannot replicate it from one window.
3. **The retrieval channel was already at its local ceiling.** Hit@5 stayed at 0.912 across the entire G-series. The actual win came from the L3 novelty channel, which was underexploited — the original fixed `max_conf < 0.5` heuristic was leaving structural metadata signal (window_type, scenario_family) on the table.

---

## 8. Results

### 8.1 Headline: TCH-Final vs the locked v2f baseline

| Metric | v2f baseline | **TCH-Final** | Δ rel |
|---|---:|---:|---:|
| Hit@1 | 0.7069 | **0.7221** | +2.1% |
| Hit@5 | 0.9124 | **0.9124** | tied |
| MRR | 0.7880 | **0.7937** | +0.7% |
| PR-AUC strict | 0.9998 | **0.9998** | tied |
| PR-AUC inclusive | 0.8527 | **0.8562** | +0.4% |
| Novel precision | 0.9402 | **0.9405** | tied (matched) |
| **Novel recall** | **0.1625** | **0.7932** | **+388%** |

Every retrieval / triage metric ties or improves; no metric regresses; novel recall improves 4.9× at unchanged precision.

### 8.2 TCH vs every single-pipeline baseline

TCH ties or beats every individual pipeline on every metric except Hit@1 (ties BiEncoder within the 95% CI). The Hit@5 gap of **+11.5 points absolute over the best single retriever (HRRF-rule)** is the strongest evidence that the four retrievers carry complementary signal.

Paired-bootstrap deltas vs key baselines:
* vs BiEncoder: Hit@5 **+0.123** [+0.080, +0.167] (significant); MRR **+0.065** [+0.040, +0.092] (significant); Hit@1 +0.027 (not significant — TCH ties).
* vs HRRF-rule: Hit@1 **+0.139** [+0.085, +0.193] (significant); Hit@5 **+0.114** [+0.075, +0.155] (significant).

### 8.3 Robustness

| Test | Result |
|---|---|
| Distractor sweep at 50% noise ratio | Hit@5 −2.0% rel; Hit@1 −14.2% rel |
| Leave-one-family-out novelty F1 (best τ = 0.30) | 0.788 (vs 0.890 in-distribution; −11.4% rel) |
| LOFO precision | 19 of 27 families exceed 0.90 precision at τ = 0.50 |
| LOFO novel-recall vs the v2f baseline | +381% rel even at OOD |

The headline novel-recall win survives the family-shift OOD setting; only the precision-recall trade-off shifts.

### 8.4 Engineer time-to-diagnose

Under a serial-candidate-review simulation (30 sec per top-K candidate the engineer evaluates, 30-minute manual fallback), the memory-augmented pipelines save **~6–7 minutes per incident** relative to detection-only HGB.

### 8.5 Cost

Training-time LLM work totals ~10 hours of local Qwen 35B compute (extraction + agent runs). Inference is essentially free once cached: **252 ms for the entire 1,008-window test split.**

---

## 9. What we explicitly do not claim

To be honest about scope:

* Memory augmentation does **not** improve anomaly detection — HGB already saturates this dataset.
* We have no commercial-observability-tool comparison; out of scope.
* The system is a research prototype, not production-ready (no auth, multi-tenancy, latency SLOs, etc.).
* We do not solve cold-start: with zero past tickets, retrieval is 0% by definition.
* Trace sampling is 100% in our lab (production typically samples 1–10%); single-cluster, single-region; synthetic traffic with no diurnal pattern; single fault per run.

These bound external validity. The next section addresses the biggest one.

---

## 10. Where this needs to go next — the path to ICSE

The single most important critique an ICSE reviewer will raise is **external validity**: every number above is on one app (Online Boutique), one humanized Jira corpus (347 tickets), and one architectural style (synchronous gRPC microservices). To make the paper defensible, we need *cross-architecture evidence* that the cascade is portable.

You asked me to brainstorm three options. Here is an honest comparison and a recommendation.

### Option A — Collect telemetry for the TAWOS repositories

**Idea:** TAWOS already has Jira tickets for 39 real OSS projects (MongoDB, Mesos, Mule, Hyperledger Fabric, …). Deploy each project, inject faults, collect telemetry to match the tickets.

**Pros:** Real Jira text instead of synthetic. Real engineer voice, real distractor distribution.

**Cons (decisive):**
* **The Jira–telemetry pairing is the hard part of our dataset, and TAWOS doesn't give it to us.** TAWOS tickets are post-hoc; they were not written with any specific telemetry window in mind. We would have to construct an artificial mapping — back-dating each ticket to a synthesized fault window — which loses exactly the realism we wanted.
* **Workload diversity is a feature, but deployment cost dominates.** Each of the 39 projects is a different beast: Moodle is a PHP monolith with Apache, MongoDB is a C++ service-cluster, Mesos is a distributed scheduler, Mule is a Java integration platform. Stand-up + scenario authoring + Jira-to-telemetry alignment per project is weeks of work. We would burn the entire submission cycle on infrastructure.
* **Cross-project faults don't transfer.** "cart-redis-degradation" makes no sense in MongoDB or Moodle. We would lose the family taxonomy that all our pipelines are calibrated against.

**Verdict:** Strong as a *future-paper* angle (TAWOS as a noisy real-Jira retrieval test corpus). Wrong as the headline external-validity move for this paper.

### Option B — Stand up a second Online-Boutique-like app and repeat the synthetic collection

**Idea:** Pick a second microservice demo, instrument it the same way, build a parallel 347-ticket humanized corpus, repeat the full evaluation.

**Pros:** Demonstrates cross-app generalization with a clean apples-to-apples protocol. Reuses all our existing tooling.

**Cons:** Still synthetic data (which is fine — that's how our charter scoped the project), but the second app needs to be *meaningfully different* in architecture. Otherwise reviewers will say "you tested on two flavors of the same thing." A simple Online-Boutique clone in different services is not enough — we need architectural diversity (asynchronous messaging, different runtime semantics).

**Verdict:** This is the right *shape* of move. The question is which app to pick.

### Option C — Cross-app collection on the OpenTelemetry Demo (Astronomy Shop) — **what we are already doing on the `otel-demo-cross-app` branch**

This is Option B done with a deliberately-chosen second app. Status as of today (2026-06-09):

**Why the OpenTelemetry Demo specifically:**
* **OpenTelemetry-native:** zero re-instrumentation work. The OTel Demo's services already emit the kinds of logs / traces / metrics we hand-built as M1–M5 on Online Boutique. We get the instrumentation for free.
* **Kafka async backbone:** this is the *architectural* diversity that matters. Online Boutique is pure synchronous gRPC. The OTel Demo has `checkout-service` producing to Kafka, with `accounting-service` and `fraud-detection` consuming. Five new failure modes exist only here: `kafka-broker-outage`, `kafka-consumer-lag`, `kafka-consumer-crash`, `kafka-partition-rebalance`, `kafka-dead-letter-spike`.
* **15+ services in 12+ languages:** wider polyglot footprint than Online Boutique.
* **Built-in fault injection via flagd:** the demo ships with feature-flag-driven fault scenarios (paymentFailure, recommendationCacheFailure, kafkaQueueProblems, …) that map cleanly onto our scenario YAMLs.
* **CNCF provenance:** signals to reviewers that we did not cherry-pick a friendly testbed.

**What we will report — a two-column headline:**

| Setting | What's locked | What's reported |
|---|---|---|
| **Zero-shot transfer** | Entire cascade (L1 stacker, L2 fusion weights, L3 novelty model) trained on Online Boutique | Hit@5, novel-recall on OTel Demo — strict external-validity number |
| **L1 retrained on OTel Demo train** | L2 fusion + L3 novelty + all pipeline architectures | Apples-to-apples retrieval / novelty number |

Zero-shot is the harder claim; L1-retrained is the operating number a practitioner cares about. Reporting both shows reviewers exactly how much of the cascade is data-portable vs feature-portable.

**Status:**
* Phases 0a–1d (deployment overlay, service catalog refactor, new Flagd fault primitive, multi-fault orchestration, 44 scenario YAMLs + 5 run plans + 9 multi-fault sidecar JSONs): **done locally.**
* Phase 2 local pilot on kind cluster: **all GREEN.** Harness primitives validated end-to-end; telemetry routing GREEN; `build_triage_dataset.py` produces **94/94 `triage_feature_*` columns** — schema-identical match to Online Boutique. Cascade builder runs unchanged.
* **A clean cross-app finding already in hand:** 82 of the 94 feature columns are zero on OTel Demo, because they depend on Online Boutique-specific metric names (`cart_operations_total{op=add,result=success}` and similar). 12 feature columns populate from generic OTel telemetry (trace counts, latency percentiles, container metrics). This is *exactly the kind of honest cross-app result reviewers like to see*: structural compatibility holds; the feature-value gap is the boundary of "where source-app instrumentation matters."
* Phase 4 (full corpus collection on GCP `e2-standard-16` VM): **in progress.** Targets ~135 runs / ~9,300 windows / 32 scenario families (27 transferred + 5 new Kafka-only).

**Why this is the strongest path for ICSE acceptance:**

1. It directly addresses the most likely reviewer critique (external validity).
2. The architectural-distance evidence is *structural* (Kafka async), not just scale (more services). Reviewers can see why it matters.
3. The two-column zero-shot / L1-retrained design is honest and quantitative — it tells reviewers exactly what generalizes and what doesn't.
4. The local-pilot cross-app gap (12/94 features populate generically) is already a publishable mini-finding, even before the full GCP collection finishes.
5. It reuses the existing pipeline — no architectural rewrite — so the engineering risk is bounded.

### Recommendation

**Stay the course on OTel Demo cross-app collection (Option C) as the headline external-validity story.** Keep TAWOS as a length-and-style anchor and as a real-Jira retrieval reference (we already have it loaded locally). Defer Train-Ticket (we have the scaffolding) and the TAWOS-telemetry-pairing direction (Option A) as future work that other papers can build on.

For an ICSE submission, the suggested table-of-contents is:

1. Introduction — bottleneck framing, headline claim.
2. Dataset construction — Online Boutique 6,720 windows + 347 V2 tickets + 110 distractors.
3. The seven pipelines and the Pareto-incomparable observation.
4. The TCH cascade — four layers, math, worked example.
5. Results on Online Boutique — Hit@5 0.912, novel recall 0.793.
6. **Cross-app generalization on OTel Demo — zero-shot + L1-retrained two-column table.** (the new headline)
7. Ablations and robustness — 13 baseline ablations, G-series KEEP/SKIP, OOD F1.
8. Three findings — composition-fragility, three-rerankers-fail, retrieval-ceiling.
9. Limitations and threats to validity.
10. Conclusion.

The non-negotiables to land before submission:
* Finish OTel Demo full corpus collection on GCP (~135 runs).
* Run the cascade in zero-shot and L1-retrained modes on the OTel Demo test split.
* Report the feature-value-gap finding honestly (12/94 generic features) as a separate sub-result.
* Re-run the leave-one-family-out OOD F1 on OTel Demo to show novelty generalizes across *both* family shift and app shift.

The nice-to-haves:
* Score-scale renormalization to rescue G3 (Follow-up F-1 in our meta-analysis) — could close part of the 6.4-point Hit@5 ceiling gap. ~3 hours work.
* Smaller-LLM agent (Qwen 14B or 7B) for real-time inference at lower cost — would respond to the natural reviewer question "is this practical?"

---

## 11. Conclusion (one paragraph)

We built a controlled microservice-telemetry corpus from scratch (6,720 labeled windows + 347 humanized Jira tickets), trained seven complementary diagnostic pipelines, and found that no single one dominated. A four-layer cascade — logistic-regression stacker over triage scores, dual-rule retrieval fusion (overlap-rerank for top-1, RRF for top-5), three-signal novelty detector, dict composition — combined the seven into a system that ties or beats every single baseline on every metric (Hit@5 = 0.912, Hit@1 = 0.722, MRR = 0.794, strict PR-AUC = 0.9998) while lifting novel recall from 0.163 to 0.793 (+388% rel) at unchanged precision. The cascade runs at 16 µs per window. The next move — already in progress on the `otel-demo-cross-app` branch — is a cross-architecture validation on the OpenTelemetry Demo, with a two-column zero-shot / L1-retrained headline designed to answer the external-validity question an ICSE reviewer will ask.

---

## Appendix — Where to find more

| Topic | File |
|---|---|
| Comprehensive technical report (full 40-page version) | `technical-paper/main.tex` |
| Dataset construction details | `technical-paper/sections/02-dataset-construction.tex` |
| TCH cascade mathematical specification | `technical-paper/sections/05-tch-cascade.tex` |
| G-series per-phase observation logs | `docs4/G{1..8}-*.md`, `docs4/META-ANALYSIS.md` |
| Cross-app plan and status | `docs5/00-otel-demo-cross-app-plan.md`, `docs5/02-implementation-status.md` |
| GCP collection runbook | `docs5/03-gcp-instructions.md` |
| Reproducibility guide | `docs3/19-REPRODUCE.md` |
| Cascade implementation | `src/v2_advanced/tch/build_cascade.py` |
| Locked dataset | `data/derived/global/2026-05-25-dataset-v5-large-global/` |
| Final cascade commit | `b7557c4` on `master-final-models` |
