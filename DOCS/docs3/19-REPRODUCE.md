# Reproducing TCH from Scratch — End-to-End Guide

A step-by-step recipe to reproduce every number reported in the TCH cascade, starting from raw telemetry runs and ending with `Hit@5 = 0.912`. Each step explains **why** we do it, **what command** to run, **what output** to expect, and **how that output feeds the next step**.

This guide is also a template for applying the pipeline to your own corpus. The sections labeled **"Adapting to your data"** highlight what to change.

---

## Table of contents

1. [Two reproduction paths — pick yours](#two-reproduction-paths--pick-yours)
2. [System requirements](#system-requirements)
3. [Stage 0 — One-time environment setup](#stage-0--one-time-environment-setup)
4. [Stage 1 — Collect raw telemetry runs](#stage-1--collect-raw-telemetry-runs)
5. [Stage 2 — Build per-run derived datasets](#stage-2--build-per-run-derived-datasets)
6. [Stage 3 — Build the global triage corpus](#stage-3--build-the-global-triage-corpus)
7. [Stage 4 — Humanize the Jira memory corpus (LLM)](#stage-4--humanize-the-jira-memory-corpus-llm)
8. [Stage 5 — Extract structured info via LLM (Phase D)](#stage-5--extract-structured-info-via-llm-phase-d)
9. [Stage 6 — Load the Neo4j knowledge graph](#stage-6--load-the-neo4j-knowledge-graph)
10. [Stage 7 — The v2 in-distribution re-split](#stage-7--the-v2-in-distribution-re-split)
11. [Stage 8 — Train the underlying pipelines](#stage-8--train-the-underlying-pipelines)
12. [Stage 9 — Run the DiagnosisAgent (LLM)](#stage-9--run-the-diagnosisagent-llm)
13. [Stage 10 — Build and verify the TCH cascade](#stage-10--build-and-verify-the-tch-cascade)
14. [Stage 11 — Reproduce the headline numbers](#stage-11--reproduce-the-headline-numbers)
15. [Adapting the pipeline to your own data](#adapting-the-pipeline-to-your-own-data)
16. [Troubleshooting](#troubleshooting)
17. [Total time budget](#total-time-budget)

---

## Two reproduction paths — pick yours

### Path A — Full reproduction from scratch (4-5 days)

You want to verify the entire pipeline end-to-end on a fresh dataset. Start at Stage 1 (collect raw runs) and follow every stage. Recommended for academic replication, debugging a step that may have changed, or learning the whole system.

### Path B — Skip to modeling (1-2 days)

You have access to `data/runs/` from our published artifact (the 100 runs collected on the GCP VM). Skip Stage 1, start at Stage 2 (build derived datasets) and follow the rest. This is what most users will do.

**This guide assumes Path B by default.** Stage 1 is included for completeness — it points to the production runbooks in `docs/`.

---

## System requirements

| Component | Required | Why |
|---|---|---|
| OS | Windows 11 with PowerShell, or Linux/macOS (most scripts have both .ps1 and .py) | Pipeline was developed on Windows; most steps are Python so other OSes work |
| Python | 3.11+ | sklearn, sentence-transformers, etc. |
| GPU | Optional but recommended — RTX 5060 (8 GB VRAM) or better | BiEncoder fine-tune (~15 min), LLM inference (~30 sec/window) |
| Disk space | 80 GB free | Raw runs ~40 GB + derived ~20 GB + cached models ~5 GB |
| RAM | 16 GB minimum, 32 GB comfortable | LLM model takes 7-8 GB, BiEncoder fine-tune another 4 GB |
| Neo4j | 5.x community edition, running on `localhost:7687` | Knowledge graph for `kg_retrieval` pipeline |
| LM Studio | Latest, with Qwen 3.6 35B-A3B (Q4_K_M GGUF) loaded | LLM extraction + DiagnosisAgent verify |

Optional but skipped in Path B (you'd need them for Stage 1):
- `kind` (Kubernetes-in-Docker)
- Docker Desktop with 12 GB RAM allocated
- chaos-mesh
- Online Boutique deployment

---

## Stage 0 — One-time environment setup

**Why:** Get the codebase, virtualenv, and dependencies in place before doing anything else.

### 0.1 Clone the repository

```bash
git clone https://github.com/YOUR/JiraAndLogs.git
cd JiraAndLogs
```

### 0.2 Create a Python virtual environment

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 0.3 Install dependencies

```bash
pip install -U pip
pip install -r requirements.txt
pip install -r scripts/research-lab/requirements.txt
```

**What's installed:** scikit-learn, sentence-transformers, torch (CPU or CUDA), transformers, numpy, pandas, neo4j Python driver, structlog, pydantic, networkx, and ~20 more.

### 0.4 Verify GPU (if you have one)

```python
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

Expected output if you have CUDA: `CUDA available: True; Device: NVIDIA GeForce RTX 5060`. CPU-only also works but is much slower.

### 0.5 Install and start Neo4j

```powershell
# Download Neo4j Desktop or Community Edition 5.x
# Start the database — default bolt://127.0.0.1:7687
# Set password to "123456789" (matches our scripts)
```

Verify it's reachable:

```bash
python -c "from neo4j import GraphDatabase; d = GraphDatabase.driver('bolt://127.0.0.1:7687', auth=('neo4j', '123456789')); print(d.verify_connectivity()); d.close()"
```

### 0.6 Install LM Studio

Download from <https://lmstudio.ai>. Inside LM Studio:

1. Open the model browser, search for `qwen3.6-35b-a3b`.
2. Download the Q4_K_M GGUF quantization (~21 GB).
3. Settings → Inference → set context length 8192, structured output **enabled**.
4. Click "Start Server" — it should bind to `http://localhost:1234`.

Verify the server:

```bash
curl -s http://127.0.0.1:1234/v1/models
```

Expected: a JSON listing of `qwen/qwen3.6-35b-a3b` and any other models you have.

---

## Stage 1 — Collect raw telemetry runs

**This is Path A only. Skip to Stage 2 if you're using the published `data/runs/` artifact.**

**Why:** TCH needs a corpus of past incidents with full telemetry to train and evaluate on. The "raw run" is a 30-90 minute slice of telemetry (logs, metrics, traces, k8s events) from a controlled Kubernetes deployment where we inject controlled faults.

**What you get from this stage:** ~100 directories under `data/runs/`, each containing `manifest.json`, `episodes.jsonl`, `telemetry_windows.jsonl`, `jira_shadow_issues.jsonl`, and a `raw/` subdirectory with `loki/`, `tempo/`, `prometheus/`, `kubernetes/`, and `prometheus_supplement/` payloads.

### 1.1 Local Kind cluster (small dataset, ~6 hours)

Follow `docs/dataset-v5-quick-runbook.md` end-to-end. Key steps:

1. Build the M0-M5 instrumented Docker images (the original Online Boutique images don't emit the OpenTelemetry signals we need).
2. Load images into the kind containerd.
3. Deploy Online Boutique to the `online-boutique-research` namespace.
4. Verify pods are running M0-M5 images, not `v0.10.5`.

The single command that drives everything once setup is done:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -CorpusFile "deploy\research-lab\corpora\dataset-v5-quick.json" `
  -DatasetRunPrefix "2026-05-25-dataset-v5-quick" `
  -GlobalDatasetId "2026-05-25-dataset-v5-quick-global" `
  -PythonExe .venv\Scripts\python.exe `
  -Quick -BuildTriage -HaltOnValidationFail `
  -SkipDerivedBuild -SkipAggregateBuild
```

**What it does:** for each scenario family in the corpus manifest, runs the load-generator, injects the fault (via chaos-mesh or kubectl-edit), waits the planned window, collects telemetry into `data/runs/<run_id>/raw/`, generates the `jira_shadow_issues.jsonl` (the gold ticket for this run), and writes a `manifest.json`.

**Output:** `data/runs/2026-05-25-dataset-v5-quick-*/` — about 16 directories.

### 1.2 Full GCP VM corpus (large dataset, 4-5 days)

Follow `docs/gcp-production-dataset-vm-runbook.md` for the production 100-run v5-large corpus. Key differences from local:

- VM shape: `e2-standard-8` (8 vCPU, 32 GB RAM), 1 TB pd-balanced disk.
- OS: Ubuntu 24.04 LTS.
- 27 scenario families instead of 8.
- Includes 24 orphan-incident runs (ticket-worthy windows with NO Jira filed — for novelty evaluation).
- Includes 10 system-fault runs (chaos-mesh DNS, network partition, packet loss, etc.).

**The result is the corpus you'll see in `data/runs/2026-05-25-dataset-v5-large-*` — 100 directories.**

Why both local and GCP variants exist: local is faster to iterate (one developer's laptop). GCP is the production corpus for the headline numbers. Both share the exact same downstream processing in Stages 2-11.

---

## Stage 2 — Build per-run derived datasets

**Why:** the raw telemetry is huge (~30-40 GB) and not directly trainable. This stage converts each run into compact derived JSONL files: `triage_examples.jsonl` (features per window), `window_memory_matchings.jsonl` (mapping to gold Jira tickets), and a summary report.

**Input:** `data/runs/<run_id>/`
**Output:** `data/derived/<run_id>/triage_examples.jsonl`, `data/derived/<run_id>/window_memory_matchings.jsonl`

### 2.1 Build derived data for all runs

If you used the `-BuildTriage` flag in Stage 1, you already have these. If not, or you're starting from a published `data/runs/`:

```powershell
# Iterate over all runs
$runs = Get-ChildItem -Path "data\runs\2026-05-25-dataset-v5-large-*" -Directory

foreach ($run in $runs) {
    $runId = $run.Name
    Write-Host "Building derived for $runId..."

    pwsh -NoProfile -ExecutionPolicy Bypass `
      -File scripts\research-lab\build-triage-dataset.ps1 `
      -RunId $runId `
      -PythonExe .venv\Scripts\python.exe
}
```

**What each script does internally:**

1. `build_triage_dataset.py` reads `telemetry_windows.jsonl` + `raw/prometheus/*.json` + `raw/loki/*.json` + `raw/tempo/*.json`, computes 94 numeric features per window (CPU%, latency percentiles, error rates, restart counts, k8s events, etc.), and writes `triage_examples.jsonl` — one row per window with `feature_columns` + `triage_label` (noise / borderline / ticket_worthy).

2. `build_window_memory_matchings.py` reads `jira_shadow_issues.jsonl` (the gold ticket) and `episodes.jsonl` (the fault timeline), assigns the gold ticket ID to every ticket-worthy window that occurred during the fault. Writes `window_memory_matchings.jsonl` — one row per window with `matched_memory_issue_ids` (usually a single ID).

**Output per run:** ~50-100 windows in `triage_examples.jsonl`, ~30-80 ticket-worthy entries in `window_memory_matchings.jsonl`.

### 2.2 Verify the per-run output

```powershell
ls data\derived\2026-05-25-dataset-v5-large-control-r01\
# Expect: triage_examples.jsonl  window_memory_matchings.jsonl  summary.json
```

Sanity-check feature count:

```bash
python -c "import json; r=next(open('data/derived/2026-05-25-dataset-v5-large-control-r01/triage_examples.jsonl')); d=json.loads(r); print(len([k for k in d if k.startswith('triage_feature_')]), 'features')"
# Expect: 94 features
```

---

## Stage 3 — Build the global triage corpus

**Why:** TCH evaluates on a single train/val/test split spanning ALL runs, not per-run. This stage stitches every run's derived data into one global corpus, then splits it by **scenario family** (not by run) so the train and test sets share family but use different runs of that family.

**Input:** all `data/derived/<run_id>/triage_examples.jsonl` + `window_memory_matchings.jsonl`
**Output:** `data/derived/global/<global_id>/`

### 3.1 Run the global builder

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\build-global-triage-dataset.ps1 `
  -DatasetPrefix "2026-05-25-dataset-v5-large" `
  -GlobalDatasetId "2026-05-25-dataset-v5-large-global" `
  -PythonExe .venv\Scripts\python.exe
```

**What it does internally:**

1. Globs every `data/derived/2026-05-25-dataset-v5-large-*/triage_examples.jsonl`.
2. Concatenates them into `global-triage-examples.jsonl` (~7,400 windows for v5-large).
3. Computes the 94-column feature schema and writes `triage-feature-columns.json`.
4. Assigns each scenario family to train/validation/test deterministically (hash-based, biased toward train).
5. Writes `triage-split-manifest.json` — the split definition.
6. Builds `jira-memory-corpus.jsonl` — the 347 Jira shadow tickets collected across all runs, deduplicated by content hash.

**Why split by scenario family, not by run:** otherwise the test set has different runs of the same family in train, leaking information. We want the model to generalize across runs of a family.

### 3.2 Verify the global build

```bash
ls data/derived/global/2026-05-25-dataset-v5-large-global/
# Expect:
#   global-triage-examples.jsonl       <- one row per window with features
#   global-triage-build-manifest.json  <- summary stats
#   triage-feature-columns.json        <- 94 feature column names
#   triage-split-manifest.json         <- train/val/test family assignments
#   jira-memory-corpus.jsonl           <- 347 Jira shadow tickets
```

Confirm corpus size:

```bash
wc -l data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl
# Expect: ~7,400 lines

wc -l data/derived/global/2026-05-25-dataset-v5-large-global/jira-memory-corpus.jsonl
# Expect: 347 lines
```

---

## Stage 4 — Humanize the Jira memory corpus (LLM)

**Why:** the raw Jira shadow tickets are machine-generated from the fault injection (clean structure, terse language). Real Jira tickets are written by engineers — messy, conversational, sometimes incomplete. To train and evaluate retrieval on a realistic corpus, we use an LLM to rewrite each shadow ticket in an engineer's voice, producing the **V2 humanized corpus**.

**Input:** `data/derived/global/.../jira-memory-corpus.jsonl` (347 raw shadow tickets)
**Output:** `data/derived/global/.../jira-shadow-humanized-v2/bulk-20260531/` containing 347 humanized timelines

### 4.1 Run the bulk humanizer

```powershell
# Default: uses local Qwen via LM Studio. Make sure LM Studio is running.
python scripts\research-lab\humanize_v5_large_bulk.py `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --output-subdir jira-shadow-humanized-v2\bulk-20260531 `
  --llm-config v2
```

**What it does internally for each of the 347 tickets:**

1. Reads the shadow ticket + the source `data/runs/<id>/raw/loki/*.json` (logs from the fault window).
2. Calls the LLM 3-5 times with different "persona" prompts (junior engineer, senior SRE, on-call) and prompt styles (terse, verbose, with code snippets).
3. Each call emits a structured JSON timeline: title, description, comments, attachments, resolution.
4. The script merges these into one humanized ticket per shadow.

**Wall time:** ~80 minutes on RTX 5060 with Qwen 3.6 35B-A3B local. About 14 seconds per ticket × ~1.5 calls/ticket on average.

**Why this stage matters:** when we evaluate retrieval, the test window's evidence is "live" telemetry text. The memory it retrieves against is humanized Jira (engineer voice). The mismatch in style is what makes retrieval hard — and what makes TCH's results realistic.

### 4.2 Verify the humanized output

```bash
ls data/derived/global/2026-05-25-dataset-v5-large-global/jira-shadow-humanized-v2/bulk-20260531/
# Expect:
#   timeline.jsonl            <- one row per humanized ticket
#   generation-manifest.json  <- stats and LLM config used
#   progress.log              <- live log from the run

wc -l data/derived/global/.../jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl
# Expect: 347 lines

python -c "import json; r=json.loads(next(open('data/derived/global/2026-05-25-dataset-v5-large-global/jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl'))); print(list(r.keys()))"
# Expect: ['ticket_id', 'title', 'description', 'comments', ...]
```

### 4.3 (Optional) Generate distractors

For Phase D's distractor-robustness experiments (not needed for the headline TCH numbers, but required to reproduce the distractor sweep):

```bash
python scripts/research-lab/mint_v2_distractors.py \
  --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
  --n 110 \
  --output-subdir jira-shadow-humanized-v2-distractors/bulk-20260531
```

This produces 110 plausible-looking Jira tickets that are NOT real incidents from our runs — used to measure how the retrievers degrade as we inject noise into the memory.

---

## Stage 5 — Extract structured info via LLM (Phase D)

**Why:** the `kg_retrieval` pipeline needs structured fields (affected services, error classes, root cause, fix kind, symptoms) for each Jira ticket. Extracting these from humanized text by hand is impractical. We use the LLM to do it.

**Input:** `data/derived/global/.../jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl` (347 humanized tickets)
**Output:** `data/derived/global/.../v2_kg_extractions/all_extractions.jsonl`

### 5.1 Run the LLM ticket extractor

```powershell
# Make sure LM Studio is running with Qwen 35B-A3B loaded
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --humanized-subdir jira-shadow-humanized-v2\bulk-20260531 `
  --output-subdir v2_kg_extractions
```

**What it does internally for each of the 347 tickets:**

1. Loads the humanized ticket text.
2. Calls Qwen via LM Studio with `enable_thinking=False` (no chain-of-thought, fast path) and a strict JSON schema (`TICKET_EXTRACTION_SCHEMA` in `src/v2_advanced/shared/json_schemas.py`).
3. The schema forces the LLM to emit exactly: `affected_services`, `components`, `error_classes`, `root_cause`, `fix`, `fix_kind`, `symptoms`.
4. A canonical-services prompt block tells the LLM the 12 valid service names (e.g. `cartservice`, `checkoutservice`) so it doesn't paraphrase.
5. Writes one JSON line per ticket to `all_extractions.jsonl`.

**Wall time:** ~80 minutes. ~14 seconds per ticket, 0 failures with strict schema mode.

**Why a strict schema:** LM Studio's `response_format` with `strict: true` grammar-constrains generation to match the schema. The LLM literally cannot emit invalid JSON. This was crucial for reliability — without it ~5-10% of calls produced free-text wrapping.

### 5.2 Verify the extractions

```bash
wc -l data/derived/global/2026-05-25-dataset-v5-large-global/v2_kg_extractions/all_extractions.jsonl
# Expect: 347 lines

python -c "import json; r=json.loads(next(open('data/derived/global/2026-05-25-dataset-v5-large-global/v2_kg_extractions/all_extractions.jsonl'))); print(r.keys()); print('services:', r.get('affected_services'))"
# Expect keys: dict_keys(['ticket_id', 'affected_services', 'components', 'error_classes', 'root_cause', 'fix', 'fix_kind', 'symptoms'])
```

### 5.3 (Optional but recommended) Also extract via rules for comparison

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_rulebased_cli `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --humanized-subdir jira-shadow-humanized-v2\bulk-20260531 `
  --output-subdir v2_kg_extractions_rules
```

This produces a rule-extracted variant (7 generic symptoms, 6 components). The comparison between rule and LLM extractions is documented in `docs3/14-LLM-GRAPH-FINDINGS.md`.

---

## Stage 6 — Load the Neo4j knowledge graph

**Why:** the `kg_retrieval` pipeline queries Neo4j with Cypher. We need to load the extracted entities and relationships into the database.

**Input:** `data/derived/global/.../v2_kg_extractions/all_extractions.jsonl`
**Output:** populated Neo4j graph (in-database, accessible at `bolt://127.0.0.1:7687`)

### 6.1 Load the LLM-extracted graph

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --source llm
```

**What it does internally:**

1. Connects to Neo4j at `bolt://127.0.0.1:7687` (user `neo4j`, password `123456789`).
2. Wipes any prior content (`MATCH (n) DETACH DELETE n`).
3. For each of the 347 extracted tickets, creates: `Incident` node, `Service` nodes, `Component` nodes, `ErrorClass` nodes, `RootCause` node, `Fix` node, `Symptom` nodes.
4. Creates relationships: `Incident-AFFECTS-Service`, `Incident-OBSERVED-Component`, `Incident-MANIFESTED-ErrorClass`, `Incident-HAS_ROOT_CAUSE-RootCause`, `Incident-FIXED_BY-Fix`, `Incident-HAS_SYMPTOM-Symptom`.

**Expected graph size (LLM source):** 347 Incidents, 12 Services, 27 Components, 15 ErrorClasses, 343 RootCauses, 313 Fixes, 803 Symptoms.

### 6.2 Verify the graph

Open Neo4j Browser at <http://localhost:7474> and run:

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n ORDER BY n DESC
```

Expected output (LLM graph):

| label | n |
|---|---:|
| Symptom | 803 |
| RootCause | 343 |
| Incident | 347 |
| Fix | 313 |
| Component | 27 |
| ErrorClass | 15 |
| Service | 12 |

### 6.3 (Optional) Swap to rule-extracted graph

If you want to reproduce the rule-vs-LLM comparison:

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --source rules
```

Wipes the LLM graph, loads the rule graph (7 Symptoms vs 803, 6 Components vs 27). Re-run with `--source llm` to switch back.

---

## Stage 7 — The v2 in-distribution re-split

**Why:** the default global split assigns whole scenario families to test (orphan-family setup). This is the right setup for "can the model generalize to a new failure type" but wrong for "can the model retrieve same-family incidents from different runs". Our TCH headline uses the **in-distribution split** — same families in train and test, different runs.

**Input:** `data/derived/global/.../triage-split-manifest.json` (the default split)
**Output:** `data/derived/global/.../triage-split-manifest-v2-resplit.json` (new split definition with 4701 train / 1011 val / 1008 test)

### 7.1 Run the re-split

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_resplit `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global
```

**What it does internally:**

1. Reads `global-triage-examples.jsonl` (~7,400 windows).
2. For each scenario family, randomly assigns runs to train (70%) / val (15%) / test (15%) with `random_state=42`.
3. Writes the new manifest as `triage-split-manifest-v2-resplit.json`.

**Why a separate manifest:** the orphan-family default split is still useful for novelty evaluation. We keep both manifests side by side and `monkey-patch` the loader at run-time to use the v2 manifest (see `src/v2_advanced/proposal_a_resplit/window_split.py`).

### 7.2 Verify the split

```bash
python -c "import json; m=json.load(open('data/derived/global/2026-05-25-dataset-v5-large-global/triage-split-manifest-v2-resplit.json')); print({k: len(v) for k,v in m['windows'].items()})"
# Expect: {'train': 4701, 'validation': 1011, 'test': 1008}
```

---

## Stage 8 — Train the underlying pipelines

**Why:** TCH consumes the per-window predictions of 6 underlying pipelines. We need to train each one on the v2 train split and run inference on the test split. This is the most compute-heavy stage (~30-45 min on RTX 5060).

**Input:** v2-resplit manifest + humanized memory + Neo4j graph
**Output:** `data/derived/global/.../comparison/<dir>/per-window-predictions.jsonl` for each pipeline

### 8.1 Train and evaluate the broad panel (HGB, TabTransformer, bi_encoder, memorygraph)

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines hist_gradient_boosting_numeric,tab_transformer,bi_encoder_retrieval,memorygraph_v2_sota_nw080 `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2a-resplit
```

**What each pipeline does:**

- **`hist_gradient_boosting_numeric`** (HGB): trains sklearn `HistGradientBoostingClassifier` on 94 numeric features. ~5 seconds. Produces triage_score per window.
- **`tab_transformer`**: trains a small FT-Transformer on the same features. ~3 min. (We don't use this in TCH, but include for the comparison.)
- **`bi_encoder_retrieval`**: fine-tunes MiniLM-L6-v2 with `MultipleNegativesRankingLoss` for 3 epochs on `(window, gold_ticket)` pairs. ~15 min on RTX 5060. Produces top-10 ranked tickets per window.
- **`memorygraph_v2_sota_nw080`**: BM25 + entity graph + cross-encoder rerank with `nw=0.80` blend weight. ~5 min. (Used in TCH only marginally; main retrieval is via the 4-retriever fusion.)

**Output:** `comparison/v2a-resplit/per-window-predictions.jsonl` with 4 × 1008 = 4032 rows.

### 8.2 Train and evaluate logseq2vec

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_b_logseq2vec.run_logseq2vec `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2b-logseq2vec
```

**What it does:** trains a small transformer (4 layers, 2 heads) over tokenized log sequences for 5 epochs (~14 min on RTX 5060). Outputs top-10 ranked tickets per window via embedding similarity.

### 8.3 Run hybrid_rrf with both graph variants

First with the rule graph (must reload Neo4j first):

```powershell
# Reload Neo4j with rule graph
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --source rules

# Run hybrid pipeline
PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines hybrid_rrf_no_graph,hybrid_rrf_retrieval `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2c-hybrid
```

Then with the LLM graph:

```powershell
# Switch Neo4j to LLM graph
PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --source llm

# Run hybrid pipeline again
PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines hybrid_rrf_retrieval `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2c-hybrid-llm
```

**Each takes ~15 min wall:** SPLADE indexing (22 s) + BiEncoder fine-tune (10 min) + graph queries + RRF fusion.

### 8.4 Run kg_retrieval (rulebased variant)

```powershell
PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines kg_retrieval_rulebased `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2d-kg-rulebased
```

**What it does:** uses rule-extracted entities from the live window + Cypher queries against the loaded Neo4j graph to find structurally similar past incidents. ~5 min.

### 8.5 Verify all pipeline outputs

```bash
ls data/derived/global/2026-05-25-dataset-v5-large-global/comparison/
# Expect at least:
#   v2a-resplit/
#   v2b-logseq2vec/
#   v2c-hybrid/
#   v2c-hybrid-llm/
#   v2d-kg-rulebased/
```

Each directory has `per-window-predictions.jsonl`. The cascade in Stage 10 consumes all of these.

---

## Stage 9 — Run the DiagnosisAgent (LLM)

**Why:** the agent provides the `is_novel` signal — a capability no retriever can match. We run it on a strategically-chosen subset of windows because it's expensive (~30 s per window with thinking on).

**Input:** v2-resplit test windows + LLM-extracted memory + LM Studio
**Output:** `data/derived/global/.../comparison/v2e-agent-llm/per-window-predictions.jsonl` (200 random windows) and `comparison/v2e-agent-phase2/...` (150 hard-case windows)

### 9.1 Phase 1 — random 200-window subsample

```powershell
# Ensure LM Studio is running and Qwen is loaded.
# We use cached hybrid predictions to skip the BiEncoder refit (which would OOM if LLM is in VRAM).

V2_AGENT_HYBRID_PREDICTIONS_PATH="data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2c-hybrid-llm/per-window-predictions.jsonl" `
PYTHONPATH=src python -W ignore -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines diagnosis_agent `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2e-agent-llm
```

**What it does for each of 200 randomly-sampled windows:**

1. **Stage 1 — Hypothesize.** LLM call with `enable_thinking=False` and `HYPOTHESIZE_SCHEMA`. Outputs `{root_cause_hypothesis, key_symptoms, suspected_services}`. ~1 second per window.
2. **Stage 2 — Retrieve.** No LLM call. Reads candidates from the cached hybrid_rrf predictions.
3. **Stage 3 — Verify.** LLM call with `enable_thinking=True`, `max_tokens=1500`, and `VERIFY_SCHEMA`. Asks "are any of these 10 candidates consistent with the hypothesis?" Outputs `{ranked: [{ticket_id, confidence, consistent, reason}, ...], novel: bool}`. ~30 seconds per window.

**Wall time:** ~110 minutes total. ~31 seconds per window × 200.

### 9.2 Phase 2 — hard-case 150-window targeted run

After Stage 10 below produces the Phase 1 cascade output, we'll use it to pick the 150 windows with the LOWEST L2 retrieval confidence (most likely novel):

```powershell
# This step is included here for completeness but the input file must be produced by Stage 10 first.
# After running Stage 10 (Phase 1 cascade), the file phase2_window_ids.txt will be populated.

V2_AGENT_HYBRID_PREDICTIONS_PATH="data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2c-hybrid-llm/per-window-predictions.jsonl" `
V2_AGENT_WINDOW_IDS_PATH="data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2f-tch-phase1/phase2_window_ids.txt" `
PYTHONPATH=src python -W ignore -m v2_advanced.proposal_a_resplit.run_v2_comparison `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --runs-root data\runs `
  --pipelines diagnosis_agent `
  --no-ensemble --no-lofo `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2e-agent-phase2
```

**Wall time:** ~86 minutes.

**Why two phases:** Phase 1 (random 200) gives a representative baseline for agent metrics. Phase 2 (hard-case 150) is where the agent's novelty signal pays off most — these windows are 77% truly-novel by gold, so the agent fires correctly more often. Combined, agent coverage is 350/1008 windows.

---

## Stage 10 — Build and verify the TCH cascade

**Why:** this is where everything comes together. The cascade reads all the per-window predictions from Stages 8-9 and produces the final TCH output.

**Input:** all `comparison/<dir>/per-window-predictions.jsonl` files
**Output:** `data/derived/global/.../comparison/v2f-tch-phase1/` with the final cascade

### 10.1 Build Phase 1 cascade (without Phase 2 agent yet)

```powershell
PYTHONPATH=src python -m v2_advanced.tch.build_cascade `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2f-tch-phase1
```

**What it does internally:**

1. Loads predictions from 9 source pipelines (HGB, bi_encoder, hybrid_rrf rule, hybrid_rrf llm, logseq2vec, kg_retrieval, memorygraph SOTA, hybrid_rrf no-graph, diagnosis_agent if present) into a unified `WindowState` per window.
2. Runs the L4 stacker: 5-fold CV LogisticRegression on the 6 per-pipeline triage scores. Each window gets an out-of-fold predicted probability.
3. For each window, assembles the cascade prediction (L1 + L2 + L3 + L4).
4. Writes `per-window-predictions.jsonl`, `tch_metrics.json`, `report.md`, `stacker.pkl` (deployable trained stacker), and `phase2_window_ids.txt` (bottom 150 by L2 confidence — feeds Stage 9.2).

**Wall time:** ~252 ms for all 1008 windows (yes, milliseconds — no GPU, no LLM).

### 10.2 Phase 2 integration

Run Stage 9.2 if you haven't (uses the `phase2_window_ids.txt` produced above). Then re-run `build_cascade` — the `EXTRA_AGENT_FILES` list in `src/v2_advanced/tch/build_cascade.py` automatically merges Phase 2's predictions:

```powershell
PYTHONPATH=src python -m v2_advanced.tch.build_cascade `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global `
  --output-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2f-tch-phase1
```

Agent coverage now jumps from 200 to 350 windows; novelty recall lifts from 13.4% to 16.2%.

### 10.3 Run the regression check

```powershell
PYTHONPATH=src python -m v2_advanced.tch.check_cascade `
  --cascade-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2f-tch-phase1
```

**Expected output:**

```
metric                      actual    expected      tol  status
hit_at_1                    0.7069      0.7069    0.001  OK
hit_at_5                    0.9124      0.9124    0.001  OK
mrr                         0.7880      0.7880    0.001  OK
pr_auc                      0.9998      0.9998    0.001  OK
pr_auc_inclusive            0.8527      0.8527    0.005  OK
novel_precision             0.9402      0.9479    0.010  OK
novel_recall                0.1625      0.1344    0.020  OK
All TCH headline metrics pass the regression check.
```

If any check fails, the previous stages produced different output than ours — investigate the stage that fed that metric.

### 10.4 One-shot rebuild + check + analyze

The `finalize.py` script does all three in sequence:

```powershell
PYTHONPATH=src python -m v2_advanced.tch.finalize `
  --global-dir data\derived\global\2026-05-25-dataset-v5-large-global
```

This is the command to use after any change that could affect the cascade.

---

## Stage 11 — Reproduce the headline numbers

### 11.1 Bootstrap confidence intervals + per-stratum breakdowns

```powershell
PYTHONPATH=src python -m v2_advanced.tch.analyze_cascade `
  --cascade-dir data\derived\global\2026-05-25-dataset-v5-large-global\comparison\v2f-tch-phase1 `
  --comparison-base data\derived\global\2026-05-25-dataset-v5-large-global\comparison
```

**Expected highlights:**

```
=== Headline with 95% bootstrap CIs (1000 resamples, paired) ===
TCH                     0.707 [0.656,0.752]  0.913 [0.882,0.943]  0.788 [0.748,0.823]
bi_encoder              0.695 [0.644,0.743]  0.789 [0.746,0.834]  0.729 [0.684,0.773]
...

=== TCH minus baseline (paired delta, 95% bootstrap CI) ===
bi_encoder              +0.012 [-0.012,+0.033]  +0.125 [+0.088,+0.163]  +0.060 [+0.040,+0.079]
hybrid_rrf_rule         +0.123 [+0.069,+0.175]  +0.115 [+0.078,+0.154]  +0.118 [+0.081,+0.156]
```

Bold = statistically significant (CIs exclude zero). TCH significantly beats every baseline on Hit@5 and MRR; matches bi_encoder on Hit@1.

### 11.2 Reproduce all the auxiliary figures

```bash
# Per-family Hit@5 table → docs3/16-TCH-CASCADE.md §11
# Per-window-type breakdown → docs3/16-TCH-CASCADE.md §11
# Depth curve (Sub-claim 1 of RESEARCH-CHARTER) → docs3/16-TCH-CASCADE.md §11
# Failure analysis (10 missed windows) → docs3/16-TCH-CASCADE.md §12
```

All produced by the same `analyze_cascade.py` script above.

---

## Adapting the pipeline to your own data

You don't have OpenTelemetry-instrumented Online Boutique. You have your own production telemetry + Jira project. Here's what changes by stage:

### Stage 1 (collect raw runs) — replace entirely

Skip the kind cluster. Your "raw runs" are:

- **Loki**: existing log infrastructure. Export 5-minute slices around incidents as JSON.
- **Prometheus / Grafana**: same — export numeric metrics as JSON over the same window.
- **Tempo / Jaeger**: trace spans for the window.
- **kubernetes events**: `kubectl get events --field-selector involvedObject.namespace=YOUR-NS -o json` for each window.

Lay them out matching our schema:

```
data/runs/<your_incident_id>/
  manifest.json
  episodes.jsonl           <- one row per "phase" (pre-fault, active, recovery)
  telemetry_windows.jsonl  <- one row per 5-minute slice
  jira_shadow_issues.jsonl <- the gold Jira ticket for this incident (your real ticket)
  raw/
    loki/*.json
    prometheus/*.json
    tempo/*.json
    kubernetes/*.json
```

See `docs/triage-task-contract.md` for the exact field schemas.

### Stage 2 (per-run derived) — works as-is

`build_triage_dataset.py` computes features from the raw payloads. If your raw schema matches, no changes. If different, adapt the feature extractors in `src/loganalyzer/`.

### Stage 3 (global build) — works as-is

Scenario family in your data = something like "service-X-deadline-exceeded" or "memory-saturation" — a logical incident class. The script just groups by the `scenario_family` field in your manifests.

### Stage 4 (humanize) — replace entirely

You probably ALREADY have humanized Jira tickets — they're real Jira. Skip the LLM humanization. Point `jira-shadow-humanized-v2/` at a JSONL file of your existing tickets where each row has `ticket_id, title, description, comments`.

### Stage 5 (LLM extraction) — works as-is

Just point at your humanized Jira corpus. The strict-schema extraction will pull `affected_services`, `root_cause`, etc. from any text. Update the canonical-services list in `src/v2_advanced/proposal_d_knowledge_graph/extractor.py` to your service names.

### Stage 6 (Neo4j load) — works as-is

Same loader runs against your extractions.

### Stage 7-10 — works as-is

All the modeling stages are dataset-agnostic. Just re-run with your global ID.

### Stage 11 (reproduce numbers) — your numbers will differ

That's the point — you're producing YOUR cascade numbers on YOUR data. The regression-check tolerances in `check_cascade.py` will need to be relaxed (they're locked to our v2 numbers). Update them after your first full run to lock your own expected values.

---

## Troubleshooting

### "CUDA out of memory" during BiEncoder fine-tune

LM Studio's Qwen is hogging VRAM. Either:

- **Quick fix:** eject the model in LM Studio (click "Stop" in the server panel), run the BiEncoder fine-tune, then reload Qwen.
- **Permanent fix:** use `V2_AGENT_HYBRID_PREDICTIONS_PATH` env var to skip BiEncoder retraining when the agent runs (see Stage 9.1).

### "LM Studio HTTP 400 Bad Request"

The strict JSON schema feature requires LM Studio v0.3+ and a model that supports structured output. Open the Inference tab in LM Studio and verify "Structured Output" is enabled. Restart the server.

### "Neo4j connection refused"

The database isn't running, or the password is wrong. Open Neo4j Desktop / Neo4j Browser and confirm the bolt://127.0.0.1:7687 endpoint is up with user `neo4j` and password `123456789` (or change the credentials in `src/v2_advanced/proposal_d_knowledge_graph/loader.py`).

### "build_cascade KeyError: 'pipeline_name'"

A source pipeline's per-window predictions are missing or corrupt. Re-run that pipeline from Stage 8.

### Regression check fails on novel_recall

Phase 2 lifted novel_recall from 0.134 → 0.162, which is above the upper bound of the tolerance window (0.134 ± 0.020 = 0.154). The expected value in `check_cascade.py` is from Phase 1. If you've already run Phase 2, update `EXPECTED["novel_recall"] = (0.1625, 0.020, "higher_better")`.

### "Module not found: v2_advanced"

Set `PYTHONPATH=src` (or `set PYTHONPATH=src` on Windows cmd). The repo uses src-layout.

---

## Total time budget

| Path | Stage | Wall-clock | Compute |
|---|---|---|---|
| **Path A (full reproduction)** | Stage 1 — local kind | 6-8 hrs | local machine |
| | Stage 1 — GCP VM v5-large | 4-5 days | GCP `e2-standard-8` |
| | Stages 2-3 | ~30 min | local CPU |
| | Stage 4 — LLM humanize | ~80 min | LM Studio + RTX 5060 |
| | Stage 5 — LLM extract | ~80 min | LM Studio + RTX 5060 |
| | Stages 6-7 | ~2 min | local CPU |
| | Stage 8 — train pipelines | ~45 min | RTX 5060 |
| | Stage 9.1 — agent Phase 1 | ~110 min | LM Studio |
| | Stage 9.2 — agent Phase 2 | ~86 min | LM Studio |
| | Stage 10 — cascade + finalize | ~10 sec | local CPU |
| | Stage 11 — analyze | ~5 sec | local CPU |
| | **Total Path A (local)** | **~13-15 hrs** | **single machine** |
| | **Total Path A (with GCP for Stage 1)** | **~5 days** | **GCP + local** |
| **Path B (skip Stage 1)** | Stages 2-11 | ~7 hrs | local + RTX 5060 |

The biggest costs are LLM-related (humanize + extract + agent). If you have a faster GPU or a hosted LLM API, these scale linearly.

---

## What you should have at the end

```
data/derived/global/2026-05-25-dataset-v5-large-global/
├── global-triage-examples.jsonl                          # 7,400 windows
├── jira-memory-corpus.jsonl                              # 347 shadow tickets
├── triage-split-manifest-v2-resplit.json                 # 4701/1011/1008 split
├── jira-shadow-humanized-v2/bulk-20260531/timeline.jsonl # 347 humanized
├── v2_kg_extractions/all_extractions.jsonl               # 347 LLM extractions
├── v2_kg_extractions_rules/all_extractions.jsonl         # 347 rule extractions
└── comparison/
    ├── v2a-resplit/per-window-predictions.jsonl          # HGB + TabT + bi_enc + mg
    ├── v2b-logseq2vec/per-window-predictions.jsonl       # logseq2vec
    ├── v2c-hybrid/per-window-predictions.jsonl           # hybrid_rrf rule + no-graph
    ├── v2c-hybrid-llm/per-window-predictions.jsonl       # hybrid_rrf LLM
    ├── v2d-kg-rulebased/per-window-predictions.jsonl     # kg retrieval
    ├── v2e-agent-llm/per-window-predictions.jsonl        # agent Phase 1 (200 windows)
    ├── v2e-agent-phase2/per-window-predictions.jsonl     # agent Phase 2 (150 windows)
    └── v2f-tch-phase1/                                   # FINAL TCH CASCADE
        ├── per-window-predictions.jsonl                  # 1008 cascade outputs
        ├── tch_metrics.json                              # Hit@1=0.707, Hit@5=0.912, ...
        ├── report.md                                     # human-readable report
        ├── stacker.pkl                                   # deployable L1 stacker
        └── phase2_window_ids.txt                         # 150 hard-case window IDs
```

Plus Neo4j has the 803-symptom LLM-extracted graph loaded, and LM Studio has Qwen 3.6 35B-A3B available.

That's everything needed to reproduce TCH from scratch, and the same pipeline applies to any organization's telemetry + Jira data.

---

*Last updated 2026-06-04. Cross-references: `docs3/16-TCH-CASCADE.md` for the cascade design rationale, `docs3/17-FINAL_HYBRID.md` for the plain-English guide, `docs/gcp-production-dataset-vm-runbook.md` for the GCP collection runbook, `docs/dataset-v5-quick-runbook.md` for the local-kind quick variant, `docs/triage-task-contract.md` for the data schema.*
