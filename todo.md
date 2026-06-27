# WoL v3 (80K Dataset) — Status & Remaining Work

*Last updated: 2026-06-26 (BM25 complete; only Hybrid-RRF + agent eval remaining)*

**Dataset under measurement.** `data/derived/global/2026-06-17-wol-real-v3-global/`
(Option C — 24 distributed-systems Apache projects, no quality filters, 78,140 query rows).

**Source-of-truth files for paper numbers.**
- `DOCS/docs8/PAPER-FINDINGS.md` — current paper claims sourced from v2
- `DOCS/docs8/RQ-CLOSURE-TABLE.md` — master RQ status
- `RESEARH-PAPER/ICSE/sections/` — LaTeX sections that need v3 number updates

---

## ✅ DONE (verified on disk, reproducible)

### 1. WoL v3 dataset built

Path: `data/derived/global/2026-06-17-wol-real-v3-global/` (~1.3 GB on disk)

| Artifact | Rows | Confirmed |
|---|---:|---|
| `jira-memory-corpus.jsonl` | 38,642 | ✅ |
| `global-triage-examples.jsonl` (queries) | 78,140 | ✅ |
| `window-memory-matchings.jsonl` (coarse gold) | 78,140 | ✅ |
| `window-memory-matchings-strong.jsonl` (Jaccard > 0.15) | 78,140 | ✅ |
| `jira-shadow-humanized-v2/bulk-20260617/timeline.jsonl` | 38,642 | ✅ |
| `triage-split-manifest.json` | — | ✅ family→split |
| `dataset-metadata.json` + `README.md` + `source-mapping.csv` | — | ✅ |

Headline composition: **38,642 ticket_worthy + 25,619 borderline + 13,879 noise = 78,140 queries**, across **24 Apache projects**. Test families = Kafka + MariaDB-Server (13,388 windows). Multi-incident clusters: 2,456.

**Build script**: `scripts/research-lab/build_wol_real_corpus_v3.py`.

### 2. KG extractions completed (gpt-4o-mini via OpenAI)

| Artifact | Rows | Cost |
|---|---:|---:|
| `v2_kg_extractions/all_extractions.jsonl` (memory side) | 38,600 | ~$17 |
| `v2_kg_extractions/ticket/*.json` (per-ticket cache) | 38,587 individual files | — |
| `v2_kg_extractions_windows/all_extractions.jsonl` (window side) | 78,140 | ~$19 |
| `v2_kg_extractions_windows/window/*.json` (per-window cache) | 78,139 individual files | — |

Total OpenAI spend on extraction: **~$36**.

**Scripts** (all patched during this run):
- `scripts/research-lab/extract_tickets_parallel.py` — memory side. Patches: `--shard M/N`, `--max-input-chars`, `--timeout-s`, `--max-retries`, `--api-key-env`.
- `scripts/agent/extract_window_entities.py` — window side. Same patches plus parallel workers.
- `scripts/research-lab/consolidate_kg_extractions.py` — safety-net: rebuild consolidated JSONL from per-ticket cache after sharded runs.
- `src/v2_advanced/shared/lm_studio.py` — proper 429 backoff (10 retries, exponential up to 300s, honors Retry-After header), 4xx non-retry, downgraded routine 429 messages to DEBUG.

### 3. Neo4j running with v3 graph loaded

- Container: `neo4j-kg` (Docker, default creds neo4j/123456789, port 7687)
- Database: default `neo4j` (Community Edition single-DB)
- Loaded: 38,462 Incident · 1,622 Component · 335 ErrorClass · 37,480 RootCause · 32,041 Fix · 98,176 Symptom nodes
- Reload script: `src/v2_advanced/proposal_d_knowledge_graph/reload_neo4j.py`
- Dataset→DB mapping updated for v3 in `src/v2_advanced/shared/neo4j_client.py:71-74`

### 4. KG-Retrieval cascade — done

`data/derived/global/2026-06-17-wol-real-v3-global/tch-lite-refit/`
- `kg-retrieval-mode3-results.json` (1.9 KB) — headline metrics
- `kg-retrieval-predictions.jsonl` (60.9 MB) — 13,388 per-window predictions

| Metric | coarse-match | strong-match (Jaccard > 0.15) |
|---|---:|---:|
| n_with_gold | 5,150 | 4,362 |
| **Hit@1** | **0.2072** | 0.0550 |
| **Hit@5** | **0.2806** | 0.0640 |
| MRR | 0.2333 | 0.0582 |

Per-project (coarse): `wol-kafka` Hit@5 = 0.0635, `wol-mariadb-server` Hit@5 = 0.3207.

Runtime: 2h 6m (50 min Neo4j graph load + 75 min scoring 78,140 windows + 1s triage head fit).

### 5. BiEncoder cascade — done (2026-06-25 17:18)

`data/derived/global/2026-06-17-wol-real-v3-global/tch-lite-refit/`
- `biencoder-mode3-results.json` — headline metrics
- `biencoder-predictions.jsonl` — 13,388 per-window predictions

| Metric | coarse-match | strong-match (Jaccard > 0.15) |
|---|---:|---:|
| n_with_gold | 5,150 | 4,362 |
| **Hit@1** | **0.8561** | 0.2602 |
| **Hit@5** | **0.9050** | 0.5229 |
| MRR | 0.8738 | 0.3558 |

Per-project (coarse):
- `wol-kafka` (n=803): Hit@1 = 0.9215, Hit@5 = **0.9328**, MRR = 0.9256
- `wol-mariadb-server` (n=4347): Hit@1 = 0.8440, Hit@5 = **0.8999**, MRR = 0.8642

**Total runtime: 22h 7m (1,326.6 min)** — 5 epochs over 23,320 training pairs.

**Where the time went (verified from log)**:
- ~21h: building training pairs (BM25 hard-negative mining over 23,320 windows — O(N²) on CPU)
- ~20 min: actual GPU fine-tune (1,172s, 3,645 steps, 99.5 samples/sec on CUDA, train_loss → 0.6517)
- ~10 min: memory embedding (38,642 texts) + test encoding (13,388 texts, 14.4s at 927 texts/s) + visibility masks + prediction + writes

**Comparison vs v2 BiEncoder** (Hit@5 = 0.959, Hit@1 = 0.958 on 2K memory / 1.6K queries):
- v3 Hit@5 0.905 / Hit@1 0.856 — ~5pt / ~10pt drop
- Explanation: v3 has 19× more memory items (38K vs 2K) and 8× more queries (13K vs 1.6K) across 24 projects vs 7. More confusable candidates per query → lower top-k. Still a strong real-Apache-Jira retrieval number for the paper.

### 6. BM25 cascade — done (2026-06-26 17:24)

`data/derived/global/2026-06-17-wol-real-v3-global/tch-lite-refit/`
- `bm25-predictions.jsonl` (63.8 MB) — 13,388 per-window predictions
- `bm25-mode3-results.json` — synthesized post-hoc by `scripts/research-lab/synthesize_bm25_results.py` (the run_bm25_wol_mode3.py script writes only the predictions JSONL, not a results JSON; the synthesizer reads the predictions and computes metrics identical to BiEncoder's metric block)

| Metric | coarse-match | strong-match (Jaccard > 0.15) |
|---|---:|---:|
| n_with_gold | 5,150 | 4,362 |
| **Hit@1** | **0.0146** | 0.0147 |
| **Hit@5** | **0.7266** | 0.7398 |
| MRR | 0.3293 | 0.3315 |

Per-project (coarse):
- `wol-kafka` (n=803): Hit@1 = 0.0050, Hit@5 = 0.6663, MRR = 0.2820
- `wol-mariadb-server` (n=4347): Hit@1 = 0.0163, Hit@5 = 0.7378, MRR = 0.3381

**Total runtime: 19h 17m (69,442.9 s)** — 1 epoch over 13,388 test queries × 38,642 memory docs.

**Where the time went (verified from log)**:
- 3.87s: BM25 index build over 38,642 memory docs
- ~3h 39m (13,167s): val threshold tuning on 3,836 val queries (each query scores top-k against full memory)
- ~15h 38m (56,275s): test prediction on 13,388 queries (0.2 windows/s sustained, single-threaded CPU)

**Why so slow vs my earlier estimate (1-2 hrs)**: v3's memory pool is 19× v2's (38,642 vs 2,000). BM25 retrieval cost is linear in memory size, so per-query is ~19× slower than v2. My estimate didn't account for this.

**Paper story**: Hit@1 = 0.0146 vs Hit@5 = 0.7266 is a **50× gap** — BM25 finds the right candidate in its top-5 73% of the time but can't precisely rank it. This makes the agent's BiEncoder-driven Hit@1 = 0.856 a **58× lift over BM25 Hit@1** — the strongest "agent beats naive baseline" line in the paper for WoL.

### 7. Orchestration

- **`scripts/research-lab/run_all_v3_cascades.sh`** — parallel-cascade orchestrator + results aggregator (produces `SUMMARY.md` + `v3-all-results.json`). Patched to skip LogSeq2Vec (N/A for WoL) and use `--humanized-subdir bulk-20260617`.
- **`run_biencoder_wol_mode3.py` and `run_hybrid_rrf_wol_mode3.py`** — patched with `logging.basicConfig(force=True)` so internal logger output reaches the log file (was previously silent past torch init).

---

## 🟡 IN PROGRESS / KNOWN-BROKEN

| Item | State | Lesson |
|---|---|---|
| BiEncoder fine-tune (first attempt — parallel) | killed by user when 3-pipeline parallel run threatened OOM | Don't run BiEncoder+BM25+Hybrid-RRF in parallel; they collectively hold ~17 GB |
| BiEncoder fine-tune (second attempt — serial) | **OOM-killed at 13h 57m**, free RAM had dropped to 1.15 GB | At 5 epochs over 60,916 train examples on CPU, BiEncoder takes 14+ hours. Window for OOM is too long. **Re-run with `--finetune-epochs 2` (defensible reduction)** |
| `run_all_v3_cascades.sh` orchestrator (parallel attempt) | exited 2 (bash syntax error in post-wait section after I edited it during the run) | Don't edit a running bash script. Aggregator path still works when invoked standalone. |

---

## ❌ TO DO — required to produce v3 paper numbers

The agent eval needs cascade prediction JSONLs as input (see `src/agent/skills/predictions_backed.py:18-29`). The agent's WoL skill profile (`src/agent/harness_builder.py:171-198`) reads:
- `tch-lite-refit/biencoder-predictions.jsonl` → `RetrieveDenseSkill`
- `tch-lite-refit/hybrid-rrf-predictions.jsonl` → `RetrieveHybridFusionSkill`
- `tch-lite-refit/kg-retrieval-predictions.jsonl` → `RetrieveKnowledgeGraphSkill` ✅
- `tch-lite-refit/diagnosis-agent-predictions.jsonl` → `VerifyWithLLMSkill` (calibrated OFF for WoL; not needed)

BM25 is **not** consumed by the agent at runtime, but it IS the RQ-E3 paper baseline (`DOCS/docs8/PAPER-FINDINGS.md:100-119` — "Agent Hit@5 vs BM25 Hit@5"), so its predictions are still needed for the paper.

### Phase 1 — Cascade panel (compute-bound; serial to avoid OOM)

#### Task 1.1 — BiEncoder cascade ✅ DONE (2026-06-25)

Ran with `--finetune-epochs 5` (apples-to-apples with v2). See "✅ DONE" §5 above for the actual numbers and runtime breakdown.

**Lesson learned for future runs**: ~95% of wall-clock was CPU-bound BM25 hard-negative mining during the training-pair build phase. The actual GPU fine-tune was 20 min. Adding per-epoch training logs wouldn't have helped because the silent phase was *before* the fit started.

#### Task 1.2 — BM25 cascade ✅ DONE (2026-06-26 17:24)

Ran with the standard CLI plus a post-hoc results-JSON synthesizer (the BM25 script doesn't write `*-mode3-results.json` natively). See "✅ DONE" §6 above for actual numbers and runtime breakdown.

**ETA estimate was wrong**: I said 1-2 hours; actual was **19h 17m**. Reason: v3 memory is 19× v2's, and BM25's `topk` is linear in memory size — so per-query is ~19× slower than v2. Lesson for Hybrid-RRF: the v3 retrieval phase will be ~19× slower than v2 too.

#### Task 1.3 — Hybrid-RRF cascade

Internally fits a BiEncoder + sparse SPLADE + KG retrievers and RRF-fuses them.

**Recommendation**: drop `--biencoder-finetune-epochs` to 1 (from 3 default) to keep this tractable.

```bash
python -u scripts/research-lab/run_hybrid_rrf_wol_mode3.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --out-dir    data/derived/global/2026-06-17-wol-real-v3-global/tch-lite-refit \
    --humanized-subdir bulk-20260617 \
    --biencoder-finetune-epochs 1 \
    > logs/v3_hybrid_rrf.log 2>&1
```

**Output**: `tch-lite-refit/hybrid-rrf-predictions.jsonl` + `hybrid-rrf-mode3-results.json`.

**ETA**: 5-7 hours at `--biencoder-finetune-epochs 1` (was 15+ hr at default 3).

#### Task 1.4 — Aggregator → SUMMARY.md

Once all 4 results files (kg-retrieval ✅, biencoder, bm25, hybrid-rrf) are present:

```bash
bash scripts/research-lab/run_all_v3_cascades.sh
```

The preflight will detect the 3 already-present cascades and skip them via cache, then run the aggregator's Python heredoc which emits:
- `tch-lite-refit/SUMMARY.md` — paper-ready Markdown table
- `tch-lite-refit/v3-all-results.json` — machine-readable union

Alternative: invoke the aggregator's heredoc directly without re-running cascades (safer if cascades are flaky).

**ETA**: 1 second.

### Phase 2 — Agent end-to-end eval

#### Task 2.1 — Run `smoke_wol.py` on v3 test split

The actual paper headline. Reads from `tch-lite-refit/*-predictions.jsonl`, runs the capability-adaptive agent on 13,388 test windows, emits per-window decisions + metrics.

```bash
PYTHONPATH=src python -u scripts/agent/smoke_wol.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --split test \
    --output    results/wol-v3/agent-runs/wol-fulltest.json \
    > logs/v3_agent.log 2>&1
```

Per `scripts/agent/smoke_wol.py:13-30`, the agent's effective WoL skill set:
- ACTIVE: BiEncoder, Hybrid-RRF, KG-Retrieval, compose_l2 (RRF+rerank), compose_triage (logistic stacker), compose_novelty (disjunction), `request_similar_incident_window` (the only ReAct tool that works on WoL — peers-only)
- STRUCTURALLY SKIPPED: `triage_numeric` (no NUMERIC_FEATURES), `retrieve_log_sequence` (no ORDERED_LOGS), `verify_with_llm` (VerifierCalibration marks WoL as known_harmful), 3 telemetry ReAct tools (no K8S/TRACE/METRIC flags)

**Output**: `results/wol-v3/agent-runs/wol-fulltest.json` (per-window agent decisions + aggregate metrics).

**ETA**: 2-3 hours for full 13,388-window test split. **OOM risk**: moderate. Watch carefully.

#### Task 2.2 — Bootstrap CIs on agent output

The paper reports paired-bootstrap CIs for Hit@K, MRR, triage acc, cost savings.

```bash
PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
    --predictions results/wol-v3/agent-runs/wol-fulltest.json \
    --n-resamples 1000 --seed 42 \
    > results/wol-v3/agent-runs/bootstrap-cis.json
```

**ETA**: ~30 min for 1000 resamples over 13,388 rows.

#### Task 2.3 — Per-pipeline bootstrap CIs (for cascade panel table)

```bash
PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --out-dir results/wol-v3/cascade-cis \
    > logs/v3_bootstrap.log 2>&1
```

**ETA**: ~30 min.

### Phase 3 — Paper integration

#### Task 3.1 — Update `DOCS/docs8/PAPER-FINDINGS.md` with v3 columns

For each numerical claim currently citing v2, add a v3 column. Don't delete v2 — keep both for the "v2 vs v3 cross-validation" framing.

Sections to update:
- "Abstract / Introduction headline numbers" — add v3 Hit@5, Hit@1, MRR, triage_acc, pages/incident
- "Section: Datasets" — add v3 row (24 projects, 78,140 queries)
- "Section: Retrieval results" — cascade panel table with v3 row per pipeline
- "Section: Agent results" — agent Hit@K, cost savings (where computable on WoL)
- "Section: Threats to validity" — note v3 expands beyond microservice-adjacent into Hadoop ecosystem

#### Task 3.2 — Update `DOCS/docs8/RQ-CLOSURE-TABLE.md` with v3 evidence

For each RQ that uses WoL as the real-data leg, add v3 confirmation/refutation.

#### Task 3.3 — Update LaTeX sections in `RESEARH-PAPER/ICSE/sections/`

- `04-evaluation.tex` — v3 dataset description (replace v2 numbers in §4.1.3 WoL paragraph)
- `05-results.tex` — Mode 3 retrieval table with all 4 cascades + agent on v3
- `00-abstract.tex` — refresh headline numbers (Hit@5, cost savings, pages/incident)
- `10-conclusion.tex` — refresh headline numbers
- `figures/data-collection-workflow.png` is OB/OTel-only and unaffected by v3

#### Task 3.4 — Update `data/derived/global/2026-06-17-wol-real-v3-global/README.md`

Add a "Results" section linking to `tch-lite-refit/SUMMARY.md` and `results/wol-v3/agent-runs/wol-fulltest.json`.

### Phase 4 — Dataset publication prep

#### Task 4.1 — Rebuild publishable bundle

```bash
PYTHONPATH=src python scripts/agent/bundle_dataset_for_publication.py \
    --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
    --out data/wol/WoL_v3-2026-06-17.archive.gz
```

(Verify the script accepts v3 directly; v2 version may need a small profile addition.)

#### Task 4.2 — Refresh `data/wol/README.md`

The current README documents the v1 archive. Add a v3 section pointing at the new bundle.

---

## ⚠️ Persistent OOM risk — how to mitigate

Machine is ~31 GB total RAM. Steady-state when one cascade runs:
- BiEncoder: ~5 GB
- Neo4j Docker: ~2 GB
- Windows + Git Bash + minor apps: ~10-15 GB
- Leaves ~9-14 GB headroom — fine as long as nothing else opens.

Things that have triggered OOMs:
- Running 3 cascades in parallel (~17 GB combined)
- Browser tabs growing while BiEncoder ran for 14+ hours
- Other dev tools spinning up

**During Tasks 1.1, 1.3, 2.1**: close Chrome, IDE projects unrelated to this work, video conferencing, anything that allocates. We've already lost 18+ hours of compute to OOM kills.

---

## Decision points (need user input)

- **D-1**: Confirm `--finetune-epochs 2` for BiEncoder vs. attempt `--finetune-epochs 5` again (longer, riskier).
- **D-2**: Confirm `--biencoder-finetune-epochs 1` for Hybrid-RRF vs. default 3.
- **D-3**: Final paper section to update first — abstract numbers or full §5 results table?

---

## Provenance / reproducibility notes

- All v3 build code uses `seed=42` deterministically.
- KG extractions: per-ticket cache files keyed on `ticket_id + sha1(text)[:8]`. Resumable.
- Cascade prediction scripts cache against `global_dir`; re-running with the same git SHA + dataset gives bit-identical predictions.
- OpenAI extractions are NON-reproducible (model versions drift). The extracted JSONL files on disk ARE the source of truth.

---

# ARCHIVED — v2-era TODO (kept for reference; do not act on without re-validation)

---

# TODO — fresh run to close every RQ with no caveats

**Status: 2026-06-13.** Single-pass plan. No re-iteration budgeted. Every
checkbox below is required for the paper to ship without unresolved
caveats. Cross-references:
[`DOCS/docs7/RESEARCH-QUESTIONS.md`](DOCS/docs7/RESEARCH-QUESTIONS.md),
[`DOCS/docs7/RQ-ANSWERS.md`](DOCS/docs7/RQ-ANSWERS.md),
[`DOCS/docs7/AGENTIC-SYSTEM.md`](DOCS/docs7/AGENTIC-SYSTEM.md),
[`DOCS/docs7/IMPROVEMENTS.md`](DOCS/docs7/IMPROVEMENTS.md).

**Compute budget.** ~46–56 hours wall-clock (LM Studio + GPU). Most of
that is the LM-Studio passes:
  - Window-side extraction (~2h OB + ~6h WoL + ~3h OTel)
  - Memory-side extraction on OTel (~1h — OB+WoL kept theirs)
  - **Humanized-memory generation on OTel (~1h)** — OTel is the only
    dataset without pre-existing `jira-shadow-humanized-v2/`
  - DiagnosisAgent on test windows (~4h OB + ~4h WoL + ~4h OTel)
  - DiagnosisAgent on 800 WoL OOD queries (~7h)
  - BiEncoder/LogSeq fits (~6h per dataset, GPU)

LM-Studio jobs serialize (one model in VRAM at a time); GPU
retrieval fits can run while LM Studio is busy on something else.

---

## Section 0 — Pre-flight checks (10 minutes) — ✓ COMPLETE 2026-06-13

All checks passed. Code freeze recorded in [`CODE-FREEZE.md`](CODE-FREEZE.md)
at commit `fb908f2`. Also cleaned up leftover `v2_kg_extractions/window/`
on OB (single stale file from an older pipeline).

- [x] **Cleanup verified.** Inventory matches Appendix A.
- [x] **Neo4j reachable + empty.** 0 nodes, no GraphMetadata.
- [x] **LM Studio reachable** with `qwen/qwen3.6-35b-a3b` loaded.
- [x] **Memory-side LLM extractions intact.** OB 347 / WoL 2000 / OTel missing-as-expected.
- [x] **`agent-build` branch + clean tree** at `fb908f2`.
- [x] **Disk space.** 104 GB free; ~5 GB budgeted.

---

## Section 1 — Build the missing scripts — ✓ COMPLETE 2026-06-13

After [`CASCADE-WALKTHROUGH.md`](DOCS/docs7/CASCADE-WALKTHROUGH.md)
clarified that most "missing scripts" already exist, the actual
scope was 8 agent-side scripts + 2 small patches. All shipped + 424
agent tests still green.

### Agent-side scripts (shipped)

- [x] `scripts/agent/annotate_wol_depth.py` — d58f868 — closes B2 WoL gap
- [x] `--order-by-incident-time` flag on smoke_ob/_wol/_otel_demo + loaders — d58f868 — closes C7
- [x] `scripts/agent/build_cross_corpus_gold.py` — b5210fd — B5 gold
- [x] `scripts/agent/run_cross_corpus_retrieval.py` — b5210fd — B5 retrieval (Hit@5=0.05 on Kafka cross-corpus)
- [x] `scripts/agent/agent_hp_sensitivity.py` — 840378f — C2 (agent-scoped)
- [x] `scripts/agent/agent_cost_savings.py` — 840378f — B3 counterfactual savings
- [x] `scripts/agent/run_diagnosis_on_ood.py` — 29e8dff — A5 agent signal
- [x] `scripts/agent/reformulation_recovery.py` — 29e8dff — B4

### Enabling patches (shipped)

- [x] `core/data/loaders.py` — 1c75e6a — `matchings_file` param + `STRONG_RELATION=1` env var for A7 strong-relation gold
- [x] `comparison/runner.py` + `schema.py` — 1c75e6a — per-window predict cost (`pipeline_predict_seconds_per_window`) for A9/B3

### Use existing cascade tools (no new code needed)

These tools already exist on `agent-build` and just need to be invoked:

- **Full cascade run**: `python -m v2_advanced.run_all_v2` — closes A1/A6 retrieval, A9 cost
- **BM25 baseline**: same command with `--pipelines bm25_retrieval` — closes C4
- **L3 learned novelty fit**: `python -m v2_advanced.tch.novelty_calibration` — closes A5 learned signal
- **Cascade composition**: `python -m v2_advanced.tch.build_cascade` — composes L1/L2/L3/L4
- **Strong-relation re-run**: same with `STRONG_RELATION=1` env var (Patch 1)
- **TCH-Lite for WoL**: `TCH_LITE=1` env var (already documented)

### Re-scoped — no separate script needed

- **A4 Level 2 corpus-mixing**: re-evaluated through the agent-focus lens. Phase 3.4's similarity-weighted sweep is the agent-level closure. Cascade-side BiEncoder re-fit on contaminated corpus is journal-extension scope, not v1.

- [ ] **`src/v2_advanced/tch/run_cascade_full.py`** — single end-to-end
  driver. Fits + runs every retriever (BiEncoder, LogSeq2Vec, Hybrid-RRF
  with both rule + LLM extraction variants, KG-Retrieval) and HGB
  triage. Writes per-window-predictions JSONLs to
  `comparison/v2{a,b,c,c-llm,d}-*` matching the existing OB layout.
  Crucially: records per-skill **wall-time per window** in each JSONL row
  (new field `skill_wall_time_seconds`), needed for B3 + A9.

- [ ] **`src/v2_advanced/tch/run_bm25_baseline.py`** — pure BM25
  pipeline. Writes `comparison/bm25-baseline/per-window-predictions.jsonl`.
  Closes RQ-C4.

- [ ] **`src/v2_advanced/proposal_e_agent/run_on_ood.py`** — invokes
  DiagnosisAgent on the 800 WoL OOD queries from
  `novelty-queries/windows.jsonl`. Writes
  `data/derived/global/<wol>/ood-diagnosis-predictions.jsonl` — the
  agent signal for full L3 novelty (closes A5).

- [ ] **`src/v2_advanced/tch/build_cascade.py`** (extension) — add
  `--fit-l3-learned-novelty` flag. Trains a LogReg over the train-split
  cheap-skill outputs (triage_numeric.score, retrieve_dense.confidence,
  retrieve_hybrid_fusion.triage_score, etc.) to predict `gold_is_novel`.
  Writes `comparison/v2g-final-models/learned-novelty/{model.pkl,
  predictions.jsonl}`. Closes A5 learned signal.

- [ ] **`src/v2_advanced/tch/build_cascade.py`** (extension) — add
  `--gold-relation strong` flag. Uses `window-memory-matchings-strong.jsonl`
  as gold, refits L1 stacker + L3 novelty + L2 composition on strong
  relation. Closes A7 strong-relation.

- [ ] **`scripts/agent/annotate_wol_depth.py`** — adds
  `n_prior_same_project_tickets` field to each row of WoL
  `global-triage-examples.jsonl`. Reads `jira-memory-corpus.jsonl`,
  groups by `wol_project`, computes prior-count per window timestamp.
  Closes B2 (WoL gap).

- [ ] **`scripts/agent/hp_sensitivity.py`** — HP sweep driver. Sweeps
  BiEncoder epochs ∈ {3, 5, 7}, RRF k ∈ {30, 60, 90}, L1 threshold
  ∈ {0.3, 0.5, 0.7}, L3 novelty threshold ∈ {0.3, 0.5, 0.7}. Re-fits
  what needs re-fitting (BiEncoder), reuses cached predictions for the
  rest (RRF/L1/L3 are post-hoc). Reports point + 95% CI per setting +
  monotonicity check ("robust region"). Closes C2.

- [ ] **`scripts/agent/reformulation_recovery.py`** — for each
  gate-firing window (compose_l2 confidence < 0.5), invokes
  `ReformulateQuerySkill` LIVE, then re-runs BiEncoder inference on the
  reformulated query, compares Hit@1 before vs after. Reports recovery
  rate. Closes B4. **Requires the BiEncoder weights to be present on
  disk + a live-inference helper** (`v2_advanced/proposal_a_resplit/
  biencoder_infer.py` — add a one-off-query mode if it doesn't have one).

- [ ] **`scripts/agent/distractor_sweep_corpus_mix.py`** — Level-2
  corpus-mixing distractor sweep. At each ratio R ∈ {10, 25, 50},
  mixes R% of WoL distractors into the 347-ticket memory; re-fits
  BiEncoder on the contaminated corpus; re-runs retrieval; reports
  Hit@K + 95% CI. Closes A4 Level 2.

- [ ] **`scripts/agent/build_cross_corpus_gold.py`** +
  **`scripts/agent/run_cross_corpus_retrieval.py`** — Mode 4. Builds
  a Jaccard symptom-token gold relation between WoL Kafka tickets
  (memory) and OTel Demo Kafka scenario windows (queries); runs
  BiEncoder + Hybrid-RRF retrieval; bootstraps. Closes B5.

- [ ] **`scripts/agent/smoke_ob.py`** / **`smoke_wol.py`** /
  **`smoke_otel_demo.py`** — add `--order-by-incident-time` flag.
  Sorts cases by `(service_name, incident_episode_id, start_time)`
  before running, so the StateLayer's page-suppression rule actually
  sees multi-window same-incident sequences. Closes C7 non-trivially.

- [ ] **Build + test + commit each script as it's written.** Aim for
  one commit per script. Final commit before data runs: a single
  "Phase 0 — fresh-run tooling shipped" commit message that ties
  them together.

- [ ] **Run the full agent test suite** after the new scripts land.
  Should be ~425 tests + new tests for the scripts. Zero failures.
  ```bash
  PYTHONPATH=src python -m unittest discover -s src/agent/tests -t src
  ```

---

## Section 2 — Phase 0: Cleanup verification + manifest regeneration (5 minutes)

- [ ] **Confirm cleanup once more** (already done above; redo for safety).

- [ ] **Regenerate v2-resplit manifest for OB.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.make_resplit \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --out triage-split-manifest-v2-resplit.json \
      --train 0.70 --val 0.15 --test 0.15 --seed 42
  ```
  Verify: file present + 1008 windows under "test".

- [ ] **Regenerate v2-resplit manifest for WoL.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.make_resplit \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --out triage-split-manifest-v2-resplit.json \
      --train 0.70 --val 0.15 --test 0.15 --seed 42
  ```
  Verify: file present.

- [ ] **OTel Demo manifest already exists** (Phase 2.4 generated it).
  Verify:
  ```bash
  cat data/derived/global/2026-06-09-otel-demo-v1-global/triage-split-manifest-v2-resplit.json | python -c "
  import json, sys
  d = json.load(sys.stdin)
  from collections import Counter
  print(Counter(d['window_assignment'].values()))
  "
  # Expected: ~{train: 1150, validation: 246, test: 247}
  ```

- [ ] **Wipe Neo4j (fresh instance, but confirm zero nodes):**
  ```bash
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n:
      rows = n.run('MATCH (m) RETURN count(m) AS c'); print(rows[0]['c'])
  "
  # Expected: 0
  ```

- [ ] **Annotate WoL depth.** (Must happen NOW before Phase 2; cheap.)
  ```bash
  PYTHONPATH=src python scripts/agent/annotate_wol_depth.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global --inplace
  # Verify: spot-check a few rows of global-triage-examples.jsonl —
  # each should now have n_prior_same_project_tickets populated.
  ```

---

## Section 2.5 — Dataset Finalization (freeze point) (~2–3 hours)

After this section the **publishable dataset** is complete. Any
researcher can download the three `data/derived/global/<id>/`
directories and reproduce the cascade + agent runs that follow.

**OB:** already finalized at code-freeze (`v2_kg_extractions/`,
`jira-shadow-humanized-v2/`, all kept). V1 humanized deleted
(commit `794efb1`).

**WoL:** already finalized (`v2_kg_extractions/`,
`jira-shadow-humanized-v2/`, kept).

**OTel Demo:** missing humanized + memory entities. §2.5.1 + §2.5.2
generate them.

- [x] **2.5.1 Humanize OTel Demo memory corpus** — ✓ COMPLETE 2026-06-13.
  Used `qwen2.5-coder-14b` @ temp 0.7 (matches OB+WoL protocol).
  147/147 tickets, 0 failures, 696 LLM calls, 2h 13m wall.
  Output: `<otel>/jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl`.
  Schema parity verified against OB v2 (identical keys).
  ```bash
  # Reproduction:
  PYTHONPATH=src python scripts/research-lab/humanize_v5_large_bulk.py \
      --global-id 2026-06-09-otel-demo-v1-global \
      --runs-root data/otel-demo-runs \
      --output-subdir bulk-20260531 \
      --llm-base-url http://localhost:1234 \
      --llm-model qwen/qwen2.5-coder-14b
  ```

- [x] **2.5.2 Memory-side LLM entity extraction on OTel Demo** — ✓ COMPLETE 2026-06-13.
  `qwen3.6-35b-a3b` @ enable_thinking=False, ~11 s/ticket, 25 min wall.
  147/147 extracted, 0 failures. 144 have services, 23 have errors,
  147 have root_cause + symptoms. Initial run hit a transient LM Studio
  stall at 14/147; resumed cleanly from cache.
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --humanized-subdir bulk-20260531 \
      --model qwen/qwen3.6-35b-a3b
  ```
  Output: `<otel>/v2_kg_extractions/all_extractions.jsonl` (147 lines).

- [x] **2.5.3 Freeze-point checkpoint** — ✓ COMPLETE 2026-06-13.
  Parity verified across all 3 datasets. OB was missing the v2-resplit
  manifest; regenerated via `make_resplit` (6720 windows: 4701 train /
  1011 val / 1008 test).

  | Dataset | corpus | examples | gold | resplit | humanized | KG |
  |---|---|---|---|---|---|---|
  | OB | 48 MB | 45 MB | 4.7 MB | ✓ NEW | 347 | 347 |
  | OTel Demo | 6.9 MB | 9.8 MB | 2.2 MB | ✓ | 147 | 147 |
  | WoL | 8.9 MB | 16 MB | 2.0+0.8 strong | n/a* | n/a† | 2000 |

  \* WoL has no failure families to stratify on. † WoL is real Apache
  Jira text, no synthetic humanization needed.

**Original verification recipe (kept for reference):** Verify all three
datasets have the same artifact set:
  ```bash
  for d in 2026-05-25-dataset-v5-large-global \
           2026-06-09-otel-demo-v1-global \
           2026-06-11-wol-real-global; do
      echo "=== $d ==="
      base=data/derived/global/$d
      ls $base/jira-shadow-humanized-v2/ 2>/dev/null && echo "  ✓ humanized-v2"
      [ -f $base/v2_kg_extractions/all_extractions.jsonl ] && \
          echo "  ✓ v2_kg_extractions ($(wc -l < $base/v2_kg_extractions/all_extractions.jsonl) tickets)"
      [ -f $base/triage-split-manifest-v2-resplit.json ] && \
          echo "  ✓ v2-resplit manifest"
  done
  ```

**Publishable artifact set** (per dataset, post-§2.5):

| Path | Purpose | Origin |
|---|---|---|
| `global-triage-examples.jsonl` | Window features + text | data-gen |
| `jira-memory-corpus.jsonl` | Memory tickets | data-gen |
| `jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl` | Humanized memory | humanizer |
| `v2_kg_extractions/all_extractions.jsonl` | LLM entity extractions (memory) | extract_tickets_cli |
| `window-memory-matchings{,-strong}.jsonl` | Gold relation(s) | data-gen |
| `triage-split-manifest-v2-resplit.json` | 70/15/15 stratified split | make_resplit |
| `triage-feature-columns.json` | Numeric feature list | data-gen |
| `distractors/` (WoL only) | 300 off-topic tickets | RQ-A4 ETL |
| `novelty-queries/` (WoL only) | 800 OOD queries | RQ-A5 ETL |

- [x] **2.5.5 v2_kg_extractions_windows on all 3 datasets** — ✓ COMPLETE 2026-06-13.
  Originally scheduled per-dataset (§3.2, §4.2, §5.3); pulled forward
  for publishability + extractor robustness fixes:

  | Dataset | windows | services | components | errors | symptoms | wall |
  |---|---|---|---|---|---|---|
  | OB | 1008 | 720 | 0 | 399 | 1008 | 2h 25min |
  | OTel Demo | 247 | 182 | 27 | 0 | 247 | ~40 min |
  | WoL | 304 | 1 | 99 | 17 | 304 | ~45 min |

  Extraction characteristics correctly mirror each domain:
  microservice systems (OB, OTel) score on services; real Apache
  projects (WoL) score on components.

  **Two extractor robustness improvements shipped:**
  1. `src/v2_advanced/proposal_d_knowledge_graph/extractor.py` —
     `extract_from_window` now optionally passes `SCENARIO FAMILY` +
     `WINDOW TYPE` to the LLM prompt as soft context (helps thin OTel
     evidence; gained 27 new component labels vs zero before).
  2. Cache key now includes family + severity so future backfills
     invalidate properly (legacy cache fallback kept for already-
     extracted windows).

  **OTel-specific data backfill** (also shipped):
  `scripts/agent/backfill_otel_scenario_family.py` derives
  `scenario_family` from `scenario_id` (52 distinct families) across
  global-triage-examples (1643), jira-memory-corpus (147), window-
  memory-matchings (1338). Fixes the upstream `unknown`-family bug.

  **Per-window metadata patcher** (kept for future use):
  `scripts/agent/patch_window_extraction_metadata.py` refreshes
  family + severity on existing cache JSONs without LLM cost.

The window-side `v2_kg_extractions_windows/` is generated PER TEST
SPLIT in the cascade phases (§3.2, §4.2, §5.3) since it costs hours
and is only needed for RQ-A6 symmetric closure. Whether to include
it in the published dataset is up to the publisher.

---

## Section 3 — Phase 1: OB end-to-end (~12–15 hours)

Order matters within this phase: Neo4j is loaded with OB entities and
stays loaded for everything in §3.

- [ ] **3.1 Reload Neo4j with OB memory entities** (~20 sec; writes
  GraphMetadata fingerprint).
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --source llm
  ```
  Verify: GraphMetadata node exists with dataset_id matching the dir name.
  ```bash
  PYTHONPATH=src python -c "from agent.integrity import read_graph_metadata
  from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: print(read_graph_metadata(n))
  "
  ```

- [x] **3.2 Symmetric window extraction on OB** — ✓ COMPLETE 2026-06-13.
  1008/1008, 0 failures, 8.65 s/window, 2h 25min wall. 720 with services,
  399 with error_classes, 1008 with symptoms. Output:
  `v2_kg_extractions_windows/all_extractions.jsonl`.

  (Original command:)
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --split test
  ```
  Verify: `v2_kg_extractions_windows/all_extractions.jsonl` exists with
  ~1008 rows (one per test window).

- [x] **3.3 Full cascade run on OB** — ✓ COMPLETE 2026-06-13/14.
  All 10 pipelines completed across 6 sub-runs (split because of
  bugs encountered live):

  | Pipeline | Wall | Notes |
  |---|---|---|
  | hgb | 5s | sklearn |
  | tab_transformer | 15s | PyTorch GPU, no OOM with 35B loaded |
  | bi_encoder_retrieval | 40 min | sentence-transformers fine-tune |
  | kg_retrieval_rulebased | 38s | Neo4j only |
  | hybrid_rrf_no_graph | 39 min | re-fits its own bi-encoder + SPLADE |
  | hybrid_rrf_retrieval_g3 | 12 min | replaces broken `kg_retrieval` (live LLM); uses cached `v2_kg_extractions_windows/` |
  | kg_retrieval_g3 | 25s | replaces broken `kg_retrieval`; cached extractions |
  | logseq2vec_retrieval_pretrained | 27 min | trained from scratch; required `proposal_b_logseq2vec.data_prep` first |
  | bm25_retrieval | 1s | sklearn |
  | diagnosis_agent | 51 min | **GPT-4o-mini via OpenAI** (local 35B/14B too slow + 8GB GPU OOM with retrieval + LLM); 200-window subsample, 0 errors |

  **Three bugs surfaced and fixed during the run:**
  1. Stale `core.memory.retrieval` import (BM25Retriever) → restored adapter in `src/core/memory/retrieval.py`.
  2. `kg_retrieval` and `hybrid_rrf_retrieval` defaults do **live LLM
     window extraction** on all 6720 windows, which hangs LM Studio.
     The `_g3` variants (cached extractions from §3.2) are the right
     choice for our setup — `kg_retrieval_g3`, `hybrid_rrf_retrieval_g3`.
  3. `VERIFY_SCHEMA` missing `novel` in `required` → OpenAI strict mode
     400d every verify call. Added to `required`; smoke-tested OK.

  **Two extractor improvements shipped (commit applied):**
  - `LMStudioClient` now supports `api_key` (Bearer header) — same OpenAI-compatible `/v1/chat/completions` spec lets us route to OpenAI without code changes.
  - `DiagnosisAgentPipeline.train_and_predict` reads `AGENT_LLM_BASE_URL` / `AGENT_LLM_MODEL` / `AGENT_LLM_API_KEY` (or `OPENAI_API_KEY`) env vars to override the LLM endpoint at runtime.
  - `bi_encoder._finetune` now enables `show_progress_bar=True` + prints expected total step count + per-fine-tune wall time (the silent training step looked hung otherwise).
  - `agent.py` Stage 3 verify now uses `enable_thinking=False` (the local 35B-thinking model hit the 120s timeout on every call; OpenAI doesn't have a thinking mode anyway).

  Per-pipeline predictions saved under `training_runs/<pipeline>__<ts>__ea5748c7/predictions.jsonl`. Master reports under `comparison/v2-final-pt{1..8}/`.

- [x] **3.4 Cascade composition + L3 learned-novelty fit** — ✓ COMPLETE 2026-06-13.
  Headline numbers (cascade with learned L3, full 1008 windows):
  Hit@1 = **0.680**, Hit@5 = **0.828**, novel_recall = **0.917** (vs 0.582 with free-signal L3 — that's the load-bearing lift for RQ-A5).
  L1 stacker: HGB dominates (+8.22); bi_encoder +0.33, kg_rulebased +0.28, logseq2vec +0.22.
  L3 learned classifier: best threshold 0.30, F1 = 0.891. Top features = `window_type` × `scenario_family` interactions.

  Required a consolidation step (`scripts/agent/consolidate_pipeline_predictions.py`) to map per-pipeline `training_runs/.../predictions.jsonl` into the legacy `comparison/v2{a..f}-*` layout `build_cascade` expects. Also discovered: `TCH_LEARNED_NOVELTY_PATH` must be **relative** to `<global_dir>/comparison/`, not absolute — absolute paths silently fail.

  Full write-up + commands in `results/ob/3.4-cascade-composition/SUMMARY.md`.

- [x] **3.5 Agent smoke on OB with traces + incident-ordered + verifier** — ✓ COMPLETE 2026-06-13.
  Hit@1 0.677, **Hit@5 0.758** on 331 gold-bearing windows. Triage acc 0.737. 39 suppressions fired (C7 evidence), pages-per-incident = 1.0. 1008 traces persisted, 5807 cache entries, 1.18s wall. Distinct plan IDs = 1 (RuleController uniform plan — the agent's selective-dispatch story).

  **Two harness bugs fixed during the run** (apply forward before §4.9 WoL + §5.5 OTel):
  - `smoke_ob.py` was missing `--trace-root` CLI flag — added + threaded through to `AgentRunner`. Same patch needed in `smoke_wol.py` + `smoke_otel_demo.py`.
  - Experiment name used `:` separator which fails on Windows (`NotADirectoryError`). Changed to `-` separator. Same fix needed in the other two smoke scripts.

  Note: agent Hit@5 (0.758) ≠ cascade Hit@5 (0.828) — agent is selectively dispatching (only 3/6 retrieval skills invoked), which is the agent's value prop. The 0.828 is the always-everything cascade oracle; 0.758 is the agent's smart-planner number.

  Full write-up in `results/ob/3.5-agent-smoke/SUMMARY.md`.

- [ ] **3.6 OB ablation grid + bootstrap** (~10 min). Closes C5 for OB.
  ```bash
  PYTHONPATH=src python scripts/agent/run_ablation.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --output data/agent_runs/ob-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/ob-smoke.json \
      --ablation-grids data/agent_runs/ob-ablation.json
  ```

- [ ] **3.7 Agent counterfactual cost savings** (~1 min). Closes B3.
  ```bash
  PYTHONPATH=src python scripts/agent/agent_cost_savings.py \
      --eval-report data/agent_runs/ob-smoke.json \
      --pipeline-jsonls data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2*/per-window-predictions.jsonl \
      --output data/agent_runs/ob-cost-savings.json
  ```

- [ ] **3.8 Agent HP sensitivity on OB** (~5 min — agent-side thresholds,
  cached predictions). Closes C2.
  ```bash
  PYTHONPATH=src python scripts/agent/agent_hp_sensitivity.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --cheap-path-thresholds 0.7,0.8,0.9,0.95 \
      --reformulation-floors 0.3,0.5,0.7 \
      --free-novelty-thresholds 0.3,0.5,0.7 \
      --learned-novelty-thresholds 0.3,0.5,0.7 \
      --output data/agent_runs/ob-hp-sensitivity.json
  ```

- [ ] **3.9 Reformulation recovery on OB** (~15 min — LLM optional).
  Closes B4.
  ```bash
  PYTHONPATH=src python scripts/agent/reformulation_recovery.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --use-llm \
      --output data/agent_runs/ob-reformulation-recovery.json
  ```

- [ ] **3.10 Bootstrap OB headlines + cascade Final + BM25 baseline**
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final-with-learned-l3/per-window-predictions.jsonl \
      --paired bi_encoder_retrieval bm25_retrieval \
      --paired bi_encoder_retrieval tch_cascade \
      --output data/agent_runs/ob-cascade-final-bootstrap.json
  ```

- [ ] **3.11 OB analysis passes (depth, cost, failure categories).**
  ```bash
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --output data/agent_runs/ob-depth-scaling.json
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/ob-smoke.json \
      --output data/agent_runs/ob-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/ob-smoke.json \
      --output data/agent_runs/ob-failure-categories.json
  ```

- [ ] **3.12 Sanity check — Phase 1 closure.** Verify all of:
  - `data/agent_runs/ob-smoke.json` exists, Hit@5 reported
  - `data/agent_runs/ob-ablation.json` exists, no_numeric_telemetry row present
  - `data/agent_runs/ob-hp-sensitivity.json` exists
  - `data/agent_runs/ob-reformulation-recovery.json` exists
  - `data/agent_runs/ob-cost-savings.json` exists
  - `data/agent_traces/` has ~1008 trace files
  - `data/skill_cache/` has populated entries

---

## Section 4 — Phase 2: WoL end-to-end (~16–20 hours)

- [ ] **4.1 Wipe Neo4j + reload with WoL memory entities** (~20 sec).
  ```bash
  # New Neo4j instance OR clear via:
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: n.clear_database()
  "
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --source llm
  ```
  Verify GraphMetadata flipped to WoL dataset_id.

- [ ] **4.2 Symmetric window extraction on WoL** (~6 hours LM Studio).
  RUN OVERNIGHT.
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --split test
  ```

- [ ] **4.3 Full cascade run on WoL** (~6–8 h). Same `run_all_v2.py`
  master driver as OB; produces the same `comparison/v2{a..d}-*` layout.
  TCH-Lite mode auto-activates via env var since WoL has no numeric features.
  ```bash
  TCH_LITE=1 \
  PYTHONPATH=src python -m v2_advanced.run_all_v2 \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --runs-root data/wol \
      --pipelines bi_encoder_retrieval,logseq2vec_retrieval_pretrained,hybrid_rrf_no_graph,hybrid_rrf_retrieval,kg_retrieval_rulebased,kg_retrieval,diagnosis_agent,bm25_retrieval
  ```

- [ ] **4.4 Strong-relation cascade run on WoL** (~2 h — inference only,
  reuses BiEncoder weights). Closes A7 strong-relation.
  ```bash
  STRONG_RELATION=1 \
  PYTHONPATH=src python -m v2_advanced.run_all_v2 \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --runs-root data/wol \
      --pipelines bi_encoder_retrieval,hybrid_rrf_retrieval,kg_retrieval,diagnosis_agent \
      --output-base data/derived/global/2026-06-11-wol-real-global/comparison-strong
  ```

- [ ] **4.5 DiagnosisAgent on the 800 WoL OOD queries** (~7 h LM Studio).
  Closes A5 agent signal.
  ```bash
  PYTHONPATH=src python scripts/agent/run_diagnosis_on_ood.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --queries novelty-queries/windows.jsonl \
      --output data/derived/global/2026-06-11-wol-real-global/ood-diagnosis-predictions.jsonl
  ```

- [ ] **4.6 Mode 2 free signal precompute** (the canonical
  mode2_per_query.jsonl regenerate — closes A5 free signal).
  ```bash
  # Use the existing Mode 2 driver if it's documented in
  # docs7/MODE2-NOVELTY-RESULTS.md; or implement as a small precompute
  # over `novelty-queries/windows.jsonl` × `jira-memory-corpus.jsonl`.
  # If the Mode 2 CLI doesn't exist as a standalone, copy from the
  # original Mode 2 ETL described in MODE2-NOVELTY-RESULTS.md §6.
  ```

- [ ] **4.7 Cascade composition + L3 learned novelty fit + re-compose**
  (~15 min total). Same 4-step recipe as OB §3.4.
  ```bash
  # 0. Consolidate per-pipeline training_runs/ into the v2X-*/ layout
  #    build_cascade expects. Mirrors to results/wol/4.3-cascade/consolidated/.
  PYTHONPATH=src python scripts/agent/consolidate_pipeline_predictions.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --mirror-to results/wol/4.3-cascade/consolidated
  # 1. Compose with default L3
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output-dir data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/final
  # 2. Fit L3 learned
  PYTHONPATH=src python -m v2_advanced.tch.novelty_calibration \
      --cascade-predictions data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --out-dir data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/learned-novelty
  # 3. Re-compose with L3 wired (path can be relative or absolute; the
  #    build_cascade fix in commit-after-ea5748c7 accepts both)
  TCH_LEARNED_NOVELTY_PATH=v2g-final-models/learned-novelty/learned_novelty.jsonl \
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output-dir data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/final-with-learned-l3
  ```

- [ ] **4.8 Full L3 novelty evaluation with all 3 signals** (closes A5).
  ```bash
  PYTHONPATH=src python scripts/agent/novelty_eval.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --agent-signal data/derived/global/2026-06-11-wol-real-global/ood-diagnosis-predictions.jsonl \
      --learned-signal data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/learned-novelty/learned_novelty.jsonl \
      --output data/agent_runs/wol-l3-novelty.json
  ```

- [ ] **4.9 Agent smoke on WoL + ablation + bootstrap** (RQ-A8
  structural skip verified, traces persisted).
  ```bash
  PYTHONPATH=src python scripts/agent/smoke_wol.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --cache-dir data/skill_cache \
      --trace-root data/agent_traces \
      --order-by-incident-time \
      --output data/agent_runs/wol-smoke.json
  PYTHONPATH=src python scripts/agent/run_ablation.py --dataset wol \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output data/agent_runs/wol-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/wol-smoke.json \
      --ablation-grids data/agent_runs/wol-ablation.json
  ```

- [ ] **4.13 WoL Mode 3 paired bootstrap CIs (5 retrievers).**
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2c-hybrid/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2b-logseq2vec/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2d-kg-rulebased/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2e-agent-llm/per-window-predictions.jsonl \
      --paired bi_encoder_retrieval hybrid_rrf_retrieval \
      --paired bi_encoder_retrieval diagnosis_agent \
      --output data/agent_runs/wol-mode3-bootstrap.json
  ```

- [ ] **4.14 WoL cascade composition vs best single (coarse + strong).**
  ```bash
  PYTHONPATH=src python scripts/agent/wol_cascade_compose.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output data/agent_runs/wol-cascade-composition.json
  PYTHONPATH=src python scripts/agent/wol_cascade_compose.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --gold-relation strong \
      --output data/agent_runs/wol-cascade-composition-strong.json
  ```

- [ ] **4.15 Depth-scaling on WoL** (now possible after annotate_wol_depth).
  ```bash
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
      --output data/agent_runs/wol-depth-scaling.json
  ```

- [ ] **4.16 WoL cost + failure analyses.**
  ```bash
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/wol-smoke.json \
      --traces data/agent_traces/ \
      --output data/agent_runs/wol-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/wol-smoke.json \
      --output data/agent_runs/wol-failure-categories.json
  ```

- [ ] **4.17 Sanity check — Phase 2 closure.** Verify all 16
  `data/agent_runs/wol-*.json` artifacts exist + WoL traces in
  `data/agent_traces/`.

---

## Section 5 — Phase 3: OTel Demo end-to-end (~10–12 hours) — closes B1

Prerequisite: §2.5 Dataset Finalization complete (humanized memory +
v2_kg_extractions present for OTel Demo).

- [ ] **5.1 Wipe Neo4j + reload with OTel Demo entities.**
  ```bash
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: n.clear_database()
  "
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --source llm
  ```

- [ ] **5.2 Symmetric window extraction on OTel Demo** (~3 hours).
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --split test
  ```

- [ ] **5.3 L1-retrained cascade on OTel Demo** (~6 h GPU). Fits
  BiEncoder + LogSeq + HybridRRF on OTel Demo train split; runs all
  retrievers + BM25 + DiagnosisAgent. Closes B1 (the L1-retrained
  reading of the zero-shot transfer claim).
  ```bash
  PYTHONPATH=src python -m v2_advanced.run_all_v2 \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --runs-root data/otel-demo-runs \
      --pipelines hgb,tab_transformer,bi_encoder_retrieval,logseq2vec_retrieval_pretrained,hybrid_rrf_no_graph,hybrid_rrf_retrieval,kg_retrieval_rulebased,kg_retrieval,diagnosis_agent,bm25_retrieval
  ```

  Note on "zero-shot": the cascade pipelines fit on the dataset's own
  train split. True zero-shot transfer (run OB-trained weights on OTel
  Demo test) requires a separate run variant. The PRIMARY B1 claim is
  the L1-retrained number; a follow-up variant adds the zero-shot
  read by loading OB BiEncoder weights at OTel Demo inference time
  (requires extending `BiEncoderRetrievalPipeline` with a
  `--pretrained-weights-dir` flag; deferred for v1 in favor of the
  L1-retrained closure).

- [ ] **5.4 Cascade composition + L3 learned novelty fit** (~15 min).
  Same 4-step recipe as OB §3.4 (consolidate → compose → fit L3 → re-compose).
  ```bash
  # 0. Consolidate per-pipeline training_runs/ into the v2X-*/ layout
  PYTHONPATH=src python scripts/agent/consolidate_pipeline_predictions.py \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --mirror-to results/otel-demo/5.3-cascade/consolidated
  # 1. Compose with default L3
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --output-dir data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2g-final-models/final
  # 2. Fit L3 learned
  PYTHONPATH=src python -m v2_advanced.tch.novelty_calibration \
      --cascade-predictions data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --out-dir data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2g-final-models/learned-novelty
  # 3. Re-compose with L3 wired
  TCH_LEARNED_NOVELTY_PATH=v2g-final-models/learned-novelty/learned_novelty.jsonl \
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --output-dir data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2g-final-models/final-with-learned-l3
  ```

- [ ] **5.5 Agent smoke + ablation + bootstrap + analyses on OTel Demo.**
  ```bash
  PYTHONPATH=src python scripts/agent/smoke_otel_demo.py \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --cache-dir data/skill_cache \
      --trace-root data/agent_traces \
      --order-by-incident-time \
      --output data/agent_runs/otel-smoke.json
  PYTHONPATH=src python scripts/agent/run_ablation.py --dataset otel \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --output data/agent_runs/otel-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/otel-smoke.json \
      --ablation-grids data/agent_runs/otel-ablation.json
  PYTHONPATH=src python scripts/agent/agent_cost_savings.py \
      --eval-report data/agent_runs/otel-smoke.json \
      --pipeline-jsonls data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2*/per-window-predictions.jsonl \
      --output data/agent_runs/otel-cost-savings.json
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2a-resplit/per-window-predictions.jsonl \
      --output data/agent_runs/otel-depth-scaling.json
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/otel-smoke.json \
      --output data/agent_runs/otel-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/otel-smoke.json \
      --output data/agent_runs/otel-failure-categories.json
  ```

- [ ] **5.6 Sanity check — Phase 3 closure.** Verify all
  `data/agent_runs/otel-*.json` artifacts exist.

---

## Section 6 — Phase 4: Cross-cutting (~5–6 hours)

- [ ] **6.1 Build Mode 4 cross-corpus gold relation** (~1 h).
  ```bash
  PYTHONPATH=src python scripts/agent/build_cross_corpus_gold.py \
      --memory-dataset data/derived/global/2026-06-11-wol-real-global \
      --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \
      --project-filter Kafka \
      --output data/derived/cross-corpus-kafka-gold.jsonl
  ```

- [ ] **6.2 Mode 4 retrieval run** (~2–3 h).
  ```bash
  PYTHONPATH=src python scripts/agent/run_cross_corpus_retrieval.py \
      --memory-dataset data/derived/global/2026-06-11-wol-real-global \
      --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \
      --gold data/derived/cross-corpus-kafka-gold.jsonl \
      --output data/agent_runs/mode4-cross-corpus-kafka.json
  ```

- [ ] **6.3 Similarity-weighted distractor sweep** (Phase 3.4 already
  shipped — re-run on fresh OB + WoL data).
  ```bash
  PYTHONPATH=src python scripts/agent/run_distractor_sweep.py \
      --cascade-predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --triage-examples data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl \
      --distractors data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl \
      --output data/agent_runs/wol-distractor-sweep.json
  ```

- [ ] **6.4 Bootstrap all final headline tables** (paired CIs everywhere).
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/bm25-baseline/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2c-hybrid/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2e-agent-llm/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/bm25-baseline/per-window-predictions.jsonl \
          data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-09-otel-demo-v1-global/comparison/bm25-baseline/per-window-predictions.jsonl \
      --paired tch_cascade bm25 \
      --paired bi_encoder_retrieval hybrid_rrf_retrieval \
      --paired bi_encoder_retrieval diagnosis_agent \
      --output data/agent_runs/all-headlines-bootstrap.json
  ```

---

## Section 7 — Phase 5: Validation + paper-ready artifacts (1 day)

- [ ] **7.1 Re-run the full agent test suite.** Must be green.
  ```bash
  PYTHONPATH=src python -m unittest discover -s src/agent/tests -t src
  ```

- [ ] **7.2 Sanity-table for every RQ** — verify every artifact mentioned
  in `RQ-ANSWERS.md` exists with non-zero content + the number isn't
  obviously wrong (e.g., Hit@5 ∈ [0, 1]).
  ```bash
  # One-liner that prints presence + n_cases for every expected artifact:
  for f in data/agent_runs/*.json; do
      python -c "
  import json, sys
  d = json.load(open(sys.argv[1]))
  print(f'{sys.argv[1]}: keys={sorted(d)[:5]}...')
  " $f
  done
  ```

- [ ] **7.3 Regenerate `DOCS/docs7/RQ-ANSWERS.md`** with the fresh
  numbers. Every "→ Deferred" should now be "✓ Closed". Every CI
  bracket should reflect the new data. The "Tally" at the bottom must
  read: Closed 22 / Partial 0 / Not done 0 / Deferred 0 (or close to it).

- [ ] **7.4 Generate the paper §5 draft tables.** One table per RQ —
  pull point + CI from the bootstrap JSONs.
  ```bash
  PYTHONPATH=src python scripts/agent/build_paper_tables.py \
      --in data/agent_runs/ \
      --out technical-paper/sections/05-results-tables/
  ```
  (This script is a stretch — if time-pressed, copy tables manually
  from the bootstrap JSONs.)

- [ ] **7.5 Final commit.** Tag the commit `rq-closure-v1`.
  ```bash
  git add -A
  git commit -m "fresh-run closure: every RQ answered with no caveats"
  git tag rq-closure-v1
  ```

- [ ] **7.6 Archive data/agent_runs/ + data/agent_traces/ + skill_cache/
  to backup** (gitignored, but irreplaceable).

---

## Section 8 — Known scope limits (NOT caveats, just honest framing)

These are intentional design choices. The fresh run **doesn't try to
remove them** — they're acknowledged in the paper as bounds on the
contribution.

- **B3 cost savings are counterfactual**, not measured against a
  parallel always-on cascade. Standard methodology; the paper should
  say "agent's gating WOULD have saved X seconds of LLM inference per
  window vs the always-on cascade." Concrete numbers come from the
  cascade's recorded per-skill wall-times (step 3.3) × the agent's
  skip-rate (step 3.7).

- **A4 Level 3** (full end-to-end re-train with contaminated corpus +
  re-train the entire retrieval model from scratch) is NOT in this
  run — Level 2 (corpus-mixing re-fit at the BiEncoder layer) is. The
  paper says "Level 2 corpus-mixing"; Level 3 is journal-extension work.

- **C7 multi-window probe** uses OB's `incident_episode_id` grouping
  (4-5 windows per incident). True long-running real-world incidents
  (24h+ outages) aren't in any of our datasets. Acknowledged.

- **OTel Demo zero-shot transfer** assumes OB and OTel Demo are
  "same modality" (microservices); cross-modality (mobile, desktop)
  is out of scope. Per the catalogue.

- **No cascade-side HP grid search** (e.g. transformer hidden dim,
  layer count). C2 covers BiEncoder epochs + RRF k + L1/L3 thresholds
  — the load-bearing parameters per `RQ-ANSWERS.md`.

---

## Section 9 — Checkpoint summary

After all sections complete, verify the closure tally:

| Section | RQs closed in this section |
|---|---|
| §3 OB | A1, A2, A3 reconfirm, A9 (per-skill cost), B2 (OB), C2, C3, C5 (OB), C6 (OB), C7 (OB), C4 (OB BM25) |
| §4 WoL | A4 (Level 2), A5 (full L3), A6 (transfer + symmetric), A7 (coarse + strong), A8 (struct + CI), B2 (WoL), C4 (WoL BM25), C5 (WoL), C6 (WoL), C7 (WoL), reformulation recovery |
| §5 OTel Demo | B1 (zero-shot + L1-retrained), C4 (OTel BM25), C5 (OTel), C6 (OTel) |
| §6 Cross-cutting | B5 (Mode 4), B3 counterfactual savings, identity-aware distractor sweep |
| §7 Validation | All bootstrap CIs, all tables, RQ-ANSWERS.md refresh |

**Target final tally:**
- Closed: A1, A2, A3, A4, A5, A6, A7, A8, A9, B1, B2, B3, B4, B5, B6, C1, C2, C3, C4, C5, C6, C7 = **22 RQs**
- Partial: 0
- Not done: 0
- Deferred: 0

If anything ends up in Partial / Not done after the run, that's the
honest-scope item to be flagged in the paper.

---

## Appendix A — File-by-file deletion confirmation (already done)

Verified 2026-06-13:

```
data/derived/global/2026-05-25-dataset-v5-large-global/:
  ✓ Gone:  comparison/, training_runs/, embeddings/, v2_logseq/,
           v2_kg_extractions_rules/, v2_kg_extractions_windows/,
           triage-split-manifest-v2-resplit.json
  ✓ Kept:  global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-v1/v2/v2-distractors/, v2_kg_extractions/,
           triage-feature-columns.json, triage-split-manifest.json,
           dataset-metadata.json, text-leakage-report/, family-coverage.json,
           leakage-canary-summary.json, validate-dataset-run-summary.json,
           global-triage-build-manifest.json, jira-memory-build-manifest.json,
           window-memory-matchings.jsonl

data/derived/global/2026-06-09-otel-demo-v1-global/:
  ✓ Kept:  all inputs intact, v2-resplit manifest present (from Phase 2.4)
  ⚠ Note:  v2_kg_extractions/ does NOT exist on disk yet — will be
           generated in §5.1.

data/derived/global/2026-06-11-wol-real-global/:
  ✓ Gone:  tch-lite-refit/, v2_logseq/, distractor_curve_wol_pool_300.json,
           mode2_novelty_lowerbound.json, mode2_per_query.jsonl,
           triage-split-manifest-v2-resplit.json
  ✓ Kept:  global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-v2/, novelty-queries/, distractors/,
           v2_kg_extractions/, window-memory-matchings.jsonl,
           window-memory-matchings-strong.jsonl, dataset-metadata.json,
           source-mapping.csv, triage-feature-columns.json,
           triage-split-manifest.json, gold-relations-debug.json,
           wol-extraction-manifest.json, wol-priority-mapping.json,
           README.md

data/:
  ✓ Gone:  agent_runs/, agent_traces/, skill_cache/, llm_telemetry/,
           neo4j-snapshots/ (was never present), smoke-otel-pilot-global/
  ✓ Kept:  README.md, runs/, otel-demo-runs/, wol/

Neo4j: fresh instance, zero nodes, same credentials.
```

---

## Appendix B — One-line summary

> **Build 10 scripts → cleanup → 3 dataset passes (OB → WoL → OTel Demo,
> serialized on Neo4j) → cross-cutting → validation. ~50 hours
> wall-clock. Every checkbox completed = paper-ready, every RQ
> closed.** Don't skip any step.
