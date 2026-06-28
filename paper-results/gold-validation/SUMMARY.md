# Gold validation (LLM-as-judge) — SUMMARY

Qwen2.5-7B rates gold ticket vs a random control (1-5). A positive gap (gold > random) is evidence the gold labels are meaningful.

| dataset | gold mean | random mean | gap | gold %rel(≥4) | random %rel |
|---|---|---|---|---|---|
| online-boutique | 2.35 | 1.89 | 0.47 | 16% | 6% |
| otel-demo | 2.31 | 1.97 | 0.34 | 11% | 3% |
| wol-v3 | 2.60 | 1.36 | 1.24 | 6% | 0% |
