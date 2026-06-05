# Headline results table

Each row is a pipeline configuration. Columns are metric (point estimate, 95% bootstrap CI on Hit@K and MRR over 1000 resamples, seed=42).

| Pipeline | n | PR-AUC | ROC-AUC | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| `bi_encoder_retrieval` | 317 | 0.2418 | 0.4554 | 0.177 [0.136, 0.221] | 0.233 [0.183, 0.284] | 0.196 [0.156, 0.240] |
| `hist_gradient_boosting_numeric` | 317 | 0.7718 | 0.9267 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| `memorygraph_v2_sota_nw080` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `tab_transformer` | 317 | 0.7687 | 0.9382 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |

Notes:
- `n` = number of retrievable test windows (gold_label=ticket_worthy and non-empty gold_matched_issue_ids).
- HGB has zero matched_issue_ids by construction (no retrieval head); Hit@K and MRR are exactly 0.
- PR-AUC / ROC-AUC are computed over the full test set (n=2940), not just the retrievable subset.