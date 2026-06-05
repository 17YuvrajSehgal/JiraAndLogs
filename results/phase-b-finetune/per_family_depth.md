# Per-family × per-depth Hit@5 cross-stratification

Cells = mean Hit@5. Empty cells = zero retrievable windows in that (family, bucket).

## Per pipeline tables

### hist_gradient_boosting_numeric

| family | 1-2 | 3-5 | 6-20 | 21+ |
|---| ---: | ---: | ---: | ---: |
| `cart-redis` | 0.000 (n=16) | 0.000 (n=24) | 0.000 (n=92) | 0.000 (n=28) |
| `checkout-outage` | 0.000 (n=8) | 0.000 (n=12) | 0.000 (n=32) | — |
| `currency-outage` | 0.000 (n=6) | 0.000 (n=9) | 0.000 (n=24) | — |
| `network-latency` | 0.000 (n=6) | 0.000 (n=9) | 0.000 (n=12) | — |
| `productcatalog-latency` | 0.000 (n=6) | 0.000 (n=9) | 0.000 (n=24) | — |

### memorygraph_v2_sota_nw080

| family | 1-2 | 3-5 | 6-20 | 21+ |
|---| ---: | ---: | ---: | ---: |
| `cart-redis` | 0.125 (n=16) | 0.125 (n=24) | 0.196 (n=92) | 0.250 (n=28) |
| `checkout-outage` | 0.000 (n=8) | 0.000 (n=12) | 0.000 (n=32) | — |
| `currency-outage` | 0.500 (n=6) | 0.222 (n=9) | 0.208 (n=24) | — |
| `network-latency` | 0.000 (n=6) | 0.000 (n=9) | 0.000 (n=12) | — |
| `productcatalog-latency` | 0.500 (n=6) | 0.556 (n=9) | 0.667 (n=24) | — |

### memorygraph_v2_sota_nw080_ft

| family | 1-2 | 3-5 | 6-20 | 21+ |
|---| ---: | ---: | ---: | ---: |
| `cart-redis` | 0.125 (n=16) | 0.125 (n=24) | 0.185 (n=92) | 0.250 (n=28) |
| `checkout-outage` | 0.000 (n=8) | 0.000 (n=12) | 0.000 (n=32) | — |
| `currency-outage` | 0.500 (n=6) | 0.444 (n=9) | 0.250 (n=24) | — |
| `network-latency` | 0.000 (n=6) | 0.000 (n=9) | 0.333 (n=12) | — |
| `productcatalog-latency` | 0.500 (n=6) | 0.556 (n=9) | 0.667 (n=24) | — |
