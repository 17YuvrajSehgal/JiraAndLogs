## Q7. Help me complete the architecture diagram — what's missing and how should it be laid out?

What you have so far covers the **input substrate**: `Data` → loader/gate arrows → `InputBundle` + `MemoryView`, with the three caches (Data Lake / Tool Cache / Skill Cache) and `Skills` + `Capabilities Observer` sketched in below.

What's missing is the **decision-making spine** — the controller, plan, runner, and decision output — plus the **state layer** (your page-suppression mechanism) and the **LLM provider**. Here's a complete component inventory in the order I'd add them, plus a layered Mermaid blueprint you can render to compare against your draw.io canvas.

### 7.1 Components you already have (left as-is)

| Component | Role | Source-of-truth file |
|---|---|---|
| **Data** | Per-dataset on-disk JSONL files | `data/derived/global/<dataset>/global-triage-examples.jsonl` + `jira-memory-corpus.jsonl` |
| **Data Loader** (arrow) | Reads one row → builds bundle + view | `src/agent/data_loaders/{ob,wol,otel_demo}_loader.py` |
| **Capability Gate** (arrow) | Loader sets `bundle.extra` markers; observer surfaces flags | `extra={"k8s_events_fetchable": True, ...}` |
| **InputBundle** | 5-min window of evidence (features + logs + events + extra) | `src/agent/types.py:109` |
| **MemoryView** | Read-only iterable over past Jira tickets, signature-stamped | `src/agent/skills/base.py:88` |
| **Data Lake** | Reads raw run JSONs on demand | `src/agent/data_lake/raw_run.py` |
| **Tool Cache** | Content-addressed cache for ReAct fetches | `data/tool_cache/<tool>/<args_hash>.json` |
| **Skill Cache** | Content-addressed cache for skill outputs | `data/skill_cache/` |
| **Skills** | Skill registry (15 skills) | `src/agent/skills/` |
| **Capabilities Observer** | bundle → Capabilities (flags + richness) | `src/agent/capabilities_observer.py:217` |

### 7.2 Components to add — priority-ordered

#### Priority 1 — the decision-making spine (you can't show the agent without these)

| Component | One-liner | File |
|---|---|---|
| **Capabilities** (output object) | `frozenset[str]` flags + `dict` richness — the Observer's emit | `capabilities.py:88` |
| **Controller (CapabilityAwareRuleController)** | Reads (bundle, caps, state) → picks 1 of 6 branches → emits Plan | `controller/capability_aware.py:100` |
| **6 Branches** | `state_suppress` / `pre_fault_baseline` / `recovery_window` / `observation_window` / `active_fault` / `default` | same |
| **Plan** | Tuple of `SkillInvocation`s, each with `gate` closure + per-call budget. `plan_id = SHA-1` | `plan.py:35` |
| **Runner (AgentRunner)** | Walks the Plan: evaluate gate → check cache → check budget → invoke → emit trace event | `runner/runner.py:93` |
| **Budget** | Mutable counters (tokens / time / $ / calls); `can_afford` / `deduct` / `snapshot` | `budget.py:38` |
| **Trace** | Event log per window — 10 event kinds; serialised JSON. Replayable. | `trace.py:40` |
| **AgentDecision** | Final output: triage + matched_issue_ids + is_novel + confidence + cost + trace_path | `types.py:316` |

#### Priority 2 — State + page suppression (your operational claim hangs on this)

| Component | One-liner | File |
|---|---|---|
| **StateLayer** | Per-service ring buffer of WindowStates (default size 12) | `state/state_layer.py` |
| **ServiceStateView** | Frozen window of recent windows for one service; used by controller branch logic | same |
| **check_page_suppression** | Conservative rule: same top1 in last N + same family + no recovery → suppress | same |
| **WindowState** | One row in the ring: `(timestamp, triage_decision, top1_match, is_novel, incident_id, ...)` | `state/window_state.py` |

#### Priority 3 — Skill subgroups (refine your "Skills" box)

Split your single `Skills` icon into the four cost classes — the cost story is the paper's headline.

| Subgroup | Members | Cost class |
|---|---|---|
| **Cheap** | `triage_numeric` (HGB), `retrieve_dense` (BiEncoder) | `cheap` |
| **Medium retrievers** | `retrieve_log_sequence`, `retrieve_hybrid_fusion`, `retrieve_hybrid_fusion_llm`, `retrieve_knowledge_graph` | `medium` |
| **Expensive LLM** | `verify_with_llm`, `reformulate_query`, `extract_entities_llm` | `expensive_llm` |
| **Composition** | `compose_l2`, `compose_triage`, `compose_novelty` | `cheap` (trace-readers) |
| **Phase-2 ReAct tools** | `request_pod_events`, `request_extended_trace_window`, `request_pod_metrics`, `request_similar_incident_window` | `medium` / `low` |
| **Rerank** | `rerank_with_evidence` (consumes tool_results, re-ranks compose_l2's top-K) | `cheap` |

#### Priority 4 — Infrastructure layer

| Component | One-liner | File |
|---|---|---|
| **LLMProvider** | ABC for LM Studio / OpenAI / Anthropic / Ollama / vLLM / Generic | `llm/base.py:147` |
| **Telemetry hook** | Records every LLM call → `data/llm_telemetry/<exp>.jsonl` | `llm/base.py:120` |
| **EvalHarness** | Per-case: observe → state → plan → run → score → aggregate | `eval_harness/harness.py:54` |
| **ApplesToApplesContract** | 6 rules (dataset + split + gold + memory + metric + envelope) | `eval_harness/types.py` |
| **EvaluationReport** | Hit@K + MRR + triage_acc + pages/incident + $cost + CIs | same |

### 7.3 Suggested layout — three vertical bands

Map your canvas into **three vertical bands** to keep flow direction obvious:

```
┌────────────────────────────────────────────────────────────────────────────┐
│ BAND 1 — INGEST (top)                                                       │
│  Data sources ─→ Data Loader ─→ InputBundle  +  MemoryView                  │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ BAND 2 — DECIDE (middle)                                                    │
│  Capabilities Observer ─→ Capabilities ─┐                                   │
│                                          ├─→ Controller ─→ Plan ─→ Runner   │
│  StateLayer  ─→ ServiceStateView ───────┘                       │           │
│                                                                 │           │
│  Runner walks Plan, talks to:  Skills (4 subgroups) + Cache + Budget        │
│                                ReAct tools ─→ Data Lake ─→ Tool Cache       │
│                                LLM Provider (telemetry hook)                │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ BAND 3 — EMIT (bottom)                                                      │
│  Runner ─→ Trace + AgentDecision                                            │
│  AgentDecision ─→ check_page_suppression ─→ (back to StateLayer record)     │
│  AgentDecision ─→ EvalHarness ─→ EvaluationReport                           │
└────────────────────────────────────────────────────────────────────────────┘
```

Stores (`Tool Cache`, `Skill Cache`) hang off their owners as cylinders — keep them where you have them but draw the bidirectional `lookup / put` arrows.

### 7.4 Color / style suggestions (5 categories)

Borrowing from `AGENTIC-SYSTEM-V3.md` §3:

| Category | Color | Members |
|---|---|---|
| **Abstractions / interfaces** | blue (`#dfe7fd` fill, `#395dc7` stroke) | Controller, Plan, Runner, StateLayer, MemoryView, Capabilities ABC |
| **Live / executing skills** | green (`#d5f4e6` fill, `#268050` stroke) | All 4 skill subgroups, Capabilities Observer |
| **Caches** | yellow (`#fdf2cc` fill, `#caa61f` stroke) | Skill Cache, Tool Cache, Trace store |
| **ReAct + Data Lake** | orange (`#fde4d6` fill, `#c76a39` stroke) | ReAct tools, Data Lake, Rerank |
| **Outputs** | purple (`#e7d6fd` fill, `#7239c7` stroke) | AgentDecision, Trace, EvaluationReport |

InputBundle + MemoryView can stay as gray "data cylinders" since they're inputs, not abstractions you author.

### 7.5 The annotation tier (small text on each box)

For each component, include ONE phrase that captures *what changes when this is missing* — this is how a reviewer reads diagrams fast:

| Component | Annotation |
|---|---|
| InputBundle | "Required: window_id + dataset; everything else optional" |
| MemoryView | "Signature → cache key; same view shared across all windows" |
| Capabilities Observer | "Stateless; fetchable markers unlock disk-resident telemetry" |
| Controller | "6 branches; picks at plan-emit time on (window_type, state)" |
| Plan | "plan_id = SHA-1; gates are closures evaluated at runtime" |
| Budget | "Hard ceiling: tokens / wall / $ / calls; raises BudgetExhausted" |
| Runner | "Dumb by design — all policy is in the Plan" |
| Skill Cache | "Key includes memory.signature() — corpus changes invalidate" |
| Data Lake | "Reads `data/runs/<run>/raw/{k8s,tempo,prom}/<window>.json`" |
| Tool Cache | "args_hash = sha256(args)[:16]; per-tool subdirs" |
| StateLayer | "Per-service ring (size 12); rule: same top1 + same family + no recovery → suppress" |
| AgentDecision | "evaluation_mode tag enforces apples-to-apples in eval harness" |
| Trace | "Bit-replayable from `results/<dataset>/agent-runs/<exp>/<window_id>.json`" |
| LLMProvider | "ABC — 6 concrete providers; one telemetry hook records every call" |

### 7.6 Renderable Mermaid blueprint

Copy this into a Mermaid renderer (or the validator MCP tool) to see the full component map. Your draw.io canvas can mirror the layout one cluster at a time. **Bold the boxes you already have**; the rest are the additions:

```mermaid
flowchart TB
  subgraph DATA["📁 Data sources — per-dataset on disk"]
    JSONL[global-triage-examples.jsonl<br/>+ jira-memory-corpus.jsonl]
    RAW[raw runs/<br/>k8s · tempo · prom JSON]
  end

  subgraph LOAD["🔌 Data Loader (ob / wol / otel)"]
    BUILD[_build_bundle&nbsp;+&nbsp;MemoryView assembly]
  end

  subgraph INPUT["📥 Per-bundle input"]
    BUNDLE["**InputBundle**<br/>window_id + evidence + extra markers"]
    MEM["**MemoryView**<br/>read-only · signature-stamped"]
  end

  subgraph L0["L0 — Capabilities"]
    OBS["**CapabilitiesObserver**<br/>bundle → flags + richness"]
    CAPS[Capabilities<br/>frozenset flags]
    VC[VerifierCalibration<br/>OOD structural skip]
  end

  subgraph L5["L5 — State"]
    STATE[StateLayer<br/>per-service ring · size 12]
    VIEW[ServiceStateView]
    SUPP{{check_page_<br/>suppression}}
  end

  subgraph L1["L1 — Controller"]
    CTRL[CapabilityAware<br/>RuleController]
    BR{{select_branch}}
    B1[state_suppress]
    B2[pre_fault_baseline]
    B3[recovery_window]
    B4[observation_window]
    B5[active_fault<br/>FULL + ReAct]
    B6[default]
  end

  subgraph L2["L2 — Plan"]
    PLAN[Plan<br/>SkillInvocations + gates<br/>+ per-call budget + fallback chains<br/>plan_id = SHA-1]
  end

  subgraph L3["L3 — Runner"]
    RUN[AgentRunner<br/>walks plan · emits trace]
    BUD[Budget<br/>tokens · wall · $ · calls]
    TR[("Trace<br/>events + final decision")]
    SCACHE[("**Skill Cache**<br/>data/skill_cache/")]
  end

  subgraph L4["L4 — Skills (registry)"]
    direction LR
    CHEAP[cheap<br/>triage_numeric<br/>retrieve_dense]
    MED[medium retrievers<br/>log_seq · hybrid_rrf<br/>hybrid_llm · kg]
    LLM[expensive_llm<br/>verify_with_llm<br/>reformulate_query]
    COMP[composition<br/>compose_l2 / triage / novelty]
    REACT[ReAct Phase-2<br/>pod_events · trace<br/>pod_metrics · peers]
    RERANK[rerank_with_evidence]
  end

  subgraph LAKE["Data lake (on-demand)"]
    RAWRUN["**RawRunDataLake**"]
    TCACHE[("**Tool Cache**<br/>data/tool_cache/")]
  end

  subgraph LLM_PROV["LLM provider"]
    PROV[LMStudio · OpenAI<br/>Anthropic · Ollama · vLLM]
    TELE[telemetry hook<br/>llm_telemetry/*.jsonl]
  end

  subgraph EVAL["Eval harness"]
    HARNESS[EvalHarness]
    CONTRACT[ApplesToApplesContract<br/>6 rules]
    REPORT[EvaluationReport<br/>Hit@K · MRR · cost · CIs]
  end

  DEC[(AgentDecision<br/>triage + top-5 + novel + cost + trace_path)]

  DATA --> LOAD --> INPUT
  BUNDLE --> OBS
  OBS --> CAPS
  VC -.policy.-> OBS
  STATE --> VIEW
  CAPS --> CTRL
  VIEW --> CTRL
  CTRL --> BR
  BR --> B1 & B2 & B3 & B4 & B5 & B6
  B1 & B2 & B3 & B4 & B5 & B6 --> PLAN
  PLAN --> RUN
  MEM --> RUN
  BUNDLE --> RUN
  RUN <-.lookup / put.-> SCACHE
  RUN <-.check / deduct.-> BUD
  RUN --> CHEAP & MED & LLM & COMP & REACT & RERANK
  REACT -.fetch.-> RAWRUN
  RAWRUN <-.cache.-> TCACHE
  LLM <-.chat_json.-> PROV
  PROV -.records.-> TELE
  REACT -->|tool_results| RERANK
  RUN --> TR
  RUN --> DEC
  DEC --> SUPP
  SUPP -->|suppress?| STATE
  DEC --> HARNESS
  CONTRACT -.enforce.-> HARNESS
  HARNESS --> REPORT

  classDef abstr fill:#dfe7fd,stroke:#395dc7,color:#000
  classDef live fill:#d5f4e6,stroke:#268050,color:#000
  classDef cache fill:#fdf2cc,stroke:#caa61f,color:#000
  classDef react fill:#fde4d6,stroke:#c76a39,color:#000
  classDef out fill:#e7d6fd,stroke:#7239c7,color:#000

  class CTRL,PLAN,RUN,STATE,VIEW,MEM,BUNDLE,CAPS abstr
  class OBS,CHEAP,MED,LLM,COMP,VC,HARNESS,CONTRACT live
  class SCACHE,TCACHE,TR cache
  class REACT,RERANK,RAWRUN cache
  class DEC,REPORT out
```

### 7.7 What to add to your draw.io canvas next, in order

1. **Add the Controller box** (under "Capabilities Observer") with the **6 branch fan-out** below it. Keep the branches collapsed if space is tight; expand active_fault only.
2. **Add the Plan box** (under the controller). Annotate `plan_id = SHA-1`.
3. **Add the Runner box** (under the Plan). Connect to Plan, Skill Cache (bi-directional), Budget (new box), and the skill subgroups.
4. **Refactor Skills** from one icon → 4 sub-icons (cheap / medium / expensive / composition) + a separate ReAct cluster. The ReAct cluster connects to Data Lake (which you already have).
5. **Add the State Layer + ServiceStateView** on the LEFT side of the controller (state feeds in alongside capabilities).
6. **Add the AgentDecision output box** at the bottom-right. Connect Runner → Decision → check_page_suppression (diamond) → back to StateLayer record.
7. **Add the LLM Provider + telemetry hook** off to the side — it's wired only to the "expensive_llm" skills cluster. Small box, but reviewers will look for it.
8. **Add the Eval Harness + EvaluationReport** as the final destination. AgentDecision → harness → report.

### 7.8 What I'd defer to a v2 of the diagram

Don't try to show everything at once. Defer for a "details" version:
- `VerifierCalibration` (it's a small policy object inside the observer)
- `ApplesToApplesContract` rules (a footnote, not a box)
- `JiraMemoryIssue` internals (the MemoryView box is enough at this zoom)
- Individual `TraceEventKind` enum values (just show one cylinder "Trace")
- Cost-class color coding inside skill boxes (the subgrouping does the same work)
- Failure-mode taxonomy details (a sub-diagram of its own)

### 7.9 Why this layout matters for the paper figure

The same structure becomes the paper's Figure 1. Three vertical bands map directly to the contribution claims:

| Band | Paper claim it supports |
|---|---|
| Band 1 (Ingest) | "**Capability-driven, not dataset-driven**" — same bundle shape across OB / OTel / WoL |
| Band 2 (Decide) | "**Capability-adaptive policy**" — controller branches on (caps, state); runner is dumb |
| Band 3 (Emit) | "**Replayable + auditable**" — Trace is the audit log; AgentDecision carries evaluation_mode |

When the figure caption can match the band labels, reviewers absorb the architecture in one glance. That's "really nice."

**Citations.**
- Existing mermaid blueprint: `DOCS/docs8/AGENTIC-SYSTEM-V3.md` §3.
- 6-layer table (with file:line pointers for each box): `AGENTIC-SYSTEM-V3.md` §4.

---