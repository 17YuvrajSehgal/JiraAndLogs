# v2_advanced — Second-iteration research pipelines

Five proposals from `docs3/08-RESEARCH-DIRECTIONS.md`, each implemented
as a parallel pipeline. **The v1 code in `src/{comparison, memorygraph,
neural_models}` is UNTOUCHED** — both panels can be run side-by-side so
we can show v2 vs v1 in the paper.

## What's where

```
src/v2_advanced/
├── shared/                            common utilities
│   ├── logging.py                     uniform structured logging
│   ├── lm_studio.py                   OpenAI-compatible client
│   └── neo4j_client.py                Neo4j driver wrapper
│
├── proposal_a_resplit/                Proposal A: in-distribution split
│   ├── make_resplit.py                generate window-level manifest
│   ├── window_split.py                loader + iter_split equivalent
│   └── run_v2_comparison.py           monkey-patched comparison driver
│
├── proposal_b_logseq2vec/             Proposal B: log-sequence encoder
│   ├── data_prep.py                   parse raw Loki JSON -> per-window sequences
│   ├── model.py                       two-stage LogSeq2Vec model
│   ├── train.py                       (TODO) contrastive training
│   └── pipeline.py                    (TODO) full PipelineRunner
│
├── proposal_c_hybrid_retrieval/       Proposal C: SPLADE + BiEncoder + Graph via RRF
│   ├── splade.py                      SPLADE retriever
│   ├── rrf.py                         Reciprocal Rank Fusion
│   └── pipeline.py                    HybridRRFRetrievalPipeline
│
├── proposal_d_knowledge_graph/        Proposal D: LLM-extracted knowledge graph
│   ├── schema.py                      node/edge schema
│   ├── extractor.py                   LLM-based extraction
│   ├── extract_tickets_cli.py         batch extract all V2 tickets
│   ├── loader.py                      load extractions into Neo4j
│   ├── graph_retriever.py             Cypher-based retriever
│   └── pipeline.py                    KnowledgeGraphRetrievalPipeline
│
└── proposal_e_agent/                  Proposal E: DiagnosisAgent (capstone)
    ├── agent.py                       3-stage LLM workflow
    └── pipeline.py                    DiagnosisAgentPipeline
```

## Prerequisites the user needs to set up

1. **LM Studio with a JSON-capable model**

   Open LM Studio → search → download:
       `lmstudio-community/Qwen2.5-14B-Instruct-GGUF`  (pick the Q4_K_M quant ~ 8 GB)

   Or smaller for faster iteration:
       `lmstudio-community/Qwen2.5-7B-Instruct-GGUF`  (pick Q5_K_M ~ 5.5 GB)

   Then in LM Studio: load the model, start the local server (defaults
   to `http://localhost:1234`).

2. **Neo4j running** at `neo4j://127.0.0.1:7687`

   Confirmed already running. We use credentials `neo4j` / `123456789`.

## Running each phase

### Phase A — in-distribution re-split (no LLM needed)

```powershell
$env:PYTHONPATH = "src"

# 1. Generate the v2 split manifest (one-time, ~1s)
python -m v2_advanced.proposal_a_resplit.make_resplit `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --train 0.70 --val 0.15 --test 0.15 --seed 42

# 2. Run all baseline pipelines on the new split
python -W ignore -m v2_advanced.proposal_a_resplit.run_v2_comparison `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --pipelines hgb,tab_transformer,memorygraph_v2_sota_nw080,bi_encoder_retrieval `
    --no-ensemble --no-lofo `
    --n-bootstrap 1000 `
    --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2a-resplit
```

### Phase D — extract tickets to Neo4j (needs LM Studio)

```powershell
# 1. Make sure LM Studio is running with Qwen2.5-14B loaded.

# 2. Extract entities + relations from all 347 V2 tickets
#    (LM Studio call per ticket; cached on disk, retries on failure)
python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global

# 3. Run a comparison that includes the KG retriever
python -W ignore -m comparison.cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --pipelines kg_retrieval_rulebased,kg_retrieval `
    --no-ensemble `
    --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2d-kg
```

### Phase C — hybrid retrieval (depends on D)

```powershell
python -W ignore -m comparison.cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --pipelines hybrid_rrf_no_graph,hybrid_rrf_retrieval `
    --no-ensemble `
    --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2c-hybrid
```

### Phase B — LogSeq2Vec (data prep + train)

```powershell
# 1. Parse raw Loki dumps once (~10 min, CPU-bound)
python -m v2_advanced.proposal_b_logseq2vec.data_prep `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --max-lines-per-window 80

# 2. Train (TODO: train.py + pipeline integration)
```

### Phase E — DiagnosisAgent (capstone)

```powershell
# Requires Phase C running successfully + LM Studio + Neo4j loaded.
# Defaults to a 200-window subsample because each window takes ~5-10s
# of LLM time. Pass `subsample_size=0` to run all 1008 test windows.

python -W ignore -m comparison.cli `
    --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
    --runs-root data\runs `
    --pipelines diagnosis_agent `
    --no-ensemble `
    --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2e-agent
```

## What we still need from you

Just one thing: **load a model in LM Studio** and start the local server. The pipelines auto-detect at `http://localhost:1234`. We recommend `Qwen2.5-14B-Instruct-Q4_K_M` for the best JSON extraction quality on the RTX 5060.

Until LM Studio has a model loaded, Phases D and E will fail at fit() time with a clear error. Phases A, B, and C can all run without an LLM.

## Logging

Every v2_advanced module uses `v2_advanced.shared.get_logger("phase_X.module")` which produces structured lines like:

```
[02:43:20] [INFO ] [v2_advanced.phase_d.extractor] extraction progress  done=50 total=347 cached=10 extracted=38 failed=2
```

The `step=foo` markers from `log_step(...)` context manager track timing automatically.

## Comparing against v1

The comparison harness pipes both panels through the same metrics +
bootstrap CI infrastructure, so:

```powershell
# v1 vs v2 head-to-head in a single run
python -W ignore -m comparison.cli `
    --pipelines memorygraph_v2_sota_nw080,bi_encoder_retrieval,kg_retrieval_rulebased,hybrid_rrf_no_graph `
    --output-dir data\...\comparison\v1-vs-v2-comparison
```

Every reported metric is paired-bootstrap'd over shared window IDs, so
the comparison is apples-to-apples even though the pipelines have very
different internal architectures.
