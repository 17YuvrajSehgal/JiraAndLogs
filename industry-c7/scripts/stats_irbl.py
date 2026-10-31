"""Paired bootstraps for the IRBL baselines and the firewall-leakage
experiment. Same machinery as stats.py (2,000 resamples, shared indices,
BH over the whole family).

Comparisons per project x {overall, hard} x {acc@5, mrr}:
  leak_simiscore   simiscore_leaky    - simiscore_fw     (the leakage)
  leak_buglocator  buglocator_leaky_a3- buglocator_fw_a3
  leak_brtracer    brtracer_leaky     - brtracer_fw
  ours_vs_brtracer cond_ours          - brtracer_fw      (cross-file join)
  ours_vs_buglocator cond_ours        - buglocator_fw_a3
  s4_vs_simiscore  memory_bm25        - simiscore_fw     (our S4 vs classic)

Usage:
    python industry-c7/scripts/stats_irbl.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
P = ("kafka", "mariadb", "mongodb", "qt")
WITHIN = (("leak_simiscore", "simiscore_leaky", "simiscore_fw"),
          ("leak_buglocator", "buglocator_leaky_a3", "buglocator_fw_a3"),
          ("leak_brtracer", "brtracer_leaky", "brtracer_fw"))
CROSS = (("ours_vs_brtracer", "cond_ours", "brtracer_fw"),
         ("ours_vs_buglocator", "cond_ours", "buglocator_fw_a3"),
         ("s4_vs_simiscore", "memory_bm25", "simiscore_fw"))
METRICS = ("acc@5", "mrr")
B, SEED = 2000, 42


def paired_boot(da, db, idx):
    n = len(da)
    obs = sum(da) / n - sum(db) / n
    ds = sorted(sum(da[i] - db[i] for i in s) / n for s in idx)
    p = 2 * min(sum(1 for x in ds if x <= 0), sum(1 for x in ds if x >= 0)) / len(ds)
    return {"delta": round(obs, 4), "ci_low": round(ds[int(.025 * B)], 4),
            "ci_high": round(ds[int(.975 * B)], 4), "p": min(1.0, p), "n": n}


def main() -> int:
    rng = random.Random(SEED)
    tests = []
    for proj in P:
        irbl = {r["issue_key"]: r for r in
                (json.loads(l) for l in
                 (RES / f"{proj}-irbl-instances.jsonl").open(encoding="utf-8"))}
        ours = [json.loads(l) for l in
                (RES / f"{proj}-instances.jsonl").open(encoding="utf-8")]
        n_dev = json.load((RES / f"{proj}-summary.json").open())["n_dev"]
        ours.sort(key=lambda r: r["fix_time"])
        ev = [r for r in ours[n_dev:] if r["issue_key"] in irbl]
        pops = {"overall": ev,
                "hard": [r for r in ev if not r["strata"]["easy"]]}
        for pop_name, pop in pops.items():
            n = len(pop)
            idx = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
            for metric in METRICS:
                for cname, a, b in WITHIN:
                    da = [irbl[r["issue_key"]]["metrics"][a][metric] for r in pop]
                    db = [irbl[r["issue_key"]]["metrics"][b][metric] for r in pop]
                    tests.append({"project": proj, "population": pop_name,
                                  "comparison": cname, "metric": metric,
                                  **paired_boot(da, db, idx)})
                for cname, a, b in CROSS:
                    da = [r["metrics"][a][metric] for r in pop]
                    db = [irbl[r["issue_key"]]["metrics"][b][metric] for r in pop]
                    tests.append({"project": proj, "population": pop_name,
                                  "comparison": cname, "metric": metric,
                                  **paired_boot(da, db, idx)})

    m = len(tests)
    order = sorted(range(m), key=lambda j: tests[j]["p"])
    prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, tests[j]["p"] * m / (m - rank + 1))
        tests[j]["q_bh"] = round(prev, 4)
        tests[j]["significant"] = prev < 0.05

    (RES / "stats-irbl.json").write_text(
        json.dumps({"seed": SEED, "n_bootstrap": B, "n_tests": m,
                    "tests": tests}, indent=2), encoding="utf-8")
    for t in tests:
        if t["metric"] != "acc@5":
            continue
        print(f"{t['project']:<9}{t['population']:<9}{t['comparison']:<20}"
              f"{t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]"
              f" q={t['q_bh']:.4f} {'SIG' if t['significant'] else 'ns'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
