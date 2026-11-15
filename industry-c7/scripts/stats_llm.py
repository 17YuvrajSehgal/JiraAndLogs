"""Paired bootstraps for the LLM comparisons (same machinery as
stats.py / stats_irbl.py: 2,000 resamples, shared indices per
population, Benjamini-Hochberg over the whole family).

Comparisons, each on the instances BOTH systems answered:
  ours_vs_llm_a2    cond_ours      - LLM standalone (Agentless 2-stage)
  llm_rr_vs_ours    LLM rerank     - cond_ours        (does the LLM add?)
  llm_rr_vs_llm_a2  LLM rerank     - LLM standalone   (does retrieval add?)
  llm_deid_effect   LLM standalone - its de-identified replay (contamination)
  llm_think_effect  thinking-ON    - thinking-OFF     (reasoning ablation)

Usage:
    python industry-c7/scripts/stats_llm.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
LLM = ROOT / "industry-c7/data/llm"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
METRICS = ("acc@5", "acc@10", "mrr")
B, SEED = 2000, 42


def load(tag: str) -> dict[str, dict]:
    path = LLM / f"scored-{tag}.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if not d.get("variant"):
            out[d["id"]] = d
    return out


def paired_boot(da, db, idx):
    n = len(da)
    obs = sum(da) / n - sum(db) / n
    ds = sorted(sum(da[i] - db[i] for i in s) / n for s in idx)
    p = 2 * min(sum(1 for x in ds if x <= 0), sum(1 for x in ds if x >= 0)) / len(ds)
    return {"delta": round(obs, 4), "ci_low": round(ds[int(.025 * B)], 4),
            "ci_high": round(ds[int(.975 * B)], 4), "p": min(1.0, p), "n": n}


def main() -> int:
    rng = random.Random(SEED)
    a2, rr = load("a2"), load("rr")
    a2d, think = load("a2d"), load("a2-think")
    pairs = [("ours_vs_llm_a2", a2, "ours", a2, "llm"),
             ("llm_rr_vs_ours", rr, "llm", rr, "ours"),
             ("llm_rr_vs_llm_a2", rr, "llm", a2, "llm"),
             ("llm_deid_effect", a2, "llm", a2d, "llm"),
             ("llm_think_effect", think, "llm", a2, "llm")]
    tests = []
    for name, A, akey, Bm, bkey in pairs:
        if not A or not Bm:
            continue
        for proj in P:
            ids = [i for i in A if i in Bm and A[i]["project"] == proj
                   and A[i]["is_eval"] and Bm[i]["is_eval"]]
            if len(ids) < 30:
                continue
            for pop_name, pop in (
                    ("overall", ids),
                    ("hard", [i for i in ids if not A[i]["strata"]["easy"]])):
                if len(pop) < 30:
                    continue
                n = len(pop)
                idx = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
                for metric in METRICS:
                    da = [(A[i]["metrics"] if akey == "llm"
                           else A[i]["ours_metrics"])[metric] for i in pop]
                    db = [(Bm[i]["metrics"] if bkey == "llm"
                           else Bm[i]["ours_metrics"])[metric] for i in pop]
                    tests.append({"project": proj, "population": pop_name,
                                  "comparison": name, "metric": metric,
                                  **paired_boot(da, db, idx)})
    if not tests:
        print("no comparisons available yet")
        return 1
    m = len(tests)
    order = sorted(range(m), key=lambda j: tests[j]["p"])
    prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, tests[j]["p"] * m / (m - rank + 1))
        tests[j]["q_bh"] = round(prev, 4)
        tests[j]["significant"] = prev < 0.05
    (RES / "stats-llm.json").write_text(
        json.dumps({"seed": SEED, "n_bootstrap": B, "n_tests": m,
                    "tests": tests}, indent=2), encoding="utf-8")
    for t in tests:
        if t["metric"] != "acc@5":
            continue
        print(f"{t['project']:<9}{t['population']:<9}{t['comparison']:<20}"
              f"{t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]"
              f" n={t['n']:<5} q={t['q_bh']:.4f} "
              f"{'SIG' if t['significant'] else 'ns'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
