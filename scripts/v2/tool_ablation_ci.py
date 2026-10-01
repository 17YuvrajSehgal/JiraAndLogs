"""Paired-bootstrap CIs for the evidence-tool ablation (paper Fig. 4b).

R3 asked why Fig. 3 gets confidence intervals and Fig. 4 does not. There was no
principled reason — the per-case data needed for a paired bootstrap was already
in `paper-results/agent-value/*/tool-cells/*-report.json`; we simply plotted
point estimates. This script computes the intervals with the same procedure
Fig. 3 uses (1,000 resamples, seed 42, paired over bundles evaluable in both
cells) and writes them where the figure script can read them.

Two findings change the paper:

  * "the extended-trace reader is net-harmful to top-1" SURVIVES, but only in
    isolation: -0.018 Hit@1 (CI excludes 0) against the empty tool set, and only
    -0.003 (n.s.) when added on top of the peer-incident lookup.
  * "the peer-incident lookup is the only clearly beneficial tool" DOES NOT
    SURVIVE: +0.015 with a CI that includes zero.

On OTel Demo and World of Logs every tool effect is identically 0.000 with a
degenerate CI — the tools never change the outcome there at all.

Usage
-----
    python scripts/v2/tool_ablation_ci.py \
        --paper-results paper-results --out paper-results-v2/tool-ablation-ci
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

#: Single-tool cells plus the no-tool reference, in the order Fig. 4b draws them.
SINGLE_TOOLS = ("events", "trace", "metrics", "peers")

#: (with_tool_cell, without_tool_cell) pairs that isolate the trace reader's
#: effect in different tool contexts — the conditional form of the claim.
TRACE_CONTEXTS = (
    ("trace", "none"),
    ("events+trace", "events"),
    ("trace+metrics", "metrics"),
    ("trace+peers", "peers"),
    ("events+trace+metrics+peers", "events+metrics+peers"),
)

B_DEFAULT = 1000
SEED_DEFAULT = 42


def load_cell(root: Path, dataset: str, cell: str) -> dict[str, dict] | None:
    p = root / "agent-value" / dataset / "tool-cells" / f"{cell}-report.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return {c["bundle_id"]: c for c in d.get("case_results", [])}


def paired_bootstrap(a: dict, b: dict, metric: str, *, n_boot: int, seed: int):
    """Bootstrap b-minus-a over bundles scoreable in BOTH cells.

    Returns None when the two cells share no evaluable bundle for this metric.
    """
    keys = [k for k in a
            if k in b
            and a[k].get(metric) is not None
            and b[k].get(metric) is not None]
    if not keys:
        return None
    da = [float(a[k][metric]) for k in keys]
    db = [float(b[k][metric]) for k in keys]
    n = len(keys)
    observed = sum(db) / n - sum(da) / n

    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(db[i] - da[i] for i in idx) / n)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[int(0.975 * n_boot)]
    # two-sided bootstrap p: twice the smaller tail mass at 0
    p = 2 * min(sum(1 for x in diffs if x <= 0),
                sum(1 for x in diffs if x >= 0)) / n_boot
    return {
        "delta": observed,
        "ci_low": lo,
        "ci_high": hi,
        "p": min(1.0, p),
        "significant": bool(lo > 0 or hi < 0),
        "n_paired": n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper-results", type=Path, default=Path("paper-results"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--datasets", nargs="+",
                    default=["online-boutique", "otel-demo", "wol-v3"])
    ap.add_argument("--n-bootstrap", type=int, default=B_DEFAULT)
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    out: dict[str, dict] = {
        "_meta": {
            "n_bootstrap": args.n_bootstrap,
            "seed": args.seed,
            "procedure": "paired bootstrap over bundles evaluable in both cells; "
                         "same protocol as the Fig. 3 significance forest",
        }
    }

    for ds in args.datasets:
        base = load_cell(args.paper_results, ds, "none")
        if base is None:
            print(f"[skip] {ds}: no 'none' tool cell")
            continue
        print(f"\n=== {ds} — single-tool effect vs the no-tool cell ===")
        print(f"{'tool':<10}{'dHit@1':>10}{'95% CI':>22}{'p':>8}  "
              f"{'dHit@5':>10}{'95% CI':>22}")
        singles: dict[str, dict] = {}
        for tool in SINGLE_TOOLS:
            cur = load_cell(args.paper_results, ds, tool)
            if cur is None:
                continue
            r1 = paired_bootstrap(base, cur, "hit_at_1",
                                  n_boot=args.n_bootstrap, seed=args.seed)
            r5 = paired_bootstrap(base, cur, "hit_at_5",
                                  n_boot=args.n_bootstrap, seed=args.seed)
            if r1 is None:
                continue
            singles[tool] = {"hit_at_1": r1, "hit_at_5": r5}
            star = "*" if r1["significant"] else " "
            ci1 = f"[{r1['ci_low']:+.4f},{r1['ci_high']:+.4f}]"
            ci5 = f"[{r5['ci_low']:+.4f},{r5['ci_high']:+.4f}]"
            print(f"{tool:<10}{r1['delta']:>+10.4f}{ci1:>22}{r1['p']:>8.3f}{star} "
                  f"{r5['delta']:>+10.4f}{ci5:>22}")

        # The trace reader's effect is context-dependent; record every context
        # so the paper can state the conditional form instead of the bare claim.
        contexts: dict[str, dict] = {}
        for with_cell, without_cell in TRACE_CONTEXTS:
            a = load_cell(args.paper_results, ds, without_cell)
            b = load_cell(args.paper_results, ds, with_cell)
            if a is None or b is None:
                continue
            r = paired_bootstrap(a, b, "hit_at_1",
                                 n_boot=args.n_bootstrap, seed=args.seed)
            if r:
                contexts[f"{without_cell} -> {with_cell}"] = r
        if contexts:
            print(f"\n  trace-reader effect on Hit@1, by context:")
            for k, r in contexts.items():
                print(f"    {k:<52} {r['delta']:+.4f} "
                      f"[{r['ci_low']:+.4f},{r['ci_high']:+.4f}] "
                      f"{'SIG' if r['significant'] else 'n.s.'}")

        out[ds] = {"singles": singles, "trace_contexts": contexts}

    dest = args.out / "tool-ablation-ci.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")

    # Explicit callouts for the two claims this analysis changes.
    ob = out.get("online-boutique", {}).get("singles", {})
    if "peers" in ob:
        r = ob["peers"]["hit_at_1"]
        if not r["significant"]:
            print(f"\n[claim check] 'peer-incident lookup is the only clearly "
                  f"beneficial tool' is NOT supported: {r['delta']:+.4f} "
                  f"CI [{r['ci_low']:+.4f},{r['ci_high']:+.4f}] includes zero.")
    if "trace" in ob:
        r = ob["trace"]["hit_at_1"]
        if r["significant"]:
            print(f"[claim check] 'extended-trace reader is net-harmful to top-1' "
                  f"holds in isolation: {r['delta']:+.4f} "
                  f"CI [{r['ci_low']:+.4f},{r['ci_high']:+.4f}] — but see the "
                  f"context table; the effect vanishes alongside the peer lookup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
