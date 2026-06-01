# Headline results table

Each row is a pipeline configuration. Columns are metric (point estimate, 95% bootstrap CI on Hit@K and MRR over 1000 resamples, seed=42).

| Pipeline | n | PR-AUC | ROC-AUC | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| `memorygraph_v2_sota_d000pct` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `memorygraph_v2_sota_d010pct` | 317 | 0.6185 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `memorygraph_v2_sota_d025pct` | 317 | 0.6187 | 0.7866 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.132, 0.212] |
| `memorygraph_v2_sota_d050pct` | 317 | 0.6180 | 0.7860 | 0.151 [0.114, 0.192] | 0.202 [0.155, 0.246] | 0.168 [0.129, 0.206] |

Notes:
- `n` = number of retrievable test windows (gold_label=ticket_worthy and non-empty gold_matched_issue_ids).
- HGB has zero matched_issue_ids by construction (no retrieval head); Hit@K and MRR are exactly 0.
- PR-AUC / ROC-AUC are computed over the full test set (n=2940), not just the retrievable subset.