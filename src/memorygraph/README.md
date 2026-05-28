# memorygraph — Agentic, skill-based cross-context retrieval

A new triage / retrieval pipeline that treats observability data and Jira
issues as **two different contexts** and bridges them with a typed
**contextual memory graph**. Every retrieval decision is made by an
**agent** that invokes small **semantic skills** — each skill is a
composable, self-describing operation that reads the graph or scores a
candidate. The agent's final output includes a human-readable
**explanation** built by joining source-entity nodes (from the failed
telemetry window) to target-entity nodes (in past Jira issues) through
the graph.

This is the project's first pipeline that produces **why** answers, not
only **what** scores.

## Why this exists

The existing Jira-as-memory pipelines (`loganalyzer_with_jira`,
`jira_only`) reduce the whole Jira corpus to BM25 / embedding similarity
plus 11 scalar `jira_*` features. That works for ranking, but it loses
structure:

- "this window is on `paymentservice`, this Jira lists `paymentservice`
  in its Components field" is a **direct, hard match** — but BM25 only
  sees the word `paymentservice` and gives it the same weight as any
  other token.
- "this window shows a 30× latency p95 spike, this Jira is in the
  `latency_regression` reason class" is an **indirect, learned
  correlation** — BM25 cannot see it; even an embedding model only sees
  it if the underlying sentence embeddings happen to align.
- "this window has no matching Jira; explain why we still flagged it"
  needs a **negative graph reason**, not just a low similarity score.

The memory graph captures all three signal types explicitly.

## Three-stage retrieval

For every telemetry window the agent runs three stages:

1. **Extract** observability entities from the window and (offline)
   extract Jira entities from the memory corpus. Both sides emit the
   same `Entity` shape so they can join.
2. **Filter** the candidate Jira pool by **direct cross-context
   matches** — component overlap, service overlap, compatible
   severity/fault class. This is the cheap pre-filter the project
   sketch calls out: "first exclude logs / records that are not related
   to that component before running similarity search." It typically
   shrinks the candidate set 10–50× and cuts noise.
3. **Rank** the surviving candidates with similarity (BM25 + optional
   embedding) **plus** graph-aware bonuses (an edge in the graph that
   directly connects window-entities to Jira-entities adds weight). The
   agent then writes a one-paragraph explanation by traversing those
   edges.

## Architecture

```
                        ┌─────────────────────────────────────┐
   Window ───entity──►  │   ObservabilityEntities             │
   (evidence_text,      │   (service, components, errors,     │
    numeric features)   │    latency_band, k8s_signal, …)     │
                        └──────────────┬──────────────────────┘
                                       │
                                  add to graph
                                       │
                                       ▼
                        ┌─────────────────────────────────────┐
   Jira issue ──────►   │   JiraEntities                      │
   (memory_text,        │   (component, fault_class, severity,│
    affected_service,   │    error_class, reason_class, …)    │
    fault_type, …)      └──────────────┬──────────────────────┘
                                       │
                                  add to graph
                                       │
                                       ▼
                     ┌────────────────────────────────────────┐
                     │   MemoryGraph                          │
                     │     nodes  = Entities (typed)          │
                     │     edges  = relationships             │
                     │              same_component,           │
                     │              same_service,             │
                     │              severity_aligned,         │
                     │              error_class_compatible,   │
                     │              fault_class_match,        │
                     │              latency_band_match, ...   │
                     │     window_node → entity_node          │
                     │     jira_node   → entity_node          │
                     └──────────────┬─────────────────────────┘
                                    │
                                    ▼
                     ┌──────────────────────────────────┐
                     │   Agent (controller + planner)   │
                     │   picks a skill chain per window │
                     └──────────────┬───────────────────┘
                                    │
                  ┌─────────────────┼─────────────────────────┐
                  ▼                 ▼                         ▼
            Filter skills     Similarity skills          Graph skills
            component_filter  lexical_similarity         graph_traverse
            service_filter    embedding_similarity       graph_explain
            severity_align    triage_decide              novelty_check
            error_align
                                    │
                                    ▼
                     ┌────────────────────────────────────┐
                     │   AgentDecision                    │
                     │     - top-k matched Jira issues    │
                     │     - per-match graph evidence     │
                     │     - human-readable explanation   │
                     │     - calibrated triage_score      │
                     └────────────────────────────────────┘
```

## Module map

| File | Purpose |
| --- | --- |
| `entities.py` | `Entity` / `EntityId` / `Edge` dataclasses + extractors for observability (`extract_obs_entities`) and Jira (`extract_jira_entities`), with lab-leakage stripping (no `scenario-*`, `dataset-*`, `severity-*`, `root-*` labels reach the graph). |
| `graph.py` | `MemoryGraph` store (nodes, edges, attribute dicts), builder that ingests entities into the graph, relationship-discovery code that adds cross-domain edges, plus relationship-quality statistics (e.g. `severity_alignment_strength`). |
| `skills.py` | `Skill` ABC + concrete skills. Each skill is a small named operation with `.run(context) -> SkillResult`. The agent picks which skills to run; skills don't call each other directly. |
| `agent.py` | `Agent` controller (skill-execution loop), `RulePlanner` (deterministic skill chain), optional `LLMPlanner` (LM Studio Qwen picks the chain), `Explainer` that turns the chain output + graph paths into a one-paragraph natural-language explanation. |
| `pipeline.py` | `MemoryGraphPipeline` — implements the existing `PipelineRunner` protocol so this slots into `src/comparison/runner.py` and the standard leaderboard. |
| `cli.py` | Standalone CLI: `python -m memorygraph.cli --global-dir … --output-dir …`. Emits per-window predictions, graph stats, and explanations. |
| `tests/test_smoke.py` | Pure-Python smoke tests on synthetic data. No optional dependencies required. |

## Production-realism contract

This pipeline follows the same hard rules as the rest of the project
(`docs/triage-task-contract.md` Field Policy):

- **Window inputs**: only `triage_evidence_text`, `triage_feature_*`, and
  `service_name` / `window_type` (the production-known metadata). Never
  `scenario_id`, `scenario_family`, `triage_label`, `triage_severity`,
  `triage_components`, `triage_reason_class`, `is_hard_case`.
- **Jira inputs**: the full memory corpus (`memory_text`, `severity`,
  `affected_service`, `fault_type`, `fault_compatibility_class`, …) is
  allowed — that *is* the system's memory — but the Jira entity
  extractor strips lab-leakage labels (`scenario-*`, `dataset-*`,
  `synthetic-incident`, `telemetry-linked`, `severity-*`, `root-*`)
  before they reach the graph, so retrieval cannot exploit them.
- **Time-ordering / own-run exclusion**: enforced by the existing
  `MemoryCorpus.visible_to(window)` — the pipeline only ever calls into
  it, never reaches around it.

## How agentic-ness shows up in the code

There are three layers that fit the standard "agent + skills" mental
model:

1. **Skills are tools**. Each `Skill` exposes a `name`, a
   `description`, and an `input_schema`. They are addressable by name,
   just like an LLM-callable function or an MCP tool.
2. **The planner picks a tool chain**. The default `RulePlanner` runs a
   fixed best-known chain
   (`extract → filter → similarity → graph_score → explain`), but
   `LLMPlanner` can read the window evidence, the available skill list,
   and return a custom chain in JSON via LM Studio. Both are
   interchangeable.
3. **The controller executes the chain with shared state**. Each skill
   reads from and writes to a shared `AgentContext` dict; this is where
   "skill chaining" happens. Adding a new skill = a new class + one
   line in the registry.

## Where it sits on the leaderboard

Once registered as `memorygraph` in `src/comparison/runner.py`, the
pipeline runs alongside `loganalyzer_hybrid_bm25`,
`bi_encoder_hybrid`, `nomic_retrieval`, etc. The headline metrics
(`PR-AUC`, `Precision@FPR=5%`, `Recall@5`, `MRR`) are produced by the
same `PipelineResult` shape, so the existing significance / stratified
/ pairwise-bootstrap code stays unchanged. The new artifact the
pipeline contributes that no other pipeline does is the
`explanations.jsonl` file under the output dir — one human-readable
graph-justified explanation per test window.

## Running it

```powershell
# Standalone on the v5-quick global dataset
& .venv\Scripts\python -m memorygraph.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-global" `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-global\memorygraph\baseline"

# Via the comparison harness (alongside other pipelines)
& .venv\Scripts\python -m src.comparison.cli `
  --global-dir "data\derived\global\2026-05-25-dataset-v5-quick-global" `
  --runs-root "data\runs" `
  --pipelines loganalyzer,memorygraph `
  --output-dir "data\derived\global\2026-05-25-dataset-v5-quick-global\comparison\memorygraph-vs-loganalyzer"
```

LM Studio at `http://localhost:1234` is optional. When present:
- `LLMPlanner` becomes available (still falls back to `RulePlanner`).
- `embedding_similarity` skill uses Nomic embeddings; otherwise it
  silently disables itself.
- `llm_entity_extract` skill becomes available (richer Jira entity
  extraction); otherwise the deterministic extractor runs.

## What this pipeline measures that nothing else does

| Question | Answer it produces |
| --- | --- |
| Why did we pick this Jira ticket? | A natural-language path: window → service → matching Jira component → fault class link. |
| Why didn't we pick any Jira ticket? (novelty) | The component / service / fault class entities have no edge to any visible Jira node — concrete graph evidence of novelty. |
| Which entity types are the most discriminative? | Per-edge-type contribution to PR-AUC (logged at fit time). |
| Are component fields actually aligned across the two contexts? | `severity_alignment_strength` + `component_match_rate` summary stats. |

These outputs feed back into the project's "Does Jira help?" thesis with
*mechanism-level* evidence, not only a delta.
