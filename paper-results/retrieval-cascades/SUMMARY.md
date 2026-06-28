# Retrieval cascades — SUMMARY

Coarse-match Hit@K / MRR on the test split (per-pipeline panel).

| dataset | metric | BiEncoder | BM25(raw-corpus) | KG | Hybrid-RRF |
|---|---|---|---|---|---|
| online-boutique | hit_at_1 | 0.432 | 0.051 | 0.396 | 0.414 |
|  | hit_at_5 | 0.634 | 0.088 | 0.465 | 0.559 |
|  | mrr | 0.512 | 0.065 | 0.420 | 0.461 |
| otel-demo | hit_at_1 | 0.445 | 0.387 | 0.067 | 0.513 |
|  | hit_at_5 | 0.681 | 0.563 | 0.412 | 0.672 |
|  | mrr | 0.549 | 0.432 | 0.227 | 0.568 |
| wol-v3 | hit_at_1 | 0.856 | 0.015 | 0.083 | 0.839 |
|  | hit_at_5 | 0.905 | 0.727 | 0.308 | 0.970 |
|  | mrr | 0.874 | 0.329 | 0.152 | 0.897 |
