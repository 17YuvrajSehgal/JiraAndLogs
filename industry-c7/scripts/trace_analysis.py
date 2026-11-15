"""Where the agent wins and loses, decision by decision.

Reads the main-run rows and the per-instance decision digest written by
trace_decisions.py, and prints the measurements the staged workflow
(agent/workflow.py) is designed from. Every number in the workflow's
design notes comes from this script.

Usage:
    python industry-c7/scripts/trace_analysis.py
"""

from __future__ import annotations

import collections as C
import glob
import json
import statistics as S
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / "data/agent/full"


def rank(lst, gold):
    g = set(gold)
    return next((i + 1 for i, f in enumerate(lst) if f in g), None)


def same(a, b):
    a, b = a.strip("/"), b.strip("/")
    return bool(a) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


def load():
    rows = {}
    for f in glob.glob(str(FULL / "agent-full-*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("stop_reason") == "submitted":
                rows[r["id"]] = r
    D = []
    for line in open(FULL / "trace-decisions.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d["id"] not in rows or "turns" not in d:
            continue
        r = rows[d["id"]]
        d["r"] = r
        d["rl"] = rank(r["lexical_seed"], r["gold_files"])
        d["ra"] = rank(r["agent_ranking"], r["gold_files"])
        d["cat"] = ("right" if d["ra"] == 1 else "ordering" if d["ra"]
                    else "dismissed" if d["rl"] else "notfound")
        calls = [(ti, c) for ti, t in enumerate(d["turns"]) for c in t["calls"]]
        d["calls"] = calls
        reads = [(ti, c) for ti, c in calls if c["tool"] == "read_code"]
        d["first_gold_read"] = next((ti + 1 for ti, c in reads if c["path_is_gold"]), None)
        d["first_gold_seen"] = next((ti + 1 for ti, c in calls
                                     if c["gold_in_out"] > 0 or c["path_is_gold"]), None)
        files = [c["arg"].get("path", "") for _, c in reads]
        d["files"] = files
        d["n_reads"], d["n_files"] = len(files), len(set(files))
        d["gold_reads"] = sum(1 for _, c in reads if c["path_is_gold"])
        d["top"] = (r["agent_ranking"] or [""])[0]
        d["top_reads"] = sum(1 for f in files if same(f, d["top"]))
        d["forced"] = bool(d["turns"]) and d["turns"][-1]["offered"] == 0
        d["nturn"] = len(d["turns"])
        D.append(d)
    return D


def main() -> int:
    D = load()
    N = len(D)

    def pct(x, n=None):
        n = N if n is None else n
        return f"{100 * x / n:.1f}%" if n else "-"

    def right(sub):
        return pct(sum(d["cat"] == "right" for d in sub), len(sub))

    print("traces joined", N, dict(C.Counter(d["cat"] for d in D)))

    print("\n0. OUTCOME: retrieval top-1 vs the agent's top-1")
    t = C.Counter((d["rl"] == 1, d["ra"] == 1) for d in D)
    for lab, k in [("both right (kept)", (True, True)), ("agent broke it (harm)", (True, False)),
                   ("agent fixed it (rescue)", (False, True)), ("both wrong", (False, False))]:
        print(f"  {lab:24s} {t[k]:6d} {pct(t[k])}")
    fail = [d for d in D if d["cat"] != "right"]
    print(f"  failures {len(fail)}: ordering {pct(sum(d['cat'] == 'ordering' for d in fail), len(fail))}, "
          f"dismissed {pct(sum(d['cat'] == 'dismissed' for d in fail), len(fail))}, "
          f"not found {pct(sum(d['cat'] == 'notfound' for d in fail), len(fail))}")

    print("\n1. STOPPING: who ended the run")
    for lab, sub in [("forced by budget", [d for d in D if d["forced"]]),
                     ("own stop", [d for d in D if not d["forced"]])]:
        print(f"  {lab:17s} n={len(sub):6d} ({pct(len(sub))}) top1 right {right(sub)}"
              f"  lexical@1 {pct(sum(d['rl'] == 1 for d in sub), len(sub))}")

    print("\n2. READING: read_code calls vs distinct files")
    tot = sum(d["n_reads"] for d in D)
    print(f"  mean reads/run {S.mean(d['n_reads'] for d in D):.1f}, mean distinct files "
          f"{S.mean(d['n_files'] for d in D):.1f}, re-reads of a file already read "
          f"{pct(sum(d['n_reads'] - d['n_files'] for d in D), tot)}")
    for lo, hi in [(0, 0), (1, 1), (2, 2), (3, 4), (5, 7), (8, 99)]:
        sub = [d for d in D if lo <= d["n_files"] <= hi]
        if sub:
            print(f"   distinct files read {lo}-{hi}: n={len(sub):6d} ({pct(len(sub))}) "
                  f"top1 right {right(sub)} mean reads {S.mean(d['n_reads'] for d in sub):.1f}")
    print(f"  reads on the file it finally ranked FIRST: mean "
          f"{S.mean(d['top_reads'] for d in D):.1f}, share of all reads "
          f"{pct(sum(d['top_reads'] for d in D), tot)}")
    print("  read_code style:", dict(C.Counter(
        "symbol" if c["around"] else "line" if "line" in c["arg"] else "top-of-file"
        for d in D for _, c in d["calls"] if c["tool"] == "read_code")))

    print("\n3. WHEN the gold file is first READ, by outcome")
    for cat in ("right", "ordering", "dismissed", "notfound"):
        sub = [d for d in D if d["cat"] == cat]
        fr = [d["first_gold_read"] for d in sub if d["first_gold_read"]]
        print(f"  {cat:9s} n={len(sub):6d} gold ever read {pct(len(fr), len(sub))}; "
              f"median turn {S.median(fr) if fr else '-'}; by turn 1 "
              f"{pct(sum(x <= 1 for x in fr), len(sub))}, by turn 3 "
              f"{pct(sum(x <= 3 for x in fr), len(sub))}; gold named in any tool output "
              f"{pct(sum(bool(d['first_gold_seen']) for d in sub), len(sub))}")

    print("\n4. TURNS SPENT AFTER the gold file was first read (top-1 right runs)")
    sub = [d for d in D if d["cat"] == "right" and d["first_gold_read"]]
    after = [d["nturn"] - d["first_gold_read"] for d in sub]
    print(f"  median {S.median(after)}, mean {S.mean(after):.1f}; "
          f">=8 more turns {pct(sum(a >= 8 for a in after), len(after))}")

    print("\n5. ORDERING failures: gold is in the agent's list, not first")
    sub = [d for d in D if d["cat"] == "ordering"]
    print(f"  n={len(sub)}; gold read at all {pct(sum(d['gold_reads'] > 0 for d in sub), len(sub))}; "
          f"mean reads gold {S.mean(d['gold_reads'] for d in sub):.1f} vs top-ranked "
          f"{S.mean(d['top_reads'] for d in sub):.1f}; top-ranked read MORE than gold "
          f"{pct(sum(d['top_reads'] > d['gold_reads'] for d in sub), len(sub))}; "
          f"top-ranked never read {pct(sum(d['top_reads'] == 0 for d in sub), len(sub))}")
    print("   rank of gold in the agent list:",
          sorted(C.Counter(d["ra"] for d in sub).items())[:5])

    def seed_rank_of_top(d):
        x = next((i + 1 for i, f in enumerate(d["r"]["lexical_seed"]) if f == d["top"]), None)
        return "1" if x == 1 else "2-3" if x and x <= 3 else "4-10" if x else "not in seeds"
    print("   seed rank of the file it ranked first:",
          C.Counter(seed_rank_of_top(d) for d in sub).most_common())
    print("   same question, top-1 RIGHT runs:      ",
          C.Counter(seed_rank_of_top(d) for d in D if d["cat"] == "right").most_common())
    ngold = C.Counter("1 gold file" if len(d["r"]["gold_files"]) == 1 else "multi" for d in sub)
    print("   gold-file count:", dict(ngold))

    print("\n6. HARM: lexical top-1 was right, agent ranked something else first")
    sub = [d for d in D if d["rl"] == 1 and d["ra"] != 1]
    print(f"  n={len(sub)}; gold read {pct(sum(d['gold_reads'] > 0 for d in sub), len(sub))}; "
          f"gold still in agent list {pct(sum(bool(d['ra']) for d in sub), len(sub))}; "
          f"agent's pick was in the seeds "
          f"{pct(sum(d['top'] in d['r']['lexical_seed'] for d in sub), len(sub))}; "
          f"mean reads gold {S.mean(d['gold_reads'] for d in sub):.1f} vs pick "
          f"{S.mean(d['top_reads'] for d in sub):.1f}")

    print("\n7. NOT FOUND: gold in neither list")
    sub = [d for d in D if d["cat"] == "notfound"]
    print(f"  n={len(sub)}; gold named in some tool output "
          f"{pct(sum(bool(d['first_gold_seen']) for d in sub), len(sub))}; gold read "
          f"{pct(sum(d['gold_reads'] > 0 for d in sub), len(sub))}; hard "
          f"{pct(sum(d['r']['hard'] for d in sub), len(sub))}")
    seen = C.Counter()
    for d in sub:
        for _, c in d["calls"]:
            if c["gold_in_out"] > 0:
                seen[c["tool"]] += 1
                break
    print("   tool whose output first named a gold file:", seen.most_common())

    print("\n8. RESCUE: gold absent from the seeds, agent listed it anyway")
    sub = [d for d in D if d["rl"] is None and d["ra"]]
    seen, turn = C.Counter(), []
    for d in sub:
        for ti, c in d["calls"]:
            if c["gold_in_out"] > 0 or c["path_is_gold"]:
                seen[c["tool"]] += 1
                turn.append(ti + 1)
                break
        else:
            seen["(never in a tool output)"] += 1
    print(f"  n={len(sub)}", seen.most_common(), "median turn", S.median(turn) if turn else "-")

    print("\n9. YIELD per call: P(the output names a gold file)")
    y = C.defaultdict(lambda: [0, 0, 0, 0, 0])
    for d in D:
        seen_gold = False
        for _, c in d["calls"]:
            a = y[c["tool"]]
            g = c["gold_in_out"] > 0 or bool(c["path_is_gold"])
            a[0] += 1
            a[1] += g
            a[2] += c["repeat"]
            a[3] += c["err"]
            a[4] += g and not seen_gold      # the FIRST sighting in this run
            seen_gold = seen_gold or g
    for t, a in sorted(y.items(), key=lambda x: -x[1][0]):
        print(f"  {t:17s} calls {a[0]:7d}  names gold {pct(a[1], a[0])}  first sighting "
              f"{pct(a[4], a[0])}  refused as repeat {pct(a[2], a[0])}  error {pct(a[3], a[0])}")

    print("\n10. WHEN a gold file is first named by a tool")
    first = C.Counter(d["first_gold_seen"] for d in D)
    cum = 0
    for t in range(1, 15):
        cum += first.get(t, 0)
        print(f"  turn {t:2d}: {pct(first.get(t, 0))}  cumulative {pct(cum)}")
    print("  never:", pct(first.get(None, 0)))

    print("\n11. FIRST ACTION (tools called on turn 1) and outcome")
    fa = C.defaultdict(list)
    for d in D:
        k = ("+".join(sorted({c["tool"] for c in d["turns"][0]["calls"]}))
             if d["turns"] and d["turns"][0]["calls"] else "(none)")
        fa[k].append(d)
    for k, sub in sorted(fa.items(), key=lambda x: -len(x[1]))[:8]:
        print(f"  {k:42s} n={len(sub):6d} ({pct(len(sub))}) top1 right {right(sub)}")
    print("  tool calls per turn:",
          C.Counter(min(len(t["calls"]), 4) for d in D for t in d["turns"]).most_common())

    print("\n12. CONTEXT at the final call: tool output no longer visible")
    cuts = sorted(d["turns"][-1]["cut"] for d in D if d["turns"])
    print(f"  median {S.median(cuts)}%, p90 {cuts[int(.9 * len(cuts))]}%")
    for lo, hi in [(0, 1), (1, 30), (30, 50), (50, 101)]:
        sub = [d for d in D if d["turns"] and lo <= d["turns"][-1]["cut"] < hi]
        print(f"   cut {lo}-{hi}%: n={len(sub):6d} top1 right {right(sub)}; "
              f"ordering failure {pct(sum(d['cat'] == 'ordering' for d in sub), len(sub))}")

    print("\n13. RECENCY: is the file ranked first the one read last?")

    def last_turn(d, pred):
        xs = [ti for ti, c in d["calls"] if c["tool"] == "read_code" and pred(c)]
        return max(xs) if xs else -1
    sub = [d for d in D if d["cat"] == "ordering" and d["gold_reads"] > 0]
    later = sum(last_turn(d, lambda c: same(c["arg"].get("path", ""), d["top"]))
                > last_turn(d, lambda c: c["path_is_gold"]) for d in sub)
    print(f"  ordering failures that read gold (n={len(sub)}): the wrong top file was "
          f"read LATER than the last gold read: {pct(later, len(sub))}")
    sub2 = [d for d in D if d["cat"] == "right" and d["n_files"] > 1]
    later2 = sum(last_turn(d, lambda c: not c["path_is_gold"])
                 > last_turn(d, lambda c: c["path_is_gold"]) for d in sub2)
    print(f"  right runs that read >1 file (n={len(sub2)}): some non-gold file was "
          f"read later than the last gold read: {pct(later2, len(sub2))}")

    print("\n14. LIST LENGTH: how many files the agent names")
    for lab, cond in [("1 gold", lambda n: n == 1), ("2-3 gold", lambda n: 2 <= n <= 3),
                      ("4+ gold", lambda n: n >= 4)]:
        sub = [d for d in D if cond(len(d["r"]["gold_files"]))]
        print(f"  {lab:8s} n={len(sub):6d} agent names {S.mean(len(d['r']['agent_ranking']) for d in sub):.2f} "
              f"files; recall@5 agent-only {S.mean(d['r']['metrics_agent_only']['recall@5'] for d in sub):.3f} "
              f"final {S.mean(d['r']['metrics']['recall@5'] for d in sub):.3f} "
              f"lexical {S.mean(d['r']['metrics_lexical']['recall@5'] for d in sub):.3f}")

    print("\n15. REGIONS: does the named function exist, by position")
    for pos in (0, 1, 2):
        g = [d["r"]["regions"][pos] for d in D if len(d["r"].get("regions") or []) > pos]
        print(f"  position {pos + 1}: n={len(g)} symbol resolves in the file "
              f"{pct(sum(bool(x.get('resolved')) for x in g), len(g))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
