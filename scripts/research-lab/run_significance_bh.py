"""Paired-bootstrap significance + Benjamini-Hochberg correction (robustness).

For the headline retrieval claims (Hybrid-RRF vs each competitor, and the KG
±graph effect), compute per-window Hit@5 paired-bootstrap deltas + two-sided
p-values (seed 42, 1000 resamples), then apply BH FDR correction across the
whole family of tests. Writes paper-results/robustness/significance-bh.{json,md}.

Predictions are read from the on-disk JSONLs (gitignored but present).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from agent.eval_harness.bootstrap import benjamini_hochberg

ROOT = Path("paper-results")
N_BOOT, SEED, K = 1000, 42, 5


def hit5_by_window(path: Path) -> dict[str, int]:
    """window_id -> Hit@5 indicator (only windows with gold)."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        gold = set(d.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        top = list(d.get("matched_issue_ids") or [])[:K]
        out[d["window_id"]] = int(any(t in gold for t in top))
    return out


def paired(a_map: dict, b_map: dict):
    keys = sorted(set(a_map) & set(b_map))
    if not keys:
        return None
    a = np.array([a_map[k] for k in keys], float)
    b = np.array([b_map[k] for k in keys], float)
    delta = float(a.mean() - b.mean())
    rng = np.random.default_rng(SEED)
    n = len(keys)
    deltas = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, n)            # same indices for both -> paired
        deltas[i] = a[idx].mean() - b[idx].mean()
    # two-sided p: fraction of resamples on the opposite side of 0
    p = 2.0 * min((deltas <= 0).mean(), (deltas >= 0).mean())
    p = min(1.0, p)
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return {"n_paired": n, "delta_hit5": delta, "ci95": [float(lo), float(hi)],
            "p_value": float(p), "a_hit5": float(a.mean()), "b_hit5": float(b.mean())}


def main():
    cas = lambda ds, m: ROOT / "retrieval-cascades" / ds / f"{m}-predictions.jsonl"
    base = lambda fam, ds, m: ROOT / "baselines" / fam / ds / f"{m}-predictions.jsonl"
    nog = lambda ds: ROOT / "kg-usefulness" / ds / "hybrid-rrf-nograph-predictions.jsonl"

    comparisons = []
    for ds in ["online-boutique", "otel-demo", "wol-v3"]:
        H = cas(ds, "hybrid-rrf")
        comparisons += [
            (f"{ds}: Hybrid vs BiEncoder", H, cas(ds, "biencoder")),
            (f"{ds}: Hybrid vs BM25(fair)", H, base("bm25", ds, "bm25")),
            (f"{ds}: Hybrid vs BGE-dense", H, base("sota-dense", ds, "bge")),
            (f"{ds}: Hybrid vs KG", H, cas(ds, "kg-retrieval")),
            (f"{ds}: Hybrid vs LLM-RAG", H, base("llm-rag", ds, "llm-rag")),
            (f"{ds}: KG-effect (Hybrid vs no-graph)", H, nog(ds)),
        ]

    results, pvals = [], []
    for label, pa, pb in comparisons:
        r = paired(hit5_by_window(pa), hit5_by_window(pb))
        if r is None:
            print(f"SKIP (no shared/missing): {label}")
            continue
        r["comparison"] = label
        results.append(r)
        pvals.append(r["p_value"])

    bh = benjamini_hochberg(pvals, alpha=0.05)
    for r, q, rej in zip(results, bh["qvalues"], bh["rejected"]):
        r["q_value_bh"] = q
        r["significant_bh"] = bool(rej)

    out = {"method": "paired bootstrap Hit@5, two-sided", "n_resamples": N_BOOT,
           "seed": SEED, "alpha": 0.05, "correction": "benjamini-hochberg",
           "n_tests": len(results), "results": results}
    (ROOT / "robustness").mkdir(parents=True, exist_ok=True)
    (ROOT / "robustness" / "significance-bh.json").write_text(json.dumps(out, indent=2))

    md = ["# Significance — paired bootstrap (Hit@5) + Benjamini-Hochberg", "",
          f"{N_BOOT} resamples, seed {SEED}, two-sided, BH FDR α=0.05 across "
          f"{len(results)} tests.", "",
          "| comparison | Hybrid Hit@5 | other | Δ | 95% CI | p | q(BH) | sig |",
          "|---|---|---|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['comparison']} | {r['a_hit5']:.3f} | {r['b_hit5']:.3f} | "
                  f"{r['delta_hit5']:+.3f} | [{r['ci95'][0]:+.3f},{r['ci95'][1]:+.3f}] | "
                  f"{r['p_value']:.3f} | {r['q_value_bh']:.3f} | {'✓' if r['significant_bh'] else '·'} |")
    (ROOT / "robustness" / "significance.md").write_text("\n".join(md) + "\n")
    print(f"wrote significance for {len(results)} tests; "
          f"{sum(r['significant_bh'] for r in results)} significant after BH")


if __name__ == "__main__":
    main()
