# Reproducibility Checklist — ICSE 2027 Submission

This checklist lets reviewers re-derive every reported number from the public artifacts. It maps each paper claim to a specific git commit and a specific results file.

## End-to-end reproduction

### 1. Hardware

- Single machine
- CPU: any x86_64 supporting AVX2 (Windows 11 in our case)
- GPU: NVIDIA RTX 5060 Laptop (8 GB VRAM) — required for full neural fine-tune. CPU-only works but BiEncoder fine-tune takes ~10x longer.
- RAM: ≥ 16 GB
- Disk: ~5 GB for the dataset + ~200 MB for fine-tuned model checkpoints

### 2. Environment

```powershell
# Python 3.13+ with the project venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # includes torch, sentence-transformers, accelerate, datasets, matplotlib, sklearn

# Key versions (locked):
# torch 2.12+cu128
# sentence-transformers 5.5+
# accelerate 1.13+
# datasets 4.8+
# transformers 5.x
# scikit-learn 1.5+
```

### 3. Dataset

Pull the synthetic-but-realistic dataset from `data/derived/global/2026-05-25-dataset-v5-large-global/`. Critical files:

```
data/derived/global/<id>/
├── global-triage-examples.jsonl       # 6720 windows with 94 numeric features each
├── triage-feature-columns.json        # ordered list of the 94 columns
├── triage-split-manifest.json         # train/val/test split + LOFO folds
├── window-memory-matchings.jsonl      # gold (window -> compatible memory ticket IDs)
├── jira-memory-corpus.jsonl           # legacy metadata reference
├── jira-shadow-humanized-v2/
│   └── bulk-20260531/timeline.jsonl   # 347 V2 humanized tickets
└── jira-shadow-humanized-v2-distractors/
    └── mint-20260601/timeline.jsonl   # 110 distractor tickets
```

### 4. Comparison runs

| Paper section | Command (executed verbatim) | Output |
|---|---|---|
| §5.1 Anchor (Phase A) | `python -m comparison.cli --pipelines hgb,memorygraph_v2_sota_nw080 --output-dir .../comparison/phase-a-anchor --n-bootstrap 1000` | `phase-a-anchor/{report.json, per-window-predictions.jsonl}` |
| §5.2 Fine-tuned cross-encoder (Phase B) | `python -m comparison.cli --pipelines hgb,memorygraph_v2_sota_nw080,memorygraph_v2_sota_nw080_ft --output-dir .../comparison/phase-b-finetune --n-bootstrap 1000` | `phase-b-finetune/` |
| §5.4 Channel ablation (Phase C) | `python -m comparison.cli --pipelines memorygraph_v2_sota_nw080,memorygraph_v2_sota_nw080_no_logs,memorygraph_v2_sota_nw080_no_traces,memorygraph_v2_sota_nw080_no_k8s --output-dir .../comparison/phase-c-channels --n-bootstrap 500` | `phase-c-channels/` |
| §5.5 Distractor robustness (Phase D) | `python -m comparison.cli --pipelines memorygraph_v2_sota_d000pct,memorygraph_v2_sota_d010pct,memorygraph_v2_sota_d025pct,memorygraph_v2_sota_d050pct --output-dir .../comparison/phase-d-distractors --n-bootstrap 500` | `phase-d-distractors/` |
| §5b Neural models (Phase G) | `python -m comparison.cli --pipelines hgb,tab_transformer,memorygraph_v2_sota_nw080,bi_encoder_retrieval --output-dir .../comparison/phase-g-neural --n-bootstrap 1000` | `phase-g-neural/` |

All commands prefixed with `PYTHONPATH=src python -W ignore -m comparison.cli ...` and the standard environment variables:
- `HF_HUB_DISABLE_SYMLINKS_WARNING=1`
- `TRANSFORMERS_VERBOSITY=error`

### 5. Figures

After each run, regenerate figures:

```powershell
# Headline depth curve (anchor figure)
python scripts/depth_analysis.py `
    --predictions data\...\comparison\phase-g-neural\per-window-predictions.jsonl `
    --out-json results\phase-g-neural\depth_analysis.json `
    --out-md results\phase-g-neural\depth_analysis.md `
    --fig-dir results\figures `
    --n-resamples 1000

# Combined 3-panel anchor figure (Hit@1, Hit@5, MRR side by side)
python scripts\figures\combined_depth_curve.py `
    --predictions data\...\comparison\phase-g-neural\per-window-predictions.jsonl `
    --out results\figures\anchor_combined.png

# Diagnosis time bar chart
python -m util.diagnosis_sim `
    --predictions data\...\comparison\phase-g-neural\per-window-predictions.jsonl `
    --out results\phase-e-utility\diagnosis_sim_phase-g.json `
    --out-md results\phase-e-utility\diagnosis_sim_phase-g.md
python scripts\figures\diagnosis_chart.py `
    --sim results\phase-e-utility\diagnosis_sim_phase-g.json `
    --out results\figures\diagnosis_time.png
```

### 6. Tracing every number to a git commit

Every pipeline fit writes its config to:

```
data/derived/global/<global_id>/training_runs/<pipeline>__<UTC>__<sha8>/config.json
```

This file contains:

```json
{
  "run_id": "bi_encoder_retrieval__20260602T134941Z__b36d9cbd",
  "pipeline_name": "bi_encoder_retrieval",
  "started_at": "2026-06-02T13:49:41.860068+00:00",
  "git_sha": "b36d9cbd1e2f456abc...",
  "python_version": "3.14.3 (...)",
  "pipeline_class": "BiEncoderRetrievalPipeline",
  "global_dir": "data\\derived\\global\\2026-05-25-dataset-v5-large-global",
  "target_fpr": 0.05
}
```

Reviewers can `git checkout <git_sha>` and re-run the exact pipeline command above to reproduce.

## Sanity checks

After re-running, verify these invariants hold:

1. Every per-window-predictions.jsonl has exactly **2940 unique `window_id`** per pipeline.
2. The retrievable subset (gold_label=ticket_worthy AND gold_matched_issue_ids non-empty) has **317 entries** per pipeline.
3. HGB and TabTransformer have `matched_issue_ids = []` always (no retrieval head).
4. SOTA and BiE always have `matched_issue_ids` of length 5 (top-5).
5. The headline depth curve (HGB at 0 across all buckets, SOTA/BiE monotone-rising) is visually monotone except for confidence-interval-explained dips at the smallest buckets (n_retrievable = 28 at the 21+ bucket).

## Known sources of non-determinism

- **CUDA kernel launch order** — bitwise-different floating-point results across runs at the same seed. Magnitude << bootstrap CI width.
- **GPU memory pressure** — if LM Studio or another process loads the GPU between pipelines, runtime varies; results do not.
- **HF hub network access** — first run downloads MiniLM-L6-v2 (~80 MB) and the cross-encoder (~80 MB). Subsequent runs hit the local cache.
- **OS-level thread scheduling** — BM25 indexing in the BiEncoder pair builder is single-threaded; multi-thread parallelism is not used. Determinism preserved.

## Released artifacts

Following ICSE's Artifacts track conventions, the public repository (URL redacted in submission) contains:

- All source under `src/` (pipelines, neural models, comparison harness)
- All comparison outputs under `data/derived/global/<id>/comparison/phase-{a,b,c,d,g}-*/` (predictions.jsonl + report.json + report.md)
- All training-run directories under `training_runs/`
- All figures under `results/figures/`
- The locked research charter `RESEARCH-CHARTER.md` from 2026-06-01 (pre-results)
- This `docs3/` directory containing the model architecture / data flow / training recipe / GPU usage / experimental protocol / reproducibility checklist
- The full ICSE LaTeX source under `paper/`

Large binary artifacts (the BiEncoder model.safetensors, the cross-encoder fine-tuned model.safetensors, the raw 50M-row Loki logs) are gitignored due to size but are reproducible from the source + dataset.
