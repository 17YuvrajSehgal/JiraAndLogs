# Depth-Stratified Retrieval Analysis

Computed from `per-window-predictions.jsonl` with bootstrap CIs (n_resamples=1000, seed=42).

Stratification axis: `n_prior_family_tickets` = number of memory tickets the gold-truth matcher considers compatible with each window (i.e., |gold_matched_issue_ids|).

## Why Hit@5 is the primary metric

The standard `recall@K = |top_K ∩ gold| / |gold|` definition mechanically *drops* as |gold| grows beyond K (e.g., with |gold|=21, max possible recall@5 = 5/21 = 0.238). This makes deep-history buckets look worse than they are. **Hit@K** = `1 if any gold in top-K else 0` is the right metric for 'did the engineer find a relevant ticket'.


## hit_at_5

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.1905 [0.0714, 0.3095] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.1587 [0.0635, 0.2540] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.2120 [0.1576, 0.2717] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2500 [0.1071, 0.4286] |

## hit_at_3

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.1190 [0.0238, 0.2143] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.1587 [0.0635, 0.2540] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.2011 [0.1413, 0.2609] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2500 [0.1071, 0.4286] |

## hit_at_1

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.0476 [0.0000, 0.1190] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.1270 [0.0476, 0.2063] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.1793 [0.1250, 0.2337] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2500 [0.1071, 0.4286] |

## mrr

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.0948 [0.0298, 0.1718] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.1376 [0.0582, 0.2275] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.1902 [0.1377, 0.2468] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2500 [0.1071, 0.4286] |

## precision_at_5

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.0476 [0.0190, 0.0810] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.0635 [0.0254, 0.1048] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.1152 [0.0804, 0.1543] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2071 [0.0857, 0.3429] |

## recall_at_5_norm

| Bucket | n | hist_gradient_boosting_numeric | memorygraph_v2_sota_nw080 |
|---|---:| ---: | ---: |
| 0 | 0 | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 1-2 | 42 | 0.0000 [0.0000, 0.0000] | 0.1548 [0.0595, 0.2619] |
| 3-5 | 63 | 0.0000 [0.0000, 0.0000] | 0.0831 [0.0339, 0.1413] |
| 6-20 | 184 | 0.0000 [0.0000, 0.0000] | 0.1152 [0.0804, 0.1543] |
| 21+ | 28 | 0.0000 [0.0000, 0.0000] | 0.2071 [0.0857, 0.3429] |
