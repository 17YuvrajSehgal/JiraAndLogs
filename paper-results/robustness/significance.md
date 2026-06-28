# Significance — paired bootstrap (Hit@5) + Benjamini-Hochberg

1000 resamples, seed 42, two-sided, BH FDR α=0.05 across 15 tests.

| comparison | Hybrid Hit@5 | other | Δ | 95% CI | p | q(BH) | sig |
|---|---|---|---|---|---|---|---|
| online-boutique: Hybrid vs BiEncoder | 0.559 | 0.634 | -0.076 | [-0.136,-0.018] | 0.016 | 0.027 | ✓ |
| online-boutique: Hybrid vs BM25(fair) | 0.559 | 0.356 | +0.202 | [+0.136,+0.275] | 0.000 | 0.000 | ✓ |
| online-boutique: Hybrid vs BGE-dense | 0.559 | 0.341 | +0.218 | [+0.163,+0.275] | 0.000 | 0.000 | ✓ |
| online-boutique: Hybrid vs KG | 0.559 | 0.465 | +0.094 | [+0.033,+0.151] | 0.002 | 0.004 | ✓ |
| online-boutique: Hybrid vs LLM-RAG | 0.559 | 0.344 | +0.215 | [+0.157,+0.272] | 0.000 | 0.000 | ✓ |
| online-boutique: KG-effect (Hybrid vs no-graph) | 0.559 | 0.592 | -0.033 | [-0.076,+0.006] | 0.148 | 0.202 | · |
| otel-demo: Hybrid vs BiEncoder | 0.672 | 0.681 | -0.008 | [-0.076,+0.059] | 0.938 | 0.942 | · |
| otel-demo: Hybrid vs BM25(fair) | 0.672 | 0.597 | +0.076 | [+0.000,+0.160] | 0.064 | 0.096 | · |
| otel-demo: Hybrid vs BGE-dense | 0.672 | 0.664 | +0.008 | [-0.059,+0.076] | 0.942 | 0.942 | · |
| otel-demo: Hybrid vs KG | 0.672 | 0.412 | +0.261 | [+0.151,+0.370] | 0.000 | 0.000 | ✓ |
| otel-demo: Hybrid vs LLM-RAG | 0.672 | 0.639 | +0.034 | [-0.034,+0.101] | 0.444 | 0.555 | · |
| otel-demo: KG-effect (Hybrid vs no-graph) | 0.672 | 0.681 | -0.008 | [-0.059,+0.042] | 0.886 | 0.942 | · |
| wol-v3: Hybrid vs BiEncoder | 0.970 | 0.905 | +0.065 | [+0.058,+0.073] | 0.000 | 0.000 | ✓ |
| wol-v3: Hybrid vs BGE-dense | 0.970 | 0.829 | +0.141 | [+0.131,+0.152] | 0.000 | 0.000 | ✓ |
| wol-v3: Hybrid vs LLM-RAG | 0.978 | 0.856 | +0.122 | [+0.094,+0.152] | 0.000 | 0.000 | ✓ |
