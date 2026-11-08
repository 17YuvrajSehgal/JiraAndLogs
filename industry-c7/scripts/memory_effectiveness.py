"""How effective is memory FOR THE AGENT, as opposed to for the retrieval layer?

RQ2/RQ3 measure what the memory signal is worth inside the retrieval
pipeline: standalone, in fusion, and in the tuned conditioned system.
Nothing measures what it is worth to the AGENT, which consumes it very
differently -- once unconditionally in phase 0, and then 0.23 times per
run by its own choice.

This decomposes the agent's memory use into the two things that can
independently fail:

    HIT RATE    does memory surface a gold file at all?
    CONVERSION  when it does, does the agent put that file first?

A high hit rate with low conversion is an attention problem: the answer
was handed over and ignored. A low hit rate is a retrieval problem. The
two need opposite fixes, and a single accuracy number hides which it is.

This is CORRELATIONAL, not an ablation: it cannot say the agent would
have been wrong without memory, only whether memory had the answer and
whether the agent agreed with it. A causal number needs a run with
recall_incidents disabled.

Usage:
    python industry-c7/scripts/memory_effectiveness.py [n]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(HERE))
import run_agent as RA  # noqa: E402
import tools as T  # noqa: E402
from localize import parse_iso_epoch  # noqa: E402
from localize import is_dead_row  # noqa: E402

RES = ROOT / "data/results"


def main() -> int:
    n_want = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    rows = {}
    for line in (ROOT / "data/agent/agent-v3-full.jsonl").open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if not is_dead_row(r):
            rows[r["id"]] = r

    pop = {f"{p}:{b['issue_key']}": (p, b, row)
           for p, b, row in RA.build_population(list(RA.P), 0, True)}
    ids = sorted(set(rows) & set(pop))
    random.Random(11).shuffle(ids)
    ids = ids[:n_want]

    support: dict = {}
    # memory surfaced gold x agent got it right
    cell = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
    hard_cell = dict(cell)
    n_adm, n_zero = 0, 0
    done = 0
    for rid in ids:
        p, b, row = pop[rid]
        if p not in support:
            support[p] = RA.load_support(p, RA.PROJECTS[p]["key_prefix"])
        mem, dup, created, _ = support[p]
        ws = T.Workspace(p, b["snapshot_sha"], b["query_text"], mem, dup,
                         parse_iso_epoch(b.get("created"))
                         or created.get(b["issue_key"]) or b["fix_time"],
                         b["issue_key"], set(b["fix_shas"]), {},
                         list(row["rankings"]["cond_ours"][:20]))
        ws.strict_memory_firewall = True       # the v3 construction
        matches = ws.recall_incidents(ws.query_text, k=5).get(
            "admissible_matches", [])
        files = {f for m in matches for f in (m.get("fixed_files") or [])}
        n_adm += len(matches)
        n_zero += (not matches)
        gold = set(b["gold_files"])
        had = bool(gold & files)
        won = rows[rid]["metrics"]["acc@1"] == 1.0
        cell[(had, won)] += 1
        if rows[rid].get("hard"):
            hard_cell[(had, won)] += 1
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(ids)} ...", flush=True)

    def report(c, label):
        tot = sum(c.values()) or 1
        had = c[(True, True)] + c[(True, False)]
        nohad = c[(False, True)] + c[(False, False)]
        hit = had / tot
        conv = c[(True, True)] / had if had else 0.0
        base = c[(False, True)] / nohad if nohad else 0.0
        print(f"\n  {label}  (n={tot})")
        print(f"    HIT RATE    memory surfaced a gold file   {hit:.1%}")
        print(f"    CONVERSION  ...and the agent ranked it #1 {conv:.1%}")
        print(f"    BASELINE    agent #1 when memory did NOT  {base:.1%}")
        print(f"    difference                                {conv - base:+.1%}")
        return {"n": tot, "hit_rate": round(hit, 4),
                "conversion": round(conv, 4), "baseline": round(base, 4),
                "lift": round(conv - base, 4)}

    out = {"n_scored": done,
           "mean_admissible_matches": round(n_adm / max(done, 1), 2),
           "pct_with_no_admissible_memory": round(n_zero / max(done, 1), 4),
           "all": report(cell, "ALL INSTANCES"),
           "hard": report(hard_cell, "HARD INSTANCES (report names no gold file)")}
    print(f"\n  memory returned nothing admissible on "
          f"{out['pct_with_no_admissible_memory']:.1%} of instances")
    print(f"  mean admissible matches per instance: "
          f"{out['mean_admissible_matches']}")
    print("\n  Correlational. The lift is not memory's causal contribution:")
    print("  instances where memory hits may be easier for other reasons.")
    print("  A causal number needs a run with recall_incidents disabled.")

    (RES / "memory-effectiveness.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {RES / 'memory-effectiveness.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
