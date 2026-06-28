# Comparison Report

Pipelines:
- `hist_gradient_boosting_numeric` (threshold=0.0007, fit=3.0s, predict=0.0s)
- `calibrated_random_forest_numeric` (threshold=0.0702, fit=1.1s, predict=0.1s)
- `logistic_numeric_sklearn` (threshold=0.3402, fit=0.0s, predict=0.0s)
- `bm25_retrieval_only` (threshold=1.0000, fit=0.0s, predict=0.1s)
- `bi_encoder_hybrid` (threshold=0.3078, fit=10.8s, predict=0.0s)

## Orphan-detection recall gap (D12.6)

`gap_pts = 100 × (recall on reported ticket_worthy - recall on orphan ticket_worthy)`. Verdict: < 10pts = signal_learning, 10-20 = borderline, > 20 = pattern_matching, n_orphan=0 = no_orphan_data.

| pipeline | n_reported | recall_reported | n_orphan | recall_orphan | gap_pts | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bi_encoder_hybrid | 52 | 1.000 | 0 | 0.000 | +100.0 | no_orphan_data |
| bm25_retrieval_only | 52 | 0.923 | 0 | 0.000 | +92.3 | no_orphan_data |
| calibrated_random_forest_numeric | 52 | 1.000 | 0 | 0.000 | +100.0 | no_orphan_data |
| hist_gradient_boosting_numeric | 52 | 1.000 | 0 | 0.000 | +100.0 | no_orphan_data |
| logistic_numeric_sklearn | 52 | 1.000 | 0 | 0.000 | +100.0 | no_orphan_data |

## Headline (overall, with 95% bootstrap CIs)

### pr_auc
| pipeline | pr_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 1.0000 | [1.0000, 1.0000] |
| bm25_retrieval_only | 0.2737 | [0.2160, 0.3303] |
| calibrated_random_forest_numeric | 1.0000 | [1.0000, 1.0000] |
| hist_gradient_boosting_numeric | 1.0000 | [1.0000, 1.0000] |
| logistic_numeric_sklearn | 1.0000 | [1.0000, 1.0000] |

### roc_auc
| pipeline | roc_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 1.0000 | [1.0000, 1.0000] |
| bm25_retrieval_only | 0.4960 | [0.4542, 0.5366] |
| calibrated_random_forest_numeric | 1.0000 | [1.0000, 1.0000] |
| hist_gradient_boosting_numeric | 1.0000 | [1.0000, 1.0000] |
| logistic_numeric_sklearn | 1.0000 | [1.0000, 1.0000] |

### precision_at_fpr_5pct
| pipeline | precision_at_fpr_5pct | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.8947 | [0.8594, 0.9111] |
| bm25_retrieval_only | 0.4286 | [0.0000, 0.5000] |
| calibrated_random_forest_numeric | 0.8947 | [0.8594, 0.9111] |
| hist_gradient_boosting_numeric | 0.8947 | [0.8594, 0.9111] |
| logistic_numeric_sklearn | 0.8947 | [0.8594, 0.9111] |

### recall_at_5
| pipeline | recall_at_5 | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| bm25_retrieval_only | 0.1077 | [0.0585, 0.1678] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

### mrr
| pipeline | mrr | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| bm25_retrieval_only | 0.4400 | [0.3148, 0.5769] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

## Pairwise deltas (paired bootstrap)

### pr_auc
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| pr_auc | bi_encoder_hybrid | bm25_retrieval_only | -0.7263 | [-0.7840, -0.6697] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | bi_encoder_hybrid | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | bm25_retrieval_only | calibrated_random_forest_numeric | +0.7263 | [+0.6697, +0.7840] | 0.000 | yes |
| pr_auc | bm25_retrieval_only | hist_gradient_boosting_numeric | +0.7263 | [+0.6697, +0.7840] | 0.000 | yes |
| pr_auc | bm25_retrieval_only | logistic_numeric_sklearn | +0.7263 | [+0.6697, +0.7840] | 0.000 | yes |
| pr_auc | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

### precision_at_fpr_5pct
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| precision_at_fpr_5pct | bi_encoder_hybrid | bm25_retrieval_only | -0.4662 | [-0.8816, -0.3971] | 0.000 | yes |
| precision_at_fpr_5pct | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | bi_encoder_hybrid | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | bm25_retrieval_only | calibrated_random_forest_numeric | +0.4662 | [+0.3971, +0.8816] | 0.000 | yes |
| precision_at_fpr_5pct | bm25_retrieval_only | hist_gradient_boosting_numeric | +0.4662 | [+0.3971, +0.8816] | 0.000 | yes |
| precision_at_fpr_5pct | bm25_retrieval_only | logistic_numeric_sklearn | +0.4662 | [+0.3971, +0.8816] | 0.000 | yes |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

### recall_at_5
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| recall_at_5 | bi_encoder_hybrid | bm25_retrieval_only | +0.1077 | [+0.0585, +0.1678] | 0.000 | yes |
| recall_at_5 | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bm25_retrieval_only | calibrated_random_forest_numeric | -0.1077 | [-0.1678, -0.0585] | 0.000 | yes |
| recall_at_5 | bm25_retrieval_only | hist_gradient_boosting_numeric | -0.1077 | [-0.1678, -0.0585] | 0.000 | yes |
| recall_at_5 | bm25_retrieval_only | logistic_numeric_sklearn | -0.1077 | [-0.1678, -0.0585] | 0.000 | yes |
| recall_at_5 | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

## Per-family PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| family=ad-gc-pressure | 6 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| family=ad-high-cpu | 5 | 1.000 | 1.000 | 1.000 | 0.200 | 1.000 |
| family=ad-outage | 2 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| family=baseline-normal-traffic | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cart-failure | 4 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| family=cart-redis-degradation | 8 | 1.000 | 1.000 | 1.000 | 0.375 | 1.000 |
| family=cascade-currency-frontend-errors | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cascade-kafka-broker-checkout | 8 | 1.000 | 1.000 | 1.000 | 0.125 | 1.000 |
| family=cascade-productcatalog-latency-recommendation-timeout | 7 | 1.000 | 1.000 | 1.000 | 0.286 | 1.000 |
| family=cascade-valkey-cart-checkout | 8 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=checkout-restart | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=compound-saturation-network-latency | 7 | 1.000 | 1.000 | 1.000 | 0.429 | 1.000 |
| family=concurrent-ad-recommendation | 9 | 1.000 | 1.000 | 1.000 | 0.433 | 1.000 |
| family=concurrent-currency-shipping | 8 | 1.000 | 1.000 | 1.000 | 0.196 | 1.000 |
| family=concurrent-kafka-lag-payment-outage | 5 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=concurrent-payment-cart-redis | 12 | 1.000 | 1.000 | 1.000 | 0.417 | 1.000 |
| family=concurrent-productcatalog-latency-flapping-pod | 3 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=currency-outage | 5 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=dns-outage | 4 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=email-memory-leak-1000x | 4 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=email-memory-leak-100x | 3 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=email-outage | 5 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=flapping-pod-cart | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=frontend-restart | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=frontend-traffic-pressure | 3 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=kafka-broker-outage | 8 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=kafka-consumer-crash | 5 | 1.000 | 1.000 | 1.000 | 0.400 | 1.000 |
| family=kafka-consumer-lag | 6 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| family=kafka-dead-letter-spike | 3 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=kafka-partition-rebalance | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=latency-near-miss-partial-recovery | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=llm-inaccurate | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=llm-rate-limit | 3 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=network-latency | 9 | 1.000 | 1.000 | 1.000 | 0.111 | 1.000 |
| family=network-packet-loss | 8 | 1.000 | 1.000 | 1.000 | 0.375 | 1.000 |
| family=network-partition | 9 | 1.000 | 1.000 | 1.000 | 0.222 | 1.000 |
| family=payment-failure-100pct | 9 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=payment-failure-50pct | 4 | 1.000 | 1.000 | 1.000 | 0.333 | 1.000 |
| family=payment-outage | 4 | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 |
| family=payment-unreachable | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-latency | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-targeted-failure | 4 | 1.000 | 1.000 | 1.000 | 0.667 | 1.000 |
| family=recommendation-cache-failure | 4 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=recommendation-outage | 2 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| family=scheduled-job-spike | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=shipping-outage | 4 | 1.000 | 1.000 | 1.000 | 0.250 | 1.000 |
| family=shipping-slowdown-10sec | 9 | 1.000 | 1.000 | 1.000 | 0.375 | 1.000 |
| family=shipping-slowdown-5sec | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=single-pod-restart-cart | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=third-party-image-slow | 5 | 1.000 | 1.000 | 1.000 | 0.950 | 1.000 |

## Per-family recall@5
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| family=ad-gc-pressure | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=ad-high-cpu | 5 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=ad-outage | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=baseline-normal-traffic | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cart-failure | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cart-redis-degradation | 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cascade-currency-frontend-errors | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cascade-kafka-broker-checkout | 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cascade-productcatalog-latency-recommendation-timeout | 7 | 0.000 | 0.000 | 0.000 | 0.099 | 0.000 |
| family=cascade-valkey-cart-checkout | 8 | 0.000 | 0.000 | 0.000 | 0.064 | 0.000 |
| family=checkout-restart | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=compound-saturation-network-latency | 7 | 0.000 | 0.000 | 0.000 | 0.159 | 0.000 |
| family=concurrent-ad-recommendation | 9 | 0.000 | 0.000 | 0.000 | 0.500 | 0.000 |
| family=concurrent-currency-shipping | 8 | 0.000 | 0.000 | 0.000 | 0.053 | 0.000 |
| family=concurrent-kafka-lag-payment-outage | 5 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=concurrent-payment-cart-redis | 12 | 0.000 | 0.000 | 0.000 | 0.102 | 0.000 |
| family=concurrent-productcatalog-latency-flapping-pod | 3 | 0.000 | 0.000 | 0.000 | 0.088 | 0.000 |
| family=currency-outage | 5 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=dns-outage | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=email-memory-leak-1000x | 4 | 0.000 | 0.000 | 0.000 | 0.077 | 0.000 |
| family=email-memory-leak-100x | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=email-outage | 5 | 0.000 | 0.000 | 0.000 | 0.167 | 0.000 |
| family=flapping-pod-cart | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=frontend-restart | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=frontend-traffic-pressure | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=kafka-broker-outage | 8 | 0.000 | 0.000 | 0.000 | 0.500 | 0.000 |
| family=kafka-consumer-crash | 5 | 0.000 | 0.000 | 0.000 | 0.093 | 0.000 |
| family=kafka-consumer-lag | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=kafka-dead-letter-spike | 3 | 0.000 | 0.000 | 0.000 | 0.077 | 0.000 |
| family=kafka-partition-rebalance | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=latency-near-miss-partial-recovery | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=llm-inaccurate | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=llm-rate-limit | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-latency | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-packet-loss | 8 | 0.000 | 0.000 | 0.000 | 0.048 | 0.000 |
| family=network-partition | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=payment-failure-100pct | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=payment-failure-50pct | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=payment-outage | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=payment-unreachable | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-latency | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-targeted-failure | 4 | 0.000 | 0.000 | 0.000 | 0.154 | 0.000 |
| family=recommendation-cache-failure | 4 | 0.000 | 0.000 | 0.000 | 0.115 | 0.000 |
| family=recommendation-outage | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=scheduled-job-spike | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=shipping-outage | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=shipping-slowdown-10sec | 9 | 0.000 | 0.000 | 0.000 | 0.103 | 0.000 |
| family=shipping-slowdown-5sec | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=single-pod-restart-cart | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=third-party-image-slow | 5 | 0.000 | 0.000 | 0.000 | 0.077 | 0.000 |

## Per-window-type PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| window_type=active_fault | 72 | 1.000 | 1.000 | 1.000 | 0.939 | 1.000 |
| window_type=observation_window | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| window_type=pre_fault_baseline | 81 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| window_type=recovery_window | 92 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Stratified by is_hard_case (True = engineered to confuse simple models)

F1 here directly answers 'does the pipeline handle hard cases?'. The gap between true and false is the practical hard-case headroom.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| is_hard_case=false | 158 | 0.971 | 0.971 | 0.971 | 0.054 | 0.971 |
| is_hard_case=true | 89 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Stratified by triage_reason_class

Per fault category — `outage`, `latency_regression`, `restart_with_impact`, etc. Rows where PR-AUC is low identify the fault types your model doesn't detect well.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| triage_reason_class=latency_regression | 78 | 1.000 | 1.000 | 1.000 | 0.444 | 1.000 |
| triage_reason_class=outage | 75 | 1.000 | 1.000 | 1.000 | 0.424 | 1.000 |
| triage_reason_class=unknown | 94 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Stratified by is_novel (true = no matching past Jira; false = match exists; unscored = not ticket_worthy)

Novel incidents are the product axis where Jira pattern matching fundamentally cannot help — the model must detect from telemetry alone. If pipelines drop substantially on `novel` vs `known`, they're leaning on memory pattern matching.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| is_novel=known | 197 | 1.000 | 1.000 | 1.000 | 0.256 | 1.000 |
| is_novel=novel | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| is_novel=unscored | 48 | 1.000 | 1.000 | 1.000 | 0.320 | 1.000 |

## Inclusive borderline handling (borderline counted as positive)

The strict variant above is the headline. This inclusive variant rewards pipelines that surface human-interesting (borderline) windows. Pipelines whose inclusive PR-AUC is meaningfully higher than their strict PR-AUC are picking up signal on the borderline class even if they don't quite call it `ticket_worthy`.

### Overall PR-AUC (inclusive)

| Pipeline | PR-AUC | ROC-AUC | ECE | Precision@FPR=5% |
| --- | ---: | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 0.8694 | 0.7602 | 0.3440 | 0.9459 |
| `calibrated_random_forest_numeric` | 0.8256 | 0.7578 | 0.3415 | 0.9467 |
| `logistic_numeric_sklearn` | 0.7547 | 0.4937 | 0.3759 | 0.9444 |
| `bm25_retrieval_only` | 0.6314 | 0.5242 | 0.3783 | 0.4286 |
| `bi_encoder_hybrid` | 0.7548 | 0.4942 | 0.3729 | 0.9444 |

## Leave-one-family-out macros (numeric pipelines)

Each family is held out as the test set; train uses all other families pooled across train+val+test. The macro average weights every family equally regardless of size. Single-class folds (no positives in the held-out family) are skipped.

**The macro is the primary generalization signal.** A pipeline that wins the fixed-split leaderboard but loses LOFO has overfit to the families that happen to be in the train split.

### Headline LOFO macros (strict)

| Pipeline | Folds scored | Macro PR-AUC | Macro ROC-AUC |
| --- | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 46 | 0.9944 | 0.9953 |
| `calibrated_random_forest_numeric` | 46 | 0.9913 | 0.9933 |
| `logistic_numeric_sklearn` | 46 | 0.9707 | 0.9784 |

### Per-family LOFO PR-AUC

| Family | n_windows | n_pos | `hist_gradient_boosting_numeric` | `calibrated_random_forest_numeric` | `logistic_numeric_sklearn` |
| --- | ---: | ---: | ---: | ---: | ---: |
| ad-gc-pressure | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| ad-high-cpu | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| ad-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| baseline-normal-traffic | 8 | 0 | skip | skip | skip |
| cart-failure | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| cart-redis-degradation | 45 | 15 | 1.0000 | 1.0000 | 1.0000 |
| cascade-currency-frontend-errors | 36 | 12 | 0.8891 | 1.0000 | 0.9653 |
| cascade-kafka-broker-checkout | 48 | 16 | 1.0000 | 1.0000 | 1.0000 |
| cascade-productcatalog-latency-recommendation-timeout | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| cascade-valkey-cart-checkout | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| checkout-restart | 27 | 0 | skip | skip | skip |
| compound-saturation-network-latency | 54 | 18 | 1.0000 | 1.0000 | 1.0000 |
| concurrent-ad-recommendation | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| concurrent-currency-shipping | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| concurrent-kafka-lag-payment-outage | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| concurrent-payment-cart-redis | 84 | 28 | 1.0000 | 1.0000 | 1.0000 |
| concurrent-productcatalog-latency-flapping-pod | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| currency-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| dns-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| email-memory-leak-1000x | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| email-memory-leak-100x | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| email-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| flapping-pod-cart | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| frontend-restart | 18 | 0 | skip | skip | skip |
| frontend-traffic-pressure | 27 | 9 | 1.0000 | 1.0000 | 0.9889 |
| kafka-broker-outage | 54 | 18 | 1.0000 | 1.0000 | 1.0000 |
| kafka-consumer-crash | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| kafka-consumer-lag | 45 | 15 | 1.0000 | 1.0000 | 1.0000 |
| kafka-dead-letter-spike | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| kafka-partition-rebalance | 18 | 0 | skip | skip | skip |
| latency-near-miss-partial-recovery | 27 | 9 | 0.8513 | 0.5988 | 0.4625 |
| llm-inaccurate | 27 | 9 | 1.0000 | 1.0000 | 0.9556 |
| llm-rate-limit | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| network-latency | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| network-packet-loss | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| network-partition | 45 | 15 | 1.0000 | 1.0000 | 1.0000 |
| payment-failure-100pct | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| payment-failure-50pct | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| payment-outage | 36 | 12 | 1.0000 | 1.0000 | 1.0000 |
| payment-unreachable | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| post-deploy-churn-rolling | 18 | 0 | skip | skip | skip |
| productcatalog-latency | 27 | 9 | 1.0000 | 1.0000 | 0.9722 |
| productcatalog-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| productcatalog-targeted-failure | 27 | 9 | 1.0000 | 1.0000 | 0.9722 |
| recommendation-cache-failure | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| recommendation-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| recovered-in-window | 27 | 9 | 1.0000 | 1.0000 | 0.3339 |
| scheduled-job-spike | 18 | 0 | skip | skip | skip |
| shipping-outage | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| shipping-slowdown-10sec | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| shipping-slowdown-5sec | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
| single-pod-restart-cart | 18 | 0 | skip | skip | skip |
| third-party-image-slow | 27 | 9 | 1.0000 | 1.0000 | 1.0000 |
