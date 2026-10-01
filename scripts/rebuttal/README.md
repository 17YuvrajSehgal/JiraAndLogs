# Rebuttal analyses (ICSE reviewer response)

Every quantitative claim in `ICSE/reviewers-comments/response-R{1,2,3}.md` is
produced by one of these scripts. Run from the repo root.

| Script | Answers | Key output |
|---|---|---|
| `01_component_metadata_and_gold_stats.py` | R1 (component metadata quality) | 75.3% of issues carry a component; 23.9% of held-out ticket-worthy queries have none (this is why n=5,150 not 6,773). Coarse gold: mean 410/query; strict: mean 50. |
| `02_random_baseline_and_kg_vocab_overlap.py` | R1-Q1, R2-Q1 | Random-ranker Hit@5 = 0.036 (coarse) / 0.0044 (strict). LLM-extracted KG component vocabulary overlaps the gold vocabulary by only 9.9%. |
| `03_indexed_corpus_leakage_check.py` | R2-Q1 (leakage) | The indexed (humanized) corpus contains **no** `Components:` field; only 34.6% of gold component names appear anywhere in indexed text, 15.9% on the query side. The legacy `jira-memory-corpus.jsonl` (100%) is *not* what is indexed. |
| `04_strict_relation_leaderboard_significance.py` | R2-Q1 | Full strict-relation leaderboard + paired bootstrap + BH. Hybrid best on Hit@1/Hit@5/MRR against every system with per-query predictions (only exception: Hit@5 vs. degenerate raw-corpus BM25, n.s.). |
| `05_wol_text_triage_classifier.py` | R1-Q3, R2-Q3 | **Confirms the published WoL triage numbers are degenerate**: 0 of 78,140 rows have a non-zero `triage_feature_*`. Re-run on ticket text: ROC-AUC 0.572–0.601 (CI excludes 0.500), not 0.500. |
| `06_tool_ablation_bootstrap_ci.py` | R3-Q2 | Paired-bootstrap CIs for Fig. 4. Trace reader -0.018 Hit@1 CI [-0.033,-0.006] in isolation only; peer-lookup benefit n.s.; all Hit@5 effects exactly 0.000. |
| `07_seed_vs_sampling_variance.py` | R3-Q1 | Seed contributes 32% of Hit@5 variance on Online Boutique, 1.2% on OTel Demo. |

## Inputs

- `data/derived/global/2026-06-17-wol-real-v3-global/` — the WoL v3 corpus
  (note: the Zenodo dataset record currently ships **v2**; see
  `scripts/agent/bundle_dataset_for_publication.py`, which hard-codes the v2 id).
- `paper-results/` — published predictions and per-cell ablation reports.

## Defects these analyses found in the submission

1. **WoL triage classifiers were fed an all-zero design matrix.** The reported
   ROC-AUC 0.500 / PR-AUC 0.506 is forced, not learned. "Collapses to chance"
   must be replaced with the measured ROC-AUC 0.57–0.60.
2. **Artifact ships WoL-v2, not v3.** `bundle_dataset_for_publication.py:44`
   hard-codes `2026-06-15-wol-real-v2-global`.
3. **Cost saving is an estimated counterfactual, not a measurement.** Sec. VI-C
   says "measured"; it is gate-decision counting priced with a fixed per-skill
   cost table.
4. **"Peer-incident lookup is the only clearly beneficial tool"** is not
   supported — its CI includes zero.
5. **The legacy `jira-memory-corpus.jsonl` carries the gold-defining
   `Components:` field.** It is not indexed, but it ships in the artifact
   without a warning label.
