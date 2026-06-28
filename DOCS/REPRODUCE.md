# Reproduction guide

Every result in `paper-results/` with the exact script that produces it. All runs
use **seed 42** and the configs in `paper-results/provenance/config.json`.
Datasets live under `data/derived/global/<DSID>/` (see `DOCS/PUBLICATION.md` to
obtain them).

## Environment
```bash
module load python/3.12 arrow/21.0.0          # (Trillium / Alliance; or local py3.12 + pyarrow)
python -m venv .venv && source .venv/bin/activate
pip install --no-index -r paper-results/provenance/venv-freeze.txt   # or: pip install -r (online)
export PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HOME=/path/to/hf_cache
```
Pre-cache HF models offline: `BAAI/bge-large-en-v1.5`, `intfloat/e5-large-v2`,
`sentence-transformers/all-mpnet-base-v2`, `sentence-transformers/all-MiniLM-L6-v2`,
`cross-encoder/ms-marco-MiniLM-L-6-v2`, `Qwen/Qwen2.5-7B-Instruct`.

`DSID` / `HSUB` per dataset: OB=`2026-05-25-dataset-v5-large-global`/`bulk-20260531`,
OTel=`2026-06-09-otel-demo-v1-global`/`bulk-20260531`,
WoL=`2026-06-17-wol-real-v3-global`/`bulk-20260617`.

## Result → script map

| paper-results/ | producer | Slurm wrapper |
|---|---|---|
| `retrieval-cascades/<ds>/` | `scripts/research-lab/run_{biencoder,bm25,kg_retrieval,hybrid_rrf}_wol_mode3.py` | `trillium_cascade_panel.sbatch` (DSID,LABEL,HSUB) |
| `baselines/{sota-dense,tfidf,cross-encoder-rerank}/<ds>/` | `run_baseline_retrievers.py --method {bge,e5,mpnet,tfidf,ce}` | `trillium_baselines.sbatch` |
| `baselines/bm25/<ds>/` | `run_baseline_retrievers.py --method bm25` | (compute node; O(N²) on WoL) |
| `baselines/llm-rag/<ds>/` | `run_llm_rag.py` (Qwen rerank of bge top-k) | `trillium_llm_rag.sbatch` |
| `agent-end-to-end/<ds>/` | `scripts/agent/smoke_{ob,otel_demo,wol}.py --output … --trace-root …` | (CPU; runs on login/compute) |
| `agent-value/<ds>/` | `scripts/agent/{cost_vs_cascade,skill_ablation,tool_ablation,budget_curve}.py` | (CPU) |
| `kg-usefulness/<ds>/` (±graph) | `run_hybrid_rrf_wol_mode3.py --skip-graph` | `trillium_kg_ablation.sbatch` |
| `kg-usefulness/complementarity.*` | `scripts/research-lab/run_kg_complementarity.py` | (CPU, reads predictions) |
| `gold-validation/<ds>/` | `scripts/research-lab/run_llm_judge_gold.py` | `trillium_gold_judge.sbatch` |
| `robustness/multiseed/<ds>/seed{1,2}/` | `run_biencoder_wol_mode3.py --seed N` | `trillium_robustness.sbatch` |
| `robustness/significance*.{md,json}` | `scripts/research-lab/run_significance_bh.py` | (CPU, reads predictions) |
| `triage-leaderboard/<ds>/` | `python -m comparison.cli --pipelines … --no-ensemble --n-bootstrap 1000` | `trillium_triage_leaderboard.sbatch` |
| all `**/SUMMARY.md` + `README.md` | `scripts/research-lab/build_paper_summaries.py` | (CPU; idempotent) |

## Notes / gotchas (learned during collection)
- **Graph retriever** needs Neo4j; the cascade/KG jobs launch an in-job Apptainer
  Neo4j via `deploy/research-lab/neo4j_apptainer.sh` (`NEO4J_BASE` per dataset for
  parallel isolation). No Docker on Trillium.
- **Hybrid triage scoring**: set `HYBRID_TRIAGE_SCORE_SAMPLE=5000` (subsamples
  train/val triage scoring; **test Hit@K is never subsampled**) — without it,
  WoL score_train times out.
- **`sbatch --export`** splits on commas: pass multi-value vars (e.g. `PIPELINES`)
  via inherited env (`export PIPELINES=…; sbatch --export=ALL …`), not inline.
- **Triage leaderboard**: WoL omits `bm25_retrieval` (O(N²) over 38.6k docs,
  intractable + poor triage signal). WoL triage is at-chance (a finding, not a
  bug — see `robustness/negative-results.md`).
- **Splits**: OB/OTel use `triage-split-manifest-v2-resplit.json` (window_assignment);
  WoL uses `triage-split-manifest.json`. Honored by all loaders post-fix.
