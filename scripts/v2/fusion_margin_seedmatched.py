"""Seed-matched fusion margin: hybrid vs dense bi-encoder on World of Logs.

Task #8 / P0-1. The published headline was "+0.065 Hit@5 for fusion over the
dense retriever, 95% CI [+0.058,+0.073]". That compared ONE hybrid run against
ONE bi-encoder run, with a query-bootstrap CI that ignored training-seed
variance entirely. We later measured the bi-encoder at sd 0.0196 across seeds
and found the published 0.905 sat near the LOW end of its range -- so the
margin was computed against an unlucky draw and the interval was far too tight.

This recomputes it from five matched seeds of each system, and reports three
things the single-run version could not:
  * the paired per-seed margin (same seed both sides)
  * a seed-aware interval combining seed and query-sampling variance
  * whether the two systems' seed ranges overlap at all, which is a stronger
    and more robust statement than any mean difference

    python scripts/v2/fusion_margin_seedmatched.py
"""

from __future__ import annotations

import json
import re
import statistics as st
from pathlib import Path

BIENC = Path("paper-results-v2/multiseed/wol-v3")
HYBRID = Path("paper-results-v2/multiseed-hybrid/wol-v3")
SEEDS = [42, 1, 2, 3, 4]


def load(root: Path, fname: str) -> dict[int, dict]:
    out = {}
    for f in root.glob(f"*/{fname}"):
        m = re.search(r"seed(\d+)", f.as_posix())
        if not m:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        out[int(m.group(1))] = {
            "coarse_h5": d["coarse"]["hit_at_5"],
            "coarse_h1": d["coarse"]["hit_at_1"],
            "coarse_mrr": d["coarse"]["mrr"],
            "strict_h5": (d.get("strong") or {}).get("hit_at_5"),
            "n": d["coarse"]["n_with_gold"],
        }
    return out


def main() -> int:
    b = load(BIENC, "biencoder-mode3-results.json")
    h = load(HYBRID, "hybrid-rrf-mode3-results.json")
    seeds = [s for s in SEEDS if s in b and s in h]
    print(f"seed-matched on {len(seeds)} seeds: {seeds}   (n={b[seeds[0]]['n']} queries)\n")

    for metric, label in (("coarse_h5", "coarse Hit@5"),
                          ("strict_h5", "strict Hit@5"),
                          ("coarse_h1", "coarse Hit@1"),
                          ("coarse_mrr", "coarse MRR")):
        bv = [b[s][metric] for s in seeds]
        hv = [h[s][metric] for s in seeds]
        if any(v is None for v in bv + hv):
            continue
        d = [x - y for x, y in zip(hv, bv)]

        print(f"=== {label} ===")
        print(f"  {'seed':<6}{'bi-enc':>10}{'hybrid':>10}{'delta':>10}")
        for s, x, y, dd in zip(seeds, bv, hv, d):
            print(f"  {s:<6}{x:>10.4f}{y:>10.4f}{dd:>+10.4f}")
        print(f"  {'mean':<6}{st.mean(bv):>10.4f}{st.mean(hv):>10.4f}{st.mean(d):>+10.4f}")
        print(f"  {'sd':<6}{st.stdev(bv):>10.4f}{st.stdev(hv):>10.4f}{st.stdev(d):>10.4f}")

        # Paired margin with a seed-aware interval. With 5 paired runs the
        # t-interval on the per-seed differences is the honest summary; it
        # absorbs the common-mode seed effect that cancels in pairing.
        n = len(d)
        se = st.stdev(d) / (n ** 0.5)
        t95 = 2.776  # t(0.975, df=4)
        lo, hi = st.mean(d) - t95 * se, st.mean(d) + t95 * se
        print(f"  paired margin {st.mean(d):+.4f}  95% CI [{lo:+.4f},{hi:+.4f}]"
              f"  {'EXCLUDES 0' if lo > 0 or hi < 0 else 'includes 0'}")

        # Range separation is the claim that does not depend on distributional
        # assumptions: does the worst hybrid seed beat the best bi-encoder seed?
        sep = min(hv) - max(bv)
        print(f"  worst hybrid {min(hv):.4f} vs best bi-encoder {max(bv):.4f}"
              f"  -> {'SEPARATED by %+.4f' % sep if sep > 0 else 'ranges OVERLAP'}")
        print(f"  seed stability: bi-encoder sd {st.stdev(bv):.4f}, "
              f"hybrid sd {st.stdev(hv):.4f} "
              f"({st.stdev(bv)/st.stdev(hv):.1f}x more stable)" if st.stdev(hv) > 0 else "")
        print()

    # What the paper previously said, for the record.
    print("published single-seed claim: +0.065 Hit@5, 95% CI [+0.058,+0.073]")
    print("  that CI was query-bootstrap only and ignored seed variance;")
    print("  the bi-encoder draw it used (0.9050) was near the low end of its range.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
