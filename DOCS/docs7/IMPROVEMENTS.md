# Improvements Backlog — pre-Agentic-Build

**Status.** Draft 2026-06-12. This document captures every system-level change we want in place before (and during) the agentic redesign, so the agent we build is portable, comparable, instrumented, and industry-credible.

**Companion docs.** [`RESEARCH-QUESTIONS.md`](RESEARCH-QUESTIONS.md) (the RQ catalogue this list services), [`docs6/XX_AGENTIC_IDEA.md`](../docs6/XX_AGENTIC_IDEA.md) (the agentic proposal), [`docs6/X_FINAL_TCH_CASCADE.md`](../docs6/X_FINAL_TCH_CASCADE.md) (the cascade, used internally).

**Format.** Each item: *What is true today → what we change → action items → open questions.*

---

## Table of contents

1. [Neo4j: localhost → Aura cloud](#1-neo4j-localhost--aura-cloud)
2. [LLM serving: LM Studio → Ollama on cluster (or vLLM)](#2-llm-serving-lm-studio--ollama-on-cluster-or-vllm)
3. [Industry-grade integration surface](#3-industry-grade-integration-surface)
4. [WoL framing — credibility without overclaim](#4-wol-framing--credibility-without-overclaim)
5. [Apples-to-apples evaluation protocol](#5-apples-to-apples-evaluation-protocol)
6. [LLM telemetry and cost tracking](#6-llm-telemetry-and-cost-tracking)
7. [Fixing the RQ caveats](#7-fixing-the-rq-caveats)
8. [Security and credentials hygiene](#8-security-and-credentials-hygiene)
9. [Action-item priority order](#9-action-item-priority-order)

---

## 1. Neo4j: localhost → Aura cloud

### What is true today
- `src/v2_advanced/shared/neo4j_client.py` defaults to `neo4j://127.0.0.1:7687`, user `neo4j`, password `123456789`.
- Mode 3 KG-Retrieval and Hybrid-RRF call this client per test window with ~10–50 Cypher queries each. On localhost, total query latency is sub-millisecond per call.
- The on-disk LLM extractions (`v2_kg_extractions/all_extractions.jsonl` — 1,989 incidents, 5,021 symptoms, 208 errors, 76 components, 16 services) are loaded into Neo4j via `proposal_d_knowledge_graph.reload_neo4j.py`.

### What we change
Move to **Neo4j Aura**, the cloud-hosted managed Neo4j service. Credentials supplied separately in `Neo4j-*.txt` (gitignored). Update the client's default config to accept Aura's connection string (`neo4j+s://<id>.databases.neo4j.io`) and AuraDB authentication.

### Can we use Aura? Yes, with these caveats

| Concern | Impact | Mitigation |
|---|---|---|
| **Network latency** (50–200 ms per query vs sub-ms localhost) | Mode 3 fit runs ~10–50 queries × 450 test windows = 4.5k–22.5k queries. At 100 ms RTT, that's 7.5–37.5 min just in Cypher latency on top of inference. Bulk loads (1,989 incidents) sit on the request boundary too. | (a) Batch Cypher with `UNWIND` to amortize roundtrips. (b) Add a query-side **memoization layer** so the same window doesn't re-query graph patterns it already saw. (c) Co-locate the cluster job with an Aura region close to Compute Canada (e.g., Aura `us-east-1` or `eu-west-1`). |
| **Free-tier limits** | Aura Free caps at 200K nodes + 400K relationships, 1 instance, no APOC-full | We're at 9,179 nodes total (1,989+5,021+208+76+16+1,876 Fix=9,186). Well under. Free tier is enough for now. |
| **APOC core-only on Free tier** | Some Cypher queries may rely on `apoc.collect.coll`, `apoc.text.distance`, etc. | Grep our code: `grep -rn 'apoc\.' src/`. If we use anything beyond APOC core, either upgrade to Aura Pro or rewrite the query. |
| **Connection scheme + auth** | Our `Neo4jClient` uses `neo4j://`, no TLS, no real auth. Aura uses `neo4j+s://` with username/password. | Update `Neo4jConfig` defaults to read from environment variables: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`. Add a `.env.example` documenting the keys; **never** commit the real `.env`. |
| **Instance pause / cold start** | Free tier auto-pauses after 3 days idle; first query after pause has ~60 s warm-up | For batch jobs, ping the instance before starting the workload; for production, use paid tier. |
| **Compute Canada outbound firewall** | Some clusters restrict outbound HTTPS to known endpoints | Verify cluster has internet access to `*.databases.neo4j.io:7687`. If blocked, request an exception or self-host Neo4j on a compute node. |

### Action items
- [ ] Add `Neo4j-*.txt`, `.env`, `*.credentials`, `*.secrets` to `.gitignore` (done in this commit).
- [ ] Refactor `Neo4jConfig` (`src/v2_advanced/shared/neo4j_client.py`) to load from env vars, with sensible localhost fallbacks for dev.
- [ ] Add a `scripts/research-lab/verify_neo4j_connection.py` that asserts node counts and APOC availability before any pipeline run.
- [ ] Audit Cypher queries for non-core APOC usage.
- [ ] Add a query-side memoization decorator with on-disk cache keyed by `(window_id, query_signature_hash)` — recoverable across run interruptions, similar to the per-ticket extraction cache.
- [ ] Document the Aura migration steps in `docs/RUNBOOK-neo4j.md` (new).

### Open questions
- Will the cluster have predictable outbound network? (If not — self-host Neo4j on the cluster node, possibly via docker.)
- Do we want the cascade artifacts to depend on a *live* Aura instance, or should we keep an exported `*.dump` we can reload into a fresh instance for reproducibility?

### 1.1 Database layout for the 3 datasets — **LOCKED 2026-06-12**

The locked decision after a credibility review: **Option A — one instance, one database, reload between experiments, with a startup integrity check.** Dataset mixing in a single Neo4j instance is **forbidden** during research evaluation runs.

#### Why mixing is unsafe for research

| Dataset pair | Lexical overlap risk | Cross-contamination probability |
|---|---|---|
| OB ↔ OTel Demo | **HIGH** — both have `cartservice`, `checkoutservice`, `paymentservice`, `redis`, `kafka` (OTel Demo is based on OB) | KG queries on OTel Demo windows can silently match OB tickets via shared `Service` + `Symptom` nodes |
| OB ↔ WoL | LOW — Mode 2 measured max cosine = 0.47 across 277,600 pairs | Structurally separable |
| OTel Demo ↔ WoL | LOW — different vocabulary domains | Structurally separable |

The OB ↔ OTel Demo case is the load-bearing risk. Tagged-node filtering (option B) requires every Cypher query to carry a `WHERE n.dataset = $ds` clause; **one missing clause** silently contaminates the result. That risk is acceptable for production multi-tenancy but unacceptable for research where a single slip invalidates a published claim.

#### The four options (re-evaluated for research credibility)

| Approach | Research-grade isolation? | Free tier? | Verdict |
|---|---|---|---|
| **A. 1 instance, 1 DB, reload between experiments** | ✓ (graph only ever holds one dataset) | ✓ | **LOCKED — this is what we use for all research runs** |
| B. 1 instance, 1 DB, dataset-tagged nodes | ✗ (one missing WHERE clause = contamination) | ✓ | **Rejected for research.** Acceptable only for production multi-tenancy (deferred). |
| C. 1 instance, N databases | ✓ | ✗ (needs Aura Professional, ~$65/mo) | Optional upgrade for the final camera-ready paper run if budget allows |
| D. N separate Aura instances | ✓ | partial (one instance per free account) | Operationally clunky; skip |

#### Safety mechanisms (mandatory in v1)

1. **Fingerprint node.** `reload_neo4j.py` writes a `GraphMetadata` node on every load:
   ```cypher
   MERGE (m:GraphMetadata {key: 'loaded_dataset'})
   SET m.dataset = $dataset_id,
       m.loaded_at = datetime(),
       m.n_incidents = $n_incidents,
       m.global_dir = $global_dir
   ```
2. **Startup integrity check.** Before any KG-using skill runs, the agent queries `(m:GraphMetadata {key: 'loaded_dataset'})` and **refuses to start** if `m.dataset` doesn't match the dataset being evaluated. No silent fallback.
3. **Per-experiment reload prologue.** Every experiment script begins with a `reload_neo4j --global-dir <X>` call before any retrieval. This is wired into the agent's startup, not left to the operator.
4. **No B-mode coexistence.** The `NEO4J_DATASET_TAG` env var (originally reserved for option B) is **kept reserved** for future production multi-tenancy but is **explicitly forbidden during research runs**. The agent refuses to start if both Option A (single dataset loaded) and Option B (tagged nodes present) signals are detected in the same instance.

#### When to upgrade

- **Camera-ready paper run (post-acceptance):** consider Aura Professional + Option C for maximum isolation. ~$65/mo for the one month of camera-ready work.
- **Multi-tenant production deployment (out of v1 scope):** Option B becomes the obvious choice — each customer is a `dataset` tag.

### 1.2 Action items (additions to §1 list)
- [ ] Add `GraphMetadata` fingerprint writes to `proposal_d_knowledge_graph.reload_neo4j.py`.
- [ ] Add the startup integrity check to `src/agent/runner.py` (and the existing pipelines that read Neo4j).
- [ ] Document the locked decision in `DOCS/RUNBOOK-neo4j.md` (new).
- [ ] CI / smoke-test: a script that loads two datasets, verifies the second wipes the first cleanly, and asserts the fingerprint matches.
- [ ] *(Optional optimisation)* Wire `neo4j-admin database dump|load` as a shortcut for ~5 sec graph snapshots / restores (see §1.3).

### 1.3 Persistence and switch-back — three layers of caching

The expensive part of building the KG (LLM extraction) **runs once per dataset, forever**. Switching between datasets is cheap because of the layered persistence:

| Layer | Lives at | Built by | Cost to rebuild | Survives `reload_neo4j`? |
|---|---|---|---|---|
| **L1 LLM extractions** | `data/derived/global/<dataset>/v2_kg_extractions/all_extractions.jsonl` | `extract_tickets_cli` (~hours) | hours (WoL ≈ 8 h; OB ≈ 2 h; OTel ≈ 1 h) — only re-run if the prompt or model changes | YES — JSONL on disk, untouched by Neo4j operations |
| **L2 Neo4j graph** | Live Neo4j instance | `reload_neo4j --global-dir <X>` reads L1 and writes nodes/edges | ~20 sec — read jsonl, write MERGE statements | NO — wiped + rebuilt per switch |
| **L3 SkillCache** | `data/skill_cache/` (gitignored) | Agent runs; content-addressed by `(skill, version, bundle_hash, memory_hash)` | Free on cache hit | YES — independent of Neo4j |

**Switch-back workflow.** After working on Dataset B, returning to Dataset A is **one `reload_neo4j` call (~20 sec)** plus a re-run of the agent (cache hits make this seconds-to-minutes for previously-run experiments).

```bash
# One-time per dataset (slow, only once unless prompt/model changes):
extract_tickets_cli --global-dir data/derived/global/<dataset_id>     # hours

# Every dataset switch (fast):
reload_neo4j --global-dir data/derived/global/<dataset_id>            # ~20 sec
# GraphMetadata fingerprint check on agent startup verifies the right
# dataset is loaded — refuses to run otherwise.
```

**Optional faster path — Neo4j database dump/load (~5 sec each way).** For frequent switching (or when on Aura where MERGE round-trips are network-bound), snapshot a loaded graph once and restore from the binary dump:

```bash
# Snapshot a loaded dataset (Neo4j must be stopped briefly OR use online backup):
neo4j-admin database dump neo4j --to-path=data/neo4j-snapshots/wol.dump
neo4j-admin database dump neo4j --to-path=data/neo4j-snapshots/ob.dump

# Restore in ~5 sec (binary restore, no MERGE parsing):
neo4j-admin database load neo4j --from-path=data/neo4j-snapshots/wol.dump
```

4× speedup over `reload_neo4j.py` for our scale (~10K nodes/dataset). Not critical at current sizes; valuable when the graph grows or when on Aura. The dump file also serves as a **reproducibility artifact** — share the dump = share the exact graph state.

**Net effect.** The LLM cost (the only thing that's actually expensive) is paid once per dataset, captured in JSONL, and never repeated. Everything below it (graph, skill outputs, traces) rebuilds in seconds.

---

## 2. LLM serving: LM Studio → Ollama on cluster (or vLLM)

### What is true today
- `src/v2_advanced/shared/lm_studio.py` posts to `http://localhost:1234/v1/chat/completions`, OpenAI-compatible. Uses `response_format` with strict JSON schemas (`TICKET_EXTRACTION_RF`, `WINDOW_EXTRACTION_RF`, `AGENT_VERIFY_RF`) for grammar-constrained extraction.
- LM Studio's grammar-constrained inference is **single-threaded** — concurrent requests under the same schema produce HTTP 400 (observed during WoL KG extraction; see `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` "Files produced").
- All LLM workloads ran on a single RTX 3070 (8 GB VRAM, partial GPU offload for the 35B-A3B MoE model).

### What we change
On Compute Canada / Alliance Research clusters, run an OpenAI-compatible inference server (Ollama or vLLM) and point our existing clients at it. The clients (`LMStudioClient`) are stateless and OpenAI-compatible — minimal code change.

### Two real candidates

| | Ollama | vLLM |
|---|---|---|
| OpenAI-compatible HTTP API | ✓ | ✓ |
| Structured JSON output | basic `format:"json"` (all versions) + schema-constrained `format:<json_schema>` (0.5+) | full grammar via `guided_json` parameter |
| Concurrent requests | yes, configurable (`OLLAMA_NUM_PARALLEL`) | yes, optimized for throughput (continuous batching) |
| Model catalog | GGUF via `ollama pull` | HuggingFace transformers; manual download |
| Easy to deploy as SLURM job | ✓ | ✓ (with extra steps) |
| Production-grade throughput | moderate | high (designed for serving) |
| Multi-GPU | recent versions | yes, native tensor parallelism |
| Right call for our workload | dev / small-batch | research-cluster batch inference |

**Recommendation:** start with Ollama for parity with current dev environment; once we're confident, switch to vLLM if the cluster experiment needs higher throughput (we already saw extraction takes 8 h at ~16 sec/window on LM Studio; on vLLM with continuous batching the same 2,000 tickets should finish in ~30–60 min).

### Can we keep the same client code?

Mostly. Both Ollama (0.5+) and vLLM accept OpenAI's `/v1/chat/completions` shape plus a JSON-schema constraint. Two adjustments:

1. **Schema parameter key:**
   - LM Studio: `response_format: {type: "json_schema", json_schema: {...}}`
   - Ollama 0.5+: `format: <json_schema_object>`
   - vLLM: `extra_body: {guided_json: <json_schema>}`
   
   Wrap into a single `chat_json()` method that switches on `backend = os.environ["LLM_BACKEND"]` (values: `lm_studio` / `ollama` / `vllm`).

2. **Endpoint URL + auth:** env var `LLM_BASE_URL` and optional `LLM_API_KEY` (vLLM/Ollama can be unauthenticated on a private cluster).

### Action items
- [ ] Refactor `src/v2_advanced/shared/lm_studio.py` into `src/v2_advanced/shared/llm_client.py` with backend switch.
- [ ] Update `LMStudioConfig` → `LLMConfig` (backend, base_url, model, api_key).
- [ ] Document the cluster setup: SLURM script template launching Ollama as a long-running job with port-forwarded endpoint, plus a smoke-test that issues one extraction call and verifies the response schema.
- [ ] Run an A/B: same 50-ticket extraction subset on LM Studio (local) vs Ollama (cluster), confirm output is bit-equivalent (or document acceptable variance).
- [ ] Add a fallback path: when grammar-constrained mode fails, retry with `format:"json"` and validate against schema in Python.

### Open questions
- Which cluster (Cedar, Beluga, Narval)? Each has different GPU options (Cedar — V100, Beluga — V100, Narval — A100). Affects model size selection.
- Do we run inference as part of a SLURM job (start server, run client, kill server) or as a persistent service the cluster admins host? The former is more portable; the latter is faster for interactive iteration.

---

## 3. Industry-grade integration surface

### What is true today
- The system reads from `data/derived/global/<id>/` (hardcoded directory layout).
- Outputs are JSONL files at `<global>/comparison/<pipeline>/per-window-predictions.jsonl`.
- Configuration is via Python module constants + a few env vars; not a documented contract.
- No deployable artifact (Docker image, PyPI package, REST endpoint).

### What we change
Make the agent system a **deployable artifact** with stable input/output contracts and a documented onboarding flow. So a company evaluating it can run on their own data without forking our research code.

### The minimum industry surface

1. **Stable input contract (versioned).** Two JSON schemas the company must produce:
   - `MemoryTicket` — what a Jira ticket looks like to our system (ID, summary, description, components, severity, optional log lines, optional resolution notes).
   - `TelemetryWindow` — what a window of observability data looks like (window ID, start/end timestamps, service name, optional log lines, optional trace summaries, optional metric snapshots, optional k8s events).
   
   Document these in `schemas/v1/MemoryTicket.schema.json` and `schemas/v1/TelemetryWindow.schema.json`. **Make every field optional except IDs**, so a company with partial telemetry (e.g. logs but no traces) can still run — the agent's adaptive skill set already handles missing modalities.

2. **Stable output contract.** Per window, one JSON record with fixed schema: `{window_id, triage_decision, triage_score, matched_issue_ids, is_novel, confidence, evidence_used: [skill names], cost_tokens, latency_ms}`. Document in `schemas/v1/AgentDecision.schema.json`.

3. **Configuration via env vars + YAML.** All runtime knobs (skill enable/disable, thresholds, model identifiers, LLM backend URL, Neo4j URI) come from `agent-config.yaml` and `.env`. **No hardcoded paths in code.**

4. **Two deployment surfaces:**
   - **Python SDK.** `pip install incident-triage-agent` exposes `from incident_triage_agent import Agent; a = Agent.from_config('agent-config.yaml'); decisions = a.process(windows, memory)`.
   - **REST API.** `docker run incident-triage-agent` starts a FastAPI service on port 8080 with `POST /v1/decide` taking the input schemas above and returning the output schema.

5. **Onboarding playbook.** `docs/ONBOARDING.md`: "to run the agent on your company's data, (a) export your Jira tickets via X format, (b) export your telemetry windows via Y format, (c) set ENV vars, (d) run the agent." Plus a `scripts/onboarding/jira_csv_to_memory_ticket.py`-style adapter as an example.

### Action items
- [ ] Author the three JSON schemas (`MemoryTicket`, `TelemetryWindow`, `AgentDecision`).
- [ ] Write `agent-config.yaml.example`.
- [ ] Build the Python SDK + the FastAPI surface (probably the same `Agent` class with two callers).
- [ ] Containerize (`Dockerfile` + `docker-compose.yml` including Neo4j + Ollama for local-only smoke test).
- [ ] Write `docs/ONBOARDING.md`.

### Open questions
- Is the Python SDK enough, or do we want a TypeScript / Java client too for industry breadth?
- Should the agent persist its state (rolling window memory for page-suppression) in Redis / Postgres, or per-process in-memory?

---

## 4. WoL framing — credibility without overclaim

### What is true today
- WoL has **logs (engineer-pasted into Jira) + Jira tickets** — no traces, no metrics, no k8s events, no continuous-time telemetry stream.
- We have used WoL in 3 modes (Mode 1 distractor, Mode 2 novelty, Mode 3 self-contained retrieval) plus a bookmarked Mode 4 (WoL Kafka × OTel Demo Kafka).
- Risk: a reviewer can say *"you claim real-world Apache Jira evaluation, but the 'telemetry window' you query with is just whatever the reporter pasted into the ticket. That's not telemetry — it's a self-fulfilling test."*

### What we change — explicit honesty
Re-frame how we describe each WoL evaluation so the contribution of every result is unambiguous:

| Where WoL is used | The claim we make | What we explicitly do NOT claim |
|---|---|---|
| Mode 1 (distractor pool) | Memory contamination by real off-topic Jira tickets doesn't collapse the cascade's Hit@5. | *Not*: distractors that resemble true windows hurt as much as we measure. (Simulation is identity-agnostic; see §7 below for the fix.) |
| Mode 2 (novelty queries) | A retrieval-confidence-floor based novelty signal correctly identifies cross-domain incidents as novel. | *Not*: the system would correctly process a *full* Apache incident end-to-end. We don't claim diagnosis of these incidents — only that they don't false-match. |
| Mode 3 (self-contained retrieval) | Our retrieval signal generalises from synthetic OB humanized text to real human-written Apache Jira ticket text. | *Not*: a "live deployment" claim. The "window" here is the same engineer's prose, not telemetry. **This is a text-retrieval generalisation result, not an end-to-end diagnosis result.** |
| Mode 4 (Kafka × OTel Demo, future) | Memory built from real Apache Kafka Jira matches live OTel Demo Kafka telemetry. | *Will not claim*: the OTel Demo telemetry is identical to production Kafka telemetry (it isn't — it's a synthetic deployment of the OTel Demo app). |

### Action items
- [ ] Update `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §2 to add a "What this is *not*" subsection before headline results: explicitly states the claim is "text retrieval generalises", not "end-to-end diagnosis on live Apache telemetry".
- [ ] Update the paper's `08-discussion.tex` (or equivalent) with a paragraph titled "On the WoL evaluation: what it tests and what it does not."
- [ ] When presenting Mode 3 numbers in the paper, **always** label them "WoL Mode 3 — self-contained text retrieval" not "Mode 3 cascade Hit@5 on Apache Jira" (which sounds end-to-end).
- [ ] In `docs7/REAL-DATA-WoL-PLAN.md`, add a §3.3 subsection: "Why WoL is not equivalent to a live-deployment test."

### Open questions
- Should we attempt to *synthesise* fake telemetry to accompany each WoL ticket (e.g. generate plausible Loki / trace data from the ticket description) to enable an end-to-end claim? Risky — looks like fabrication unless extremely carefully done. Probably **no**, but worth flagging.

---

## 5. Apples-to-apples evaluation protocol

### What is true today
- Different evaluations use different memory pool sizes (347 OB synthetic / 147 OTel Demo / 2,000 WoL), different gold relations (single-gold OB / multi-gold WoL coarse and strong), different split protocols (random OB / family-stratified WoL).
- Hit@5 = 0.912 (OB cascade) and Hit@5 = 0.787 (WoL Hybrid-RRF strong) **cannot** be placed in the same row of a results table without an enormous footnote.

### What we change
Adopt and document an explicit comparison protocol. Any time two numbers appear together — in the paper, in a table, in a slide — they must be *comparable* by these rules:

1. **Same dataset + same split.** OB cascade Hit@5 vs WoL Hybrid-RRF Hit@5 — not comparable. Always state the dataset in the row label.
2. **Same gold relation.** Coarse-match vs strong-match — different relations, different "Excellent" thresholds. Always state which is reported.
3. **Same memory pool.** Adding distractors changes the pool; report the pool size next to every Hit@K.
4. **Same metric formula.** Hit@K with `len(gold) >= 1` filter vs with `len(gold) == 1` — be explicit. The Mode 3 code uses `if not gold: continue` — document this.
5. **Same statistical envelope.** 1,000-resample paired bootstrap, seed=42, the same prediction JSONLs.
6. **For agent-vs-cascade-vs-single-retriever:** all three must run on the **same** prediction inputs (same per-window evidence text, same memory pool) so the only difference is the composition rule.

### Where this hits today

A specific cleanup needed:
- The `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §3.8 table includes a comparison with OB synthetic ("BiEncoder standalone on the synthetic dataset: Hit@1 = 0.695…"). That comparison is across datasets and is currently labelled "comparison points." We should either remove it from this doc or annotate it with a footnote explaining the gold relations differ. Same for any cross-dataset claim in the paper.

### Action items
- [ ] Author `docs7/COMPARISON-PROTOCOL.md` (single page) listing the six rules above + a worked example of a legal vs an illegal table row.
- [ ] Add comment headers to every result-comparison script asserting it follows the protocol.
- [ ] Run an audit of `MODE1`, `MODE2`, `MODE3` docs for any cross-dataset numerical comparison; either remove or footnote.
- [ ] Establish a single results-table file (`docs7/PAPER-TABLES.md` or similar) where every cross-system comparison must be drafted; reject inline cross-dataset comparisons in the source documents.

### Open questions
- For the agent-vs-cascade comparison on OB, we'll fit the cascade and the agent on the same upstream predictions. Should the agent be allowed to fine-tune any sub-skill, or must it use the exact same checkpoint? Default: same checkpoint, only differences are composition + tool-selection.

---

## 6. LLM telemetry and cost tracking

### What is true today
- `LMStudioClient` does not log token counts.
- LM Studio's `/v1/chat/completions` response includes `usage: {prompt_tokens, completion_tokens, total_tokens}` but we discard it.
- No aggregated token / cost record per experiment; we only have wall-time logs.
- We currently can't say "running the agent on a 1,000-window test set costs X dollars at GPT-4o rates."

### What we change
Instrument every LLM call. Aggregate per experiment. Report in the paper.

### Schema for per-call telemetry

Write a JSONL file `data/llm_telemetry/<run_id>.jsonl` with one record per call:

```json
{
  "ts": "2026-06-12T14:23:45.123Z",
  "experiment": "wol-mode3-kg-extraction",
  "phase": "extract_tickets",
  "ticket_id": "wol-m-3589f4c00c9af528",
  "model": "qwen/qwen3.6-35b-a3b",
  "backend": "lm_studio",
  "prompt_tokens": 1842,
  "completion_tokens": 127,
  "total_tokens": 1969,
  "latency_ms": 15400,
  "success": true,
  "error": null,
  "cache_hit": false
}
```

A per-experiment summary at `data/llm_telemetry/<run_id>.summary.json`:

```json
{
  "experiment": "wol-mode3-kg-extraction",
  "started_at": "...", "finished_at": "...",
  "model": "qwen/qwen3.6-35b-a3b",
  "n_calls": 1989,
  "n_failed": 11,
  "total_prompt_tokens": 3512944,
  "total_completion_tokens": 248902,
  "total_tokens": 3761846,
  "wall_seconds": 29351,
  "monetary_equivalent_usd": {
    "gpt-4o":              { "input_per_M": 2.50, "output_per_M": 10.00, "total": 11.27 },
    "gpt-4o-mini":         { "input_per_M": 0.15, "output_per_M": 0.60,  "total": 0.68 },
    "claude-3-5-haiku":    { "input_per_M": 0.80, "output_per_M": 4.00,  "total": 3.81 },
    "self-hosted-amortized": "not applicable — local GPU"
  }
}
```

### Action items
- [ ] Add a `TokenLogger` class in `src/v2_advanced/shared/llm_telemetry.py` — wraps the OpenAI-compatible client, intercepts the `usage` field, appends to JSONL.
- [ ] Threaded the experiment / phase name through the call sites (most-frequent ones: `extract_from_ticket`, `extract_from_window`, `DiagnosisAgent.diagnose`).
- [ ] Per-run summarisation script: `scripts/research-lab/summarise_llm_telemetry.py <run_id>` → emits the `.summary.json`.
- [ ] Add a "Compute resources" subsection to the paper showing per-experiment token totals + monetary equivalents at hosted-model rates (for industry credibility).
- [ ] Document this convention in `IMPROVEMENTS.md` (this file) and `CLAUDE.md` (so future runs respect it).

### Open questions
- Do we report self-hosted GPU cost in $? If yes, by which model — GPU-hour pricing on Compute Canada (free) vs equivalent AWS p4d.24xlarge ($32/hr)? Both should be in the paper's appendix.
- Should we track *successful inference cost* separately from *retry-call cost* (the 11 oversized-context failures still consumed tokens before the 400)?

---

## 7. Fixing the RQ caveats

Each caveat in [`RESEARCH-QUESTIONS.md`](RESEARCH-QUESTIONS.md) Buckets A-B that we can close cheaply:

| RQ | Caveat | Fix | Cost |
|---|---|---|---|
| **A4** distractor robustness | Simulation is identity-agnostic (per-slot displacement is random); only tests pool-size effect | Implement similarity-weighted simulation: for each window, score distractors by TF-IDF cosine to the window text, replace top-K slots with highest-similarity distractors first. Re-run sweep. | ~half day |
| **A5** novelty cross-domain | Lower-bound only — uses just the free signal, not the full L3 disjunction | Run the LM-Studio agent on the 800 WoL OOD queries (~4 h), run the learned classifier, OR-combine, recompute novel precision/recall. | ~5–6 h |
| **A6** WoL transfer | Window-side uses rule-based entity extraction (limits KG-Retrieval and Hybrid-RRF graph signal) | LLM extract 1,750 WoL windows (~6 h LM Studio time), reload Neo4j, re-run Hybrid-RRF and KG-Retrieval. | ~6–8 h |
| **A8** verifier OOD-failure | Only OB-tuned verify prompt tested on WoL | Author a WoL-specific verify prompt; re-run DiagnosisAgent on the 450 test windows; compare Hit@K. **Don't expect a positive result** — the negative finding is itself valuable, but having tried to mitigate it strengthens the paper. | ~5 h |
| **B2** depth-scaling on real data | Predictions cached but depth-stratified analysis not done | Pure analysis pass on the cached `biencoder-predictions.jsonl`. | ~1 h |

### Action items
- [ ] Prioritize A6 fix (LLM window extraction) — unlocks the cleanest full Hybrid-RRF / KG-Retrieval-LLM numbers.
- [ ] Build similarity-weighted distractor sweep as A4 fix.
- [ ] Run the full-L3 novelty for A5.
- [ ] Defer A8 mitigation until the agentic system is built (the agent's adaptive selection naturally handles when the verifier helps vs hurts).

### Open questions
- Do we keep the lower-bound Mode 2 result in the paper alongside the full-L3 result? Probably yes — the lower-bound is the cleaner methodological statement; the full-L3 is the achieved performance.

---

## 8. Security and credentials hygiene

### What is true today
- `Neo4j-ba1e0503-Created-2026-06-12.txt` is in the working directory, **untracked but not ignored**. A `git add .` would have committed it.
- The cascade's default Neo4j password (`123456789`) is *hardcoded* in `src/v2_advanced/shared/neo4j_client.py:31`.
- LM Studio runs unauthenticated on localhost; that's fine locally but won't work on a shared cluster.
- No `.env` example file documenting which variables to set.

### What we change
- All credentials live in `.env` (gitignored). Code reads via `os.environ` or `dotenv`.
- Provide `.env.example` listing every required key with placeholder values.
- For team rotation: document how to rotate the Aura password (`lms ps`-style explicit rotation in the runbook).
- Pre-commit hook scans staged files for password-like strings.

### Action items
- [x] Add `Neo4j-*.txt`, `*.credentials`, `*.secrets`, `.env`, `.env.*` (except `.env.example`) to `.gitignore`. **Done in this change.**
- [ ] Replace the hardcoded `password: str = "123456789"` default in `Neo4jConfig` with `password: str = os.environ.get("NEO4J_PASSWORD", "")` and raise a clear error if empty.
- [ ] Author `.env.example` with `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `LLM_BACKEND`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- [ ] Document credential rotation in `docs/RUNBOOK-credentials.md` (or similar).
- [ ] Optional: add a pre-commit hook (`detect-secrets` or equivalent) scanning for high-entropy strings.

### Open questions
- Do we want a single `.env` for all environments, or one per (dev / staging / cluster) with a shared structure?

---

## 9. Action-item priority order

Ordered by the principle: *unlock parallel work first, then quality / robustness, then nice-to-haves.*

| # | Action | Unblocks | Effort |
|---|---|---|---|
| 1 | Refactor `Neo4jConfig` to read from env + test against Aura | Cluster migration | 2 h |
| 2 | Refactor `LMStudioClient` to backend-switchable `llm_client.py` | Cluster migration + Ollama/vLLM | 4 h |
| 3 | `.env.example` + credentials hygiene | All deploys | 1 h |
| 4 | `TokenLogger` + per-call JSONL telemetry | Paper "Compute resources" claim; cost reporting | 4 h |
| 5 | `docs7/COMPARISON-PROTOCOL.md` + audit pass on Mode docs | Paper consistency | 3 h |
| 6 | WoL framing edits across MODE1 / MODE2 / MODE3 docs | Credibility | 2 h |
| 7 | A6 fix: LLM window extraction → re-run Hybrid-RRF + KG-Retrieval | Closes the Mode 3 story | ~8 h compute |
| 8 | A5 fix: full L3 disjunction on 800 OOD queries | Tightens Mode 2 claim | ~5 h compute |
| 9 | A4 fix: similarity-weighted distractor sweep | Tightens Mode 1 claim | ~half day |
| 10 | B2 depth-scaling analysis on cached predictions | New claim for free | 1 h |
| 11 | Industry surface (JSON schemas, SDK, REST, Docker) | Pre-deployment industry credibility | 1–2 weeks |
| 12 | Agentic system implementation per [`docs7/AGENTIC-SYSTEM.md`] (to follow) | THE paper contribution | 4–6 weeks |

Items 1–5 are pure-engineering and can run in parallel with research compute (7–10) on the cluster. The agentic implementation (12) consumes the outputs of 1–11 — particularly 4 (telemetry), 5 (protocol), and 11 (industry surface).

---

## 10. Cross-references

- **The RQ catalogue this list services:** [`docs7/RESEARCH-QUESTIONS.md`](RESEARCH-QUESTIONS.md).
- **Agentic system spec (to follow):** `docs7/AGENTIC-SYSTEM.md`.
- **Cascade end-state (internal-only):** [`docs6/X_FINAL_TCH_CASCADE.md`](../docs6/X_FINAL_TCH_CASCADE.md).
- **Agentic design proposal that this builds on:** [`docs6/XX_AGENTIC_IDEA.md`](../docs6/XX_AGENTIC_IDEA.md).
- **WoL mode results referenced in §4 and §7:** [`MODE1-DISTRACTOR-RESULTS.md`](MODE1-DISTRACTOR-RESULTS.md), [`MODE2-NOVELTY-RESULTS.md`](MODE2-NOVELTY-RESULTS.md), [`MODE3-TCH-LITE-WoL-RESULTS.md`](MODE3-TCH-LITE-WoL-RESULTS.md).

---

*Generated 2026-06-12 to capture the system-level improvements that should land before, or alongside, the agentic redesign. Every item here is bounded — none is open-ended research; all are engineering or analysis with known cost.*
