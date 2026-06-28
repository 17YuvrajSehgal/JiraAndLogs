# KG complementarity (angle 2) — unique-hit analysis

Per window-with-gold (shared across retrievers), Hit@5. 'KG correct/dense wrong' = windows the graph gets right that the BiEncoder misses (the graph's marginal recall); 'KG unique vs both' = only the graph is correct (neither dense nor sparse).

| dataset | n | BiEncoder | KG | BM25 | KG✓&dense✗ | dense✓&KG✗ | KG-only(vs both) | union |
|---|---|---|---|---|---|---|---|---|
| online-boutique | 331 | 0.634 | 0.465 | 0.088 | 14.2% | 31.1% | 13.6% | 0.779 |
| otel-demo | 119 | 0.681 | 0.412 | 0.563 | 10.1% | 37.0% | 4.2% | 0.790 |
| wol-v3 | 5150 | 0.905 | 0.308 | 0.727 | 1.6% | 61.4% | 0.5% | 0.974 |

**Reading:** a non-trivial 'KG✓&dense✗' and 'KG-only' share means the graph adds correct candidates the embedding/lexical retrievers miss — justifying its inclusion in the RRF fusion even when KG-alone Hit@5 is low. The union coverage upper-bounds what a perfect fuser could reach.
