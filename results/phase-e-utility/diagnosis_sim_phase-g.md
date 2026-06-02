# Time-to-diagnose simulation (Phase E)

Parameters: `t_per_candidate=30s`, `t_fallback=30min`, `top_k=10` (engineer scans at most this many candidates).

| Pipeline | n resolvable | Found in top-K | Find rate | Mean min | Median min |
|---|---:|---:|---:|---:|---:|
| `bi_encoder_retrieval` | 317 | 74 | 0.233 | 23.18 | 30.00 |
| `hist_gradient_boosting_numeric` | 317 | 0 | 0.000 | 30.00 | 30.00 |
| `memorygraph_v2_sota_nw080` | 317 | 64 | 0.202 | 24.09 | 30.00 |
| `tab_transformer` | 317 | 0 | 0.000 | 30.00 | 30.00 |

Interpretation:
- Lower mean / median minutes = faster diagnosis.
- Find rate < 1.0 means a fraction of incidents fall back to 30min manual investigation.