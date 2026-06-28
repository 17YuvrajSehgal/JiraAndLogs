# Pre-collection Code Audit — Findings & Fix Status

*Full audit of the result-collection path before the (non-repeatable) ICSE runs.
2026-06-28. Severity = impact on published numbers / run safety.*

Status legend: ☐ to fix · ☑ fixed · ▶ in progress · ✔ verified-OK (no change needed)

## CRITICAL — corrupts numbers or crashes (must fix before that dataset/run)

- ☐ **C1. OB/OTel evaluated on the WRONG split.** The cascade scripts
  (`run_*_wol_mode3.py`) and the comparison harness use
  `core.data.loaders.load_dataset`/`iter_split`, which read
  `triage-split-manifest.json` and split by `scenario_family`, **ignoring** the
  per-window `triage-split-manifest-v2-resplit.json`. Measured: OTel test=0,
  OB test=2940 (paper split is 1008). → any OB/OTel cascade/comparison number is
  on the wrong/empty partition. **Central fix:** make `load_dataset` honor the
  resplit `window_assignment` when present. (The agent loaders + the new
  baseline runner already do this; baselines job 621191 is correct.)
- ☐ **C2. KG-retrieval temporal leakage.** `proposal_d/pipeline.py` returns graph
  matches with no `before_ts` and **no visible-set post-filter**, so KG can match
  tickets that became available *after* the window → inflated KG Hit@K (all
  datasets). The *hybrid* is safe (it post-filters by `vis`). Fix: post-filter
  proposal_d rows by `corpus.visible_to(w)`.
- ☐ **C3. BM25 results JSON uses FABRICATED timings + hardcoded out-dir.**
  `synthesize_bm25_results.py` hardcodes `fit/predict/wall_seconds` from an old
  log and writes to `global_dir/tch-lite-refit` (no `--out-dir`). A fresh run
  emits stale timings into the paper table and may miss/clobber the new preds.
  Fix: real timings (or null) + `--out-dir`.

## HIGH — wrong numbers in specific cells / reproducibility

- ☐ **H1. Hybrid-RRF under-trains BiEncoder at 3 epochs.**
  `run_hybrid_rrf_wol_mode3.py:94` defaults `--biencoder-finetune-epochs 3`,
  overriding the pipeline's correct 5. (Our sbatch passes 5, so the running
  620673 is fine, but the default is wrong for any other invocation.) Fix:
  default 5.
- ☐ **H2. Headline CIs + pairwise p-values run at seed=17, not 42.**
  `comparison/significance.py:117` `paired_bootstrap_ci(seed=17)`, not overridden
  at `runner.py:762`; only the depth-stratified path uses 42. Fix: seed=42.
- ☐ **H3. Page-suppression deflates agent triage_accuracy.**
  `eval_harness/harness.py` mutates `ticket_worthy→borderline` *before* triage is
  scored, so suppressed-but-correct windows count as triage-wrong (all agent runs
  with state on). Fix: score triage against the pre-suppression decision.
- ☐ **H4. Agent silently drops a missing retriever.**
  `harness_builder.py:247-252` only warns on a missing predictions JSONL →
  silent empty-retrieval baseline (docstring promises fail-fast). Fix: raise.
- ☐ **H5. Hybrid triage metric skew on OB/OTel.** Inner BiEncoder emits rankings
  only for test → train/val triage features are biencoder-blind, test is
  populated → corrupts hybrid triage PR-AUC/precision@FPR (NOT Hit@K; WoL moot).
  Fix: emit biencoder features for train+val+test (or recompute per split).
- ☐ **H6. Missing logging** in `run_kg_retrieval_wol_mode3.py` and
  `run_diagnosis_agent_wol_mode3.py` (silent multi-hour runs). Add basicConfig.
- ☐ **H7. Offline-unsafe comparison pipelines.** `nomic_retrieval` silently
  degrades to BM25 (mislabeled) and `nomic_lm_rerank` **crashes the whole run**
  (LM Studio at localhost unavailable on compute nodes). Exclude both from
  offline collection; only run offline-safe pipelines.

## MEDIUM — fix where on our path

- ☐ **M1. No multiple-comparison correction** anywhere (needed across the RQ
  bootstrap tests). Add Benjamini–Hochberg.
- ☐ **M2. Ensemble missing stratification/depth fields** (`ensemble.py`,
  `runner.py` ordering) → ensemble absent from the depth-stratified figure and
  wrong hard-case/reason-class strata. Fix only if we publish the ensemble.
- ☐ **M3. Per-pipeline artifacts written under `data/...training_runs`**
  (`runner.py:689`) regardless of `--output-dir`. Redirect for the clean dir.
- ☐ **M4. Stale humanized-subdir defaults** (`bulk-20260611`) in the cascade
  scripts; correct per-dataset values must be passed explicitly.
- ☐ **M5. Script polish:** `paired_delta_bootstrap.py` latent None-format crash;
  `bootstrap_headlines.py` no `--out-dir`; `agent_cost_savings.py` doc/flag
  mismatch; `cost_vs_cascade.py` synthetic cost model + dead loop;
  `tool_ablation.py` n_cases always 0.

## VERIFIED-OK (no change needed)
- ✔ `bi_encoder.py` parallel BM25 mining: deterministic, memory-bounded,
  `BIENC_BM25_JOBS=1` preserves original behavior, CUDA-fork guard correct;
  serial==parallel pair sets.
- ✔ `HYBRID_TRIAGE_SCORE_SAMPLE` subsamples **only** train/val; **test (Hit@K)
  is provably never subsampled**.
- ✔ Inner BiEncoder config matches the standalone (use_all_golds=False, 2 hard /
  1 random, epochs passed through).
- ✔ Bootstrap library is correctly paired (same indices across systems),
  defaults seed=42 / n=1000.
- ✔ Agent smokes default to full test split (no `--limit`), seed=42, and use the
  resplit for OB/OTel (test counts 1008 / 247 / 13388).
- ✔ Classical comparison pipelines (hgb/rf/logistic/xgb/bm25) seeded, real HP,
  offline-safe.

## Notes on currently-running jobs
- **620673 (WoL hybrid):** epochs=5 (sbatch), WoL single-class triage, hybrid
  graph visibility-filtered → its **Hit@K is valid**; keep it.
- **621191 (baselines):** uses the resplit correctly → **valid**; keep it.

---

## Fix status — 2026-06-28 (validated: 439/439 agent tests pass, all edits import)

**FIXED & verified:**
- ☑ C1 split — `core/data/{schema,splits,loaders}.py` now honor the v2-resplit
  `window_assignment`. Verified test counts: OB=1008, OTel=247, WoL=13388.
- ☑ C2 KG leakage — `proposal_d/pipeline.py` over-fetches then filters by
  `corpus.visible_to(w)` in both `_predict_test` and `_build_features_and_labels`.
- ☑ C3 BM25 synth — `synthesize_bm25_results.py` gains `--out-dir`; fabricated
  timings replaced with null (+ optional `--wall-seconds`).
- ☑ H1 — `run_hybrid_rrf_wol_mode3.py` `--biencoder-finetune-epochs` default 3→5.
- ☑ H2 — `significance.py` headline CI seed 17→42.
- ☑ H3 — `eval_harness/harness.py` scores triage on the pre-suppression decision.
- ☑ H4 — `harness_builder.py` missing-predictions now a LOUD error (run script
  will enforce hard fail-fast on REQUIRED retrievers per dataset).
- ☑ H6 — `logging.basicConfig` added to `run_kg_retrieval` + `run_diagnosis_agent`.
- ☑ M1 — `benjamini_hochberg()` added to `eval_harness/bootstrap.py` (applied at
  cross-RQ aggregation).

**Handled operationally (no code change):**
- H7 — exclude `nomic_retrieval` / `nomic_lm_rerank` from offline comparison
  runs (LM Studio unavailable); run only offline-safe pipelines.
- M4 — pass correct `--humanized-subdir` explicitly per dataset in the sbatch.

**Deferred / documented (not on the headline-number path):**
- H5 — hybrid inner-BiEncoder emits rankings for test only → hybrid *triage*
  metric (PR-AUC/precision@FPR) skewed on OB/OTel. Hit@K UNAFFECTED; WoL moot
  (single-class). The headline triage comes from the agent's compose_triage, not
  the hybrid's internal head. Fix later if the hybrid triage cell is published.
- M2 ensemble strat fields, M3 `training_runs` path, M5 script polish — low
  impact; address if the corresponding artifact is published.
