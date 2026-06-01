# Headline results table

Each row is a pipeline configuration. Columns are metric (point estimate, 95% bootstrap CI on Hit@K and MRR over 1000 resamples, seed=42).

| Pipeline | n | PR-AUC | ROC-AUC | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| `hist_gradient_boosting_numeric` | 317 | 0.7718 | 0.9267 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| `memorygraph_v2_sota_nw080` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `memorygraph_v2_sota_nw080_ft` | 317 | 0.6211 | 0.7932 | 0.132 [0.095, 0.170] | 0.221 [0.180, 0.265] | 0.162 [0.125, 0.200] |

Notes:
- `n` = number of retrievable test windows (gold_label=ticket_worthy and non-empty gold_matched_issue_ids).
- HGB has zero matched_issue_ids by construction (no retrieval head); Hit@K and MRR are exactly 0.
- PR-AUC / ROC-AUC are computed over the full test set (n=2940), not just the retrievable subset.