"""Draw the causal-annotation sample (T1) from benchmark.

Two strata, for two different jobs:

  CORE (100)    drawn from the 790 study population, where every system's
                ranking already exists. This is what makes T4 possible now:
                causal-gold can be re-scored against the full Table III
                without waiting for v2 results. Balanced between instances
                REMEMBER got right and wrong, because the reviewer explicitly
                asked for the failures to be included.

  BREADTH (50)  drawn from the other 23 projects, so the annotation also
                speaks to the expanded benchmark rather than only the four
                projects already in the paper.

KAFKA-6624, the paper's motivating example and a known REMEMBER miss, is
forced in.

The sample is seeded and written once. Re-running reproduces it exactly.

Usage:
    python industry-c7/scripts/annotation_sample.py
"""

from __future__ import annotations

import glob
import json
import os
import hashlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "industry-c7/data/benchmark"
AGENT = ROOT / "industry-c7/data/agent/agent-v2.jsonl"
OUT = ROOT / "industry-c7/annotation/sample.json"

SEED = 20261102
N_CORE = 100
N_BREADTH = 50
ORIG = {"kafka", "mariadb", "mongodb", "qt"}
FORCE = ["kafka:KAFKA-6624"]


def load_v2() -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(V2 / "*.jsonl"))):
        p = os.path.basename(f)[:-6]
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            out[f"{p}:{r['issue_key']}"] = r
    return out


def main() -> int:
    v2 = load_v2()
    print(f"benchmark: {len(v2):,} instances")

    # agent outcomes, used ONLY to balance the core stratum. The labels
    # themselves are never shown to the annotator (see annotation_render.py).
    agent = {}
    if AGENT.exists():
        for line in open(AGENT, encoding="utf-8"):
            r = json.loads(line)
            if not r.get("error"):
                agent[r["id"]] = r["metrics"]["acc@5"] == 1
    print(f"agent outcomes available for {len(agent):,} instances")

    core_pool = [i for i in agent if i in v2]
    missing = len(agent) - len(core_pool)
    print(f"of those, {len(core_pool):,} survive into v2 "
          f"({missing} dropped by the new filters)")

    def rank(i: str) -> str:
        """Each instance's position depends only on its own id and the seed.

        rng.shuffle() orders a bucket as a whole, so adding or removing a few
        instances reshuffles all of them: one benchmark correction changed
        20 of 21 already-annotated instances, discarding the work. Hashing
        per instance keeps every other instance where it was, so a later
        correction costs only the instances it actually touches.
        """
        return hashlib.sha256(f"{SEED}:{i}".encode()).hexdigest()

    def pick(pool: list[str], n: int, key) -> list[str]:
        """Even draw across the strata produced by key()."""
        buckets: dict = {}
        for i in sorted(pool):
            buckets.setdefault(key(i), []).append(i)
        out, bl = [], sorted(buckets)
        for b in bl:
            buckets[b].sort(key=rank, reverse=True)  # pop() takes the lowest
        k = 0
        while len(out) < n and any(buckets[b] for b in bl):
            b = bl[k % len(bl)]
            if buckets[b]:
                out.append(buckets[b].pop())
            k += 1
        return out

    # CORE: balance on (agent right/wrong) x (hard/easy)
    core = pick(core_pool, N_CORE,
                lambda i: (agent[i], not v2[i]["gold_named_in_text"]))

    # BREADTH: the 23 new projects, balanced on (project, hard/easy)
    breadth_pool = [i for i in v2 if i.split(":")[0] not in ORIG]
    breadth = pick(breadth_pool, N_BREADTH,
                   lambda i: (i.split(":")[0], not v2[i]["gold_named_in_text"]))

    sample = list(dict.fromkeys(FORCE + core + breadth))
    sample = [i for i in sample if i in v2]

    rows = []
    for i in sample:
        r = v2[i]
        rows.append({
            "id": i, "project": i.split(":")[0], "issue_key": r["issue_key"],
            "stratum": "core" if i in agent else "breadth",
            "n_gold": len(r["gold_files"]), "n_universe": r.get("n_universe", 0),
            "fix_sha": r["fix_sha"], "snapshot_sha": r["snapshot_sha"],
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"seed": SEED, "n": len(rows),
         "note": "agent outcome was used to balance the core stratum and is "
                 "deliberately NOT stored here, so it cannot leak to the "
                 "annotator",
         "instances": rows}, indent=1), encoding="utf-8")

    print(f"\nsample: {len(rows)} instances -> {OUT}")
    print(f"  core    {sum(1 for r in rows if r['stratum'] == 'core'):3d} "
          f"(systems' rankings exist; T4 runs on these)")
    print(f"  breadth {sum(1 for r in rows if r['stratum'] == 'breadth'):3d} "
          f"(the 23 new projects)")
    hard = sum(1 for r in rows if not v2[r["id"]]["gold_named_in_text"])
    print(f"  hard    {hard:3d} / {len(rows)}")
    print(f"  projects covered: {len(Counter(r['project'] for r in rows))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
