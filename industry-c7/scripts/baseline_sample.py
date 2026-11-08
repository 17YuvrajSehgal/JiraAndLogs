"""Draw the population the agentic baselines run on (T25).

Running LocAgent-style and CoSIL-style on all 37,900 scored instances is
far beyond the GPU budget. A stratified subsample is affordable. The
subsample is only sound if every other system is scored on exactly those
instances, which is free here: every system stores per-instance results
keyed by issue_key, so the restricted score is a recomputation, not a
re-run (`full_split_breakdown.py --subset=...`).

The sample is drawn ONCE, written to disk, and committed, so the population
is fixed before any GPU time is spent and cannot drift afterwards. It is
proportionally allocated over project x hard/easy, which are the two strata
the paper reports.

THE POOL IS run_agent.build_population ITSELF. Two earlier versions got
this wrong in opposite directions. The first drew from agent-v3-full.jsonl
and kept only rows where our own agent had NOT errored, which conditions
the baselines' population on our system having succeeded and made the
sample undrawable until our agent had already run. The second drew from
localize.load_bench, the whole scored set -- but the agent runs the
EVALUATION SPLIT, which drops the first n_dev instances per project at a
temporal boundary and keeps only instances that have retrieval rows. That
draw put 324 of 1,000 ids outside the population the runner iterates, and
pulled dev instances into a measured sample.

So the sampler calls the runner's own function rather than re-deriving the
population from parts. Any future change to the split lands in both at
once, and a mismatch becomes impossible instead of merely unlikely.

Both files are drawn in ONE pass, pilot first, so neither depends on what
is already on disk. An earlier version drew them in separate invocations
and read the other file to avoid overlap, which made each draw depend on
whether the other existed: re-running it produced a different 1,000. A
population that moves when you regenerate it is worse than no file at all,
because the number it backs has nothing to point at.

Usage:
    python industry-c7/scripts/baseline_sample.py            # 1000 + 30
    python industry-c7/scripts/baseline_sample.py --n=500 --pilot=20
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "agent"))
from localize import PROJECTS  # noqa: E402
from run_agent import build_population  # noqa: E402

ROOT = HERE.parents[0]
AG, RES = ROOT / "data/agent", ROOT / "data/results"
SEED = 20261103


def opt(name: str, default: str = "") -> str:
    return next((a.split("=", 1)[1] for a in sys.argv
                 if a.startswith(f"--{name}=")), default)


def draw(pool: dict, keys: list[str], n_want: int, seed: int) -> list[str]:
    """Proportional allocation over project x hard, largest-remainder, so
    the subsample's mix matches the population rather than the rounding."""
    cells: dict[tuple, list] = defaultdict(list)
    for k in keys:
        cells[(pool[k]["project"], pool[k]["hard"])].append(k)
    cells = {c: sorted(v) for c, v in cells.items()}
    total = sum(len(v) for v in cells.values())
    n_want = min(n_want, total)
    exact = {c: len(v) * n_want / total for c, v in cells.items()}
    take = {c: int(e) for c, e in exact.items()}
    for c in sorted(exact, key=lambda c: (-(exact[c] - take[c]), c))[
            :n_want - sum(take.values())]:
        take[c] += 1
    rng = random.Random(seed)
    out: list[str] = []
    for c in sorted(cells):
        out += rng.sample(cells[c], min(take[c], len(cells[c])))
    return sorted(out)


def main() -> int:
    n_want, n_pilot = int(opt("n", "1000")), int(opt("pilot", "30"))
    # "hard" is run_agent.py's own definition: the gold file is not named
    # anywhere in the issue text. Taking it from the benchmark rather than
    # from a run's output keeps the two in step by construction.
    pool = {f"{proj}:{b['issue_key']}":
            {"project": proj, "hard": not b["gold_named_in_text"]}
            for proj, b, _ in build_population(sorted(PROJECTS), 0, True)}
    if not pool:
        print("no evaluation-split instances found", file=sys.stderr)
        return 1
    allk = sorted(pool)

    def mix(keys):
        n = len(keys) or 1
        by_p = Counter(pool[k]["project"] for k in keys)
        hard = sum(1 for k in keys if pool[k]["hard"])
        return {"n": len(keys), "hard_frac": round(hard / n, 4),
                "by_project": {p: round(by_p[p] / n, 4) for p in sorted(by_p)}}

    # Pilot first, from the whole pool; then the measurement sample from
    # what is left. Order is fixed here, not by what exists on disk, so the
    # pair regenerates byte for byte. A pilot instance is one we will have
    # looked at before fixing anything, so it must not also be a measured
    # one, or a tuning decision leaks into the reported number.
    pilot = draw(pool, allk, n_pilot, SEED + 1)
    rest = [k for k in allk if k not in set(pilot)]
    sample = draw(pool, rest, n_want, SEED)
    popmix = mix(allk)

    for name, ids, seed, note in (
            ("pilot", pilot, SEED + 1, "drawn first, from the whole pool"),
            ("sample", sample, SEED, "drawn from the pool minus the pilot")):
        f = RES / f"baseline-{name}.json"
        f.write_text(json.dumps(
            {"tag": name, "seed": seed, "n": len(ids),
             "drawn_from": len(pool), "draw_order": note,
             "population": "run_agent.build_population(--full), the "
                           f"evaluation split over {len(PROJECTS)} projects",
             "n_projects": len(popmix["by_project"]),
             "disjoint_from": "baseline-sample.json" if name == "pilot"
                              else "baseline-pilot.json",
             "stratified_on": ["project", "hard"],
             "sample_mix": mix(ids), "population_mix": popmix,
             "ids": ids}, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {len(ids)} of {len(pool)} -> {f.name}  ({note})")

    assert not (set(pilot) & set(sample)), "pilot and sample overlap"
    smix = mix(sample)
    print(f"\n  {'stratum':16s} {'sample':>9s} {'population':>12s}")
    print(f"  {'hard':16s} {smix['hard_frac']:>9.4f} "
          f"{popmix['hard_frac']:>12.4f}")
    for p in sorted(popmix["by_project"]):
        print(f"  {p:16s} {smix['by_project'].get(p, 0):>9.4f} "
              f"{popmix['by_project'][p]:>12.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
