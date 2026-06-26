# Agentic Incident Triage System

This document explains how the agent works: what it does, what data flows through it, how its components connect, and how to run it. It is intended for a new researcher who wants to understand or extend the system.

---

## Table of Contents

1. [What the Agent Does](#what-the-agent-does)
2. [Architecture Overview](#architecture-overview)
3. [Core Data Types](#core-data-types)
4. [Layer-by-Layer Walkthrough](#layer-by-layer-walkthrough)
   - [Data Loaders](#1-data-loaders)
   - [Capabilities Observer](#2-capabilities-observer)
   - [Controller](#3-controller)
   - [Runner](#4-runner)
   - [Skills](#5-skills)
   - [State Layer](#6-state-layer)
   - [Data Lake](#7-data-lake)
   - [LLM Layer](#8-llm-layer)
5. [Per-Dataset Behaviour](#per-dataset-behaviour)
6. [Budget and Cost Management](#budget-and-cost-management)
7. [Evaluation Harness](#evaluation-harness)
8. [Running the Agent](#running-the-agent)
9. [Key File Index](#key-file-index)

---

## What the Agent Does

The agent receives a **window of telemetry** — a short time-slice of logs, metrics, and traces from a running microservice system — and produces two verdicts:

1. **Triage decision**: is this window `ticket_worthy` (a real engineer should open a Jira issue), `borderline`, or `noise`?
2. **Matched past incidents**: up to 5 Jira issue IDs from the memory corpus that are most similar to what the agent is observing.

Optionally the agent also flags a window as **novel** (no close match exists in memory).

The agent runs on three datasets, each progressively harder:

| Dataset | Evidence available | Challenge |
|---|---|---|
| **Online Boutique** | text, numeric features, K8s events, traces, metrics | Telemetry diagnosis in a known microservice environment |
| **OTel Demo** | same as OB but 18 services + Kafka | Unseen architecture; Kafka async failure modes |
| **World of Logs** | text only (real Apache Jira issues, no telemetry) | Generalisation to real-world engineer-written tickets |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         INPUT SIDE                                   │
│                                                                      │
│  global-triage-examples.jsonl   jira-memory-corpus.jsonl            │
│           │                              │                           │
│           ▼                              ▼                           │
│     DataLoader                      MemoryView                      │
│   (ob / wol / otel)          (retrieval corpus, shared)             │
│           │                                                          │
│           │  InputBundle                                             │
│           ▼                                                          │
│  CapabilitiesObserver ──► Capabilities (frozenset of 11 flags)      │
└──────────────────────────────────────────────────────────────────────┘
                    │
                    │  Capabilities + InputBundle
                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        CONTROLLER                                    │
│                                                                      │
│  CapabilityAwareRuleController                                       │
│                                                                      │
│  Selects branch based on window_type:                                │
│  ┌──────────────┬─────────────────┬──────────────┬───────────┐      │
│  │ active_fault │ recovery_window │ pre_fault    │ suppress  │      │
│  │ (full ReAct) │ (cheap path)    │ (numeric+    │ (compose  │      │
│  │              │                 │  compose)    │  only)    │      │
│  └──────────────┴─────────────────┴──────────────┴───────────┘      │
│                                                                      │
│  Emits: Plan (ordered SkillInvocations + gate functions)             │
└──────────────────────────────────────────────────────────────────────┘
                    │
                    │  Plan
                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         RUNNER                                       │
│                                                                      │
│  For each SkillInvocation in Plan:                                   │
│  1. Evaluate gate function → skip or proceed                         │
│  2. Check SkillCache → cache hit or miss                             │
│  3. Check Budget → abort if exhausted                                │
│  4. skill.invoke(bundle, memory, ctx) → SkillOutput                  │
│  5. Record in Trace; deduct from Budget                              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                     SKILLS                                  │     │
│  │                                                             │     │
│  │  Retrieval Skills (predictions-backed, read pre-computed)   │     │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │     │
│  │  │triage_numeric│ │retrieve_dense│ │retrieve_hybrid│        │     │
│  │  └──────────────┘ └──────────────┘ └──────────────┘        │     │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │     │
│  │  │retrieve_log_ │ │retrieve_know-│ │verify_with_  │        │     │
│  │  │sequence      │ │ledge_graph   │ │llm (gated)   │        │     │
│  │  └──────────────┘ └──────────────┘ └──────────────┘        │     │
│  │                                                             │     │
│  │  ReAct Evidence Tools (active_fault branch only)            │     │
│  │  ┌────────────────────┐ ┌──────────────────────────────┐   │     │
│  │  │request_pod_events  │ │request_extended_trace_window │   │     │
│  │  └────────────────────┘ └──────────────────────────────┘   │     │
│  │  ┌────────────────────┐ ┌──────────────────────────────┐   │     │
│  │  │request_pod_metrics │ │request_similar_incident_     │   │     │
│  │  └────────────────────┘ │window                        │   │     │
│  │                         └──────────────────────────────┘   │     │
│  │                              │ ToolResults in ctx.extra     │     │
│  │                              ▼                              │     │
│  │  ┌──────────────────────────────────────────┐              │     │
│  │  │  rerank_with_evidence                    │              │     │
│  │  │  (re-scores compose_l2 output using      │              │     │
│  │  │   tokens from accumulated ToolResults)   │              │     │
│  │  └──────────────────────────────────────────┘              │     │
│  │                                                             │     │
│  │  Composition Skills (read from Trace)                       │     │
│  │  compose_l2 → compose_triage → compose_novelty              │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  Emits: AgentDecision (triage_decision, matched_issue_ids, cost…)   │
└──────────────────────────────────────────────────────────────────────┘
                    │
                    │  AgentDecision
                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       STATE LAYER                                    │
│                                                                      │
│  Tracks per-service recent windows. If the same (top-1 match,       │
│  scenario_family) pair was seen recently with no recovery window     │
│  in between → suppress page (downgrade to "borderline").            │
│                                                                      │
│  Records WindowState for the next window in this incident.          │
└──────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
            EvaluationReport
     (Hit@1/5/10, MRR, triage_accuracy,
      novel_recall, pages_per_incident, cost)
```

---

## Core Data Types

All types are in `src/agent/types.py`. They are frozen dataclasses — immutable, hashable, serialisable.

### `InputBundle` — the central data packet

Everything the agent needs to process one telemetry window.

| Field | Type | Meaning |
|---|---|---|
| `window_id` | `str` | Unique key that links to raw telemetry files on disk |
| `dataset` | `str` | `"online_boutique"`, `"otel_demo"`, or `"wol"` |
| `text_evidence` | `str \| None` | Pre-built text summary of the window (logs + alert text) |
| `numeric_features` | `dict[str,float] \| None` | 94 `triage_feature_*` columns from the dataset |
| `log_lines` | `tuple[LogLine,...] \| None` | Structured log entries |
| `log_lines_ordered` | `bool` | True = temporally ordered (enables `ORDERED_LOGS` capability) |
| `trace_summary` | `TraceSummary \| None` | Span counts, error spans, P99 latency, affected services |
| `k8s_events` | `tuple[K8sEvent,...] \| None` | Pod warnings, OOMKills, restarts |
| `metric_snapshots` | `dict[str,tuple[float,...]] \| None` | CPU/memory time-series |
| `scenario_family` | `str \| None` | Ground-truth fault family (used by StateLayer for suppression) |
| `service_name` | `str \| None` | Which microservice this window is about |
| `window_type` | `str \| None` | `"pre_fault_baseline"`, `"active_fault"`, `"recovery_window"`, `"observation_window"` |
| `extra` | `dict` | Forward-compatible slot; carries `tool_results`, `tool_call_history`, fetchability flags |

**Fetchability flags** in `extra` tell the agent that raw telemetry exists on disk even though it is not embedded in the bundle. This allows lazy loading via ReAct tools:

```python
extra = {
    "k8s_events_fetchable": True,       # → enables K8S_EVENTS capability
    "trace_summary_fetchable": True,    # → enables TRACE_SUMMARY capability
    "metric_snapshots_fetchable": True  # → enables METRIC_SNAPSHOTS capability
}
```

### `AgentDecision` — the output per window

| Field | Type | Meaning |
|---|---|---|
| `triage_decision` | `"ticket_worthy" \| "borderline" \| "noise" \| "needs_review"` | Final verdict |
| `triage_score` | `float \| None` | Logistic stacker score (0–1); higher = more ticket-worthy |
| `matched_issue_ids` | `tuple[str,...]` | Up to 5 Jira issue IDs, ranked by relevance |
| `is_novel` | `bool \| None` | True = no close match found in memory |
| `confidence` | `float` | Confidence in the matched issues |
| `plan_id` | `str` | SHA-1 of the Plan that was executed (encodes the branch taken) |
| `skills_invoked` | `tuple[str,...]` | Which skills ran (for cost attribution and ablation) |
| `cost` | `SkillCallCost` | Aggregate LLM tokens, wall time, USD, and call count |
| `evaluation_mode` | `"telemetry_diagnosis" \| "text_retrieval_generalisation"` | Switches which metrics are computed |

### `SkillOutput` — what every skill returns

All skills return the same type so composition and aggregation are uniform:

```python
@dataclass(frozen=True)
class SkillOutput:
    skill: str                          # e.g. "retrieve_dense"
    skill_version: str                  # semver
    triage_score: float | None          # 0–1 if skill produces one
    triage_decision: TriageDecision | None
    matched_issue_ids: tuple[str, ...]  # retrieved issue IDs
    is_novel: bool | None
    confidence: float
    evidence_used: tuple[str, ...]
    cost: SkillCallCost
    extra: dict                         # skill-specific details
```

---

## Layer-by-Layer Walkthrough

### 1. Data Loaders

**Location**: `src/agent/data_loaders/`

The data loaders are the entry point. They read the locked global datasets and produce a list of `EvaluationCase` objects — one per telemetry window. Each case bundles together the `InputBundle`, the `MemoryView` (the retrieval corpus), and gold labels for evaluation.

Three loaders exist, one per dataset:

| Loader | Source | Key differences |
|---|---|---|
| `load_ob_cases()` | `data/derived/global/.../global-triage-examples.jsonl` | Sets all 3 fetchable flags in `extra`; enables all ReAct tools |
| `load_otel_demo_cases()` | Same layout | Same as OB; auto-detects gold source (cascade vs matchings) |
| `load_wol_cases()` | `data/derived/global/2026-06-17-wol-real-v3-global/` | No numeric features, no fetchable flags, text-only bundles |

**Split handling**: every loader accepts a `split` parameter (`"train"`, `"val"`, `"test"`). A split manifest (`triage-split-manifest-v2-resplit.json` for OB/OTel, `triage-split-manifest.json` for WoL) maps `window_id → split`. Evaluation always uses `split="test"`.

**Memory corpus**: the loader reads `jira-memory-corpus.jsonl` from the same global directory and wraps it as a `MemoryView`. All windows in the same evaluation share the same `MemoryView`.

**`order_by_incident_time=True`** (used for OB): sorts cases by `(service_name, incident_episode_id, start_time)` so the StateLayer sees the full temporal sequence of each incident — necessary for page suppression to work correctly.

---

### 2. Capabilities Observer

**Location**: `src/agent/capabilities_observer.py`

The Capabilities Observer examines the `InputBundle` and produces a `Capabilities` object — a frozenset of string flags describing what evidence is available for this window. These flags gate which skills are allowed to run.

**The 11 capability flags:**

| Flag | Set when |
|---|---|
| `NUMERIC_FEATURES` | `bundle.numeric_features` is present |
| `TEXT_EVIDENCE` | `bundle.text_evidence` has ≥ 8 characters |
| `ORDERED_LOGS` | `bundle.log_lines` present AND `log_lines_ordered=True` |
| `UNORDERED_LOGS` | `bundle.log_lines` present AND `log_lines_ordered=False` |
| `TRACE_SUMMARY` | `bundle.trace_summary.n_spans > 0` OR `extra["trace_summary_fetchable"]` |
| `K8S_EVENTS` | `bundle.k8s_events` present OR `extra["k8s_events_fetchable"]` |
| `METRIC_SNAPSHOTS` | `bundle.metric_snapshots` present OR `extra["metric_snapshots_fetchable"]` |
| `MEMORY_TEXT` | Memory corpus is available (set by `ObservationContext`) |
| `KG_GRAPH_MEMORY` | KG entities were extracted for memory corpus |
| `KG_GRAPH_WINDOW` | KG entities were extracted for this window (`v2_kg_extractions_windows/` exists) |
| `VERIFIER_KNOWN_HELPFUL` | `VerifierCalibration` says the LLM verifier is net-positive on this dataset |

The fetchability flags mean the agent can be told "this data exists on disk and can be fetched if needed" without embedding all the raw telemetry in every bundle upfront. ReAct tools then fetch it lazily when the controller decides it is worth querying.

---

### 3. Controller

**Location**: `src/agent/controller/`

The controller takes an `InputBundle` and a `Capabilities` set and returns a **Plan** — an ordered list of skill invocations, each optionally gated. The controller does not execute anything; it only decides what to execute and in what order.

The primary controller is `CapabilityAwareRuleController` (extends `RuleController`).

#### Branch selection

The controller selects one of five execution branches based on `bundle.window_type` and the StateLayer's suppression check:

| Branch | Trigger | Skills invoked |
|---|---|---|
| `state_suppress` | Same (top-1, scenario_family) seen recently, no recovery between | `compose_triage` only |
| `pre_fault` | `window_type = "pre_fault_baseline"` | `triage_numeric` + `compose_triage` + `compose_novelty` |
| `recovery` | `window_type = "recovery_window"` | `triage_numeric` + `retrieve_dense` + `compose_l2` + `compose_triage` + `compose_novelty` |
| `observation` | `window_type = "observation_window"` | Same as recovery |
| `active_fault` | `window_type = "active_fault"` (or default) | Full cascade: all retrievers + 4 ReAct tools + rerank + verifier (gated) + all composition skills |

The branch name is embedded in the `plan_id`, so evaluation reports can break down behaviour per branch.

#### Gate functions

Within the `active_fault` branch, skills are not all unconditional:

- **Escalation gate** (`make_escalation_gate(threshold=0.90)`): the expensive retrievers (log-sequence, hybrid fusion, KG) only run if the cheap path (`triage_numeric` score < 0.90 OR `retrieve_dense` found < 1 match). This avoids spending LLM budget when a simple lookup already found a confident answer.

- **Reformulation gate** (`make_reformulation_gate(confidence_floor=0.5)`): `reformulate_query` only runs if `compose_l2` was invoked AND the best retriever confidence is below 0.5 — i.e., retrieval is uncertain enough to be worth retrying with a rewritten query.

#### Plan object

```python
@dataclass(frozen=True)
class Plan:
    invocations: tuple[SkillInvocation, ...]  # ordered execution list
    global_budget: Budget                      # hard caps for this invocation
    fallback_chains: dict[str, tuple[str,...]] # on-failure routing
    controller_name: str
    plan_id: str                               # SHA-1 of (controller, budget, invocations)
```

---

### 4. Runner

**Location**: `src/agent/runner/runner.py`

The runner takes a `Plan` and an `InputBundle` and executes each `SkillInvocation` in order. It is stateless across calls — a single `AgentRunner` instance can safely process hundreds of windows concurrently if needed.

**Execution sequence for each invocation:**

```
1. gate(trace, budget) → False?  → emit "skill_skipped_by_gate", continue
2. registry.try_get(skill_name)  → None? → handle on_failure policy
3. cache.get(skill, key)         → hit?  → emit "cache_hit" + "skill_end", continue
4. budget.can_afford(per_call)   → False? → emit "budget_exceeded", abort plan
5. emit "skill_start"
6. skill.invoke(bundle, memory, ctx)  ← the actual work
7. exception?                    → emit "skill_failed", handle on_failure
8. budget.deduct(output.cost)    ← raises BudgetExhausted if over cap
9. cache.put(skill, key, output) ← best-effort
10. emit "skill_end"
```

`on_failure` policies: `"abort"` (stop the plan), `"fallback"` (try the next skill in the chain), `"continue"` (skip this skill and keep going).

**Building the final decision** (`_build_decision`):

The runner reads the trace after all skills have run and picks the best sources:

- `triage_decision` + `triage_score`: from `compose_triage` (always present)
- `matched_issue_ids`: from `rerank_with_evidence` if it ran, else `compose_l2`, else `retrieve_dense`
- `is_novel`: from `compose_novelty`
- `cost`: sum of all `skill_end` events that were not cache hits

The complete trace is serialised to `<trace_root>/<experiment>/<window_id>.json` for audit.

---

### 5. Skills

**Location**: `src/agent/skills/`

Every skill is a subclass of `Skill(ABC)` and has three class-level attributes that drive the controller and runner:

```python
class Skill(ABC):
    name: str                          # used as dict key in registry
    version: str                       # semver; mismatch triggers a warning
    required_flags: frozenset[str]     # capabilities needed to run
    cost_class: CostClass              # "cheap" | "medium" | "expensive_llm"
```

A skill only appears in the Plan if it is both registered and `can_invoke(capabilities)` returns True (i.e., `required_flags ⊆ capabilities.flags`).

#### 5a. Predictions-backed skills (retrievers and triage)

These skills do not call any external API at runtime. Instead, they read pre-computed predictions from JSONL files on disk — one file per pipeline, per dataset. The pipeline predictions were produced offline by the cascade retrieval system.

| Skill | Class | `required_flags` | Pipeline | Subdir |
|---|---|---|---|---|
| `triage_numeric` | `TriageNumericSkill` | `NUMERIC_FEATURES` | `hist_gradient_boosting_numeric` | `v2a-resplit` |
| `retrieve_dense` | `RetrieveDenseSkill` | `TEXT_EVIDENCE, MEMORY_TEXT` | `bi_encoder_retrieval` | `v2a-resplit` |
| `retrieve_log_sequence` | `RetrieveLogSequenceSkill` | `ORDERED_LOGS` | `logseq2vec_retrieval_pretrained` | `v2b-logseq2vec` |
| `retrieve_hybrid_fusion` | `RetrieveHybridFusionSkill` | `TEXT_EVIDENCE, MEMORY_TEXT` | `hybrid_rrf_retrieval` | `v2c-hybrid` |
| `retrieve_hybrid_fusion_llm` | `RetrieveHybridFusionLLMSkill` | `TEXT_EVIDENCE, MEMORY_TEXT, KG_GRAPH_MEMORY` | `hybrid_rrf_retrieval` | `v2c-hybrid-llm` |
| `retrieve_knowledge_graph` | `RetrieveKnowledgeGraphSkill` | `KG_GRAPH_MEMORY` | `kg_retrieval_rulebased` | `v2d-kg-rulebased` |
| `verify_with_llm` | `VerifyWithLLMSkill` | `VERIFIER_KNOWN_HELPFUL, TEXT_EVIDENCE` | `diagnosis_agent` | `v2e-agent-llm` |

Each file is a JSONL where each row is identified by `window_id`. The skill loads the file lazily on first access (thread-safe), then looks up the current `window_id`. `cost` is `SkillCallCost.zero()` because the prediction was pre-computed.

#### 5b. Composition skills

These run after the retrievers and read their outputs from the `Trace`.

**`compose_l2`** — Fuses retriever outputs into a single ranked list:
- Position 1: BiEncoder-anchored overlap rerank — take the top-3 from `retrieve_dense`, then score each by how many other retrievers also ranked it highly; pick the highest-overlap candidate.
- Positions 2–5: Reciprocal Rank Fusion (RRF, k=60) across all L2 retrievers.

**`compose_triage`** — Produces the final triage decision:
- Reads triage scores from `triage_numeric` and from `retrieve_dense` (its confidence).
- Runs a logistic stacker (trained coefficients + intercept) over these scores.
- Applies threshold 0.5: score ≥ 0.5 → `"ticket_worthy"`, else `"noise"`.

**`compose_novelty`** — Flags whether the incident is novel:
- Signal 1 (`free`): max retriever confidence < 0.5 (no strong match found).
- Signal 2 (`agent`): `verify_with_llm.is_novel` if the verifier ran.
- Signal 3 (`learned`): `ctx.extra["learned_novelty_prob"] >= 0.5` if a learned novelty scorer was attached.
- `is_novel = signal1 OR signal2 OR signal3`.

#### 5c. ReAct evidence-request tools

These run only in the `active_fault` branch. They are the **ReAct loop** — each tool fetches one piece of raw telemetry from the Data Lake, appends it as a `ToolResult` to `ctx.extra["tool_results"]`, and returns a `SkillOutput` with `triage_score=None` and `matched_issue_ids=[]`. Their outputs are consumed by `rerank_with_evidence`.

| Skill | `required_flags` | What it fetches |
|---|---|---|
| `request_pod_events` | `K8S_EVENTS` | K8s events from `raw/kubernetes/<window_id>.json` (warning count, reason, message) |
| `request_extended_trace_window` | `TRACE_SUMMARY` | Trace data from `raw/tempo/<window_id>.json` (services seen, error span names, counts) |
| `request_pod_metrics` | `METRIC_SNAPSHOTS` | Prometheus data from `raw/prometheus/<window_id>.json` (restarts, CPU/memory, alert count) |
| `request_similar_incident_window` | _(none)_ | Peer incident text from `jira-memory-corpus.jsonl` filtered by `scenario_family` |

Loop-detection guard: if the same tool is called ≥ 3 times with the same arguments, the skill returns `FAILURE_LOOPING` without fetching. A global cap (`max_tool_calls`, default 6) stops the loop if budget runs out.

#### 5d. `rerank_with_evidence`

After all ReAct tools have run, this skill reads the accumulated `ToolResults` from `ctx.extra` and re-scores the candidate list from `compose_l2`:

1. Extracts **evidence tokens** from each ToolResult:
   - Pod events: service name + `CamelCase`-split reason tokens + warning message tokens.
   - Extended trace: services seen + error span name tokens.
   - Pod metrics: synthesised tokens (`restart`→`{restart,crash,pod}`, `high_mem`→`{memory,oom,kill}`).
   - Similar incident: peer memory text tokens + component names.
2. For each of the top-K candidates from `compose_l2`, counts token overlap with evidence.
3. Re-sorts by `(-overlap_count, original_rank_in_l2)`.

If no evidence tokens were gathered (all tools failed or were skipped), the output is identical to `compose_l2` — it is a safe passthrough.

#### 5e. `reformulate_query`

An optional LLM skill that rewrites `text_evidence` when retrieval confidence is low, then re-runs the retrieval pipeline. It is gated by the `reformulation_gate` and only activates when `compose_l2` ran with confidence below 0.5.

Three reformulation actions: `drop_token` (remove a noisy term), `add_service` (add the service name if missing), `substitute_synonym` (swap a domain term for a synonym). The action is chosen by the LLM (or by a deterministic stub if no LLM is configured).

---

### 6. State Layer

**Location**: `src/agent/state/`

The State Layer tracks what the agent has decided across **multiple consecutive windows** of the same service. This is important because a single incident typically spans several windows (pre-fault → active → recovery), and without memory the agent would emit a duplicate "ticket_worthy" page for each window.

Internally it is a ring buffer (`deque(maxlen=12)`) of `WindowState` objects per service name, protected by a reentrant lock.

**Page suppression** (`check_page_suppression`):
- Looks back `suppression_lookback=3` windows for the same service.
- If the same (top-1 issue ID, scenario_family) pair was seen within that window AND no `recovery_window` intervened → return `suppress=True`.
- The runner then downgrades the decision from `ticket_worthy` to `borderline` and attaches the `incident_id` from the earlier window, grouping the windows into the same incident.

**Incident tracking**:
- The first `ticket_worthy` window for a new incident gets an auto-generated `incident_id` (`inc-<12-char-uuid>`).
- Suppressed follow-up windows inherit that `incident_id`.
- `pages_per_incident` (target ≤ 1.5) in the evaluation report measures how well suppression is working.

---

### 7. Data Lake

**Location**: `src/agent/data_lake/raw_run.py`

The Data Lake is what the ReAct evidence tools query. It reads raw telemetry from the on-disk run directories captured during dataset collection.

```
data/runs/<run_id>/raw/
    kubernetes/<window_id>.json   ← K8s events (kubectl get events/pods/deployment)
    tempo/<window_id>.json        ← Trace search + trace bodies
    prometheus/<window_id>.json   ← Pod CPU/memory/restart metric series
```

`RawRunDataLake` resolves the run ID from the window ID (the window ID is prefixed with the run directory name), reads the relevant JSON file, and returns a structured dict. Results are optionally cached to `data/tool_cache/` (SHA-256 of the query args) to avoid re-reading on repeated evaluation runs.

The `get_similar_incidents` method is special — it reads `jira-memory-corpus.jsonl` and returns up to `top_k=3` peer incidents from the same `scenario_family`, excluding the current episode. This gives the agent a concrete example of what a ticket for this type of fault looks like.

---

### 8. LLM Layer

**Location**: `src/agent/llm/`

The LLM layer provides a single method — `chat_json()` — that every LLM-using skill calls. It handles retries, schema validation, JSON parsing, and telemetry.

```python
response = ctx.llm.chat_json(
    system="...", user="...",
    schema={"type": "object", ...},
    temperature=0.0,
    max_tokens=256
)
```

Six provider backends are registered, selectable by `LLM_PROVIDER` environment variable:

| Provider | Default endpoint | API key env var |
|---|---|---|
| `lm_studio` (default) | `http://localhost:1234` | — |
| `openai` | `https://api.openai.com` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` |
| `ollama` | `http://localhost:11434` | `OLLAMA_API_KEY` |
| `vllm` | `http://localhost:8000` | `VLLM_API_KEY` |
| `generic_openai` | `http://localhost:8080` | `LLM_API_KEY` |

Provider resolution order (later wins): built-in defaults → `agent-config.yaml` → environment variables → function arguments.

The LLM is only used by `verify_with_llm` and `reformulate_query` during inference. All other skills are predictions-backed and make no LLM calls at evaluation time.

---

## Per-Dataset Behaviour

The same code runs on all three datasets, but the active skill set differs automatically based on which capability flags are observed:

### Online Boutique (active_fault branch)

All 11 flags can be set → full pipeline is available.

```
triage_numeric   ✓  (NUMERIC_FEATURES)
retrieve_dense   ✓  (TEXT_EVIDENCE + MEMORY_TEXT)
retrieve_hybrid  ✓  (TEXT_EVIDENCE + MEMORY_TEXT)
retrieve_kg      ✓  (KG_GRAPH_MEMORY, if KG built)
verify_with_llm  ✓  (VERIFIER_KNOWN_HELPFUL — calibrated as net-positive on OB)
ReAct tools      ✓  (K8S_EVENTS + TRACE_SUMMARY + METRIC_SNAPSHOTS fetchable)
```

### OTel Demo (active_fault branch)

Same as OB but verifier is `skip` (not calibrated for OTel Demo):

```
verify_with_llm  ✗  (VERIFIER_KNOWN_HELPFUL absent — policy = "skip")
```

### World of Logs

Text-only. No telemetry, no numeric features. The loader sets none of the fetchability flags:

```
triage_numeric   ✗  (NUMERIC_FEATURES absent — no Prometheus instrumentation)
retrieve_log_seq ✗  (ORDERED_LOGS absent — WoL has no log streams)
verify_with_llm  ✗  (VERIFIER_KNOWN_HELPFUL absent — calibrated as net-HARMFUL on WoL: −0.272 Hit@5)
request_pod_*    ✗  (K8S_EVENTS / TRACE_SUMMARY / METRIC_SNAPSHOTS absent)
retrieve_dense   ✓  (TEXT_EVIDENCE + MEMORY_TEXT always present)
retrieve_hybrid  ✓  (same)
request_similar_ ✓  (no required_flags — always available)
```

The result is a lightweight text-only retrieval pipeline, which is exactly what a real Jira issue search needs.

---

## Budget and Cost Management

**Location**: `src/agent/budget.py`

Every plan execution has a hard budget:

| Cap | Default |
|---|---|
| `max_llm_tokens` | 100,000 |
| `max_wall_seconds` | 90.0 s |
| `max_usd_equivalent` | $0.50 |
| `max_skill_calls` | 12 |

The budget is cloned fresh for each window (`budget.clone()`). Skills pre-check with `budget.can_afford()` before running; after running they call `budget.deduct()`, which raises `BudgetExhausted` if the cap would be exceeded. The runner catches `BudgetExhausted` and aborts the plan, returning whatever partial results exist.

**Actual costs per skill** (from `scripts/agent/cost_vs_cascade.py`):

| Skill | Wall time | LLM tokens | USD |
|---|---|---|---|
| All cheap/predictions-backed skills | 0.5–1 ms | 0 | $0 |
| `reformulate_query` | ~300 ms | ~400 | ~$0.00010 |
| `verify_with_llm` | ~15,400 ms | ~1,969 | ~$0.00050 |

The gate system means the expensive verifier only runs when escalation is warranted, keeping the typical per-window cost well below the cap.

---

## Evaluation Harness

**Location**: `src/agent/eval_harness/`

The evaluation harness wraps the entire agent loop and computes metrics.

### Metrics

| Metric | Definition |
|---|---|
| **Hit@1** | Did the correct issue appear at rank 1? (avg over windows with ≥1 gold match) |
| **Hit@5** | Did the correct issue appear in the top 5? |
| **Hit@10** | Did the correct issue appear in the top 10? |
| **MRR** | Mean Reciprocal Rank — 1/rank of first correct match |
| **Triage accuracy** | Fraction of windows where `triage_decision == gold_triage` |
| **Novel recall** | Of truly novel incidents, fraction flagged as novel |
| **Novel precision** | Of flagged-as-novel, fraction that are truly novel |
| **Pages per incident** | Mean pages emitted per identified incident (target ≤ 1.5) |

Windows with no gold matches (orphan faults, baselines) are excluded from the Hit@K and MRR denominators.

### Statistical testing

All reported deltas use **paired bootstrap** (1,000 resamples, seed=42, 95% CI) — the same resample indices are applied to both systems so per-window correlation is preserved. A delta is considered statistically significant when the 95% CI excludes zero.

### Ablation

`AblationHarness` runs the full evaluation grid while systematically removing skills or masking capability flags. Each ablation creates a fresh EvalHarness and StateLayer so there is no state bleed between cells. The grid results include per-ablation deltas vs the baseline (Δ Hit@5, Δ MRR).

---

## Running the Agent

### Quick smoke tests

```powershell
# Online Boutique (full pipeline)
python scripts/agent/smoke_ob.py --split test --cache-dir data/skill_cache

# WoL (text-only pipeline — verifier must be absent)
python scripts/agent/smoke_wol.py --split test

# OTel Demo
python scripts/agent/smoke_otel_demo.py --split test
```

Common flags available on all smoke scripts:

| Flag | Effect |
|---|---|
| `--no-verifier` | Drop `verify_with_llm` from the registry |
| `--no-state` | Disable the StateLayer (no suppression) |
| `--skip-skill <name>` | Drop a specific skill (repeatable) |
| `--max-tool-calls N` | Cap total ReAct tool calls per window |
| `--order-by-incident-time` | Sort cases by incident sequence (needed for suppression) |
| `--trace-root <dir>` | Write per-window trace JSON here |
| `--cache-dir <dir>` | Skill cache location |
| `--output <path>` | Write EvaluationReport JSON here |

### Ablation studies

```powershell
# Skill ablation: drops each skill individually and measures Hit@5 damage
python scripts/agent/skill_ablation.py --dataset ob --split test

# Tool ablation: sweeps all 2^4 = 16 subsets of ReAct tools
python scripts/agent/tool_ablation.py --dataset ob --split test

# Budget curve: sweeps max_tool_calls 0–4
python scripts/agent/budget_curve.py --dataset ob --split test
```

### Cost analysis

```powershell
# Summarise token/cost/latency from saved EvaluationReports
python scripts/agent/cost_summary.py --reports path/to/report.json

# Compare agent cost to full-cascade counterfactual
python scripts/agent/cost_vs_cascade.py --trace-root path/to/traces/
```

### Cross-corpus retrieval (WoL Kafka → OTel Demo)

```powershell
# TF-IDF retrieval: WoL Kafka memory items → OTel Demo Kafka test windows
python scripts/agent/run_cross_corpus_retrieval.py \
  --wol-global data/derived/global/2026-06-17-wol-real-v3-global \
  --otel-global data/derived/global/2026-06-09-otel-demo-v1-global
```

---

## Key File Index

| Path | What it contains |
|---|---|
| `src/agent/types.py` | `InputBundle`, `AgentDecision`, `SkillOutput`, `SkillCallCost`, `LogLine`, `TraceSummary`, `K8sEvent` |
| `src/agent/budget.py` | `Budget`, `BudgetExhausted`, `BudgetSnapshot` |
| `src/agent/plan.py` | `Plan`, `SkillInvocation`, `GateFn`, `OnFailurePolicy` |
| `src/agent/trace.py` | `Trace`, `TraceEvent`, `TraceEventKind` |
| `src/agent/capabilities.py` | 11 flag constants, `Capabilities` |
| `src/agent/capabilities_observer.py` | `CapabilitiesObserver`, `VerifierCalibration`, `ObservationContext` |
| `src/agent/tool_protocol.py` | `ToolRequest`, `ToolResult`, loop-detection helpers |
| `src/agent/harness_builder.py` | `build_harness_for_dataset()`, `DatasetProfile`, 3 built-in profiles (OB, OTel, WoL) |
| `src/agent/controller/base.py` | `Controller` ABC |
| `src/agent/controller/rule.py` | `RuleController`, gate functions (`make_escalation_gate`, `make_reformulation_gate`) |
| `src/agent/controller/capability_aware.py` | `CapabilityAwareRuleController`, branch logic, ReAct skill constants |
| `src/agent/runner/runner.py` | `AgentRunner` |
| `src/agent/state/window_state.py` | `WindowState` |
| `src/agent/state/state_layer.py` | `StateLayer`, `ServiceStateView`, `PageSuppressionResult` |
| `src/agent/skills/base.py` | `Skill` ABC, `AgentContext`, `MemoryView`, `CostClass` |
| `src/agent/skills/cache.py` | `SkillCache`, `NullSkillCache` |
| `src/agent/skills/registry.py` | `SkillRegistry`, `get_default_registry()` |
| `src/agent/skills/predictions_backed.py` | `PredictionsBackedSkill` (lazy JSONL loader base class) |
| `src/agent/skills/retrievers.py` | All 7 retriever/verifier skills |
| `src/agent/skills/composition.py` | `ComposeL2Skill`, `ComposeTriageSkill`, `ComposeNoveltySkill` |
| `src/agent/skills/evidence_request.py` | `EvidenceRequestSkill`, 4 ReAct tool classes |
| `src/agent/skills/rerank_with_evidence.py` | `RerankWithEvidenceSkill` |
| `src/agent/skills/reformulate_query.py` | `ReformulateQuerySkill` |
| `src/agent/skills/extract_entities_llm.py` | `ExtractEntitiesLLMSkill` (indexing time only) |
| `src/agent/data_lake/raw_run.py` | `RawRunDataLake` (reads `data/runs/.../raw/`) |
| `src/agent/data_loaders/ob_loader.py` | `load_ob_cases()` |
| `src/agent/data_loaders/wol_loader.py` | `load_wol_cases()`, `WOL_PREDICTIONS_PATHS` |
| `src/agent/data_loaders/otel_demo_loader.py` | `load_otel_demo_cases()` |
| `src/agent/data_loaders/split_manifest.py` | `load_split_manifest()`, `resolve_split()` |
| `src/agent/eval_harness/types.py` | `EvaluationCase`, `CaseResult`, `ApplesToApplesContract`, `EvaluationReport` |
| `src/agent/eval_harness/harness.py` | `EvalHarness` |
| `src/agent/eval_harness/metrics.py` | `hit_at_k`, `reciprocal_rank`, `pages_per_incident` |
| `src/agent/eval_harness/bootstrap.py` | `bootstrap_metric`, `paired_bootstrap_delta`, CI types |
| `src/agent/eval_harness/novelty.py` | `evaluate_l3_novelty`, `NoveltyReport`, signal loaders |
| `src/agent/eval_harness/ablation.py` | `AblationHarness`, `AblationSpec`, `AblationGridResult` |
| `src/agent/integrity/graph_metadata.py` | `assert_loaded_dataset()`, Neo4j dataset-isolation guard |
| `src/agent/llm/base.py` | `LLMProvider` ABC, `ChatResponse`, `LLMProviderConfig`, `ProviderHealth` |
| `src/agent/llm/factory.py` | `make_provider()`, `PROVIDER_REGISTRY` (6 backends) |
| `scripts/agent/smoke_ob.py` | End-to-end OB evaluation |
| `scripts/agent/smoke_wol.py` | End-to-end WoL evaluation (asserts verifier is structurally absent) |
| `scripts/agent/smoke_otel_demo.py` | End-to-end OTel Demo evaluation |
| `scripts/agent/skill_ablation.py` | Per-skill drop grid (OB: 10 cells, WoL: 6, OTel: 5) |
| `scripts/agent/tool_ablation.py` | All 2^4 ReAct tool subsets |
| `scripts/agent/budget_curve.py` | Hit@K vs `max_tool_calls` sweep |
| `scripts/agent/depth_scaling.py` | Hit@K vs memory depth buckets |
| `scripts/agent/cost_summary.py` | Token/latency/USD aggregation from saved reports |
| `scripts/agent/cost_vs_cascade.py` | Agent cost vs full-cascade counterfactual |
| `scripts/agent/run_cross_corpus_retrieval.py` | TF-IDF cross-corpus retrieval (WoL Kafka × OTel Demo) |
