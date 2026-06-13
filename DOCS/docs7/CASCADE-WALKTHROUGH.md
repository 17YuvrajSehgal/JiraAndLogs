# Cascade walk-through — what already exists vs what we need to build

**Generated 2026-06-13** after reading `src/comparison/`, `src/v2_advanced/`,
and `src/core/data/`. This is the document I needed before starting §1.

The big surprise: **most of the "missing scripts" already exist** in
some form. We need ~4 new scripts and ~1 small extension. Re-scoped
TODO at the bottom.

---

## 1. The architecture (data flow)

```
data/derived/global/<dataset_id>/
  ├─ global-triage-examples.jsonl       ┐
  ├─ jira-memory-corpus.jsonl           │
  ├─ window-memory-matchings.jsonl      │ INPUTS
  ├─ jira-shadow-humanized-v2/          │ (kept across runs)
  ├─ v2_kg_extractions/                 │
  └─ triage-split-manifest-v2-resplit  ─┘
        │
        │  read by core.data.loaders.load_dataset(global_dir) →
        │  LoadedDataset(windows, memory_corpus, matchings,
        │                split_manifest, feature_columns)
        │
        │  attach_matchings() copies gold onto each TriageWindow:
        │    w.matched_memory_issue_ids ← match.matched_memory_issue_ids
        │    w.is_novel ← match.is_novel
        │
        ▼
  ┌───────────────────────────────────────────────────────────────┐
  │  Each pipeline: PipelineRunner.train_and_predict()            │
  │    ↓                                                          │
  │    iter_split(windows, manifest, "train") → train_windows     │
  │    iter_split(windows, manifest, "validation") → val_windows  │
  │    iter_split(windows, manifest, "test") → test_windows       │
  │    fit() on train (e.g. BiEncoder finetune)                   │
  │    threshold-tune on val (precision_at_fpr)                   │
  │    predict() on test → list[PipelinePrediction]               │
  │    → return PipelineResult(predictions, threshold, fit_sec,   │
  │              predict_sec, metadata)                           │
  └───────────────────────────────────────────────────────────────┘
        │
        │  Orchestrator: comparison.runner.run_comparison()
        │    - calls every pipeline in `pipelines` list
        │    - wraps each in a training_run (writes config + log)
        │    - aggregates results → ComparisonReport
        │    - n_prior_family_tickets populated centrally
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │ comparison/<subdir>/                                    │
  │   per-window-predictions.jsonl   (one row per window    │
  │                                   per pipeline)         │
  │   report.json                    (CIs, pairwise tests)  │
  │   report.md                      (human-readable)       │
  └─────────────────────────────────────────────────────────┘
        │
        │  Read by v2_advanced.tch.build_cascade
        │    - per-pipeline JSONLs (PIPELINE_FILES map)
        │    - L1 stacker (CV logistic regression over triage_scores)
        │    - L2 RRF fusion over the retriever set
        │    - L3 novelty disjunction (free ∨ learned ∨ agent)
        │    - L4 final triage with overlap rerank at position 1
        │
        ▼
  comparison/v2g-final-models/final/per-window-predictions.jsonl
  + report.{json,md}
```

The v2-resplit manifest doesn't replace `triage-split-manifest.json`;
it lives alongside it. `proposal_a_resplit.run_v2_comparison.patch_iter_split()`
monkey-patches `iter_split` at process start so every pipeline sees
the v2 assignments — process-scoped, so each retriever re-import is
also re-bound.

---

## 2. The PipelineRunner contract

```python
class PipelineRunner(ABC):
    name: str = "abstract"
    @abstractmethod
    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult: ...
```

What every pipeline does inside `train_and_predict`:

1. `ds = load_dataset(global_dir)` — typed dataset
2. `train, val, test = iter_split(...)` — v2-aware after the patch
3. Fit + threshold-tune
4. Predict per test window → `PipelinePrediction(...)`
5. Return `PipelineResult(predictions=[...], triage_threshold=..., fit_seconds=..., predict_seconds=...)`

**Per-window wall-time is NOT currently tracked.** The `fit_seconds`
and `predict_seconds` are pipeline-totals. To get per-window cost,
either:
- (a) time each `predict_one()` inside the pipeline → write to a new
      field `wall_seconds` on `PipelinePrediction`, OR
- (b) divide `predict_seconds / len(predictions)` as a mean estimate.

Option (a) requires touching each pipeline's predict loop; option (b)
is one line in the post-processor. **I'll go with (b)** — it's enough
for the A9/B3 cost claim.

---

## 3. `KNOWN_PIPELINES` registry (the names you pass to `--pipelines`)

In `src/comparison/runner.py` lines 111–460. Available names include:

| Name | Source | Notes |
|---|---|---|
| `hgb` | `_NumericClassifierPipeline` | Hist gradient boosting, numeric features only |
| `rf` | `CalibratedRandomForestPipeline` | Random forest, numeric |
| `logistic_sklearn` | `LogisticNumericPipeline` | Plain logistic, numeric |
| `tab_transformer` | `TabTransformerPipeline` | Phase G neural, soft-imported |
| **`bi_encoder_retrieval`** | `BiEncoderRetrievalPipeline` | THE retriever; lives in `neural_models/bi_encoder.py` |
| **`bm25_only` / `bm25_retrieval`** | `BM25RetrievalPipeline` | **Already exists** in `pipelines_retrieval.py` (TODO C4!) |
| `nomic_retrieval` | `NomicRetrievalPipeline` | Nomic embeddings |
| `nomic_lm_rerank` | `NomicLMRerankPipeline` | Nomic + LM rerank |
| **`logseq2vec_retrieval`** | `LogSeq2VecRetrievalPipeline` | v2 Phase B |
| **`logseq2vec_retrieval_pretrained`** | `_LogSeq2VecPretrained` | Pretrained variant |
| **`kg_retrieval`** | `KnowledgeGraphRetrievalPipeline` | LLM-extracted KG |
| **`kg_retrieval_rulebased`** | `_KGRetrievalRuleBased` | Rule-extracted KG |
| **`hybrid_rrf_retrieval`** | `HybridRRFRetrievalPipeline` | SPLADE + BiEncoder + Graph |
| **`hybrid_rrf_no_graph`** | `_HybridNoGraph` | Hybrid minus graph (ablation) |
| **`diagnosis_agent`** | `DiagnosisAgentPipeline` | DiagnosisAgent over Hybrid top-10 |
| Many memorygraph variants | `MemoryGraphPipeline` subclasses | v1 cascade baselines |

**Key finding: BM25 is already registered.** I need to look up the
exact name (`bm25_only` vs `bm25_retrieval`) and verify the runner can
emit its predictions. RQ-C4 is much closer to closure than I thought.

---

## 4. How to ADD a new pipeline

Two paths:

**A. Register in `comparison.runner.KNOWN_PIPELINES`** if it follows
the `PipelineRunner` contract. Existing examples: every entry in
lines 137–460. Just do:
```python
KNOWN_PIPELINES["my_new_pipeline"] = MyNewPipelineClass
```

**B. Write a new module under `v2_advanced/proposal_*/` and import +
register in `comparison/runner.py`** — soft-imported with `try: ...
except ImportError`. That's how Phases B/C/D/E got added.

For a fresh BM25 baseline run we don't need a new pipeline class —
just call `run_comparison(..., pipelines=["bm25_retrieval", ...])`.

---

## 5. How the cascade composition works (build_cascade.py)

```python
# v2_advanced/tch/build_cascade.py
PIPELINE_FILES = {
    "hist_gradient_boosting_numeric": "v2a-resplit/per-window-predictions.jsonl",
    "bi_encoder_retrieval":           "v2a-resplit/per-window-predictions.jsonl",
    ... etc ...
}

# Env-var overrides allow refit variants to plug in:
TCH_OVERRIDE_BIENC=... → swap BiEncoder predictions path
TCH_LEARNED_NOVELTY_PATH=... → wire in the L3 learned classifier output
TCH_LITE=1 → drop HGB from L1 stacker (log-only mode for WoL)
TCH_LITE_OUTPUT_SUFFIX=lite → suffix on output filenames

# Reads all predictions, fuses:
load_all_predictions() → dict[window_id, WindowState]  # per-pipeline scores
rrf_fuse(...) → top-5 ranking
stack_triage_cv() → L1 logistic stacker via 5-fold CV
assemble_cascade_prediction() → final per-window dict
```

This is post-hoc — operates purely on cached JSONLs. **Fast** (seconds).

---

## 6. CRITICAL FINDING — many "missing scripts" ALREADY EXIST

The TODO §1 list was too pessimistic. Re-checking each:

| TODO item | Reality | Status |
|---|---|---|
| `run_cascade_full.py` | `v2_advanced.run_all_v2` exists. Wraps `comparison.cli` via the v2 manifest patch. | **EXISTS — use it** |
| Per-skill wall-time per window | `comparison.runner` records `fit_seconds` + `predict_seconds` per pipeline. **Per-window timing requires a 5-line patch** to the runner (divide predict_seconds by len, write into each prediction). | **Tiny patch needed** |
| `run_bm25_baseline.py` | `BM25RetrievalPipeline` already in `KNOWN_PIPELINES`. Just invoke via `run_all_v2 --pipelines bm25_retrieval`. | **EXISTS — use it** |
| `proposal_e_agent/run_on_ood.py` | Doesn't exist. `DiagnosisAgentPipeline` runs on the test split via `iter_split` — for OOD it needs a different window source (`novelty-queries/windows.jsonl`). | **NEW (~3h)** |
| `build_cascade.py --fit-l3-learned-novelty` | **`v2_advanced.tch.novelty_calibration` already exists.** Fits LogReg over cheap-skill outputs via 5-fold CV. Output wires into `build_cascade` via `TCH_LEARNED_NOVELTY_PATH` env var. | **EXISTS — use it** |
| `build_cascade.py --gold-relation strong` | `core.data.loaders.load_window_memory_matchings()` is hardcoded to `window-memory-matchings.jsonl`. Need a parameter to also read `window-memory-matchings-strong.jsonl`. | **Small extension** |
| `hp_sensitivity.py` | New. Coordinates multiple `run_all_v2` invocations with different params, aggregates. | **NEW (~3h)** |
| `reformulation_recovery.py` | New. Needs single-query BiEncoder inference. `BiEncoderRetrievalPipeline` has fit; need to expose `encode_query(text)` for one-shot use. | **NEW (~4h)** |
| `distractor_sweep_corpus_mix.py` | New, but several existing pipelines already accept `distractor_path=` — the mixing is supported. Just drive `BiEncoderRetrievalPipeline` (or `MemoryGraphPipeline`) at different ratios. | **NEW (~3h)** |

**Revised total: ~13h of new code (4 new scripts) + a small patch to
`comparison.runner` for per-window timing + a tiny core-loader
extension for strong-relation gold.**

---

## 7. The `runs_root` parameter — what is it?

Every `train_and_predict(global_dir, runs_root, ...)` takes a
`runs_root`. It points to the **raw collection runs** at
`data/runs/` (OB) or `data/otel-demo-runs/` (OTel) or `data/wol/`
(WoL). Used by pipelines that need to read raw logs / metrics /
traces beyond the per-window features. Numeric-only pipelines (HGB,
RF) ignore it (note `del runs_root` in their code).

---

## 8. How DiagnosisAgent gets its candidates

`DiagnosisAgentPipeline.train_and_predict` either:
1. **Re-runs Hybrid-RRF** to produce candidates (slow — heavy fit), or
2. **Reads cached Hybrid-RRF predictions** via env var
   `V2_AGENT_HYBRID_PREDICTIONS_PATH=<path-to-hybrid-jsonl>`.

For our run, after Hybrid-RRF writes to `comparison/v2c-hybrid/per-window-predictions.jsonl`,
set `V2_AGENT_HYBRID_PREDICTIONS_PATH` to that path and the agent
skips the heavy refit.

For `run_on_ood.py`, the OOD queries don't have pre-cached Hybrid
output. We'd need to:
1. Run Hybrid-RRF in inference-only mode on the OOD queries, OR
2. Use a simpler retrieval (BiEncoder solo) to fetch candidates.

Path (2) is the pragmatic choice — the agent's NOVELTY signal is what
we need from RQ-A5, not its top-K accuracy on OOD.

---

## 9. How the v2-split patch works

```python
# proposal_a_resplit/run_v2_comparison.py
def patch_iter_split(v2_manifest):
    import core.data.splits as splits_mod
    original = splits_mod.iter_split

    def iter_split_v2(windows, manifest, split):
        for w in windows:
            if v2_manifest.split_of(w.window_id) == split:
                yield w

    splits_mod.iter_split = iter_split_v2
    # Also rebind any module that already imported iter_split:
    for mod_name, mod in list(sys.modules.items()):
        if hasattr(mod, "iter_split") and getattr(mod, "iter_split") is original:
            setattr(mod, "iter_split", iter_split_v2)
```

So when you call `run_v2_comparison`, every pipeline sees the v2
manifest's assignments even though they call `iter_split` from their
own modules.

---

## 10. Revised plan for §1 remaining work

After this walk-through, the remaining work is much smaller than the
original §1 list. Here's what's actually needed:

### Existing scripts to invoke (no code changes)

| Step | Command |
|---|---|
| Full cascade run | `python -m v2_advanced.run_all_v2 --global-dir <X> --runs-root <Y>` |
| BM25 baseline | Same command with `--pipelines bm25_retrieval` |
| L3 learned novelty fit | `python -m v2_advanced.tch.novelty_calibration --cascade-predictions <X> --out-dir <Y>` |
| Cascade composition | `python -m v2_advanced.tch.build_cascade --global-dir <X> ...` |
| LLM judge (optional) | `python -m v2_advanced.tch.llm_judge ...` |
| Finalize + check | `python -m v2_advanced.tch.finalize --global-dir <X>` |

### Small patches needed

1. **`comparison/runner.py`** — after each pipeline runs, divide
   `predict_seconds / len(predictions)` and write into each
   prediction's metadata so per-window cost is recorded. ~5 lines.
2. **`core/data/loaders.py`** — `load_window_memory_matchings(global_dir,
   filename="window-memory-matchings.jsonl")` should accept a custom
   filename so strong-relation gold can flow through. ~3 lines.
3. **`comparison/cli.py`** — wire a `--matchings-file` flag through to
   the loader. ~5 lines.

### New scripts needed (4 total)

| File | Purpose | Effort |
|---|---|---|
| `scripts/agent/run_on_ood.py` | Run DiagnosisAgent on 800 WoL OOD queries; closes A5 agent signal | ~3h |
| `scripts/agent/hp_sensitivity.py` | Coordinate multiple cascade re-runs at different HPs; closes C2 | ~3h |
| `scripts/agent/reformulation_recovery.py` | Live BiEncoder inference on reformulated queries; closes B4 | ~4h |
| `scripts/agent/distractor_sweep_corpus_mix.py` | Re-fit BiEncoder at multiple distractor ratios; closes A4 Level 2 | ~3h |

### Reformulation recovery — how

Look at `neural_models/bi_encoder.py` for `BiEncoderRetrievalPipeline`.
Need to expose `encode_query(text) → np.ndarray` after fit. Then for
each gate-firing window:
1. Load reformulated query from the agent's trace
2. encode_query(reformulated)
3. Cosine vs memory embeddings (cached after pipeline fit)
4. Compare top-1 before vs after

### HP sensitivity — how

The cascade pipelines accept HP arguments via their constructors
(see `HybridRRFRetrievalPipeline.__init__` — `biencoder_finetune_epochs`,
`rrf_k`, etc.). The sweep script:
1. Construct each variant manually (not via `KNOWN_PIPELINES`)
2. Call `train_and_predict()` directly
3. Save predictions per variant
4. Bootstrap CIs

### Distractor corpus-mix — how

`MemoryGraphPipeline` already accepts `distractor_path=`. For each
ratio R, build a synthetic distractor JSONL with R% of the WoL
distractors, then re-fit BiEncoder with that distractor pool mixed
in. Save predictions per ratio.

### OOD agent — how

```python
# scripts/agent/run_on_ood.py
from v2_advanced.proposal_e_agent.agent import DiagnosisAgent
from v2_advanced.shared import LMStudioClient

# 1. Load 800 OOD queries from novelty-queries/windows.jsonl
# 2. For each: run a simple BiEncoder inference (or load cached) to get top-10 candidates
# 3. agent.diagnose(window_id=..., evidence_text=..., candidates=[...])
# 4. Write rows: {window_id, is_novel, ranked_top5, confidence}
```

---

## 11. What I'm going to do next

Given this map, here's the concrete plan:

1. **Add per-window timing patch** to `comparison/runner.py` — 5 lines.
2. **Add strong-relation gold path** to `core/data/loaders.py` + `comparison/cli.py` — 8 lines.
3. **Write the 4 new scripts** — `run_on_ood`, `hp_sensitivity`,
   `reformulation_recovery`, `distractor_sweep_corpus_mix`.
4. **Update TODO.md** with the corrected §3-§7 commands referencing
   the EXISTING tools (e.g. `python -m v2_advanced.tch.novelty_calibration`
   instead of `--fit-l3-learned-novelty` on `build_cascade`).
5. **Final agent test suite pass** + commit.

Total estimated time: ~14 hours of focused coding.

---

## 12. Cross-references

- Master cascade driver: `src/v2_advanced/run_all_v2.py`
- v2-split monkey-patch: `src/v2_advanced/proposal_a_resplit/run_v2_comparison.py`
- Pipeline ABC + numeric pipelines: `src/comparison/pipelines.py`
- Retrieval pipelines: `src/comparison/pipelines_retrieval.py`, `pipelines_neural.py`
- Pipeline registry: `src/comparison/runner.py` (KNOWN_PIPELINES)
- Per-window prediction shape: `src/comparison/schema.py`
- Dataset loader: `src/core/data/loaders.py`
- Cascade composition: `src/v2_advanced/tch/build_cascade.py`
- L3 learned novelty: `src/v2_advanced/tch/novelty_calibration.py`
- L3 OOD eval: `src/v2_advanced/tch/novelty_ood.py`
- LLM judge: `src/v2_advanced/tch/llm_judge.py`
- DiagnosisAgent: `src/v2_advanced/proposal_e_agent/{agent.py,pipeline.py}`
- HybridRRF: `src/v2_advanced/proposal_c_hybrid_retrieval/pipeline.py`
- KG retrieval: `src/v2_advanced/proposal_d_knowledge_graph/pipeline.py`
- LogSeq2Vec: `src/v2_advanced/proposal_b_logseq2vec/pipeline.py`
