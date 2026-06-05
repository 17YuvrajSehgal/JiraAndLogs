# Headline results table

Each row is a pipeline configuration. Columns are metric (point estimate, 95% bootstrap CI on Hit@K and MRR over 1000 resamples, seed=42).

| Pipeline | n | PR-AUC | ROC-AUC | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| `memorygraph_v2_sota_nw080` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `memorygraph_v2_sota_nw080_no_k8s` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |
| `memorygraph_v2_sota_nw080_no_logs` | 317 | 0.6162 | 0.7850 | 0.114 [0.082, 0.148] | 0.211 [0.167, 0.256] | 0.144 [0.109, 0.180] |
| `memorygraph_v2_sota_nw080_no_traces` | 317 | 0.6186 | 0.7881 | 0.158 [0.120, 0.199] | 0.202 [0.155, 0.246] | 0.172 [0.133, 0.212] |

Notes:
- `n` = number of retrievable test windows (gold_label=ticket_worthy and non-empty gold_matched_issue_ids).
- HGB has zero matched_issue_ids by construction (no retrieval head); Hit@K and MRR are exactly 0.
- PR-AUC / ROC-AUC are computed over the full test set (n=2940), not just the retrievable subset.