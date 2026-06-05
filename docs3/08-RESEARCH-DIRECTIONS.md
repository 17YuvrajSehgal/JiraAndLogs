# Research Directions V2 — From "Good Enough" to "ICSE Best Paper"

This document responds to the user's research questions of 2026-06-03 and lays out a coordinated plan to push past our current ceilings. Every proposal here is grounded in a specific limitation of the current Phase G state. No-compute / no-time constraint applies — we are optimizing for paper quality, not throughput.

The TL;DR of what to build:

1. **Re-split the dataset** so every fault family appears in train (better matches a real production scenario).
2. **Replace the "characteristic log line" abstraction** with a full **log-sequence encoder** trained on raw log lines.
3. **Replace BM25** in MemoryGraph SOTA with a **hybrid sparse + dense retriever (SPLADE + BiEncoder + RRF fusion)**.
4. **Build an LLM-extracted knowledge graph** from the Jira tickets (Neo4j-style document intelligence) and use it as a third retrieval channel.
5. **Wrap everything in an agentic reasoning loop**: an LLM that reads top-K candidates, queries the graph, and produces a final ranked diagnosis with citations.

Below: detailed motivation, design, and effort estimate for each.

---

## 1. Current limitations — naming the bottlenecks

The user identified four issues. Reframed as engineering bottlenecks:

| # | Limitation | Root cause | Severity |
|---|---|---|---|
| 1 | Family-disjoint train/test split | Out-of-distribution evaluation is too punishing; production reality is "we've seen this kind of problem before" | High |
| 2 | Logs reduced to one "characteristic line" + 94 features | Throws away 99.99% of the log content; engineer-vocabulary heuristics lose contextual signal | High |
| 3 | BM25 as the first-stage retriever | Lexical-only; misses semantic synonyms; was state-of-the-art in 2009 | Medium |
| 4 | Entity graph is regex-based | Coarse, brittle; misses subtle relationships an LLM would catch | Medium |
| 5 | (Not flagged but noted) Cold-start novelty unsolved | No calibrated novelty head | Low for paper, high for production |

The proposals below address each of these in order.

---

## 2. Proposal A — In-distribution re-split

### 2.1 The change

**Current:** 14 train families, 6 val families, 7 test families. Families do NOT overlap between splits.

**Proposed:** keep 27 families combined, then assign each WINDOW (not each family) to train/val/test at 70/15/15 ratio with stratification by family. The Jira ticket memory keeps its time-ordered visibility rule (a test window can only see tickets minted before it).

### 2.2 Why this is more honest for production framing

A real SRE team has been logging incidents for years. When a new pager fires, the team's memory contains LOTS of past tickets, including from the same fault family. The current family-disjoint split asks "can the system identify a brand-new kind of failure?" — that is a much harder problem than the one the system is actually for.

In-distribution evaluation asks instead: "given a fault family the team has seen before, can the system find the right past ticket fast?" This is the production question.

### 2.3 What we keep, what we lose

- **Keep:** the depth-stratification axis (`n_prior_family_tickets`) still works — in fact it works BETTER because the depth distribution is fuller.
- **Keep:** the corrected Hit@K metric.
- **Keep:** time-ordered visibility (no future tickets leak into past retrievals).
- **Lose:** the "family-disjoint OOD generalization" framing. Replace with "in-distribution retrieval with chronological holdout."

### 2.4 Honest disclosure

Reviewers may ask "but what about generalization to truly new failures?" Answer: keep a small held-out test set with 2-3 fully-unseen families as a SECONDARY benchmark. Report both numbers in the paper. The main benchmark becomes in-distribution; the secondary benchmark addresses the generalization question.

### 2.5 Effort estimate

- Code change: 1 file edit in `split_manifest` generation
- Re-run: ~30 minutes for the full panel
- Re-render figures: ~5 minutes
- Total: half a day

---

## 3. Proposal B — Log-sequence encoder

### 3.1 The problem with the current approach

For each window, we currently extract ONE "characteristic log line" (the most frequent error template after sanitization) and use it as the query for BM25. This is a 99.99% compression of the underlying log stream — we have ~150 log lines per service per window × ~10 services per window × 6720 windows = ~10M lines, and we collapse each window to one string.

Two things this loses:
1. **Sequence information.** "Error A then Error B then restart" is semantically different from "Restart then Error A then Error B," but both collapse to the same characteristic line.
2. **Multi-service evidence.** A fault in service X often shows as different symptoms in service Y. The characteristic line picks ONE service's view.

### 3.2 Proposed architecture: `LogSeq2Vec`

A small dedicated neural model that takes the raw log stream of a window and produces a single fixed-size embedding.

```
INPUT per window:
  raw log dump from raw/loki/<window>.json — typically 100-1500 lines

STAGE 1 — line embedding (encoder, runs per line):
  - parse JSON or treat as freeform text
  - strip volatile substrings (timestamps, IDs, hashes) using the existing
    log_signatures.py regex set
  - feed to a small Transformer (e.g. a 6-layer MiniLM equivalent) trained
    on log lines from train split with masked language modeling
  - 128-d embedding per line

STAGE 2 — sequence aggregation:
  - sort lines by timestamp, keep the most-anomalous 50 (those whose
    template frequency is > 3× their baseline frequency)
  - feed the sequence of 50 × 128-d vectors into a tiny Transformer
    (positional embeddings + 2 encoder layers)
  - mean-pool the output across the sequence dimension
  - 384-d window embedding

OUTPUT:  one 384-d vector per window
```

### 3.3 What this unlocks

- A **second retrieval signal**: the log-sequence embedding can be compared to a Jira-ticket embedding via cosine similarity. Combine with the BiEncoder text similarity via RRF (see Proposal C).
- A **richer triage feature**: feed the log-sequence embedding as input to the triage head alongside the 94 numeric features.
- A **better novelty detector**: a window whose log-sequence embedding is far from every training-set embedding is genuinely novel. This addresses our cold-start failure mode.

### 3.4 Training data

We have approximately 50M log lines across all runs. Use them for self-supervised pre-training (masked language modeling on log lines), then fine-tune the line encoder with a contrastive objective on (window, gold-ticket) pairs.

Two-stage training:
1. **Pretrain** (~6-12 hours on RTX 5060): MLM over all 50M lines after deduplication and templating. Lets the encoder learn the log vocabulary.
2. **Fine-tune** (~30 min): contrastive on the 12K (window, gold-ticket) pairs.

### 3.5 Existing libraries that help

- **LogBERT** (Guo et al., 2021) — already-published log-specific BERT-style model. Could use as a starting checkpoint.
- **LogParser** / **Drain** — for line templating (we already use Drain-inspired regex in `log_signatures.py`).
- **HuggingFace `datasets`** — easy MLM-style training data construction.

### 3.6 Effort estimate

- Templating + dedup pass over raw logs: half day
- Implement and pretrain `LogSeq2Vec` (MLM): 1 day + 12 hours of training
- Fine-tune on (window, gold-ticket) pairs: half day
- Integrate as a skill in memorygraph: half day
- Re-run comparison + analysis: half day
- Total: ~3-4 days of engineer time + ~18 hours of GPU time

---

## 4. Proposal C — Hybrid retrieval (replace BM25)

### 4.1 The problem with BM25

BM25 is a 1990s algorithm that ranks documents by word-overlap. It is fast and "good enough" for English keyword search but has known weaknesses:
- **No semantics**: "Redis connection failed" and "Database link broken" share zero words → BM25 gives them zero similarity.
- **No structure**: a log line and a Jira-ticket prose paragraph get compared as bags of words.
- **No context**: terms that mean different things in different contexts (e.g. "tail" of a queue vs "tail" of a file) get treated identically.

### 4.2 Proposed three-way hybrid

Combine three retrieval signals via Reciprocal Rank Fusion (RRF), a well-studied algorithm that's robust and tuning-free:

```
RRF score(doc, query) = Σ_retriever  1 / (k + rank_of_doc_in_retriever)

where:
  retriever_1 = SPLADE         (learned sparse retrieval — beats BM25 by 10-20%)
  retriever_2 = BiEncoder      (dense — already trained, Phase G)
  retriever_3 = GraphMatch     (knowledge-graph entity overlap — see Proposal D)
  k = 60     (the standard RRF smoothing constant)
```

Each retriever scores all candidates, the rankings are fused, and we take the top-K of the fused ranking.

### 4.3 Why three retrievers and not just dense?

Each catches a different failure mode:
- **Sparse (SPLADE)** is great when the exact technical term is shared between query and document (`OOMKilled`, `kubelet`, `goroutine`).
- **Dense (BiEncoder)** is great when the wording differs but the concept is the same.
- **Graph match** is great when the symbolic structure matches — e.g. `(window-affects-cartservice) ∧ (ticket-affects-cartservice)` even if neither's text mentions cartservice prominently.

RRF gives us the union of strengths with no per-corpus weight tuning.

### 4.4 SPLADE primer

SPLADE (Formal et al., 2021) is a learned sparse retriever. Conceptually: a BERT-style model takes a text and outputs a sparse vocabulary-sized vector where each dimension is the expansion weight for that vocabulary term. So "Redis connection failed" might expand to `{redis: 2.1, connection: 1.4, failed: 1.2, timeout: 0.8, network: 0.5, ...}` — including terms the original text never said but that are semantically relevant.

You then do regular sparse-vector dot product. It is BM25 with neural inductive bias and outperforms BM25 by 10-20% on most retrieval benchmarks.

Implementation: there are pretrained SPLADE-v2 checkpoints on HuggingFace; we can fine-tune on our 12K pairs.

### 4.5 Effort estimate

- Implement SPLADE retriever as a skill (~half day, mostly HF integration)
- Fine-tune on our pairs (~1 hour)
- Implement RRF fusion skill (~2 hours)
- Wire as a new pipeline variant `memorygraph_v2_hybrid_rrf` (~half day)
- Re-run comparison (~30 min)
- Total: ~2 days

---

## 5. Proposal D — LLM-extracted knowledge graph (Neo4j-style)

This is the most novel piece and directly responds to the user's interest in the Neo4j Document Intelligence blog post.

### 5.1 The idea

Use a strong LLM (Claude Opus, GPT-4o, Gemini Pro) to read each Jira ticket and extract a structured representation. Store the extractions as a graph. At query time, do the same extraction on the incoming window's evidence text, then retrieve via graph traversal.

### 5.2 The schema

```
Nodes:
  Incident         {id, severity, scenario_family, occurred_at}
  Service          {name, tier}
  Component        {name, type}        // e.g. cart-redis, redis-cart
  ErrorClass       {name}              // e.g. DeadlineExceeded, OOMKilled
  RootCause        {description}        // e.g. "redis maxmemory reached"
  Fix              {description, type}  // e.g. "increase maxmemory", "restart pod"
  Symptom          {description}        // e.g. "p99 latency > 5s"

Edges:
  Incident -[:AFFECTS]-> Service
  Incident -[:INVOLVES]-> Component
  Incident -[:RAISED]-> ErrorClass
  Incident -[:CAUSED_BY]-> RootCause
  Incident -[:FIXED_BY]-> Fix
  Incident -[:EXHIBITED]-> Symptom
  Service -[:DEPENDS_ON]-> Service
  Component -[:RUNS_IN]-> Service
  Symptom -[:OFTEN_INDICATES]-> RootCause
```

### 5.3 Extraction prompt (sketch)

For each Jira ticket:

```
You are an SRE knowledge engineer. Given the Jira ticket below, extract:
1. Affected services (list)
2. Components involved (list)
3. Error classes observed (list)
4. Root cause (1 sentence)
5. Fix applied (1 sentence + type from: config_change | restart | scale_up | code_fix | rollback)
6. Symptoms (3-5 short phrases)

Respond as strict JSON.

Ticket:
<full_text>
```

Each Jira ticket → one JSON extraction → multiple graph rows. ~347 LLM calls total (or ~700 if we extract for both ticket and resolution). On a paid API: ~$2 of LLM cost, ~30 minutes wall.

### 5.4 At query time

When a new window arrives, run the same extraction on its log+evidence text:

```
window_extraction = {
  "affected_services": ["cartservice", "redis-cart"],
  "error_classes": ["DeadlineExceeded", "ConnectionRefused"],
  "symptoms": ["cart_redis_p99_spike", "cartservice_500_rate_jump"],
}
```

Then a Cypher query (Neo4j-native):

```cypher
MATCH (i:Incident)
WHERE EXISTS {
  MATCH (i)-[:AFFECTS]->(s:Service) WHERE s.name IN $affected_services
}
WITH i, COUNT { (i)-[:AFFECTS]->(s) WHERE s.name IN $affected_services } AS service_overlap,
        COUNT { (i)-[:RAISED]->(e) WHERE e.name IN $error_classes } AS error_overlap,
        COUNT { (i)-[:EXHIBITED]->(sym) WHERE sym.description IN $symptoms } AS symptom_overlap
RETURN i.id, (service_overlap * 2 + error_overlap * 3 + symptom_overlap * 1) AS score
ORDER BY score DESC
LIMIT 20
```

The graph returns its top-20 candidates. These then fuse with the BiEncoder and SPLADE candidates via RRF.

### 5.5 Why this is a big win

- **Interpretable**: the graph traversal can be SHOWN to the engineer. "We surface this ticket because it shares 3 of your 4 affected services and the same DeadlineExceeded error."
- **Robust to phrasing**: an LLM does the entity extraction, so paraphrasing doesn't hurt.
- **Compositional**: rare entity combinations matter more than common single entities. Graph scoring captures this naturally.
- **Builds on existing infrastructure**: we already have an entity graph in `memorygraph/graph.py` — this proposal upgrades the entity extraction from regex to LLM.

### 5.6 Neo4j vs in-memory graph

For 347 Jira tickets we don't NEED a real Neo4j database — a NetworkX or in-memory graph is fine. But:
- If the corpus scales to 100K+ tickets, Neo4j becomes valuable for query performance.
- Neo4j's recent "Document Intelligence" feature (the blog post you cited) automates the LLM-extraction step.
- For the paper, we can prototype in-memory and discuss the Neo4j scaling story in §6.

### 5.7 Effort estimate

- Design extraction prompt + schema: half day
- Run extractions on all 347 tickets (LLM API + caching): 2 hours
- Implement graph builder + Cypher-like query engine (in NetworkX): 1 day
- Implement the "extract from window evidence" path: half day
- Integrate as a retriever in the RRF fusion: half day
- Re-run comparison + analysis: half day
- Total: ~3 days + minor LLM cost

---

## 6. Proposal E — Agentic reasoning layer

### 6.1 The motivation

Even with all the above, the system is still "embedding cosine similarity + graph entity overlap." It has no notion of *reasoning*. An engineer looking at top-5 candidates does not just pick the one with the highest similarity — they reason about which one's root cause is most consistent with the observed symptoms.

We can teach the system to do this with an agentic LLM loop.

### 6.2 The "DiagnosisAgent"

A small but capable LLM (Llama-3-70B or Claude-Sonnet) given access to a set of "tools":

```
TOOLS the agent can call:

  retrieve_by_dense(query_text, k=20)
    Returns top-20 from the BiEncoder.

  retrieve_by_sparse(query_text, k=20)
    Returns top-20 from SPLADE.

  retrieve_by_graph(entity_dict, k=20)
    Returns top-20 from the LLM-knowledge-graph.

  read_ticket(ticket_id)
    Returns the full Jira ticket text for inspection.

  query_graph(cypher_string)
    Run an arbitrary Cypher query (for follow-up exploration).

  get_log_signature(window_id)
    Returns the characteristic log line for verification.
```

The agent receives the live window's evidence and must produce a final ranking of past tickets with justification.

### 6.3 Workflow

```
1. Receive window evidence (logs + numeric features + extracted entities).
2. Hypothesize root cause based on evidence alone (chain-of-thought).
3. Call retrieve_by_dense, retrieve_by_sparse, retrieve_by_graph
   with the appropriate queries.
4. Fuse the three lists (RRF) → top-10.
5. For each candidate in top-10, call read_ticket and verify:
     "Is this candidate's stated root cause consistent with my hypothesis?
      If not, reject it; if yes, what's the confidence?"
6. Produce a final top-5 with one-line justification each.
7. If no candidate above confidence threshold → flag as novel.
```

### 6.4 What this fixes

- **Cold-start novelty**: the agent can refuse to commit to a top-5 if no candidate passes its consistency check. This is the calibrated novelty head we have been missing.
- **Multi-step diagnosis**: the agent can refine its retrieval based on what the first pass showed. (E.g. "the top candidate involves Redis but our cartservice errors are HTTP-500, let me query for HTTP-500 incidents.")
- **Explanations**: the engineer gets a justification, not just a similarity score.

### 6.5 The big question: latency

A multi-step LLM loop is slow — easily 10-30 seconds per window. For paper purposes this is fine (we measure quality, not latency). For production deployment, the bi-encoder pre-filter + graph + cross-encoder rerank gives 80% of the agent's benefit at 100ms latency. The paper can frame the agent as "what is the upper bound of quality if latency is no object?"

### 6.6 Effort estimate

- Tool definitions: half day
- Agent loop (using LangGraph or Claude's tool-use API): 1 day
- Prompt engineering + few-shot examples: 1 day
- Run on test set (or a sub-sample of 500 windows due to latency): a few hours
- Analyze: half day
- Total: ~3 days + LLM costs

---

## 7. Integrated architecture (all proposals together)

If we implement all five, the final pipeline looks like:

```
LIVE WINDOW (logs + traces + k8s + numeric)
  |
  +-- LogSeq2Vec encoder --> 384-d log embedding
  +-- LLM entity extraction --> {affected_services, error_classes, symptoms}
  +-- Numeric features (94)
  |
  v
TRIAGE HEAD (HGB on numerics — unchanged, owns triage)
  --> P(ticket_worthy)
  |
  v
[IF ticket_worthy:]
  |
  v
RETRIEVAL FUSION
  |
  +-- SPLADE retriever        --> top-20 (sparse)
  +-- BiEncoder retriever     --> top-20 (dense, log embedding + ticket embedding)
  +-- Graph retriever         --> top-20 (entity overlap, Cypher query)
  |
  +-> RRF fuse to top-10
  |
  v
DIAGNOSIS AGENT (LLM with tool use)
  |
  +-- Hypothesize root cause from window evidence
  +-- For each top-10 candidate:
  |     - read_ticket(id)
  |     - check consistency
  |     - assign confidence
  +-- Either return top-5 with justifications,
      or flag as novel + suggest manual investigation
```

This is a 5-stage pipeline. The first three stages (encoders + retrievers + fusion) are fast (~50ms). The fourth stage (agent) is slow (~10s) but only runs on triage-positive windows (~22% of all windows in our dataset).

### 7.1 What each piece contributes

| Stage | Question it answers | Marginal contribution |
|---|---|---|
| LogSeq2Vec | "What's in the logs beyond the characteristic line?" | Richer retrieval query; better novelty detection |
| Triage head | "Is this even worth investigating?" | Filters 78% of windows so the agent doesn't waste compute |
| SPLADE | "Sparse retrieval improved over BM25" | +5-10% Hit@5 on exact-term matches |
| BiEncoder | "Semantic retrieval" | +10-15% Hit@5 on paraphrased matches |
| Graph | "Symbolic retrieval" | +5-10% Hit@5 on rare-combination matches; interpretability |
| RRF | "Robust fusion" | +5% Hit@5 over any single retriever |
| Agent | "Reasoning + novelty detection" | +10-20% Hit@1 by rejecting wrong-top-1 candidates; solves cold-start |

Stacked, we should reasonably target **Hit@1 ≥ 0.35** and **Hit@5 ≥ 0.45** vs the current Phase G best of 0.177 / 0.233.

---

## 8. Prioritized roadmap

If we have N weeks to ship the strongest paper:

### Week 1 — Foundations
- **Day 1-2:** Proposal A (re-split). Re-run all existing pipelines on the new split. This is the cheapest big-impact change.
- **Day 3-5:** Proposal C (SPLADE + RRF). Replaces BM25 in MemoryGraph SOTA. Bonus: same data prep work as for BiEncoder, so very fast to ship.

### Week 2 — Knowledge graph
- **Day 1-3:** Proposal D (LLM-extracted knowledge graph). Includes prompt design, extraction run, in-memory NetworkX graph, query engine, integration as a retriever.
- **Day 4-5:** Re-run comparison with the three-way RRF including the graph retriever.

### Week 3 — Log sequence encoder
- **Day 1-2:** Implement `LogSeq2Vec` architecture; data prep.
- **Day 2-4:** Pretrain on 50M lines (asynchronous; runs overnight on GPU).
- **Day 5:** Fine-tune + integrate as a retriever / triage feature.

### Week 4 — Agent
- **Day 1-3:** Build `DiagnosisAgent`: tools, prompts, loop, few-shot examples.
- **Day 4:** Run on test set.
- **Day 5:** Analysis + paper writing.

If only 1 week available: Proposal A + Proposal D (re-split + knowledge graph). These give the biggest immediate uplift.

If only 3 days available: Proposal A alone. The re-split change might be worth several Hit@K points by itself.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LogSeq2Vec MLM pretraining diverges | Use LogBERT as starting checkpoint; small dataset means fewer epochs needed |
| SPLADE doesn't beat BiEncoder on our corpus | RRF fusion still helps even if SPLADE alone is worse; sparse retrieval shines on exact-term matches that dense misses |
| LLM-extracted graph is noisy | Use Claude Opus or GPT-4o (high-precision extractors); compare LLM-extracted entities against the gold scenario_family labels as a sanity check |
| Agent is too slow even for paper experiments | Run on a 500-window sub-sample; report agent metrics separately |
| Re-split makes our depth-scaling story disappear | The depth scaling is about how many compatible prior tickets exist at predict time — it does NOT depend on split direction. We checked: the depth axis is well-populated under either split scheme |
| Paper scope creep | Each proposal is independently shippable. If time pressures, drop later proposals; the paper still benefits from the earlier ones |

---

## 10. My recommendation

Implement, in this order:

1. **Proposal A** (re-split) — biggest reward-to-effort ratio. Half a day, possibly 5-10% Hit@K improvement just from the more realistic split.

2. **Proposal D** (LLM knowledge graph) — directly responds to your interest in Neo4j Document Intelligence, gives the paper a novel interpretable-AI angle, and is feasible in 3 days.

3. **Proposal C** (SPLADE + RRF) — modernizes the retrieval stack and gives a clean ablation story.

4. **Proposal B** (LogSeq2Vec) — most engineering work; biggest potential lift but also biggest risk. Defer to the second iteration if time-constrained.

5. **Proposal E** (agentic reasoning) — beautiful capstone; should only be attempted once 1-4 are solid.

A version of the paper with just Proposals A + D + C would already be a substantially stronger ICSE submission than what we have today. Adding B would put it in "best paper candidate" territory.

Let me know which proposal(s) you want me to start building first.
