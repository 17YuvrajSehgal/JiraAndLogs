"""How often the v3 phase-0 backward hop (T11) has anything to walk.

v3 runs callers_of on the report's stack-frame symbols before the agent's
loop starts, instead of offering it as a tool the model declines to use
(v2: 0.01 calls/run). That only helps on reports that carry a frame whose
symbol exists in the snapshot, so the coverage is a number the paper owes
rather than an assumption.

No LLM and no GPU: this runs exactly what phase 0 runs and stops there.

Two populations, because they differ and mixing them would be the usual
mistake. The 200/project study sample is roughly balanced; the evaluation
split is 55% MongoDB, which is the project the hop works worst on. The
weighted row is the one that predicts a full-split run.

Usage:
    python industry-c7/scripts/prewalk_coverage.py [n]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "agent"))
import run_agent as R  # noqa: E402
import tools as T  # noqa: E402
from localize import OUT, PROJECTS, load_support, parse_iso_epoch  # noqa: E402
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402

# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
SEED = 99


def measure(n: int) -> dict:
    pop = R.build_population(list(P))
    random.Random(SEED).shuffle(pop)
    pop = pop[:n]
    support, fcaches, rows = {}, {}, []
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
        syms = ws.symbols_in_snapshot(T.frame_symbols(ws.query_text))[:3]
        walk = []
        for s in syms:
            hits = (ws.callers_of(s) or {}).get("callers") or []
            if hits:
                walk.append(hits[:6])
            if len(walk) == 2:
                break
        files = {c["file"] for hs in walk for c in hs}
        rows.append({"project": proj, "issue_key": b["issue_key"],
                     "has_frame": bool(T.frame_symbols(ws.query_text)),
                     "symbol_in_snapshot": bool(syms),
                     "walked": bool(walk), "n_calling_files": len(files),
                     "gold_in_walk": bool(files & set(b["gold_files"]))})
        print(f"  {proj}:{b['issue_key']}", flush=True)

    n_eval = {p: json.load((OUT / f"{p}-summary.json").open())["n_eval"]
              for p in P}
    total = sum(n_eval.values())
    per, w_fire, w_gold = {}, 0.0, 0.0
    for p in P:
        r = [x for x in rows if x["project"] == p]
        if not r:
            continue
        fire = sum(x["walked"] for x in r) / len(r)
        gold = sum(x["gold_in_walk"] for x in r) / len(r)
        w_fire += n_eval[p] * fire
        w_gold += n_eval[p] * gold
        per[p] = {"n": len(r), "n_eval": n_eval[p],
                  "fires": round(fire, 4), "gold_in_walk": round(gold, 4),
                  "gold_given_fired": round(
                      sum(x["gold_in_walk"] for x in r)
                      / max(sum(x["walked"] for x in r), 1), 4)}
    fired = [x for x in rows if x["walked"]]
    return {
        "n_sampled": len(rows), "seed": SEED,
        "sample": {
            "has_frame": round(sum(x["has_frame"] for x in rows) / len(rows), 4),
            "symbol_in_snapshot": round(
                sum(x["symbol_in_snapshot"] for x in rows) / len(rows), 4),
            "fires": round(len(fired) / len(rows), 4),
            "gold_in_walk": round(
                sum(x["gold_in_walk"] for x in rows) / len(rows), 4),
            "gold_given_fired": round(
                sum(x["gold_in_walk"] for x in fired) / max(len(fired), 1), 4),
            "mean_calling_files": round(
                sum(x["n_calling_files"] for x in fired) / max(len(fired), 1), 2)},
        "weighted_to_eval_split": {
            "n_eval": total,
            "fires": round(w_fire / total, 4),
            "gold_in_walk": round(w_gold / total, 4)},
        "per_project": per, "rows": rows}


if __name__ == "__main__":
    res = measure(int(sys.argv[1]) if len(sys.argv) > 1 else 160)
    (OUT / "prewalk-coverage.json").write_text(
        json.dumps(res, indent=1), encoding="utf-8")
    s, w = res["sample"], res["weighted_to_eval_split"]
    print(f"\nn={res['n_sampled']}")
    print(f"  has a stack frame        {s['has_frame']*100:.0f}%")
    print(f"  symbol in the snapshot   {s['symbol_in_snapshot']*100:.0f}%")
    print(f"  hop fires                {s['fires']*100:.0f}%")
    print(f"  gold file in the walk    {s['gold_in_walk']*100:.0f}%"
          f"  ({s['gold_given_fired']*100:.0f}% of the ones that fired)")
    print(f"  calling files per walk   {s['mean_calling_files']}")
    print(f"weighted to the {w['n_eval']} eval split:"
          f"  fires {w['fires']*100:.0f}%  gold in walk {w['gold_in_walk']*100:.0f}%")
    for p, d in res["per_project"].items():
        print(f"    {p:9} n={d['n']:<4} fires {d['fires']*100:>3.0f}%"
              f"  gold {d['gold_in_walk']*100:>3.0f}%")
