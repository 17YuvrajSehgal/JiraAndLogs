"""Does the memory index leak future text? (supervisor comment 5)

The firewall currently runs at the wrong stage. BM25Index is built ONCE
per project over the whole incident pool -- MongoDB's is 19,819 incidents,
including ones resolved long after the query's report -- then the top 50
are ranked and only then are inadmissible incidents dropped
(tools.recall_incidents). Two separate problems follow:

  crowding   inadmissible incidents occupy slots in the top 50, so an
             admissible older incident can be pushed out entirely and
             never reach the agent. Worst for early reports, where almost
             everything in the pool is still in the future.

  statistics idf, df and avgdl are computed over a corpus that contains
             future documents, so even the admissible results are RANKED
             using information the system could not have had.

This measures both against the correct construction: an index built from
the admissible incidents alone, per instance. No LLM, no GPU.

Usage:
    python industry-c7/scripts/memory_index_leak.py [n] [--project P]
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "agent"))
import run_agent as R  # noqa: E402
import tools as T  # noqa: E402
from localize import (BM25Index, OUT, PROJECTS,  # noqa: E402
                      load_support, parse_iso_epoch, tokenize)

SEED = 1301
K = 5
POOL = K * 10          # what recall_incidents ranks before filtering


def one(ws: T.Workspace, b: dict) -> dict:
    qtoks = tokenize(ws.query_text)

    # what the agent sees today: global index, rank POOL, then filter
    pool = ws._memory_index().rank(qtoks, POOL)
    adm_in_pool = [k for k in pool if ws._admissible(k)]
    now = []
    for k in adm_in_pool:
        files = [f for f in ws.memory[k]["gold_files"] if f in ws.snap.blob_of]
        if files:
            now.append(k)
        if len(now) >= K:
            break

    # what it should see: index over the admissible incidents only
    adm_all = {k: r["toks"] for k, r in ws.memory.items() if ws._admissible(k)}
    fixed = []
    if adm_all:
        for k in BM25Index(adm_all).rank(qtoks, POOL):
            files = [f for f in ws.memory[k]["gold_files"]
                     if f in ws.snap.blob_of]
            if files:
                fixed.append(k)
            if len(fixed) >= K:
                break

    gold = set(b["gold_files"])

    def hits(keys):
        return any(gold & set(ws.memory[k]["gold_files"]) for k in keys)

    return {"project": ws.project, "issue_key": b["issue_key"],
            "pool_size": len(pool),
            "admissible_in_pool": len(adm_in_pool),
            "crowded_out_share": round(1 - len(adm_in_pool) / max(len(pool), 1), 4),
            "admissible_total": len(adm_all),
            "n_now": len(now), "n_fixed": len(fixed),
            "short_of_k_now": len(now) < K,
            "short_of_k_fixed": len(fixed) < K,
            "same_set": set(now) == set(fixed),
            "overlap": len(set(now) & set(fixed)),
            "gold_hit_now": hits(now), "gold_hit_fixed": hits(fixed)}


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
    pop = R.build_population(list(R.P))
    random.Random(SEED).shuffle(pop)
    pop = pop[:n]
    support, fcaches, rows = {}, {}, []
    t0 = time.time()
    for proj, b, row in pop:
        if proj not in support:
            support[proj] = load_support(proj, PROJECTS[proj]["key_prefix"])
            fcaches[proj] = {}
        mem, dup, created, _ = support[proj]
        ws = T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem, dup,
                         parse_iso_epoch(b.get("created"))
                         or created.get(b["issue_key"]) or b["fix_time"],
                         b["issue_key"], set(b["fix_shas"]), fcaches[proj],
                         list(row["rankings"]["cond_ours"][:20]))
        rows.append(one(ws, b))
        print(f"  {len(rows)}/{n} {proj}:{b['issue_key']}"
              f"  adm_in_pool={rows[-1]['admissible_in_pool']}/{POOL}"
              f"  same={rows[-1]['same_set']}", flush=True)

    N = len(rows)
    agg = {
        "n": N, "seed": SEED, "k": K, "pool": POOL,
        "elapsed_s": round(time.time() - t0, 1),
        "mean_crowded_out": round(
            sum(r["crowded_out_share"] for r in rows) / N, 4),
        "short_of_k_now": round(sum(r["short_of_k_now"] for r in rows) / N, 4),
        "short_of_k_fixed": round(
            sum(r["short_of_k_fixed"] for r in rows) / N, 4),
        "identical_top5": round(sum(r["same_set"] for r in rows) / N, 4),
        "mean_overlap": round(sum(r["overlap"] for r in rows) / N, 2),
        "gold_hit_now": round(sum(r["gold_hit_now"] for r in rows) / N, 4),
        "gold_hit_fixed": round(sum(r["gold_hit_fixed"] for r in rows) / N, 4),
        "rows": rows}
    (OUT / "memory-index-leak.json").write_text(
        json.dumps(agg, indent=1), encoding="utf-8")

    print(f"\n== memory index: current vs admissible-only, n={N} ==")
    print(f"inadmissible share of the ranked pool   "
          f"{agg['mean_crowded_out']*100:.1f}%")
    print(f"instances left short of k={K} today      "
          f"{agg['short_of_k_now']*100:.1f}%"
          f"   (admissible-only index: {agg['short_of_k_fixed']*100:.1f}%)")
    print(f"identical top-{K} incident set           "
          f"{agg['identical_top5']*100:.1f}%"
          f"   (mean overlap {agg['mean_overlap']}/{K})")
    print(f"a gold file is reachable from memory    "
          f"now {agg['gold_hit_now']*100:.1f}%"
          f"  vs fixed {agg['gold_hit_fixed']*100:.1f}%")
    print(f"elapsed {agg['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
