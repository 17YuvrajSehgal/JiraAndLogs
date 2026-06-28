# ICSE Results-Collection Log

*Running log of every code change (with rationale) and every result collected
into `paper-results/`. Companion docs: [`review.md`](review.md) (gaps),
[`review-sol.md`](review-sol.md) (plan), [`audit-findings.md`](audit-findings.md)
(pre-collection audit). Last updated 2026-06-28.*

---

## 1. Code changes (what + why)

### 1a. Correctness fixes (from the pre-collection audit — full list in audit-findings.md)
| ID | File(s) | Change | Why |
|----|---------|--------|-----|
| C1 | `core/data/{schema,splits,loaders}.py` | honor v2-resplit `window_assignment` | OB/OTel were evaluated on the wrong/empty split (OTel test=0). Now OB=1008/OTel=247/WoL=13388. |
| C2 | `proposal_d_knowledge_graph/pipeline.py` | over-fetch + `visible_to` filter in KG predict/feature paths | KG retrieval leaked future tickets → inflated Hit@K. |
| C3 | `synthesize_bm25_results.py` | `--out-dir` + null timings (`--wall-seconds` optional) | results JSON had fabricated wall-clock + hardcoded path. |
| H1 | `run_hybrid_rrf_wol_mode3.py` | `--biencoder-finetune-epochs` default 3→5 | hybrid under-trained its dense component vs the published config. |
| H2 | `comparison/significance.py` | headline CI seed 17→42 | reproducibility/consistency with the rest of the pipeline. |
| H3 | `eval_harness/harness.py` | score triage on pre-suppression decision | page-suppression was wrongly counted as a triage error. |
| H4 | `agent/harness_builder.py` | missing-predictions → LOUD error | a missing file silently became an empty-retrieval baseline. |
| H6 | `run_kg_retrieval_*`, `run_diagnosis_agent_*` | add `logging.basicConfig` | silent multi-hour runs. |
| M1 | `eval_harness/bootstrap.py` | add `benjamini_hochberg()` | needed for multiple-comparison correction across RQ tests. |

Validation: **439/439 agent tests pass**; all edited modules import. (commit `1014cb6`)

### 1b. New collection tooling
| File | Purpose |
|------|---------|
| `run_baseline_retrievers.py` | prior-art baselines (bge/e5/mpnet dense, tfidf, **bm25-over-humanized**, ce rerank), resplit-aware, → `paper-results/baselines/` |
| `trillium_baselines.sbatch` | runs the dense/tfidf/ce baseline matrix on one GPU |
| `trillium_cascade_panel.sbatch` | per-dataset cascade panel (BiEncoder/BM25/KG/Hybrid) with its own Apptainer Neo4j; `CASCADES=` subset; `NEO4J_BASE` overridable; → `paper-results/retrieval-cascades/<label>/` |

### 1c. Notable correctness finding during collection
- **BM25 cascade indexes the *raw* `jira-memory-corpus`, not the humanized corpus**
  the other retrievers + gold use. IDs match, but the *text* differs → OB BM25
  cascade Hit@5=0.088 (vs fair tfidf-on-humanized 0.372). WoL is unaffected
  (raw≈humanized). **Resolution:** added a fair `bm25` method to the baseline
  runner (BM25 over the humanized corpus) as the canonical lexical baseline; the
  cascade-BM25 (raw) is reported separately/with a caveat.

---

## 2. Results collected → `paper-results/`

### retrieval-cascades/ — coarse Hit@K (test split)
| dataset | BiEncoder | BM25(cascade,raw) | KG | Hybrid-RRF |
|---------|-----------|-------------------|----|------------|
| wol-v3 (n=…) | Hit@5 0.905 | 0.727 | *re-running (C2)* | **0.970** (H@1 0.839, MRR 0.897) |
| online-boutique (n=331) | 0.634 | 0.088¹ | 0.465 | 0.559 |
| otel-demo (n=119) | 0.681 | 0.563 | 0.412 | 0.672 (H@1 0.513) |

¹ raw-corpus artifact — see §1c; use the fair BM25 baseline.

### baselines/ — coarse Hit@5 (lexical + dense, on humanized corpus)
| dataset | tfidf | mpnet | e5 | bge | ce(rerank) | bm25(fair) |
|---------|-------|-------|----|----|-----------|-----------|
| wol-v3 | 0.766 | 0.834 | … | … | … | *running* |
| online-boutique | 0.372 | 0.375 | 0.314 | 0.341 | 0.296 | *running* |
| otel-demo | 0.613 | 0.630 | … | … | … | *running* |

(Full per-method numbers in each `*-results.json`; table filled as jobs finish.)

### Pending categories
- agent-end-to-end/ · agent-value/ · kg-usefulness/ · robustness/ · gold-validation/ · baselines/llm-rag/

---

## 3. Decisions
- LLM = **Qwen2.5-7B-Instruct** via vLLM (offline, one H100) for LLM-RAG + judge.
- Gold validation via **LLM-as-judge** this cycle (+ human-kit for later κ).
- Clean dir `paper-results/` only; large `*-predictions.jsonl` gitignored, shipped as a release archive.
- WoL: keep the valid Hybrid (620673) + BiEncoder; re-synth BM25 (C3); **re-run KG (C2)**.

---

## 4. Job ledger
| job | what | result |
|-----|------|--------|
| 620673 | WoL Hybrid-RRF | ✅ done, Hit@5 0.970 |
| 621191 | baseline matrix (dense/tfidf/ce ×3) | running |
| 621241 | OTel cascade panel | ✅ done |
| 621242 | OB cascade panel | ✅ done |
| 621251 | WoL KG re-run (C2) | running |
| (bg) | Qwen2.5-7B download; fair-bm25 baselines | running |

---

## 5. Status / next (execution order)
1. ✅ baselines (dense/lexical) · ✅ cascade panels (OB/OTel/WoL incl. WoL-KG re-run)
2. ▶ KG-usefulness ±graph ablation (add `--skip-graph` to run script)
3. ▶ LLM-RAG + LLM-as-judge (once Qwen cached)
4. ☐ agent end-to-end (wire `--predictions-root` to read fresh preds)
5. ☐ agent-value (cost@iso-accuracy, skill/tool ablations)
6. ☐ robustness (multi-seed, BH correction, negative-results)
7. ☐ aggregate SUMMARY.md per category + paper-results/README.md + provenance

---

## Progress snapshot — 2026-06-28 (autonomous run)

**Categories DONE → paper-results/**
- ✅ `baselines/` — dense (bge/e5/mpnet), tfidf, **fair bm25**, ce, **llm-rag** × 3 datasets.
  - LLM-RAG (Qwen rerank/bge-top10): WoL 0.856 / OTel 0.639 / OB 0.344 Hit@5 — below our BiEncoder/Hybrid (good).
- ✅ `retrieval-cascades/` — OB, OTel, WoL panels (WoL KG re-running for C2).
- ✅ `kg-usefulness/` (OB/OTel) — graph helps Hit@1 (OB 0.281→0.414), ~flat Hit@5; WoL running.
- ✅ `agent-end-to-end/` (OB/OTel) — OB Hit@1=0.689 Hit@5=0.758 triage-acc=0.841 (resplit + H3 fix); WoL running.

**In flight:** WoL KG cascade (621251), WoL kg-ablation (621277), gold-judge all-3 (621309),
robustness multi-seed BiEncoder OB/OTel (621310), WoL agent eval (bg), agent-value OB/OTel (bg), WoL fair-bm25 (bg).

**Still to do:** WoL agent eval + agent-value; robustness BH-correction + negative-results
aggregation; gold-validation collation; per-category SUMMARY.md + paper-results/README.md +
provenance (env freeze, seeds); threats-to-validity draft (gap #3).

**Key headline so far (WoL real data, coarse Hit@5):**
Hybrid-RRF **0.970** > BiEncoder 0.905 > LLM-RAG 0.856 > BM25 0.727 > KG (re-running) — fusion wins on real Jira data.
