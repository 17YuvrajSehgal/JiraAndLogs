# Agent value — SUMMARY

What the controller adds: cost saved vs always-run-everything (cascade counterfactual) at iso-accuracy, plus skill/tool/budget ablations.

## Cost vs cascade-counterfactual (controller gating)
| dataset | wall saved % | tokens saved % | $ saved % | n_windows |
|---|---|---|---|---|
| online-boutique | 39.970 | 41.120 | 41.120 | 1008 |
| otel-demo | 63.370 | 65.280 | 65.280 | 247 |
| wol-v3 | 78.090 | 78.990 | 78.990 | 13388 |

## Most damaging skill (ablation) + tool/budget headroom
| dataset | top-damage skill (ΔHit@1) | tool best vs none Hit@1 | budget Hit@5 (min→max) |
|---|---|---|---|
| online-boutique | no_react (-0.012) | 0.692 vs 0.677 | 0.758 → 0.758 |
| otel-demo | no_hybrid (+0.000) | 0.647 vs 0.647 | 0.756 → 0.756 |
| wol-v3 | no_hybrid (-0.004) | 0.859 vs 0.859 | 0.963 → 0.963 |
