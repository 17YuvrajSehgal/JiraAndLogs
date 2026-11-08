"""Paired-bootstrap significance for the localizer's pre-specified claims.

Comparisons (fixed before running; BH-corrected as ONE family):
  ours_vs_strongest   cond_ours      - content_bm25   (the challenge bar)
  memory_cond         cond_ours      - cond_no_memory (memory ablation, conditioned)
  memory_unweighted   fused_ours     - fused_no_memory(memory ablation, raw RRF)
  ours_vs_tracegrep   cond_ours      - trace_grep     (vs the naive baseline)

Metrics: acc@5 (primary), mrr (secondary). Populations: eval overall and
eval_hard, per project. Eval split replicated from each summary's n_dev
(rows sorted by fix_time, earliest n_dev are dev). Bootstrap indices are
shared across comparisons within a population, so every test sees the same
resamples.

Usage:
    python scripts/c7/stats.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
PROJECTS = tuple(sorted(_ALL_PROJECTS))
COMPARISONS = (
    ("ours_vs_strongest", "cond_ours", "content_bm25"),
    ("memory_cond", "cond_ours", "cond_no_memory"),
    ("memory_unweighted", "fused_ours", "fused_no_memory"),
    ("ours_vs_tracegrep", "cond_ours", "trace_grep"),
)
# hit@5 is acc@5 renamed. recall@5 and precision@5 are tested too, because
# a system can win on "did you find one of them" and lose on "how many of
# them did you find", and the paper now reports both.
METRICS = ("hit@1", "hit@5", "recall@5", "precision@5", "r_precision", "mrr")
B = 2000
SEED = 42


def paired_boot(da: list[float], db: list[float], idx: list[list[int]]) -> dict:
    n = len(da)
    obs = sum(da) / n - sum(db) / n
    ds = sorted(sum(da[i] - db[i] for i in sample) / n for sample in idx)
    p = 2 * min(sum(1 for x in ds if x <= 0), sum(1 for x in ds if x >= 0)) / len(ds)
    return {"delta": round(obs, 4), "ci_low": round(ds[int(.025 * len(ds))], 4),
            "ci_high": round(ds[int(.975 * len(ds))], 4), "p": min(1.0, p), "n": n}


def main() -> int:
    rng = random.Random(SEED)
    tests = []
    for proj in PROJECTS:
        rows = [json.loads(l) for l in
                (RES / f"{proj}-instances.jsonl").open(encoding="utf-8")]
        n_dev = json.load((RES / f"{proj}-summary.json").open())["n_dev"]
        rows.sort(key=lambda r: r["fix_time"])
        ev = rows[n_dev:]
        pops = {"overall": ev,
                "hard": [r for r in ev if not r["strata"]["easy"]]}
        for pop_name, pop in pops.items():
            n = len(pop)
            idx = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
            for cname, a, b in COMPARISONS:
                for metric in METRICS:
                    da = [r["metrics"][a][metric] for r in pop]
                    db = [r["metrics"][b][metric] for r in pop]
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

    out = {"seed": SEED, "n_bootstrap": B, "n_tests": m, "tests": tests}
    (RES / "stats.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"{'project':<9}{'pop':<9}{'comparison':<20}{'metric':<7}"
          f"{'delta':>8}{'95% CI':>19}{'q_bh':>8}  sig")
    for t in tests:
        print(f"{t['project']:<9}{t['population']:<9}{t['comparison']:<20}"
              f"{t['metric']:<7}{t['delta']:>+8.3f}"
              f"  [{t['ci_low']:+.3f},{t['ci_high']:+.3f}] {t['q_bh']:>8.4f}"
              f"  {'SIG' if t['significant'] else 'n.s.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
