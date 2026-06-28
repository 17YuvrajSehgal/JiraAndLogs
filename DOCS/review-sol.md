# ICSE Review — Solution Plan

*How each limitation in [`review.md`](review.md) will be addressed before the
deadline (2 days, no new data collection). Written 2026-06-28.*

> **STATUS (2026-06-28): COMPLETE.** Every gap below was addressed and the
> results are in [`paper-results/`](../paper-results/README.md) (see each
> category's `SUMMARY.md`). Full provenance: [`collection-log.md`](collection-log.md).
> One implementation change from the plan: the LLM ran via **transformers**
> (offline, cached weights), **not vLLM** — vLLM isn't installed and would have
> conflicted with the `transformers` version the cascade BiEncoder pins, so it
> was avoided. Qwen2.5-7B loaded fine and finished each subset in minutes.

Decisions taken with the author:
- **LLM for RAG-baseline + LLM-as-judge:** `Qwen2.5-7B-Instruct`, served
  **offline via the `transformers` library on one H100** (Apache-2.0, fits a
  single GPU, fast; cached weights, `HF_HUB_OFFLINE=1`). *(Plan originally said
  vLLM; switched to transformers — see status banner.)*
- **Gold validation:** lean on **LLM-as-judge** (no multi-annotator human study
  this cycle); ship a human-annotation kit for an optional later κ.
- **No new datasets.** Everything runs on the three existing global dirs.

---

## Clean, publishable results directory: `paper-results/`

All fresh results go into a **new top-level `paper-results/` directory** —
nothing is written into `data/` or the old (gitignored) `results/`. It is
self-contained and intended to ship with the repository.

```
paper-results/
  README.md                  # master index + how to reproduce
  provenance/                # git SHA, env (venv-freeze), seeds, configs, LLM prompts
  retrieval-cascades/        # per-pipeline retrieval panel (Hit@1/5/10, MRR, CIs)
    online-boutique/  otel-demo/  wol-v3/   SUMMARY.md
  baselines/                 # NEW: vs prior art + LLM-RAG
    sota-dense/  cross-encoder-rerank/  tfidf/  llm-rag/   SUMMARY.md
  agent-end-to-end/          # full agent: Hit@K, triage acc, novelty, pages/incident
    online-boutique/  otel-demo/  wol-v3/   SUMMARY.md
  agent-value/               # what the agent ADDS: cost@iso-accuracy, skill/tool ablations
  kg-usefulness/             # is the KG helpful: ±graph ablation, complementarity, expl. judge
  robustness/                # multi-seed variance, multiple-comparison correction, negative-results
  gold-validation/           # LLM-as-judge relevance + human-annotation kit (+ κ if done)
```

**Rules:** one leaf dir per (category × dataset); every leaf has the raw
`*-predictions.jsonl` + a `*-results.json`; every category has a `SUMMARY.md`;
every run drops a provenance stub (git SHA + seed + config) so the directory is
fully traceable. `paper-results/` is **not** gitignored.

---

## Per-gap solution

### Gap #1 — Prior-art baselines  → `paper-results/baselines/`
Add published, widely-used baselines, run on all three datasets with the same
visibility/gold contract as our pipelines:
- **SOTA dense retrievers, zero-shot:** `BAAI/bge-large-en-v1.5`,
  `intfloat/e5-large-v2`, `sentence-transformers/all-mpnet-base-v2`.
- **Cross-encoder reranker (published MS-MARCO):**
  `cross-encoder/ms-marco-MiniLM-L-6-v2` over the dense top-k.
- **Classic IR:** TF-IDF + cosine (and BM25, which we already have).
- *Honest scope:* these are strong general-retrieval baselines, not a
  domain-specific triage method; documented as such.

### Gap #2 — LLM-RAG baseline  → `paper-results/baselines/llm-rag/`
vLLM serves Qwen2.5-7B-Instruct on the H100. For each window: retrieve top-k
candidate tickets (dense), prompt the LLM to select/rank the matching ticket;
score Hit@1/5 + MRR. Run on a **500–1000-window subset per dataset** (standard
for LLM baselines; documented). Prompts saved under `provenance/`.

### Gap #3 — Synthetic-only agentic validation  → partial + framing
Cannot add real telemetry (no new data). Mitigations:
- **Run controller capabilities on WoL real data**: page-suppression over the
  **2,456 real multi-incident clusters** and the cost-savings/gating analysis →
  these validate the *agentic controller* on real data, not just synthetic.
- Draft an honest **threats-to-validity + scoped-claims** section (markdown for
  the author to paste). Telemetry *diagnosis* + ReAct evidence tools remain
  synthetic-only — stated explicitly.

### Gap #4 — Gold validation  → `paper-results/gold-validation/`
- **LLM-as-judge:** sample windows, present (window, gold ticket); the judge
  rates relevance; report judge–gold agreement + a calibration on a tiny
  hand-checked seed. Stopgap for a full human study.
- **Human-annotation kit:** sampled windows + candidate tickets + rubric + a κ
  computation script, ready if annotators become available.

### Gap #5 — Isolate the agent's marginal value  → `paper-results/agent-value/`
Using existing tooling (`agent_cost_savings.py`, `cost_vs_cascade.py`,
`budget_curve.py`, `skill_ablation.py`, `tool_ablation.py`):
- **agent vs always-run-everything at iso-accuracy** (cost/latency + CIs).
- Skill and ReAct-tool ablations; budget curve.

### KG usefulness (explicit, requested)  → `paper-results/kg-usefulness/`
Three angles so the KG's value is shown, not assumed:
1. **±graph ablation:** Hybrid-RRF **with vs without** the KG retriever (add a
   `--skip-graph` flag to the run script); report Δ Hit@K with paired-bootstrap
   CIs per dataset. Shows the KG's *marginal* contribution in fusion.
2. **Complementarity:** fraction of windows where the graph retriever supplies a
   *correct* candidate that dense+sparse missed (unique-hit analysis).
3. **Explanation utility:** LLM-as-judge rates the `memorygraph`
   path-based explanations for plausibility/usefulness.

### Lower-priority  → `paper-results/robustness/`
- **Multi-seed BiEncoder** (seeds 42/1/2): mean ± std (trivial for OB/OTel;
  parallelized for WoL v3).
- **Multiple-comparison correction** (Benjamini–Hochberg) over the RQ bootstrap
  tests.
- **Negative-results analysis**: when/why cross-corpus (Hit@5≈0.05) and
  KG-alone (Hit@5≈0.28) fail.

---

## Obstacles / honest limits
- **48h compute vs scale.** WoL v3 is the bottleneck (~9h/hybrid run; slow
  per-window graph scoring). Fits only with parallel GPU jobs + defensible
  subsampling (LLM-RAG, WoL seed-variance). Not exhaustive-at-full-scale.
- **Gap #3 is not fully closable** without real telemetry; outcome is
  scoping + partial real-data controller validation.
- **No human κ this cycle** (LLM-as-judge instead), by decision.
- **Paper draft not in repo** — deliverables are results + tooling + drafted
  markdown sections; the author pastes into the `.tex`.

## Execution order
1. SOTA + classic baselines (#1) — started first, no decisions needed.
2. Agent value + ablations (#5).
3. LLM-RAG via vLLM (#2) + LLM-as-judge gold (#4).
4. KG-usefulness ablation + complementarity (+ explanation judge).
5. Multi-seed + multiple-comparison + negative-results (robustness).
6. Aggregate every category SUMMARY + `paper-results/README.md` + provenance.
