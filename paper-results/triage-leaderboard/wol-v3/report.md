# Comparison Report

Pipelines:
- `hist_gradient_boosting_numeric` (threshold=0.5000, fit=2.4s, predict=0.0s)
- `calibrated_random_forest_numeric` (threshold=0.4725, fit=2.2s, predict=0.3s)
- `logistic_numeric_sklearn` (threshold=0.5000, fit=0.2s, predict=0.0s)
- `bi_encoder_hybrid` (threshold=0.6391, fit=51.4s, predict=0.0s)

## Orphan-detection recall gap (D12.6)

`gap_pts = 100 × (recall on reported ticket_worthy - recall on orphan ticket_worthy)`. Verdict: < 10pts = signal_learning, 10-20 = borderline, > 20 = pattern_matching, n_orphan=0 = no_orphan_data.

| pipeline | n_reported | recall_reported | n_orphan | recall_orphan | gap_pts | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bi_encoder_hybrid | 5150 | 0.032 | 1623 | 0.039 | -0.7 | signal_learning |
| calibrated_random_forest_numeric | 5150 | 1.000 | 1623 | 1.000 | +0.0 | signal_learning |
| hist_gradient_boosting_numeric | 5150 | 1.000 | 1623 | 1.000 | +0.0 | signal_learning |
| logistic_numeric_sklearn | 5150 | 1.000 | 1623 | 1.000 | +0.0 | signal_learning |

## Headline (overall, with 95% bootstrap CIs)

### pr_auc
| pipeline | pr_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.5352 | [0.5241, 0.5487] |
| calibrated_random_forest_numeric | 0.5059 | [0.4975, 0.5152] |
| hist_gradient_boosting_numeric | 0.5059 | [0.4975, 0.5152] |
| logistic_numeric_sklearn | 0.5059 | [0.4975, 0.5152] |

### roc_auc
| pipeline | roc_auc | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.5410 | [0.5309, 0.5499] |
| calibrated_random_forest_numeric | 0.5000 | [0.5000, 0.5000] |
| hist_gradient_boosting_numeric | 0.5000 | [0.5000, 0.5000] |
| logistic_numeric_sklearn | 0.5000 | [0.5000, 0.5000] |

### precision_at_fpr_5pct
| pipeline | precision_at_fpr_5pct | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.5516 | [0.5053, 0.5905] |
| calibrated_random_forest_numeric | 0.9535 | [0.4652, 0.5437] |
| hist_gradient_boosting_numeric | 0.9535 | [0.4652, 0.5437] |
| logistic_numeric_sklearn | 0.9535 | [0.4652, 0.5437] |

### recall_at_5
| pipeline | recall_at_5 | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

### mrr
| pipeline | mrr | 95% CI |
| --- | ---: | --- |
| bi_encoder_hybrid | 0.0000 | [0.0000, 0.0000] |
| calibrated_random_forest_numeric | 0.0000 | [0.0000, 0.0000] |
| hist_gradient_boosting_numeric | 0.0000 | [0.0000, 0.0000] |
| logistic_numeric_sklearn | 0.0000 | [0.0000, 0.0000] |

## Pairwise deltas (paired bootstrap)

### pr_auc
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| pr_auc | bi_encoder_hybrid | calibrated_random_forest_numeric | -0.0293 | [-0.0387, -0.0210] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | hist_gradient_boosting_numeric | -0.0293 | [-0.0387, -0.0210] | 0.000 | yes |
| pr_auc | bi_encoder_hybrid | logistic_numeric_sklearn | -0.0293 | [-0.0387, -0.0210] | 0.000 | yes |
| pr_auc | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| pr_auc | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

### precision_at_fpr_5pct
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| precision_at_fpr_5pct | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.4019 | [-0.0984, +0.0114] | 1.000 | no |
| precision_at_fpr_5pct | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.4019 | [-0.0984, +0.0114] | 1.000 | no |
| precision_at_fpr_5pct | bi_encoder_hybrid | logistic_numeric_sklearn | +0.4019 | [-0.0984, +0.0114] | 1.000 | no |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| precision_at_fpr_5pct | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

### recall_at_5
| metric | a | b | delta (b-a) | 95% CI | p-value | significant? |
| --- | --- | --- | ---: | --- | ---: | :---: |
| recall_at_5 | bi_encoder_hybrid | calibrated_random_forest_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | bi_encoder_hybrid | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | calibrated_random_forest_numeric | hist_gradient_boosting_numeric | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | calibrated_random_forest_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |
| recall_at_5 | hist_gradient_boosting_numeric | logistic_numeric_sklearn | +0.0000 | [+0.0000, +0.0000] | 1.000 | no |

## Per-family PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| family=wol-kafka | 2761 | 0.415 | 0.415 | 0.415 | 0.458 |
| family=wol-mariadb-server | 10627 | 0.529 | 0.529 | 0.529 | 0.545 |

## Per-family recall@5
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| family=wol-kafka | 2761 | 0.000 | 0.000 | 0.000 | 0.000 |
| family=wol-mariadb-server | 10627 | 0.000 | 0.000 | 0.000 | 0.000 |

## Per-window-type PR-AUC
| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| window_type=active_fault | 13388 | 0.506 | 0.506 | 0.506 | 0.535 |

## Stratified by is_hard_case (True = engineered to confuse simple models)

F1 here directly answers 'does the pipeline handle hard cases?'. The gap between true and false is the practical hard-case headroom.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| is_hard_case=false | 13388 | 0.976 | 0.976 | 0.976 | 0.108 |

## Stratified by triage_reason_class

Per fault category — `outage`, `latency_regression`, `restart_with_impact`, etc. Rows where PR-AUC is low identify the fault types your model doesn't detect well.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| triage_reason_class=latency_regression | 372 | 0.403 | 0.403 | 0.403 | 0.492 |
| triage_reason_class=network | 468 | 0.415 | 0.415 | 0.415 | 0.474 |
| triage_reason_class=other | 9948 | 0.506 | 0.506 | 0.506 | 0.535 |
| triage_reason_class=outage | 379 | 0.536 | 0.536 | 0.536 | 0.608 |
| triage_reason_class=restart_with_impact | 2221 | 0.537 | 0.537 | 0.537 | 0.545 |

## Stratified by is_novel (true = no matching past Jira; false = match exists; unscored = not ticket_worthy)

Novel incidents are the product axis where Jira pattern matching fundamentally cannot help — the model must detect from telemetry alone. If pipelines drop substantially on `novel` vs `known`, they're leaning on memory pattern matching.

| strata | n | hist_gradient_boosting_numeric | calibrated_random_forest_numeric | logistic_numeric_sklearn | bi_encoder_hybrid |
| --- | --- | --- | --- | --- | --- |
| is_novel=known | 11765 | 0.438 | 0.438 | 0.438 | 0.464 |
| is_novel=novel | 1623 | 0.000 | 0.000 | 0.000 | 0.000 |

## Inclusive borderline handling (borderline counted as positive)

The strict variant above is the headline. This inclusive variant rewards pipelines that surface human-interesting (borderline) windows. Pipelines whose inclusive PR-AUC is meaningfully higher than their strict PR-AUC are picking up signal on the borderline class even if they don't quite call it `ticket_worthy`.

### Overall PR-AUC (inclusive)

| Pipeline | PR-AUC | ROC-AUC | ECE | Precision@FPR=5% |
| --- | ---: | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 0.9066 | 0.5000 | 0.4066 | 0.9949 |
| `calibrated_random_forest_numeric` | 0.9066 | 0.5000 | 0.4340 | 0.9949 |
| `logistic_numeric_sklearn` | 0.9066 | 0.5000 | 0.4066 | 0.9949 |
| `bi_encoder_hybrid` | 0.9242 | 0.5774 | 0.4409 | 0.9257 |

## Leave-one-family-out macros (numeric pipelines)

Each family is held out as the test set; train uses all other families pooled across train+val+test. The macro average weights every family equally regardless of size. Single-class folds (no positives in the held-out family) are skipped.

**The macro is the primary generalization signal.** A pipeline that wins the fixed-split leaderboard but loses LOFO has overfit to the families that happen to be in the train split.

### Headline LOFO macros (strict)

| Pipeline | Folds scored | Macro PR-AUC | Macro ROC-AUC |
| --- | ---: | ---: | ---: |
| `hist_gradient_boosting_numeric` | 24 | 0.4901 | 0.5000 |
| `calibrated_random_forest_numeric` | 24 | 0.4901 | 0.5000 |
| `logistic_numeric_sklearn` | 24 | 0.4901 | 0.5000 |

### Per-family LOFO PR-AUC

| Family | n_windows | n_pos | `hist_gradient_boosting_numeric` | `calibrated_random_forest_numeric` | `logistic_numeric_sklearn` |
| --- | ---: | ---: | ---: | ---: | ---: |
| wol-activemq | 1920 | 944 | 0.4917 | 0.4917 | 0.4917 |
| wol-ambari | 3836 | 3084 | 0.8040 | 0.8040 | 0.8040 |
| wol-apache-arrow | 2146 | 1060 | 0.4939 | 0.4939 | 0.4939 |
| wol-apache-drill | 2453 | 1169 | 0.4766 | 0.4766 | 0.4766 |
| wol-beam | 2094 | 1005 | 0.4799 | 0.4799 | 0.4799 |
| wol-camel | 2124 | 1214 | 0.5716 | 0.5716 | 0.5716 |
| wol-cassandra | 4576 | 2121 | 0.4635 | 0.4635 | 0.4635 |
| wol-cxf | 1824 | 1116 | 0.6118 | 0.6118 | 0.6118 |
| wol-derby | 2240 | 1231 | 0.5496 | 0.5496 | 0.5496 |
| wol-flink | 4453 | 2098 | 0.4711 | 0.4711 | 0.4711 |
| wol-geode | 2744 | 1651 | 0.6017 | 0.6017 | 0.6017 |
| wol-hadoop-common | 2342 | 1144 | 0.4885 | 0.4885 | 0.4885 |
| wol-hadoop-hdfs | 2349 | 1014 | 0.4317 | 0.4317 | 0.4317 |
| wol-hadoop-yarn | 1741 | 827 | 0.4750 | 0.4750 | 0.4750 |
| wol-hbase | 4136 | 2433 | 0.5882 | 0.5882 | 0.5882 |
| wol-hive | 4178 | 1894 | 0.4533 | 0.4533 | 0.4533 |
| wol-ignite | 2655 | 1346 | 0.5070 | 0.5070 | 0.5070 |
| wol-impala | 3462 | 1931 | 0.5578 | 0.5578 | 0.5578 |
| wol-infinispan | 2454 | 1 | 0.0004 | 0.0004 | 0.0004 |
| wol-kafka | 2761 | 1147 | 0.4154 | 0.4154 | 0.4154 |
| wol-mariadb-server | 10627 | 5626 | 0.5294 | 0.5294 | 0.5294 |
| wol-mesos | 2234 | 1125 | 0.5036 | 0.5036 | 0.5036 |
| wol-solr | 2206 | 903 | 0.4093 | 0.4093 | 0.4093 |
| wol-spark | 6585 | 2558 | 0.3885 | 0.3885 | 0.3885 |
