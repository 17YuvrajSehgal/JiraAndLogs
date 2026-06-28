# Comparison Report

Pipelines:
- `hist_gradient_boosting_numeric` (threshold=0.0333, fit=3.0s, predict=0.0s)
- `calibrated_random_forest_numeric` (threshold=0.4773, fit=1.2s, predict=0.1s)
- `logistic_numeric_sklearn` (threshold=0.7455, fit=0.0s, predict=0.0s)
- `bm25_retrieval_only` (threshold=1.0000, fit=0.6s, predict=2.0s)
- `bi_encoder_hybrid` (threshold=0.7329, fit=8.1s, predict=0.0s)

## Orphan-detection recall gap (D12.6)

`gap_pts = 100 × (recall on reported ticket_worthy - recall on orphan ticket_worthy)`. Verdict: < 10pts = signal_learning, 10-20 = borderline, > 20 = pattern_matching, n_orphan=0 = no_orphan_data.

| pipeline | n_reported | recall_reported | n_orphan | recall_orphan | gap_pts | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bi_encoder_hybrid | 126 | 0.667 | 92 | 0.685 | -1.8 | signal_learning |
| bm25_retrieval_only | 126 | 1.000 | 92 | 1.000 | +0.0 | signal_learning |
| calibrated_random_forest_numeric | 126 | 0.968 | 92 | 1.000 | -3.2 | signal_learning |
| hist_gradient_boosting_numeric | 126 | 1.000 | 92 | 1.000 | +0.0 | signal_learning |
| logistic_numeric_sklearn | 126 | 0.643 | 92 | 0.598 | +4.5 | signal_learning |

## Headline (overall, with 95% bootstrap CIs)

### pr_auc
| pipeline | pr_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.7692 | [0.7139, 0.8201] |
| bm25_retrieval_only | 0.2163 | [0.1925, 0.2431] |
| calibrated_random_forest_numeric | 0.9857 | [0.9766, 0.9929] |
| hist_gradient_boosting_numeric | 0.9998 | [0.9993, 1.0000] |
| logistic_numeric_sklearn | 0.7641 | [0.7075, 0.8154] |

### roc_auc
| pipeline | roc_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.9206 | [0.8988, 0.9380] |
| bm25_retrieval_only | 0.5000 | [0.5000, 0.5000] |
| calibrated_random_forest_numeric | 0.9961 | [0.9937, 0.9980] |
| hist_gradient_boosting_numeric | 0.9999 | [0.9998, 1.0000] |
| logistic_numeric_sklearn | 0.9159 | [0.8948, 0.9342] |

### precision_at_fpr_5pct
| pipeline | precision_at_fpr_5pct | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.7771 | [0.7023, 0.8125] |
| bm25_retrieval_only | 0.2500 | [0.0952, 0.3333] |
| calibrated_random_forest_numeric | 0.8458 | [0.8268, 0.8638] |
| hist_gradient_boosting_numeric | 0.8482 | [0.8291, 0.8657] |
| logistic_numeric_sklearn | 0.7665 | [0.6977, 0.8069] |

### recall_at_5
| pipeline | recall_at_5 | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| bm25_retrieval_only | 0.0379 | [0.0154, 0.0630] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

### mrr
| pipeline | mrr | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| bm25_retrieval_only | 0.0540 | [0.0216, 0.0916] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

## Pairwise deltas (paired bootstrap)

### pr_auc
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| pr_auc | bi_encoder_hybrid | bm25_retrieval_only | -0.5529 | [-0.6022, -0.5009] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.2165 | [+0.1663, +0.2710] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.2306 | [+0.1798, +0.2858] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | logistic_numeric_sklearn | -0.0051 | [-0.0138, +0.0037] | 0.262 | no |
| pr_auc | bm25_retrieval_only | calibrated_random_forest_numeric | +0.7695 | [+0.7436, +0.7927] | 0.000 | yes |
| pr_auc | bm25_retrieval_only | hist_gradient_boosting_numeric | +0.7835 | [+0.7569, +0.8074] | 0.000 | yes |
| pr_auc | bm25_retrieval_only | logistic_numeric_sklearn | +0.5478 | [+0.4940, +0.5960] | 0.000 | yes |
| pr_auc | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0141 | [+0.0070, +0.0230] | 0.000 | yes |
| pr_auc | calibrated_random_forest_numeric | logistic_numeric_sklearn | -0.2216 | [-0.2780, -0.1724] | 0.000 | yes |
| pr_auc | hist_gradient_boosting_numeric | logistic_numeric_sklearn | -0.2357 | [-0.2924, -0.1844] | 0.000 | yes |

### precision_at_fpr_5pct
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| precision_at_fpr_5pct | bi_encoder_hybrid | bm25_retrieval_only | -0.5271 | [-0.6732, -0.4264] | 0.000 | yes |
| precision_at_fpr_5pct | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0687 | [+0.0428, +0.1385] | 0.000 | yes |
| precision_at_fpr_5pct | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0711 | [+0.0448, +0.1410] | 0.000 | yes |
| precision_at_fpr_5pct | bi_encoder_hybrid | logistic_numeric_sklearn | -0.0107 | [-0.0293, +0.0216] | 0.520 | no |
| precision_at_fpr_5pct | bm25_retrieval_only | calibrated_random_forest_numeric | +0.5958 | [+0.5140, +0.7431] | 0.000 | yes |
| precision_at_fpr_5pct | bm25_retrieval_only | hist_gradient_boosting_numeric | +0.5982 | [+0.5170, +0.7458] | 0.000 | yes |
| precision_at_fpr_5pct | bm25_retrieval_only | logistic_numeric_sklearn | +0.5165 | [+0.4232, +0.6681] | 0.000 | yes |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0024 | [+0.0000, +0.0051] | 0.062 | no |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | logistic_numeric_sklearn | -0.0794 | [-0.1402, -0.0483] | 0.000 | yes |
| precision_at_fpr_5pct | hist_gradient_boosting_numeric | logistic_numeric_sklearn | -0.0818 | [-0.1423, -0.0503] | 0.000 | yes |

### recall_at_5
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| recall_at_5 | bi_encoder_hybrid | bm25_retrieval_only | +0.0379 | [+0.0154, +0.0630] | 0.000 | yes |
| recall_at_5 | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bm25_retrieval_only | calibrated_random_forest_numeric | -0.0379 | [-0.0630, -0.0154] | 0.000 | yes |
| recall_at_5 | bm25_retrieval_only | hist_gradient_boosting_numeric | -0.0379 | [-0.0630, -0.0154] | 0.000 | yes |
| recall_at_5 | bm25_retrieval_only | logistic_numeric_sklearn | -0.0379 | [-0.0630, -0.0154] | 0.000 | yes |
| recall_at_5 | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

## Per-family PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| family=ad-outage | 45 | 1.000 | 1.000 | 0.928 | 0.267 | 0.921 |
| family=baseline-normal | 105 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cart-redis | 137 | 1.000 | 1.000 | 0.821 | 0.263 | 0.815 |
| family=checkout-outage | 25 | 1.000 | 1.000 | 0.991 | 0.400 | 1.000 |
| family=checkout-restart | 25 | 1.000 | 1.000 | 0.697 | 0.240 | 0.746 |
| family=currency-outage | 52 | 1.000 | 1.000 | 0.994 | 0.404 | 0.981 |
| family=dns-outage | 13 | 1.000 | 1.000 | 0.915 | 0.462 | 0.915 |
| family=email-outage | 33 | 1.000 | 1.000 | 0.920 | 0.364 | 0.924 |
| family=flapping-pod | 25 | 1.000 | 1.000 | 0.851 | 0.360 | 0.841 |
| family=frontend-restart | 29 | 1.000 | 1.000 | 0.797 | 0.310 | 0.908 |
| family=frontend-traffic-pressure | 38 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=latency-near-miss-partial-recovery | 29 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-latency | 13 | 1.000 | 1.000 | 1.000 | 0.462 | 1.000 |
| family=network-packet-loss | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-partition | 18 | 1.000 | 1.000 | 1.000 | 0.278 | 1.000 |
| family=payment-outage | 52 | 1.000 | 1.000 | 0.841 | 0.481 | 0.863 |
| family=post-deploy-churn | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-latency | 64 | 1.000 | 1.000 | 0.970 | 0.312 | 0.970 |
| family=productcatalog-outage | 38 | 1.000 | 1.000 | 0.922 | 0.263 | 0.924 |
| family=recommendation-outage | 38 | 1.000 | 1.000 | 0.970 | 0.211 | 0.986 |
| family=recovered-in-window | 49 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=resource-saturation | 13 | 1.000 | 1.000 | 0.917 | 0.308 | 0.893 |
| family=scheduled-job-spike | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=shipping-outage | 52 | 1.000 | 1.000 | 1.000 | 0.327 | 1.000 |
| family=single-pod-restart-healthy-replication | 15 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=slow-leak-saturation | 21 | 1.000 | 1.000 | 0.667 | 0.095 | 0.667 |
| family=third-party-blip | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Per-family recall@5
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| family=ad-outage | 45 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=baseline-normal | 105 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=cart-redis | 137 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=checkout-outage | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=checkout-restart | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=currency-outage | 52 | 0.000 | 0.000 | 0.000 | 0.173 | 0.000 |
| family=dns-outage | 13 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=email-outage | 33 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=flapping-pod | 25 | 0.000 | 0.000 | 0.000 | 0.286 | 0.000 |
| family=frontend-restart | 29 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=frontend-traffic-pressure | 38 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=latency-near-miss-partial-recovery | 29 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-latency | 13 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-packet-loss | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=network-partition | 18 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=payment-outage | 52 | 0.000 | 0.000 | 0.000 | 0.075 | 0.000 |
| family=post-deploy-churn | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-latency | 64 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=productcatalog-outage | 38 | 0.000 | 0.000 | 0.000 | 0.042 | 0.000 |
| family=recommendation-outage | 38 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=recovered-in-window | 49 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=resource-saturation | 13 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=scheduled-job-spike | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=shipping-outage | 52 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=single-pod-restart-healthy-replication | 15 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=slow-leak-saturation | 21 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=third-party-blip | 25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Per-window-type PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| window_type=active_fault | 304 | 1.000 | 0.987 | 0.856 | 0.717 | 0.856 |
| window_type=observation_window | 105 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| window_type=pre_fault_baseline | 299 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| window_type=recovery_window | 300 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Stratified by is_hard_case (True = engineered to confuse simple models)

F1 here directly answers 'does the pipeline handle hard cases?'. The gap between true and false is the practical hard-case headroom.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| is_hard_case=false | 554 | 0.840 | 0.840 | 0.775 | 0.206 | 0.783 |
| is_hard_case=true | 454 | 0.957 | 0.947 | 0.359 | 0.023 | 0.359 |

## Stratified by triage_reason_class

Per fault category — `outage`, `latency_regression`, `restart_with_impact`, etc. Rows where PR-AUC is low identify the fault types your model doesn't detect well.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| triage_reason_class=bad_config | 14 | 1.000 | 1.000 | 0.850 | 0.286 | 0.850 |
| triage_reason_class=dependency_failure | 116 | 0.999 | 0.979 | 0.802 | 0.371 | 0.789 |
| triage_reason_class=dns_outage | 11 | 1.000 | 1.000 | 1.000 | 0.545 | 1.000 |
| triage_reason_class=latency_regression | 43 | 1.000 | 0.952 | 0.835 | 0.465 | 0.847 |
| triage_reason_class=network_latency | 11 | 1.000 | 1.000 | 1.000 | 0.545 | 1.000 |
| triage_reason_class=network_packet_loss | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| triage_reason_class=network_partition | 13 | 1.000 | 1.000 | 1.000 | 0.385 | 1.000 |
| triage_reason_class=outage | 145 | 1.000 | 0.999 | 0.932 | 0.531 | 0.937 |
| triage_reason_class=resource_saturation | 10 | 1.000 | 1.000 | 1.000 | 0.400 | 1.000 |
| triage_reason_class=restart_with_impact | 100 | 1.000 | 1.000 | 0.894 | 0.530 | 0.926 |
| triage_reason_class=unknown | 541 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Stratified by is_novel (true = no matching past Jira; false = match exists; unscored = not ticket_worthy)

Novel incidents are the product axis where Jira pattern matching fundamentally cannot help — the model must detect from telemetry alone. If pipelines drop substantially on `novel` vs `known`, they're leaning on memory pattern matching.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bm25_retrieval_only | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| is_novel=known | 911 | 1.000 | 0.963 | 0.691 | 0.133 | 0.688 |
| is_novel=novel | 97 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Inclusive borderline handling (borderline counted as positive)

The strict variant above is the headline. This inclusive variant rewards pipelines that surface human-interesting (borderline) windows. Pipelines whose inclusive PR-AUC is meaningfully higher than their strict PR-AUC are picking up signal on the borderline class even if they don't quite call it `ticket_worthy`.

### Overall PR-AUC (inclusive)

| Pipeline | PR-AUC | ROC-AUC | ECE | Precision@FPR=5% |
| --- | ---: | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 0.8210 | 0.7522 | 0.2426 | 0.9036 |
| `calibrated_random_forest_numeric` | 0.8193 | 0.8243 | 0.2441 | 0.9069 |
| `logistic_numeric_sklearn` | 0.7185 | 0.6307 | 0.1973 | 0.8846 |
| `bm25_retrieval_only` | 0.4633 | 0.5000 | 0.5367 | 0.3864 |
| `bi_encoder_hybrid` | 0.7258 | 0.6371 | 0.1922 | 0.8866 |

## Leave-one-family-out macros (numeric pipelines)

Each family is held out as the test set; train uses all other families pooled across train+val+test. The macro average weights every family equally regardless of size. Single-class folds (no positives in the held-out family) are skipped.

**The macro is the primary generalization signal.** A pipeline that wins the fixed-split leaderboard but loses LOFO has overfit to the families that happen to be in the train split.

### Headline LOFO macros (strict)

| Pipeline | Folds scored | Macro PR-AUC | Macro ROC-AUC |
| --- | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 18 | 0.8777 | 0.9572 |
| `calibrated_random_forest_numeric` | 18 | 0.8848 | 0.9519 |
| `logistic_numeric_sklearn` | 18 | 0.7531 | 0.8486 |

### Per-family LOFO PR-AUC

| Family | n_windows | n_pos | `hist_gradient_boosting_numeric` | `calibrated_random_forest_numeric` | `logistic_numeric_sklearn` |
| --- | ---: | ---: | ---: | ---: | ---: |
| ad-outage | 300 | 72 | 0.5965 | 0.7806 | 0.5674 |
| baseline-normal | 696 | 0 | skip | skip | skip |
| cart-redis | 918 | 264 | 0.8729 | 0.7863 | 0.6852 |
| checkout-outage | 168 | 56 | 0.8615 | 1.0000 | 0.8594 |
| checkout-restart | 168 | 56 | 0.9449 | 0.9711 | 0.5881 |
| currency-outage | 342 | 114 | 0.6526 | 0.5875 | 0.7409 |
| dns-outage | 90 | 30 | 1.0000 | 1.0000 | 0.9386 |
| email-outage | 216 | 72 | 1.0000 | 1.0000 | 0.7050 |
| flapping-pod | 165 | 55 | 1.0000 | 1.0000 | 0.7381 |
| frontend-restart | 198 | 66 | 0.9896 | 0.9787 | 0.7711 |
| frontend-traffic-pressure | 252 | 0 | skip | skip | skip |
| latency-near-miss-partial-recovery | 198 | 0 | skip | skip | skip |
| network-latency | 90 | 30 | 1.0000 | 1.0000 | 1.0000 |
| network-packet-loss | 60 | 0 | skip | skip | skip |
| network-partition | 120 | 40 | 1.0000 | 1.0000 | 1.0000 |
| payment-outage | 342 | 114 | 0.9949 | 0.9990 | 0.5799 |
| post-deploy-churn | 165 | 0 | skip | skip | skip |
| productcatalog-latency | 426 | 114 | 0.8087 | 0.8883 | 0.6156 |
| productcatalog-outage | 252 | 84 | 0.9769 | 0.9810 | 0.7574 |
| recommendation-outage | 252 | 56 | 0.5650 | 0.4640 | 0.2440 |
| recovered-in-window | 330 | 0 | skip | skip | skip |
| resource-saturation | 90 | 30 | 1.0000 | 1.0000 | 0.9571 |
| scheduled-job-spike | 132 | 0 | skip | skip | skip |
| shipping-outage | 342 | 114 | 1.0000 | 1.0000 | 0.9371 |
| single-pod-restart-healthy-replication | 99 | 0 | skip | skip | skip |
| slow-leak-saturation | 144 | 48 | 0.5349 | 0.4904 | 0.8713 |
| third-party-blip | 165 | 0 | skip | skip | skip |
