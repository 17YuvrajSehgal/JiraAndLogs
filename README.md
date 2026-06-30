# Memory-Augmented Agentic Incident Triage

Research artifact for an ICSE submission on **agentic incident triage**: a
capability-gated controller that retrieves similar past incidents from a memory
of resolved tickets (dense + sparse + knowledge-graph fusion), triages new
telemetry windows, and suppresses duplicate pages — evaluated on two synthetic
datasets and one **real** Apache-Jira dataset.

## Headline results (real-data WoL, coarse Hit@5)

| System | WoL (real) | Online-Boutique | OTel-Demo |
|---|---|---|---|
| **Hybrid-RRF (ours)** | **0.970** | 0.559 | 0.672 |
| BiEncoder | 0.905 | 0.634 | 0.681 |
| LLM-RAG (Qwen2.5-7B rerank) | 0.856 | 0.344 | 0.639 |
| BM25 | 0.727 | 0.356 | 0.597 |
| KG-alone | 0.308 | 0.465 | 0.412 |
| **Agent (end-to-end)** | **0.963** | 0.758 | 0.756 |

On WoL, Hybrid-RRF beats every baseline with **q≈0 after Benjamini–Hochberg**
correction; the controller cuts cost **~78%** vs running every skill at
iso-accuracy. Full numbers, CIs, and honest negatives are in
[`paper-results/`](paper-results/README.md).

## Repository layout

```
src/                  library code (agent, retrieval pipelines, comparison harness, metrics)
scripts/
  research-lab/       result-collection runners + Trillium (Slurm) sbatch scripts
  agent/              agent eval + cost/ablation/bootstrap analyses
paper-results/        ← the publishable result set (committed; bulky preds/traces gitignored)
data/derived/global/  the three datasets (gitignored; published as an archive — see below)
DOCS/                 design notes, dataset docs, review, audit, reproduction guide
deploy/research-lab/  in-job Neo4j (Apptainer) for the graph retriever
```

## Datasets

| name | scope | memory / test windows | license |
|---|---|---|---|
| `online-boutique` (`2026-05-25-dataset-v5-large-global`) | synthetic (GKE μ-services) | 347 / 1008 | CC BY 4.0 |
| `otel-demo` (`2026-06-09-otel-demo-v1-global`) | synthetic (OpenTelemetry demo) | 147 / 247 | CC BY 4.0 |
| `wol-v3` (`2026-06-17-wol-real-v3-global`) | **real** Apache Jira, 24 projects | 38,642 / 13,388 | CC BY 4.0 (derived); see `DOCS/WoL-v3-dataset.md` |

Datasets are large (WoL ≈ 5 GB) and ship as a separate archive — see
[`DOCS/PUBLICATION.md`](DOCS/PUBLICATION.md). Each dataset directory has its own
`README.md` and build provenance.

## Reproduce

1. Environment: `python/3.12` + `arrow/21.0.0`; `pip install --no-index` against
   the frozen env in [`paper-results/provenance/venv-freeze.txt`](paper-results/provenance/venv-freeze.txt).
2. `export PYTHONPATH=src` and set HF offline (`HF_HUB_OFFLINE=1`).
3. Run a result family — full script→result map in
   [`DOCS/REPRODUCE.md`](DOCS/REPRODUCE.md). On Slurm, use the
   `scripts/research-lab/trillium_*.sbatch` jobs. All runs use **seed 42** and
   the configs in [`paper-results/provenance/config.json`](paper-results/provenance/config.json).
4. Aggregate: `python scripts/research-lab/build_paper_summaries.py` regenerates
   every `paper-results/**/SUMMARY.md`.

## Documentation
- [`DOCS/REPRODUCE.md`](DOCS/REPRODUCE.md) — script → result map + commands
- [`DOCS/threats-to-validity.md`](DOCS/threats-to-validity.md) — scoping & limitations
- [`DOCS/agentic-system.md`](DOCS/agentic-system.md) — system design

## License
Code: **MIT** ([`LICENSE`](LICENSE)). Datasets & derived results: **CC BY 4.0**.
(If your institution requires it, the code license can be switched to Apache-2.0.)

## Citation
See `CITATION.cff` (add on acceptance).
