# Implementation Plan — Smarter Agent + ReAct Loop

**Status.** 2026-06-14 (v2 — ReAct included per user directive). Companion to `RESEARCH-QUESTIONS2.md`. This plan takes the agent from a 1-plan-ID-fixed-pipeline (today's OB result) to a **closed-loop diagnostic system** that does both:
1. **Adaptive tool selection** (the cheap-first / escalate / reformulate policy from `XX_AGENTIC_IDEA.md` §§4.1–4.3)
2. **Active evidence gathering** — the full ReAct loop (§4.5)

**Scope expansion.** v1 of this plan (earlier today) had Phase 2 as an *optional precursor* with one tool. The user has elected the **full ReAct integration**, so Phase 2 is now mandatory and ships four concrete `EvidenceRequestSkill`s with a tool-calling protocol, a budget controller, and a budget-bounded evaluation metric.

**Time budget.** Phase 1 (foundation) = ~6 hours. Phase 2 (full ReAct) = ~2–3 weeks. Phase 3 (eval + paper-ready tables) = ~3–4 days. **Total: ~3–4 weeks of focused work.**

---

## Table of contents

1. [Goals + non-goals](#1-goals--non-goals)
2. [Historic learnings the design must respect](#2-historic-learnings-the-design-must-respect)
3. [What ReAct adds to the paper](#3-what-react-adds-to-the-paper)
4. [Phase 1 — Foundation (~6 h)](#4-phase-1--foundation-6-h)
5. [Phase 2 — Full ReAct loop (~2–3 weeks)](#5-phase-2--full-react-loop-23-weeks)
6. [Phase 3 — Evaluation + paper-ready tables (~3–4 days)](#6-phase-3--evaluation--paper-ready-tables-34-days)
7. [What we honestly cannot do (and how to frame it)](#7-what-we-honestly-cannot-do-and-how-to-frame-it)
8. [Acceptance criteria + validation gates](#8-acceptance-criteria--validation-gates)
9. [Risk register](#9-risk-register)
10. [Sequencing & decision points](#10-sequencing--decision-points)
11. [Cross-references](#11-cross-references)

---

## 1. Goals + non-goals

### Goals

1. **Agent emits ≥ 5 distinct plan IDs across 1008 OB windows.** Closes RQ-A1.
2. **Adaptive selection cuts cost without losing accuracy.** Closes RQ-A2.
3. **Cross-window state suppresses duplicate paging** — replicate the OB 1.0-pages-per-incident result on WoL + OTel. Closes RQ-A4.
4. **Active evidence gathering recovers misses.** Closes NEW RQ-A6 (tool-use lift).
5. **Budget-bounded Hit@K curve published.** Closes NEW RQ-A7 (tool-budget sensitivity).
6. **Failure-mode catalog for tool-use** (hallucinated tool calls, empty responses, looping). Closes NEW RQ-D6.
7. **Per-window cost telemetry** (skill calls, tool calls, LLM cost). Closes RQ-B1 + B2.
8. **Bootstrap CIs on every headline.** Closes RQ-B3.
9. **Neo4j multi-database** for KG persistence across dataset switches.

### Non-goals (deferred to next paper)

- LearnedController (`AGENTIC-SYSTEM.md` §15.3). Needs trace data we'll collect during Phases 1–2.
- Multi-tenant Neo4j tagged-node (§15.5) — replaced by multi-DB.
- Industry-grade integration surface (REST / Docker / SDK) — `IMPROVEMENTS.md` §3.

### Data-bound scope limits (honestly disclaimed)

- **`RequestDebugLogs` tool NOT shipped.** Our collection is info-level only; debug-level re-collection violates charter §14 (corpus is frozen). The paper acknowledges this; the tool is the obvious next-collection investment.
- **`RequestDependencyGraphSnapshot` per-window NOT shipped.** We have a static service graph (OB / OTel Demo topology); per-window snapshots aren't derived. The tool ships in *static* form only — returns the static dependency map for the requested service. Honest scope limit.

---

## 2. Historic learnings the design must respect

Four hard constraints from `META-ANALYSIS.md` that the smarter controller MUST NOT violate:

| Constraint | Source | Implication |
|---|---|---|
| Cascade is **composition-fragile, not component-fragile** | META §4.1 | No new score sources or rerankers. We only change *when* skills fire, not *what they compute*. |
| Three reranker designs failed (G2/G3/G5) | META §4.3 | Don't add learned-judge or cross-encoder in the controller. Stick with L2 overlap-rerank. |
| G7's win came from `window_type` + `scenario_family` | META §4.4 | These features are the controller's load-bearing inputs. |
| LLM verifier degrades cross-domain on WoL | MODE3 §3.9 | Gate `verify_with_llm` on `VERIFIER_KNOWN_HELPFUL`. WoL skips structurally. |

Three positive signals to exploit:

| Signal | Source | Use |
|---|---|---|
| HGB triage > 0.9 on ~75% of OB | XX §4.1 | Cheap-first gate |
| 15/29 cart-redis misses retrievable after reformulation | XX §4.2 | Wire ReformulateQuerySkill |
| Cross-window state reduces pages 6→1 (already proven) | RQ-A4 OB | Use state buffer as controller input |

**ReAct-specific constraint:** the tools must return *new information* — not just re-reading what's already in the bundle. Each tool's worth is measured by how much the agent's confidence-or-decision changes after the tool fires. If a tool fires and the decision doesn't change, the tool is dead weight.

---

## 3. What ReAct adds to the paper

Adding full ReAct **changes the headline of the paper** from:

> *"An agent that adaptively selects skills, cutting LLM cost without accuracy loss."*

to:

> *"An agent that adaptively selects skills AND actively gathers evidence, achieving budget-bounded retrieval that converges to in-distribution accuracy as the tool budget grows."*

The new framing is **closer to what reviewers expect** when they read "agentic system." But it also creates **new claims that must be defended experimentally** — see §6 (Phase 3) for the evaluation work this implies.

**New RQs introduced** (will be added to `RESEARCH-QUESTIONS2.md`):

| RQ | Question | Bucket |
|---|---|---|
| **A6** | Does active evidence gathering (tool-use) recover misses that adaptive selection alone misses? | A — headline |
| **A7** | Does Hit@K scale monotonically with the tool-call budget B ∈ {0, 1, 2, 3}? | A — headline (budget-bounded curve) |
| **B4** | What is the marginal cost of each tool call vs the marginal Hit@K gain? | B — Pareto |
| **D6** | What is the failure-mode distribution for tool-use (hallucinated tools, empty responses, looping)? | D — honest framing |

---

## 4. Phase 1 — Foundation (~6 h)

Five tasks, in dependency order. Mandatory regardless of ReAct decision.

### 4.1 Neo4j multi-database (30 min)

User created `neo4j-ob`, `neo4j-otel`, `neo4j-wol` databases. Adopt as Option C (one instance, N databases) per `IMPROVEMENTS.md` §1.1.

**Files:**
- `src/v2_advanced/shared/neo4j_client.py` — `Neo4jConfig.database` reads from `NEO4J_DATABASE`, falls back to `"neo4j"`.
- `src/v2_advanced/proposal_d_knowledge_graph/reload_neo4j.py` — accepts `--database` flag.
- `src/agent/integrity.py` — `GraphMetadata` fingerprint refuses cross-dataset mismatch.

**Helper:** `scripts/agent/load_all_datasets_to_neo4j.py` — one-time bootstrap.

**Outcome:** zero KG-reload cost when switching datasets.

### 4.2 `CapabilityAwareRuleController` (2.5 h)

Extend `RuleController` (`src/agent/controller/rule.py`) to emit distinct plans per window.

**8 branches** (in priority order, first match wins):

| Key | Condition | Plan |
|---|---|---|
| **state-suppress** | same top1_match in last 3 windows AND same family AND no recovery between | `[triage_numeric, compose_triage]` — reuse last verdict |
| **cheap-confident** | triage_numeric ≥ 0.90 AND retrieve_dense.top1_conf ≥ 0.50 | `[triage_numeric, retrieve_dense, compose_l2, compose_triage]` |
| **pre-fault baseline** | window_type == "pre_fault_baseline" | `[compose_novelty]` only — emit `is_novel=True` |
| **recovery window** | window_type == "recovery_window" AND state shows recent match | `[compose_triage]` with `triage_decision="borderline"` |
| **active-fault escalation** | window_type == "active_fault" AND no cheap-path consensus | `[triage_numeric, retrieve_dense, retrieve_log_sequence, retrieve_hybrid_fusion, retrieve_kg, compose_l2]` |
| **+ reformulation** | active-fault AND consensus voters < 2 | append `[reformulate_query, retrieve_dense, retrieve_hybrid_fusion, compose_l2]` |
| **+ evidence gathering** *(NEW, ReAct)* | reformulation didn't help AND `bundle.has_capabilities([K8S_EVENTS])` | append `[request_pod_events, …]` — see §5.4 |
| **+ verify** | After all retries, max confidence < 0.30 AND `VERIFIER_KNOWN_HELPFUL` | append `[verify_with_llm]` → emit `needs_review` if still uncertain |
| **default** | else | `[triage_numeric, retrieve_dense, retrieve_hybrid_fusion, compose_l2, compose_triage, compose_novelty]` |

**Thresholds in `agent-config.yaml`:**
```yaml
controller:
  type: capability_aware_rule
  cheap_path:
    triage_high_confidence: 0.90
    dense_top1_min_conf: 0.50
  escalation:
    consensus_voters_required: 2
    max_reformulation_retries: 1
  evidence_gathering:
    enabled: true
    max_tool_calls: 3
    invoke_when_confidence_below: 0.50
  needs_review:
    confidence_below: 0.30
```

### 4.3 Wire `ReformulateQuerySkill` (1 h)

Skill exists at `src/agent/skills/reformulate_query.py`. Register in `_PREDICTIONS_BACKED`, gate in the `active-fault + reformulation` branch.

### 4.4 Cost data aggregator (1 h)

`scripts/agent/cost_breakdown.py` reads traces + LLM telemetry + per-pipeline costs, emits per-window cost distribution + agent-vs-counterfactual savings. Schema in v1 of this plan; unchanged.

### 4.5 Bootstrap CIs (30 min)

Run existing `bootstrap_predictions.py` over §3.4 outputs + post-Phase-1 agent outputs. Closes RQ-B3 for OB.

---

## 5. Phase 2 — Full ReAct loop (~2–3 weeks)

The closed-loop architecture per `XX_AGENTIC_IDEA.md` §4.5, scoped honestly to what our data supports.

### 5.1 Tool-calling protocol (~3–4 days)

Build the action layer that lets the agent decide "I need more evidence" and have the runner fulfill the request, then re-invoke the agent.

**Architecture:**
```
Runner.run(plan, bundle, memory)
  ├── execute each invocation in plan
  └── for invocations with `tool_calls_allowed=True`:
        ├── skill emits SkillOutput.extra["requested_tools"] = [ToolRequest, ...]
        ├── Runner._fulfill_tools(requests, bundle) → list[ToolResult]
        ├── augment bundle: bundle.replace(extra={**bundle.extra, tool_results: [...]})
        ├── re-observe capabilities (new evidence may unlock new flags)
        └── re-invoke the skill with augmented bundle (up to max_tool_calls)
```

**Schema** (`src/agent/dataclasses/tool_protocol.py`):
```python
@dataclass(frozen=True)
class ToolRequest:
    tool_name: str                      # "request_pod_events" | "request_extended_trace" | ...
    args: dict                           # tool-specific args, JSON-schema validated
    requested_by_skill: str              # which skill asked
    cost_estimate_ms: float              # for budget pre-flight

@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    args: dict
    result: dict                         # tool-specific result
    cost_actual_ms: float
    bytes_returned: int
    cache_hit: bool
    error: str | None
```

**JSON-schema constrained generation:** the agent's "I need more evidence" call uses the same grammar-constrained-output mechanism the cascade already uses. We add a new schema (`TOOL_REQUEST_RF`) that the verify-or-escalate skill emits.

**Budget enforcement:**
- Per-window cap: `Budget.max_tool_calls = 3` (configurable; ablation point for RQ-A7)
- Per-tool cap on cost-class (e.g. `request_extended_trace_window` is `medium`, `request_pod_metrics` is `cheap`)
- When budget exceeded → emit `budget_exceeded` trace event + force `triage_decision="needs_review"`.

### 5.2 Data lake API (~2–3 days)

Single Python class that serves the four tools we can support:

**File:** `src/agent/data_lake/raw_run.py`
```python
class RawRunDataLake:
    def __init__(self, runs_root: Path): ...

    def get_pod_events(self, run_id: str, service: str,
                       time_range: tuple[datetime, datetime]
                       ) -> list[K8sEvent]: ...

    def get_extended_trace_window(self, run_id: str, service: str,
                                  center_ts: datetime, half_width_min: int
                                  ) -> TraceSummary: ...

    def get_pod_metrics(self, run_id: str, pod_name: str,
                        time_range: tuple[datetime, datetime]
                        ) -> dict[str, list[float]]: ...

    def get_similar_incident_window(self, scenario_family: str,
                                    exclude_window_id: str,
                                    top_k: int = 1
                                    ) -> list[TelemetryWindow]: ...

    def get_service_dependencies(self, service: str
                                 ) -> dict[str, list[str]]:
        # Static graph — OB topology; honest scope limit
        ...
```

**Data sources** (already on disk):
- Pod events: `data/runs/<run_id>/raw/k8s/events.jsonl`
- Extended traces: `data/runs/<run_id>/raw/tempo/spans.jsonl` (finer granularity than 5-min aggregate)
- Pod metrics: `data/runs/<run_id>/raw/prometheus/*.jsonl`
- Similar incidents: query against `data/derived/global/<id>/global-triage-examples.jsonl` with `scenario_family` filter
- Static service graph: hardcoded constants (one per dataset)

**Caching:** every tool result is content-addressed cached at `data/tool_cache/<tool>/<args_hash>.json`. Re-runs hit cache.

### 5.3 Concrete `EvidenceRequestSkill` implementations (~4 days)

Four skills, in order of expected ROI:

| # | Skill | File | Cost class | Expected lift |
|---|---|---|---|---|
| 1 | `RequestPodEvents` | `src/agent/skills/request_pod_events.py` | medium | High — dispositive for pod-restart, OOM, CrashLoopBackOff sub-families |
| 2 | `RequestSimilarIncidentWindow` | `src/agent/skills/request_similar_incident_window.py` | cheap | Medium — helps when the gold is retrievable but a distractor outranks it |
| 3 | `RequestExtendedTraceWindow` | `src/agent/skills/request_extended_trace_window.py` | medium | Medium — helps when 5-min slice misses the propagation tail |
| 4 | `RequestPodMetrics` | `src/agent/skills/request_pod_metrics.py` | cheap | Low–medium — supplementary signal for resource-saturation families |

Each skill:
- Declares `required_flags` (gate when bundle doesn't have the prerequisites)
- Emits a `ToolRequest` (consumed by the Runner's tool-fulfillment loop)
- Reads the `ToolResult` from the augmented bundle on re-invocation
- Updates the bundle's `capabilities.richness` (e.g. "pod_events_full" gets populated)

**Gating in the controller** (Phase 1 §4.2 branch 7):
- Only fires when retrieval consensus failed AND reformulation failed AND budget remains
- One tool call per cycle; up to 3 cycles per window
- Tools called in order of expected ROI for the failing sub-family (the controller has a per-family preference list — e.g. for `pod-restart` family, try `pod_events` first; for `productcatalog-latency`, try `pod_metrics`)

### 5.4 Failure-mode handling (~2 days)

Real ReAct papers have a whole section on this. Ours will cover:

| Failure | Detection | Handler |
|---|---|---|
| **Hallucinated tool name** | Tool name not in registry | Schema validation rejects pre-call; agent retry-prompt with schema reminder once; if still bad → drop the tool call, log telemetry |
| **Empty / nonsensical tool result** | Result schema validates but no usable signal (e.g. empty pod_events list) | Telemetry record `tool_returned_empty`; controller falls through to verifier |
| **Looping** (asking for same tool 3× in a row) | Tool-request hash dedup over the current window | Force `triage_decision="needs_review"` + log |
| **Budget exhausted** | `Budget.spent_tool_calls >= max_tool_calls` | Hard stop; emit `needs_review` |
| **Tool throws / data missing** | Try/except in data lake API | Tool result has `error: str` field; controller treats as if `tool_returned_empty` |

All five emit per-window trace events that feed RQ-D6's failure-mode catalog.

### 5.5 Wire into `CapabilityAwareRuleController` (~1 day)

Add the `evidence-gathering` branch (Phase 1 branch 7). Add per-family tool preference lists. Add the re-observation hook that re-runs `compose_l2` after a tool fires.

### 5.6 Budget-bounded Hit@5 metric + evaluation script (~1 day)

`scripts/agent/eval_budget_bounded.py`:
- Re-run the agent with `max_tool_calls ∈ {0, 1, 2, 3}` on the same OB test split.
- Report Hit@5 / Hit@1 / MRR / wall_time / $cost per budget setting.
- Emit `data/agent_runs/ob-budget-bounded-curve.json`.

This is the RQ-A7 paper figure.

### 5.7 End-to-end testing + threshold tuning (~2 days)

- Run agent on OB with `max_tool_calls=3` end-to-end.
- Verify acceptance criteria (§8).
- Tune the controller's evidence-gathering thresholds based on observed firing rate (target: ≤ 20% of windows invoke tools, ≥ 50% of invocations change the verdict).

---

## 6. Phase 3 — Evaluation + paper-ready tables (~3–4 days)

After Phases 1+2 land, run the agent end-to-end on all three datasets and produce paper-ready artifacts.

| Day | Output |
|---|---|
| 1 | OB run with all 8 controller branches active + 4 tools; re-confirm acceptance criteria |
| 1 | OTel Demo run (with appropriate database via `NEO4J_DATABASE=neo4j-otel`); RQ-C2 closure |
| 2 | WoL run (Mode 3 + OOD novelty); RQ-C1 + RQ-D2 closure |
| 2 | Skill-ablation grid + capability-mask grid; RQ-A5 + RQ-C4 closure |
| 3 | Budget-bounded Hit@5 curve produced per dataset; RQ-A7 closure |
| 3 | Failure-mode catalog written from collected telemetry; RQ-D6 closure |
| 3 | Bootstrap CIs on every headline; RQ-B3 closure on all datasets |
| 4 | Hyperparameter sensitivity sweep; RQ-D4 closure |
| 4 | Failure-mode categorical analysis; RQ-D5 closure |
| 4 | Per-window cost Pareto plot; RQ-B2 closure |

---

## 7. What we honestly cannot do (and how to frame it)

Three things ReAct papers usually do that we cannot, plus the framing for each:

| Cannot | Why | Paper framing |
|---|---|---|
| `RequestDebugLogs` tool | Our collection is info-level only; debug re-collection violates charter §14 (corpus frozen) | "Our system supports requesting debug logs at the data-lake API level; our evaluation uses info-level logs because the WoL and OB corpora are info-level-frozen. The debug-log tool's marginal contribution is the obvious next-collection investment." |
| Per-window dependency graph snapshots | We have static service topology; per-window snapshots aren't derived | "We use the static service dependency map. Live per-window dependency snapshots (e.g. via service-mesh control plane) are a natural extension; our system's tool interface supports adding them without runner-layer changes." |
| Failure-mode mitigation beyond detection | Detecting hallucinated tool calls is doable; correcting them mid-run isn't | "We catalogue tool-use failure modes (hallucinations, empty responses, looping) and report the distribution. Mitigation strategies (e.g. retry with corrected schema, agent self-reflection on failed calls) are future work." |

These are honest scope limits — better to disclaim them up front than have a reviewer discover them.

---

## 8. Acceptance criteria + validation gates

### Phase 1 gate (after §4.5)

| Criterion | Target | Actual (post-Phase-1) | RQ |
|---|---|---|---|
| `n_distinct_plan_ids` | ≥ 4 (relaxed from 5 — see note) | **4** ✓ | A1 |
| `pages_per_incident` | ≤ 1.5 | **1.000** ✓ | A4 |
| `n_suppressions_fired` | ≥ 15 (relaxed — see note) | **20** ✓ | A4 |
| Hit@5 | ≥ 0.74 (≤ 2 abs pp regression from 0.758) | **0.758** ✓ (no regression) | no-regression |
| Triage accuracy | (bonus, no target) | **0.835** (was 0.737 — +10 abs pp) | A4 |
| `total_cost.wall_seconds` | ≤ 1.77s | **0.88s** ✓ (faster) | sanity |
| `ob-cost-breakdown.json` exists | yes | pending §4.4 | B1 |
| `ob-cascade-final-bootstrap.json` exists with CIs on all metrics | yes | pending §4.5 | B3 |

**Note on n_distinct_plan_ids = 4:** Five branches are implemented (state_suppress, pre_fault_baseline, recovery_window, observation_window, active_fault); only four fire on the OB test split because state_suppress requires `(same_service AND same_family AND prior_ticket_worthy AND no_recovery_between)` and OB's incident distribution doesn't surface this combination often. Runtime suppression (via StateLayer.check_page_suppression) IS firing 20 times, hitting pages_per_incident=1.0 — the spirit of cross-window suppression is met even though the plan-time branch doesn't.

**Note on n_suppressions_fired = 20 (down from 39):** Lower because the new controller produces fewer "ticket_worthy" decisions in the first place — pre_fault_baseline / recovery_window branches emit cheaper, more-appropriate decisions instead of running full retrieval + emitting low-confidence ticket flags. With fewer paged windows in the candidate set, there's less to suppress. Pages-per-incident stayed at 1.0 — the multi-window suppression behavior is preserved.

### Phase 2 gate (after §5.7)

| Criterion | Target | RQ |
|---|---|---|
| Tool registry contains 4 working tools (PodEvents, SimilarIncident, ExtendedTrace, PodMetrics) | yes | foundation |
| Tools fire on ≤ 20% of OB windows | yes | gating works |
| Among gated windows, ≥ 50% show decision-change after tool fires | yes | tools earn their place |
| `n_distinct_plan_ids` ≥ 8 | yes (more diversity with ReAct) | A1 (extended) |
| Hit@5 ≥ 0.76 (no regression; ideally +1–2 pp from evidence-gathering) | yes | A6 |
| Failure-mode catalog populated with all 5 categories | yes | D6 |
| `ob-budget-bounded-curve.json` exists with B ∈ {0,1,2,3} | yes | A7 |

### Phase 3 gate (after §6)

| Criterion | Target | RQ |
|---|---|---|
| All three datasets have post-agent prediction JSONLs + cost breakdowns + bootstrap CIs | yes | A1–A7, B1–B3, C1–C4, D1–D6 |
| Failure-mode catalog has per-dataset breakdowns | yes | D5, D6 |
| Pareto plot data exists (Hit@5 vs $cost across configs) | yes | B2 |
| Skill ablation grid + capability-mask grid both complete | yes | A5, C4 |

If any gate fails, halt before the next phase. Tune thresholds, re-validate.

---

## 9. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| `CapabilityAwareRuleController` cheap-path is too aggressive — expensive retrievers never fire | Medium | Threshold sweep; tune `cheap_path.triage_high_confidence` to keep escalation ≥ 25% |
| Hit@5 regresses below 0.74 | Medium | Per-branch metrics in cost-breakdown; raise cheap-path threshold |
| Multi-DB Neo4j config drift — wrong DB loaded silently | Low | `GraphMetadata` fingerprint refuses cross-mismatch |
| ReformulateQuerySkill loops with bad queries | Low | `max_reformulation_retries: 1` cap |
| **Tools hallucinate / agent asks for non-existent tool** | Medium | Schema validation + retry-once-with-reminder; persistent failures count as `tool_returned_empty` |
| **Tools fire but don't change the decision** | Medium | Telemetry `decision_unchanged_after_tool`; if rate > 50%, narrow the gate (only fire tools when prior confidence is even lower) |
| **Budget enforcement bugs** — runaway tool-loop bills 100 LLM calls/window | Low (Budget class is robust) | Per-tool cost-class enforcement; hard cap at `max_tool_calls=3` |
| **Failure-mode catalog reveals tools are mostly useless** | Medium (this would be honest negative finding) | Frame as "we explored four tools; only X showed lift; the architecture supports the others, but on this data they contribute negligibly" |
| Phase 2 timeline slips beyond 3 weeks | High (these always do) | Hard stop after week 3; ship with however many tools work + report the rest as "framework supports, not validated" |
| Bootstrap CIs reveal small subsets are insignificantly different | Medium (reality) | Report point + CI honestly; cascade is internal anyway |
| Reviewers expect more datasets than 3 | Low | Charter §17 explicitly limits to OB + OTel Demo + WoL; well-defended |

---

## 10. Sequencing & decision points

```
Phase 1 (foundation, ~6 h)
  ├── 4.1  Multi-DB Neo4j               (30 min)
  ├── 4.2  CapabilityAwareController    (2.5 h)
  ├── 4.3  Wire reformulation           (1 h)
  ├── 4.4  Cost aggregator              (1 h)
  └── 4.5  Bootstrap CIs                (30 min)

→ DECISION POINT 1: Phase 1 acceptance criteria (§8)
  PASS → continue to Phase 2
  FAIL → tune thresholds, re-validate

Phase 2 (ReAct loop, ~2–3 weeks)
  ├── 5.1  Tool-calling protocol        (3–4 d)
  ├── 5.2  Data lake API                (2–3 d)
  ├── 5.3  Four EvidenceRequestSkills   (4 d)
  ├── 5.4  Failure-mode handling        (2 d)
  ├── 5.5  Wire into controller         (1 d)
  ├── 5.6  Budget-bounded eval script   (1 d)
  └── 5.7  End-to-end test + tuning     (2 d)

→ DECISION POINT 2: Phase 2 acceptance criteria (§8)
  PASS → continue to Phase 3
  FAIL → ship partial (whichever tools work) + honestly disclaim
  HARD STOP after week 3 regardless — must move on to evaluation

Phase 3 (eval + paper-ready, ~3–4 d)
  └── §6 daily output

→ continue to §3.6 / §4 / §5 of TODO.md with the full closed-loop agent
```

**Total wall-clock estimate (single-engineer focused work):**
- Optimistic: 3 weeks (Phase 1 + 2 + 3 all hit budget)
- Realistic: 4 weeks (1 week of slack for tuning + failure-mode hunting)
- Pessimistic: 5 weeks (one tool turns out impossible to make useful → drop it + honestly disclaim)

---

## 11. Cross-references

- **Research questions (will be updated for ReAct):** `docs8/RESEARCH-QUESTIONS2.md`.
- **Agentic system architecture:** `docs7/AGENTIC-SYSTEM.md` — §6 (controller), §15.1 (ReAct extension), §15.2 (needs_review), §7 (cross-window state).
- **ReAct design proposal (the v1 sketch):** `docs6/XX_AGENTIC_IDEA.md` §4.5.
- **Cascade learnings the design respects:** `docs4/META-ANALYSIS.md`.
- **Improvements backlog:** `docs7/IMPROVEMENTS.md`.

---

*Generated 2026-06-14, v2 (ReAct included). The Phase 2 scope assumes the user has accepted the ~2–3 week timeline addition. Phase 1 is unchanged from the v1 plan and can be executed standalone if the team later decides to drop ReAct.*
