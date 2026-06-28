# Triage-quality leaderboard — SUMMARY

Triage classification (ticket-worthy vs noise) + retrieval, from the comparison harness (offline-safe pipelines, seed 42, n_bootstrap=1000). PR-AUC / ECE (calibration) / precision@FPR=5% are the operating-point metrics raw accuracy can't capture.

## online-boutique
| pipeline | PR-AUC | ROC-AUC | ECE↓ | P@FPR5 | R@FPR5 | Rec@5 | MRR |
|---|---|---|---|---|---|---|---|
| hist_gradient_boosting_numeric | 1.000 | 1.000 | 0.012 | 0.848 | 1.000 | 0.000 | 0.000 |
| calibrated_random_forest_numeric | 0.986 | 0.996 | 0.059 | 0.846 | 0.982 | 0.000 | 0.000 |
| logistic_numeric_sklearn | 0.764 | 0.916 | 0.109 | 0.766 | 0.587 | 0.000 | 0.000 |
| bm25_retrieval_only | 0.206 | 0.500 | 0.784 | 0.250 | 0.060 | 0.038 | 0.054 |
| bi_encoder_hybrid | 0.769 | 0.921 | 0.108 | 0.777 | 0.624 | 0.000 | 0.000 |

## otel-demo
| pipeline | PR-AUC | ROC-AUC | ECE↓ | P@FPR5 | R@FPR5 | Rec@5 | MRR |
|---|---|---|---|---|---|---|---|
| hist_gradient_boosting_numeric | 1.000 | 1.000 | 0.000 | 0.895 | 1.000 | 0.000 | 0.000 |
| calibrated_random_forest_numeric | 1.000 | 1.000 | 0.003 | 0.895 | 1.000 | 0.000 | 0.000 |
| logistic_numeric_sklearn | 1.000 | 1.000 | 0.048 | 0.895 | 1.000 | 0.000 | 0.000 |
| bm25_retrieval_only | 0.301 | 0.496 | 0.682 | 0.429 | 0.088 | 0.108 | 0.440 |
| bi_encoder_hybrid | 1.000 | 1.000 | 0.047 | 0.895 | 1.000 | 0.000 | 0.000 |

## wol-v3
| pipeline | PR-AUC | ROC-AUC | ECE↓ | P@FPR5 | R@FPR5 | Rec@5 | MRR |
|---|---|---|---|---|---|---|---|
| hist_gradient_boosting_numeric | 0.506 | 0.500 | 0.006 | 0.954 | 1.000 | 0.000 | 0.000 |
| calibrated_random_forest_numeric | 0.506 | 0.500 | 0.033 | 0.954 | 1.000 | 0.000 | 0.000 |
| logistic_numeric_sklearn | 0.506 | 0.500 | 0.006 | 0.954 | 1.000 | 0.000 | 0.000 |
| bi_encoder_hybrid | 0.535 | 0.541 | 0.059 | 0.552 | 0.060 | 0.000 | 0.000 |

