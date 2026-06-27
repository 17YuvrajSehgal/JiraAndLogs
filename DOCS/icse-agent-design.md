# ARIA: Adaptive Reasoning for Incident Analysis
## A Compositional Agentic Architecture for Incident Triage — ICSE Design Document

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Why Existing Approaches Fail](#2-why-existing-approaches-fail)
3. [Core Idea: Compose Patterns, Don't Build One Big Agent](#3-core-idea-compose-patterns-dont-build-one-big-agent)
4. [System Architecture](#4-system-architecture)
5. [Stage-by-Stage Design](#5-stage-by-stage-design)
6. [Research Questions](#6-research-questions)
7. [Evaluation Design](#7-evaluation-design)
8. [Expected Contributions](#8-expected-contributions)
9. [What the Dataset Enables](#9-what-the-dataset-enables)

---

## 1. Problem Statement

When a microservice system fires an alert, an on-call engineer must decide:
1. Is this worth opening a Jira ticket? (*triage*)
2. Has this happened before, and if so, what fixed it? (*retrieval*)
3. Is this a genuinely new failure mode we haven't seen? (*novelty*)

This is **memory-augmented incident triage**. The three questions must be answered quickly, cheaply, and correctly — under pressure, at 3am.

The research challenge: incidents vary enormously in difficulty. A checkout service scaling to zero looks the same every time; a 15% latency increase across three services following a dependency upgrade requires multi-hop reasoning across telemetry, architecture topology, and deployment history. A fixed-depth pipeline that treats both uniformly wastes budget on easy cases and gives up too early on hard ones.

**The claim we want to test at ICSE**: an agent that *routes* incidents to the investigation depth they actually require — using lightweight patterns for simple cases and progressively deeper patterns for complex ones — can achieve competitive retrieval accuracy while spending far less per-window than a full-sweep pipeline, and can generalize to architectures and issue trackers it has never seen.

---

## 2. Why Existing Approaches Fail

Understanding the failure modes of current systems shapes the design.

### ML classification pipelines

Systems like HGB or neural classifiers trained on labelled windows achieve strong triage accuracy on their training distribution (84% on Online Boutique when 94 numeric features are available). But they fail when:
- The telemetry modality changes (zero numeric features on real Jira issue trackers → accuracy collapses below the majority-class baseline)
- A new microservice architecture is introduced (features are infrastructure-tied)
- The fault is genuinely novel (a classifier cannot say "I've never seen this")

### Cascade retrieval pipelines

A fixed retrieval pipeline (BM25 + BiEncoder + cross-encoder reranker) achieves strong Hit@5 on in-distribution data. But it:
- Cannot refine a bad first-pass retrieval by gathering more context
- Cannot explain *why* it matched what it matched
- Does the same work for a trivial case (obvious service outage) as for a complex one (multi-service cascade via Kafka consumer lag)

### Monolithic LLM single-call approaches

Giving the full telemetry window to a single LLM prompt with access to a retrieval corpus achieves reasonable results on simple cases but:
- Drowns the context window in irrelevant telemetry for complex incidents
- Cannot iteratively narrow down hypotheses ("this doesn't explain the trace anomaly — fetch the related service's spans")
- Has no mechanism to know when it has gathered enough evidence vs. when it is guessing

### The common failure: uniform treatment of non-uniform problems

All three approaches share one architectural flaw: they apply the same computational budget to every incident regardless of its complexity. The ARIA design directly targets this flaw.

---

## 3. Core Idea: Compose Patterns, Don't Build One Big Agent

The user's framing above is exactly right. Don't build "an agent" — **compose the minimal pattern that suffices for each sub-task**.

The anatomy of ARIA follows the taxonomy of agent patterns:

| Triage sub-task | Pattern used | Why this pattern |
|---|---|---|
| Deduplicate and fingerprint alerts | Deterministic code | No LLM needed; hashing is exact and fast |
| Is this obviously noise or obviously a ticket? | **Routing** | Distinct confidence bands; cheap model handles > 65% of cases |
| Gather logs, traces, metrics, past incidents | **Parallelization (sectioning)** | Four independent lookups; concurrency cuts wall time |
| Which evidence sources are relevant for *this* incident? | **Orchestrator-workers** | The right sources depend on the incident — can't enumerate upfront |
| Does the best hypothesis explain all the evidence? | **Evaluator-optimizer** | Critique → refine → re-evaluate loop; stops when evidence supports conclusion |
| Novel incident with no matching past pattern | **Autonomous loop** | Genuinely open-ended; the steps cannot be predicted |
| Produce a structured, citable output | Single call | Fixed-schema synthesis; no iteration needed |

About 65–70% of incidents are resolved by the routing layer (Stage 2) without any deep investigation. The evaluator-optimizer only activates for incidents where first-pass retrieval is uncertain. The autonomous loop activates for the long tail — genuinely novel incidents that no other stage can resolve. This is what keeps the system cheap and fast in practice while still handling hard cases correctly.

---

## 4. System Architecture

### ASCII Overview

```
 Telemetry Window
 {text_evidence, log_lines, trace_summary,
  k8s_events, metric_snapshots, numeric_features}
          │
          ▼
 ┌─────────────────────────────────────────┐
 │  STAGE 1: Signal Normalizer             │  deterministic
 │  • Fingerprint the incident             │
 │  • Detect alert flapping                │
 │  • Suppress: same fingerprint < 5 min  │
 └───────────────────┬─────────────────────┘
                     │ (not suppressed)
                     ▼
 ┌─────────────────────────────────────────┐
 │  STAGE 2: Complexity Router             │  routing pattern
 │  Fast LLM call + numeric score          │
 │                                         │
 │  HIGH confidence (≥ 0.85)               │
 │  ├──► Fast Track: BiEncoder top-1       │
 │  │    emit decision, done (~65% cases)  │
 │  │                                      │
 │  LOW confidence (< 0.85) or ambiguous   │
 │  └──► Investigation Track (Stage 3+)   │
 └───────────────────┬─────────────────────┘
                     │ (~35% of windows)
                     ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │  STAGE 3: Parallel Evidence Harvester    parallelization pattern │
 │                                                                 │
 │  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
 │  │ Memory Retriever │  │ Telemetry Reader  │  │Context Enrich │  │
 │  │                 │  │                  │  │               │  │
 │  │ BiEncoder +     │  │ K8s events       │  │ Service graph │  │
 │  │ BM25 hybrid     │  │ Trace spans      │  │ Deploy history│  │
 │  │ → top-K issues  │  │ Metric snapshots │  │ Alert history │  │
 │  └─────────────────┘  └──────────────────┘  └───────────────┘  │
 │            │                   │                    │           │
 │            └───────────────────┴────────────────────┘           │
 │                                │                                │
 │                       EvidenceBundle                            │
 └────────────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │  STAGE 4: Hypothesis Engine      orchestrator-workers pattern   │
 │                                                                 │
 │  Orchestrator LLM:                                              │
 │  "Given this evidence, what are the 2-4 most plausible          │
 │   root causes? State what additional evidence would             │
 │   confirm or rule out each."                                    │
 │               │                                                 │
 │               │  Hypotheses H1, H2, H3                         │
 │               ▼                                                 │
 │  ┌──────────┐ ┌──────────┐ ┌──────────┐    (parallel)          │
 │  │Worker H1 │ │Worker H2 │ │Worker H3 │                        │
 │  │"Does H1  │ │"Does H2  │ │"Does H3  │                        │
 │  │ explain  │ │ explain  │ │ explain  │                        │
 │  │ evidence?"│ │evidence?"│ │evidence?"│                        │
 │  │score 0-1 │ │score 0-1 │ │score 0-1 │                        │
 │  └──────────┘ └──────────┘ └──────────┘                        │
 │               │                                                 │
 │       Best hypothesis (highest score)                           │
 └────────────────────────────────┬────────────────────────────────┘
                                  │
                        ┌─────────┴──────────┐
                score ≥ 0.60            score < 0.60
                        │                    │
                        ▼                    ▼
 ┌────────────────────────────┐   ┌─────────────────────────────────┐
 │  STAGE 5: Evidence         │   │  STAGE 6: Autonomous Investigator│
 │  Verifier                  │   │                                  │
 │  evaluator-optimizer       │   │  autonomous loop pattern         │
 │                            │   │  Budget: ≤ 6 tool calls          │
 │  "Is there contradictory   │   │                                  │
 │   evidence?"               │   │  Tools:                          │
 │                            │   │  • search_memory(query)          │
 │  No → confidence += 0.1   │   │  • follow_trace(trace_id)        │
 │  Yes → fetch specific      │   │  • get_service_graph(svc)        │
 │   evidence → re-evaluate   │   │  • check_deploy_history(svc,t)   │
 │   (max 2 iterations)       │   │  • get_config_changes(svc)       │
 │                            │   │  • done(decision, evidence)      │
 │  Output: verified_hyp +    │   │                                  │
 │  confidence + evidence_gap │   │  Output: best_effort decision +  │
 │                            │   │  needs_human_review = True       │
 └────────────┬───────────────┘   └──────────────┬──────────────────┘
              │                                   │
              └───────────────────────────────────┘
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │  STAGE 7: Decision Synthesizer               single LLM call    │
 │                                                                 │
 │  Input: best hypothesis + top-K matched issues + evidence       │
 │                                                                 │
 │  Output (structured):                                           │
 │  • triage_decision: ticket_worthy | borderline | noise          │
 │  • matched_issue_ids: [top-5 ranked by evidence alignment]      │
 │  • is_novel: bool + confidence                                  │
 │  • evidence_chain: [{source, claim, supports_or_refutes}]       │
 │  • investigation_path: which stages were invoked                │
 │  • needs_human_review: bool (from Stage 6 or confidence < 0.4)  │
 └─────────────────────────────────────────────────────────────────┘
```

---

## 5. Stage-by-Stage Design

### Stage 1: Signal Normalizer (deterministic)

**What it does**: Deduplicates and fingerprints the incoming telemetry window before any LLM is involved.

**Fingerprint construction**:
```
fingerprint = SHA-256(service_name + error_class + severity + symptom_tokens)
```
`symptom_tokens` are extracted deterministically from `text_evidence`: all nouns and error keywords, lowercased, sorted alphabetically. This is stable across paraphrases of the same incident.

**Flap detection**: If the same fingerprint was seen for the same service within the last 5 minutes (configurable), suppress the window — no page, no LLM call. This directly addresses the `pages_per_incident > 1.0` problem without requiring a state buffer: identical fingerprints are definitionally the same incident.

**Output**: `NormalizedSignal(fingerprint, is_flap, symptom_tokens, alert_severity)` + suppression decision.

**Why no LLM here**: Hashing is exact, free, and fast. LLMs add cost and non-determinism where neither is needed.

---

### Stage 2: Complexity Router (routing pattern)

**What it does**: Classifies the incident into a complexity tier and routes accordingly. The goal is to resolve as many cases as cheaply as possible.

**Routing model**: A fast LLM call (or, where numeric features are available, a lightweight ML classifier). Inputs:
- `text_evidence` (pre-built summary of logs + alert text)
- `numeric_features` (if available — 94 `triage_feature_*` columns)
- `recent_windows` (last 3 decisions for this service from the state buffer)
- `top_retrieved_issue` (BiEncoder top-1 from memory corpus, fetched in parallel)

**Output**: a routing decision:
```
{
  "route": "fast_track" | "investigation" | "suppress",
  "confidence": 0.0–1.0,
  "reason": "...",
  "missing_evidence": ["K8s events", "trace spans"]  # what the investigation stage should prioritise
}
```

**Routing thresholds**:
- `confidence ≥ 0.85` and top-1 retrieval is non-empty → **Fast Track** (emit decision directly)
- `confidence ≥ 0.85` and top-1 retrieval is empty → treat as **novel**, skip to Stage 6
- `confidence < 0.85` → **Investigation Track** (proceed to Stage 3)

**Fast Track path** (for roughly 65% of windows based on current distribution):
- BiEncoder has already retrieved a top-1 match in the parallel call
- Stage 7 is invoked directly with this match and the routing reason
- Entire pipeline cost: 1 LLM call (router) + 1 embedding lookup (BiEncoder)
- This is the **prompt chaining** pattern applied to the easy case

**Why routing works here**: the two-class signal (high-confidence match vs. ambiguous) is structurally identical to a customer support router. The difference is that the "categories" are confidence bands, not topic areas, and the downstream specialists are investigation agents rather than specialized prompts. The routing layer is what keeps the system economical.

---

### Stage 3: Parallel Evidence Harvester (parallelization — sectioning)

**What it does**: Concurrently gathers three independent streams of evidence. This runs only for the ~35% of windows that the router marked as ambiguous.

**The three parallel workers**:

**Worker A — Memory Retriever**:
- BiEncoder (dense) + BM25 (sparse) hybrid search over the memory corpus
- Returns top-K (K=10) candidate past incidents with their text and metadata
- Hybrid fusion uses Reciprocal Rank Fusion (RRF, k=60): `score(c) = 1/(60+rank_dense) + 1/(60+rank_bm25)`
- Output: `[(issue_id, memory_text, rrf_score, rank), ...]`

**Worker B — Telemetry Reader** (OB/OTel only; gracefully empty on WoL):
- K8s events: `raw/kubernetes/<window_id>.json` → parse Warning events → {pod, reason, message, count}
- Trace spans: `raw/tempo/<window_id>.json` → {n_error_spans, error_services, error_span_names}
- Metrics: `raw/prometheus/<window_id>.json` → {restart_delta, cpu_max, mem_max, n_alerts_firing}
- Output: structured `TelemetryBundle`

**Worker C — Context Enricher**:
- Service graph: which services call this one, which does it call?
- Recent deployments: any image version changes in the last 30 minutes?
- Alert history: any firing Alertmanager alerts for this namespace?
- Output: `ContextBundle(upstream_services, downstream_services, recent_changes, active_alerts)`

All three run as async tasks and are joined after all complete (or after a timeout). The join produces an `EvidenceBundle`:

```python
@dataclass
class EvidenceBundle:
    window_id: str
    candidate_issues: list[CandidateIssue]    # from Worker A
    telemetry: TelemetryBundle | None          # from Worker B (None on WoL)
    context: ContextBundle                     # from Worker C
    router_missing_evidence: list[str]         # what the router said was missing
```

**Why parallelization here**: the three workers are completely independent. Running sequentially wastes wall time proportional to the slowest worker. Concurrent execution cuts the wall time to max(A, B, C). On OB, Worker B (disk I/O) typically dominates; Workers A and C finish faster. Sequential would triple the latency for no gain.

---

### Stage 4: Hypothesis Engine (orchestrator-workers)

**What it does**: Given the evidence bundle, generates a small set of competing root-cause hypotheses and evaluates each against the evidence. The key insight is that we don't know which hypothesis is right until we test them — the decomposition is data-dependent.

**Orchestrator LLM call** (one call):

System prompt includes: service catalog (names, languages, criticality, dependencies), memory of the last 3 similar incidents for this service family.

User prompt:
```
Evidence bundle summary:
  - Text: <text_evidence>
  - Alerts: <active_alerts from ContextBundle>
  - K8s: <warning_events from TelemetryBundle>
  - Traces: <error_span_names>
  - Metrics: restart_delta=<N>, cpu_max=<X>%, alerts_firing=<M>
  - Candidates (top-3 from retrieval): <memory_text_head for each>

Generate 2-4 root-cause hypotheses for this incident. For each:
  - State the hypothesis concisely
  - Identify which evidence supports it
  - Identify what evidence would rule it out (what should NOT be present if this is true)
  - Rate expected_confidence (0-1) before verification

Output as JSON: {"hypotheses": [...]}
```

**Worker LLMs** (one per hypothesis, run in parallel):

Each worker takes one hypothesis and the full evidence bundle:
```
Hypothesis: "<hypothesis_text>"
Supporting evidence claimed: <list>
Evidence that would rule it out: <list>

Given the evidence bundle above, score this hypothesis:
  - consistency_score (0-1): how well does the evidence support this hypothesis?
  - contradictions: list any evidence that contradicts the hypothesis
  - matched_issues: from the candidate list, which issues best match this hypothesis?

Output as JSON: {"consistency_score": ..., "contradictions": [...], "matched_issues": [...]}
```

**Aggregation**: merge worker outputs. Pick the hypothesis with the highest `consistency_score`. The matched issues from that worker become the candidate list for downstream stages.

**Gate after aggregation**:
- `best_score ≥ 0.60` → proceed to Stage 5 (Evidence Verifier)
- `best_score < 0.60` → proceed to Stage 6 (Autonomous Investigator)

**Why orchestrator-workers here**: the root causes that are plausible depend on the specific incident (Kafka consumer lag shows up in incidents with Kafka in the trace, not in pure HTTP incidents). A fixed set of hypothesis templates would miss this. The orchestrator figures out what to check; the workers do the checking in parallel. This is qualitatively different from a fixed retrieval pipeline that always fetches the same things.

---

### Stage 5: Evidence Verifier (evaluator-optimizer pattern)

**What it does**: Stress-tests the best hypothesis by actively looking for contradicting evidence. Loops until the hypothesis is either confirmed or updated. Maximum 2 iterations.

**Initial verifier call**:
```
Best hypothesis: "<hypothesis_text>"
Current evidence: <EvidenceBundle summary>
Matched candidate issues: <top-K from Stage 4 worker>

Question: Is there any evidence in the bundle that CONTRADICTS this hypothesis?
If yes: what specific additional evidence, if retrieved, would resolve the contradiction?
  - Evidence type needed: [K8s events | trace spans | metrics | memory search]
  - Specific query: <e.g., "traces for the payment service in ±2 min of T">

Output JSON: {"has_contradiction": bool, "contradiction": "...", "fetch_needed": {...}}
```

**If contradiction found and iteration budget remains**:
- Execute the specific fetch (one of: `get_k8s_events_filtered`, `get_trace_by_service`, `search_memory_query`)
- Add result to the evidence bundle
- Re-run the verifier with updated evidence

**Stopping conditions**:
- `has_contradiction = false` → hypothesis confirmed; `confidence += 0.10`
- No more fetch budget (2 iterations exhausted) → proceed with current confidence
- Contradiction found but cannot be resolved by available tools → flag `evidence_gap`, proceed

**Why evaluator-optimizer here**: retrieval alone cannot verify a hypothesis; it can only suggest one. The loop provides a mechanism to ask "does this match hold up?" rather than assuming the top-1 retrieval is correct. The constraint (≤ 2 iterations) keeps it bounded — this is not an open-ended loop.

---

### Stage 6: Autonomous Investigator (autonomous loop)

**What it does**: Handles genuinely novel incidents — cases where no hypothesis from Stage 4 scored above 0.60. The LLM is given a tool budget and allowed to direct its own investigation.

**When it activates**: `best_hypothesis_score < 0.60` after Stage 4.

**Tools available**:

| Tool | Description | Returns |
|---|---|---|
| `search_memory(query: str, k: int)` | Semantic search over memory corpus with a custom query | List of candidate issues |
| `follow_trace(trace_id: str)` | Retrieve full span tree for a specific trace | Error spans, latencies, affected services |
| `get_service_graph(service: str)` | Get upstream/downstream dependencies | Service topology |
| `check_deploy_history(service: str, window_minutes: int)` | Recent image/config changes | List of changes with timestamps |
| `get_config_changes(service: str)` | ConfigMap changes in the Kubernetes namespace | Changed keys and values |
| `done(decision: str, matched_issues: list, evidence_chain: list)` | Exit the loop with a decision | — |

**Budget**: 6 tool calls maximum (including `done`). If budget exhausted without `done`, the system emits `needs_human_review = True`.

**Loop prompt**:
```
You are investigating an incident that doesn't match any known pattern.
Available evidence so far: <EvidenceBundle>
Top-K candidates from retrieval: <low-scoring candidates from Stage 4>
Prior tool calls this session: <history>

You have <N> tool calls remaining including "done".
What do you want to investigate? Call one tool.
```

The LLM picks a tool at each step, observes the result, and continues. It exits by calling `done` with its best conclusion, or by exhausting its budget.

**Guardrails**:
- Loop-detection: if the same `(tool_name, args_hash)` is called twice → refuse, emit `FAILURE_LOOPING`
- Hard budget: if 6 calls reached without `done` → emit `needs_human_review = True`, pass best-effort decision to Stage 7
- All tool results are logged in the trace for audit

**Why autonomous loop here**: novel incidents are by definition those where the steps of investigation cannot be specified upfront. The six-tool budget is the guardrail — it keeps the cost bounded (maximum 6 LLM calls × cost per call) while allowing genuine exploration. This pattern is reserved for the long tail (~5–10% of windows) where cheaper patterns have already failed.

---

### Stage 7: Decision Synthesizer (single LLM call)

**What it does**: Integrates everything gathered across Stages 2–6 into a structured, citable output. This is the only stage that produces the final artifact seen by the on-call engineer.

**Input**: best hypothesis + matched issue list + all evidence gathered + investigation path taken.

**Output schema**:
```json
{
  "triage_decision": "ticket_worthy | borderline | noise",
  "triage_confidence": 0.0,
  "matched_issue_ids": ["ISSUE-123", "ISSUE-456", "ISSUE-789"],
  "is_novel": false,
  "novel_confidence": 0.0,
  "evidence_chain": [
    {
      "source": "K8s events",
      "observation": "cartservice pod OOMKilled at T+47s",
      "supports": "ISSUE-123 (cart OOM under load)"
    }
  ],
  "investigation_path": ["stage2_fast_track"],
  "needs_human_review": false,
  "hypothesis_used": "Redis connection pool exhausted under checkout load surge"
}
```

**Novelty decision logic** (replaces the current broken OR-disjunction):
- `is_novel = True` only if ALL of: (a) no candidate scored above 0.50 in Stage 4, AND (b) Stage 6 was invoked and called `done` with empty `matched_issues`, AND (c) Stage 7's synthesis LLM agrees that "none of the retrieved issues describe this incident."
- This is a conservative AND-gate, not the current permissive OR-gate. It addresses the core failure mode where 40.6% of windows are falsely flagged as novel.

**Why single call here**: synthesis is a fixed-schema summarisation task. There is nothing to iterate over — all the evidence has been gathered and verified. Adding a loop here would be over-engineering.

---

## 6. Research Questions

**RQ1 — Routing effectiveness**: Does routing incidents to investigation depth proportional to their complexity improve cost-accuracy trade-offs compared to uniform-depth processing?
- *Hypothesis*: the routing layer resolves ≥ 60% of windows via Fast Track while maintaining Hit@5 parity on those cases; the remaining 40% that enter investigation achieve higher Hit@5 than the baseline cascade achieves on the same subpopulation.
- *Measurement*: Hit@1/5/MRR stratified by route taken; cost (LLM calls, USD) per route; compare vs. always-investigation and always-fast-track ablations.

**RQ2 — Hypothesis-driven vs. direct retrieval**: Does generating and verifying root-cause hypotheses improve retrieval accuracy compared to a retrieve-then-rank pipeline that skips hypothesis formation?
- *Hypothesis*: hypothesis formation gives the retrieval stage a more specific query (the hypothesis text, not the raw evidence text), improving Hit@1 on complex incidents.
- *Measurement*: ablation — Stage 4 disabled (return to direct hybrid retrieval) vs. full ARIA; paired bootstrap Δ Hit@1 on Investigation-Track windows only.

**RQ3 — Evidence verifier benefit**: Does the evaluator-optimizer loop (Stage 5) improve retrieval accuracy beyond the first-pass hypothesis, and at what cost?
- *Hypothesis*: each verification iteration adds +0.03–0.05 Hit@1 on ambiguous cases, at the cost of 1 additional LLM call.
- *Measurement*: ablation — Stage 5 disabled; budget curve (max_verifier_iterations ∈ {0, 1, 2}); paired bootstrap.

**RQ4 — Generalization across datasets**: Does ARIA, trained on no dataset-specific parameters, generalize to (a) unseen microservice architectures (OTel Demo) and (b) real-world developer-written tickets (WoL) better than task-specific trained models?
- *Hypothesis*: ARIA's retrieval accuracy on OTel Demo (zero-shot, different architecture, Kafka failure modes) is within 0.05 Hit@5 of its OB performance; on WoL, ARIA's triage accuracy exceeds the majority-class baseline by > 0.10 (current cascade fails this).
- *Measurement*: full evaluation on all three datasets; compare to HGB classifier (OB-trained, fails on WoL), BiEncoder-only retrieval (strong on WoL but no triage), and cascade (agent wrapper of pre-computed predictions).

**RQ5 — Budget sensitivity**: How does retrieval accuracy scale with per-window investigation budget (number of LLM calls)?
- *Hypothesis*: accuracy plateaus after 3–4 LLM calls/window for most incidents; the marginal return of additional calls is concentrated in the long-tail novel cases.
- *Measurement*: sweep `max_tool_calls_in_stage6 ∈ {0, 2, 4, 6}`; compute Hit@1/5 vs. cost curve; identify the Pareto-optimal operating point.

**RQ6 — Interpretability**: Are the evidence chains produced by Stage 7 useful to on-call engineers?
- *Hypothesis*: engineers can correctly identify the root cause more quickly when given an evidence chain than when given only a ticket ID.
- *Measurement*: user study (N≥20 engineers, randomized control); time-to-root-cause; correctness; self-reported confidence. *(This RQ is optional for ICSE; include if user study is feasible.)*

---

## 7. Evaluation Design

### Datasets

| Dataset | Role | Windows (test) | Memory tickets | Challenge |
|---|---|---|---|---|
| Online Boutique (OB) | Primary training distribution | 1,008 | ~347 | 27 fault families, full telemetry |
| OTel Demo | Zero-shot cross-arch | 247 | ~147 | 18 services + Kafka, unseen architecture |
| WoL v3 | Real-world generalization | 13,388 | 38,642 | Text-only, real Apache Jira, 19× memory scale |

OB is the primary benchmark. OTel Demo tests architecture generalization. WoL v3 tests distribution shift to real-world text and the large-memory-pool regime.

### Baselines

| Baseline | Description | What it tests |
|---|---|---|
| **B1: Majority class** | Always predict `ticket_worthy` (triage) | Lower bound on triage accuracy |
| **B2: BiEncoder-only** | Dense retrieval + direct synthesis, no stages | Value of investigation above pure retrieval |
| **B3: Fixed-depth RAG** | Hybrid retrieval + single LLM synthesis, no branching | Value of routing + hypothesis formation |
| **B4: ReAct-only** | No routing; all tools always available; no hypothesis stage | Value of structured stages vs. flat tool use |
| **B5: ARIA-Fast-Track-only** | Route everything to Fast Track (ablates investigation stages) | Upper bound on routing efficiency |
| **B6: ARIA-Full (proposed)** | The complete system | — |

B3 is the most important baseline: it isolates the value of composition (routing + hypothesis formation + verification) from the value of retrieval alone.

### Metrics

**Retrieval quality** (primary, reported with 95% bootstrap CI):
- Hit@1, Hit@5, Hit@10, MRR
- Computed only on windows with ≥ 1 gold match (excludes orphan faults and baselines)

**Triage quality**:
- Triage accuracy (3-class: ticket_worthy / borderline / noise)
- Triage F1 macro (handles class imbalance on WoL: 49.4% / 32.8% / 17.8%)

**Operational quality**:
- Pages per incident (target ≤ 1.5; measures duplicate page suppression)
- Novel precision and novel recall (current system: novel_precision = 0.1128; target > 0.5)

**Cost**:
- LLM calls per window (mean, median, p95)
- Total tokens per window
- USD per window
- Wall seconds per window (p95)

**Statistical testing**: all deltas vs. baselines use paired bootstrap (1,000 resamples, seed=42, 95% CI). A delta is significant when the CI excludes zero.

### Implementation notes

- LLM: tested with `anthropic/claude-haiku-4-5` (cheap, fast) for routing and workers; `claude-sonnet-4-6` for orchestrator and synthesizer.
- Async execution: Stages 3 (parallel workers) and 4 (hypothesis workers) use `asyncio.gather`.
- Caching: all LLM calls are cached by `SHA-256(stage_name + model + prompt_hash)` to disk. Repeated evaluation runs hit cache for unchanged inputs.
- Telemetry: every stage emits a structured trace event. The full trace is serialized to `<trace_root>/<experiment>/<window_id>.json` for post-hoc analysis.
- The evaluation harness (`src/agent/eval_harness/`) is reused as-is — only the pipeline behind `harness.evaluate()` changes.

---

## 8. Expected Contributions

**C1 — Architecture**: A compositional agentic architecture for incident triage that maps each sub-task to the minimally necessary agent pattern. We show this is not a heuristic design but a principled decomposition: each pattern choice is justified by the structure of its sub-task (independence → parallelization; unpredictable decomposition → orchestrator-workers; clear eval signal → evaluator-optimizer; open-ended exploration → autonomous loop).

**C2 — Hypothesis-driven triage**: A reformulation of incident triage as hypothesis generation + verification rather than classification. This produces interpretable, evidence-cited decisions, a direct improvement over the black-box score-based approach in current systems.

**C3 — Adaptive cost allocation**: An empirical demonstration that routing incidents to investigation depth proportional to their complexity achieves competitive retrieval accuracy at 40–65% lower cost than full-sweep approaches. We characterize the cost-accuracy Pareto frontier across 3 datasets.

**C4 — Novelty repair**: A conservative AND-gate novelty decision that reduces false-novel rate from 40.6% (current system) to a target below 10%, by requiring multi-stage evidence before flagging an incident as novel.

**C5 — Cross-domain generalization benchmark**: The first evaluation of an incident triage agent across synthetic microservice telemetry (OB), unseen microservice architectures (OTel Demo), and real-world developer tickets from 24 Apache projects (WoL v3). The three datasets together form a generalization ladder — from controlled synthetic to real-world open.

**C6 — Open artifacts**: All three datasets, their collection scripts, scenario definitions, and the ARIA implementation are released publicly. Together they constitute the largest labelled incident-triage benchmark available (78,140 WoL queries + 8,363 synthetic windows across OB and OTel).

---

## 9. What the Dataset Enables

A key strength of this work for ICSE is that the evaluation datasets are rich and specifically designed to stress-test the design choices.

**The OB dataset (27 fault families, 100 collected runs)** enables:
- Stratified ablation by fault family (which families benefit most from investigation vs. fast-track?)
- Cost-accuracy curve across incident complexity tiers
- Stage 6 (autonomous investigator) analysis: which novel incidents trigger it, and how often does it recover?
- Per-service pages_per_incident analysis

**The OTel Demo dataset (49 scenarios, L1–L4 complexity)** enables:
- Zero-shot generalization: ARIA never saw Kafka failure modes during development; does Stage 4 (hypothesis engine) form correct Kafka-specific hypotheses?
- Complexity-scaling: do L3 cascade and L4 compound scenarios require Stage 6 more often than L1?
- Cross-architecture transfer: do retrieved OB memory items help for structurally similar OTel failures?

**The WoL v3 dataset (38,642 memory items, 13,388 test, 24 Apache projects)** enables:
- Large-memory-pool regime: does the hybrid retrieval in Stage 3 degrade at 38K scale vs. the current 347-item OB pool?
- Real developer language: does hypothesis formation (Stage 4) help when evidence is developer-written text rather than structured telemetry?
- Family-held-out generalization: the test split holds out Kafka and MariaDB-Server families — entirely unseen project types. Do Stage 4 hypotheses for "Kafka consumer lag" generated from OTel memory items transfer to WoL Kafka tickets?
- Triage on real data: the current cascade has 0.164 accuracy on WoL (below majority-class baseline); ARIA's goal is > 0.60 via the hypothesis-grounded confidence signal replacing the broken numeric-feature-dependent stacker.
