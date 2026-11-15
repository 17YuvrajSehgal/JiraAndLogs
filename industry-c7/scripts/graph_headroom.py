"""Would a code graph find gold files the agent's evidence misses? CPU only.

Before building a graph layer, measure what it could add. For each
instance of the fixed 1,000 sample:

  seeds   the retrieval ranking the agent starts from (cond_ours, top 20)
  table   every file the evidence pass names (workflow.build_table,
          uncapped). The reformulation call is stubbed, so this is the
          evidence WITHOUT the model's restatement: a lower bound.
  hops    one structural hop from that evidence:
            imports     files a start file imports, and files importing it
            callers     files that call a report / trace / log symbol
            callees     files defining what those symbols' functions call
            siblings    same-directory files (CONTROL: structure-free)

A hop is only useful if it reaches a gold file WITHOUT adding hundreds of
files, so every reach rate is printed with the number of files it adds.

Usage:
    python industry-c7/scripts/graph_headroom.py [--procs 8] [--limit N]
    python industry-c7/scripts/graph_headroom.py --report
"""

from __future__ import annotations

import argparse
import json
import statistics as S
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))
OUTF = HERE.parent / "data/results/graph-headroom.jsonl"
START_FILES = 5        # hops start from the top-5 seeds
MAX_SYMBOLS = 6


def one_project(job):
    project, keys, done = job
    import agent as A
    import lc_agent as LC
    import run_agent as RA
    import tools as T
    import workflow as WF
    from codegraph import Graph
    from lc_store import IncidentStore
    from localize import PROJECTS, load_support, parse_iso_epoch

    A.reformulate = lambda *a, **k: {}          # no model in this script
    pop = [x for x in RA.build_population([project], full=True)
           if x[1]["issue_key"] in keys and f"{project}:{x[1]['issue_key']}" not in done]
    if not pop:
        return []
    mem, dup, created, _ = load_support(project, PROJECTS[project]["key_prefix"])
    fcache, out = {}, []
    for _p, b, row in pop:
        rid = f"{project}:{b['issue_key']}"
        try:
            seeds = list(row["rankings"]["cond_ours"][:20])
            ws = T.Workspace(project, b["snapshot_sha"], b["query_text"], mem, dup,
                             parse_iso_epoch(b.get("created")) or created.get(b["issue_key"])
                             or b["fix_time"], b["issue_key"], set(b["fix_shas"]),
                             fcache, seeds)
            store = IncidentStore.from_pool(project, mem)
            ctx = {"cutoff": ws.cutoff, "this_key": ws.issue_key,
                   "this_fix_shas": frozenset(ws.fix_shas),
                   "dup_cluster": dup.get(ws.issue_key), "dup_of": dup}
            p = LC.prepare(ws, store, ctx, seeds, True)
            p["seed"] = seeds                      # the table sees all 20
            p["route"] = WF.route(ws, p)
            WF.TABLE_MAX = 10 ** 6                 # uncapped: what COULD be shown
            table = [c["path"] for c in WF.build_table(ws, p)[0]]

            g = Graph(ws)
            start = seeds[:START_FILES]
            imports = set()
            for f in start:
                imports |= set(g.imports_of(f)) | set(g.imported_by(f))
            siblings = {f for f in ws.snap.files
                        if any(f.rsplit("/", 1)[0] == s.rsplit("/", 1)[0] for s in start)}

            syms = list(dict.fromkeys(
                ws.symbols_in_snapshot(T.frame_symbols(ws.query_text))
                + [m["function"].rsplit("::", 1)[-1].rsplit(".", 1)[-1]
                   for m in p.get("printed_by", [])]
                + p["symbols"]))[:MAX_SYMBOLS]
            callers, callees = set(), set()
            for s in syms:
                callers |= {h["file"] for h in (ws.callers_of(s) or {}).get("callers") or []}
                # the function named s, or the first functions of the class
                # named s, in the files that declare it
                for f in (p["resolved"].get(s) or [])[:2]:
                    ents = [e for e in g.entities_of(f) if e["type"] == "function"
                            and (e["name"] == s or e.get("owner") == s)][:4]
                    for ent in ents:
                        callees |= {e["file"] for e in g.invokes(ent)}
            out.append({"id": rid, "hard": not b["gold_named_in_text"],
                        "gold": b["gold_files"], "seeds": seeds, "table": table,
                        "route": p["route"], "n_files": len(ws.snap.files),
                        "imports": sorted(imports), "callers": sorted(callers),
                        "callees": sorted(callees), "siblings": sorted(siblings),
                        "n_symbols": len(syms)})
        except Exception as e:  # noqa: BLE001 - one bad instance must not stop the pass
            out.append({"id": rid, "error": f"{type(e).__name__}: {e}"})
    return out


def report() -> int:
    R = [json.loads(l) for l in OUTF.open(encoding="utf-8")]
    bad = [r for r in R if "error" in r]
    R = [r for r in R if "error" not in r]
    N = len(R)

    def pct(x, n):
        return f"{100 * x / n:.1f}%" if n else "-"
    print(f"instances {N} ({len(bad)} errors: {[b['error'][:60] for b in bad[:3]]})")
    for r in R:
        g = set(r["gold"])
        r["in10"] = bool(g & set(r["seeds"][:10]))
        r["in20"] = bool(g & set(r["seeds"]))
        r["in_table"] = bool(g & set(r["table"]))
    print(f"gold in seeds top-10 {pct(sum(r['in10'] for r in R), N)}, top-20 "
          f"{pct(sum(r['in20'] for r in R), N)}, in the evidence table "
          f"{pct(sum(r['in_table'] for r in R), N)} "
          f"(table size median {S.median(len(r['table']) for r in R)})")

    def block(name, sub, base_key):
        n = len(sub)
        print(f"\n{name}: n={n}")
        if not n:
            return
        print(f"  {'hop':22s} {'reaches gold':>13s} {'files added':>12s}  {'gold per 100 added':>18s}")
        hops = {"imports": lambda r: set(r["imports"]),
                "callers": lambda r: set(r["callers"]),
                "callees": lambda r: set(r["callees"]),
                "imports+callers+callees": lambda r: set(r["imports"]) | set(r["callers"]) | set(r["callees"]),
                "siblings (control)": lambda r: set(r["siblings"])}
        for h, fn in hops.items():
            hit, added, ghits = 0, [], 0
            for r in sub:
                new = fn(r) - set(r[base_key])
                g = set(r["gold"]) & new
                hit += bool(g)
                ghits += len(g)
                added.append(len(new))
            tot = sum(added)
            print(f"  {h:22s} {pct(hit, n):>13s} {S.median(added):>12.0f}  "
                  f"{100 * ghits / tot if tot else 0:>18.2f}")

    block("A. gold NOT in the top-20 seeds (hops add to the seeds)",
          [r for r in R if not r["in20"]], "seeds")
    block("B. gold NOT in the evidence table (hops add to the table) <- the real headroom",
          [r for r in R if not r["in_table"]], "table")
    block("B-hard. same, hard instances only",
          [r for r in R if not r["in_table"] and r["hard"]], "table")
    miss = [r for r in R if not r["in_table"]]
    by = defaultdict(list)
    for r in miss:
        by[r["route"]].append(r)
    print("\nresidual by route:", {k: len(v) for k, v in by.items()},
          "| share of all instances:", pct(len(miss), N))
    any_hop = sum(bool(set(r["gold"]) & (set(r["imports"]) | set(r["callers"]) | set(r["callees"])))
                  for r in miss)
    print(f"upper bound on what one graph hop can add to coverage: "
          f"{pct(any_hop, N)} of all instances ({any_hop}/{N})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        return report()
    ids = json.load(open(HERE.parent / "data/results/baseline-sample.json"))["ids"]
    if args.limit:
        ids = ids[:args.limit]
    done = set()
    if OUTF.exists():
        done = {json.loads(l)["id"] for l in OUTF.open(encoding="utf-8")}
    by = defaultdict(set)
    for i in ids:
        p, k = i.split(":", 1)
        by[p].add(k)
    jobs = [(p, ks, done) for p, ks in sorted(by.items(), key=lambda x: -len(x[1]))]
    print(f"{len(ids)} ids, {len(done)} done, {len(jobs)} projects", flush=True)
    with Pool(args.procs) as pool, OUTF.open("a", encoding="utf-8") as fh:
        for rows in pool.imap_unordered(one_project, jobs):
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            if rows:
                print(rows[0]["id"].split(":")[0], len(rows), flush=True)
    return report()


if __name__ == "__main__":
    sys.exit(main())
