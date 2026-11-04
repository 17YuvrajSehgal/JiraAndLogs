"""Draw the population the agentic baselines run on (T25).

Running LocAgent-style and CoSIL-style on all 4,409 eval instances costs
roughly three to four overnight GPU jobs (see agent/BASELINES.md §7). A
stratified subsample costs one. The subsample is only sound if every other
system is scored on exactly those instances, which is free here: all 37
systems already store per-instance results keyed by issue_key, so the
restricted score is a recomputation, not a re-run
(`full_split_breakdown.py --subset=...`).

The sample is drawn ONCE, written to disk, and committed, so the population
is fixed before any GPU time is spent and cannot drift afterwards. It is
proportionally allocated over project x hard/easy, which are the two strata
the paper reports.

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
    rows = [json.loads(l) for l in
            (AG / "agent-v3-full.jsonl").open(encoding="utf-8") if l.strip()]
    pool = {f"{r['project']}:{r['issue_key']}":
            {"project": r["project"], "hard": bool(r.get("hard"))}
            for r in rows
            if not r.get("error") and r.get("stop_reason") != "llm_error"}
    if not pool:
        print("no scored full-split run found", file=sys.stderr)
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
