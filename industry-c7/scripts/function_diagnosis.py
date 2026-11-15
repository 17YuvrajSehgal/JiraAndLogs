"""Why the agent gets the file right and the function wrong.

Main run (26,541 answered rows) joined with the gold functions
({p}-functions.jsonl) and the decision digest (trace_decisions.py). A
region is `path::function`; names are compared without qualifiers and
without the start line, so an overloaded name counts once.

Usage:
    python industry-c7/scripts/function_diagnosis.py
"""

from __future__ import annotations

import collections as C
import glob
import json
import re
import statistics as S
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / "data/agent/full"
RES = ROOT / "data/results"


def bare(sym: str) -> str:
    s = re.sub(r"\(.*$", "", sym or "").strip()
    return re.split(r"::|\.|#", s)[-1].strip().lower()


def gkey(k: str):
    path, rest = k.split("::", 1)
    name, _, line = rest.rpartition("@")
    return path, bare(name), int(line)


def main() -> int:
    gold = {}
    lex = {}
    for f in glob.glob(str(RES / "*-functions.jsonl")):
        proj = Path(f).name.replace("-functions.jsonl", "")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("eligible"):
                gold[f"{proj}:{r['issue_key']}"] = [gkey(k) for k in r["gold_functions"]]
                lex[f"{proj}:{r['issue_key']}"] = [gkey(k) for k in r["ranking"]]
    dig = {}
    dfile = FULL / "trace-decisions2.jsonl"
    if dfile.exists():
        for line in open(dfile, encoding="utf-8"):
            d = json.loads(line)
            if "turns" in d:
                dig[d["id"]] = d
    R = []
    for f in glob.glob(str(FULL / "agent-full-*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("stop_reason") == "submitted" and r["id"] in gold:
                R.append(r)
    N = len(R)

    def pct(x, n=None):
        n = N if n is None else n
        return f"{100 * x / n:.1f}%" if n else "-"

    print(f"instances with gold functions: {N}")
    ng = [len(gold[r["id"]]) for r in R]
    nf = [len({g[0] for g in gold[r["id"]]}) for r in R]
    print(f"gold functions per instance: median {S.median(ng)}, mean {S.mean(ng):.1f}; "
          f"1 function {pct(sum(n == 1 for n in ng))}, 2-3 {pct(sum(2 <= n <= 3 for n in ng))}, "
          f"4+ {pct(sum(n >= 4 for n in ng))}; in one file {pct(sum(n == 1 for n in nf))}")

    cats = C.Counter()
    rows = []
    for r in R:
        g = gold[r["id"]]
        gfiles = {x[0] for x in g}
        gpairs = {(x[0], x[1]) for x in g}
        regs = [(x["path"], bare(x.get("resolved") or x.get("symbol") or ""),
                 bool(x.get("resolved"))) for x in r.get("regions") or []]
        top = regs[0] if regs else ("", "", False)
        file1 = top[0] in gfiles
        fn1 = (top[0], top[1]) in gpairs
        fn_any = any((p, s) in gpairs for p, s, _ in regs)
        d = {"r": r, "file1": file1, "fn1": fn1, "fn_any": fn_any, "top": top,
             "g": g, "gfiles": gfiles, "gpairs": gpairs, "regs": regs}
        rows.append(d)
        if fn1:
            cats["function right"] += 1
        elif not file1:
            cats["file wrong"] += 1
        elif not top[2]:
            cats["file right, named function does not exist in the file"] += 1
        else:
            cats["file right, a real but wrong function"] += 1

    print("\n1. TOP-1 REGION, where it is lost")
    for k, v in cats.most_common():
        print(f"  {v:6d} {pct(v):>6s}  {k}")
    fr = [d for d in rows if d["file1"]]
    print(f"  given the file is right (n={len(fr)}): function right {pct(sum(d['fn1'] for d in fr), len(fr))}")
    print(f"  gold function anywhere in the submitted regions: {pct(sum(d['fn_any'] for d in rows))}"
          f" (the v3 form allows ONE function per file)")

    print("\n2. FILE RIGHT, FUNCTION WRONG: what kind of miss")
    miss = [d for d in fr if not d["fn1"]]
    n = len(miss)
    multi = sum(len([g for g in d["g"] if g[0] == d["top"][0]]) > 1 for d in miss)
    print(f"  n={n}; the fix touched 2+ functions in that file: {pct(multi, n)}")
    # how far is the named function from the gold one, in lines
    near = []
    for d in miss:
        x = next((x for x in d["r"]["regions"] if x["path"] == d["top"][0] and x.get("lines")), None)
        if x:
            gl = [g[2] for g in d["g"] if g[0] == d["top"][0]]
            if gl:
                near.append(min(abs(x["lines"][0] - a) for a in gl))
    if near:
        print(f"  distance from the named function to the nearest gold function: median "
              f"{S.median(near):.0f} lines; within 50 lines {pct(sum(a <= 50 for a in near), len(near))}, "
              f"within 200 {pct(sum(a <= 200 for a in near), len(near))}")
    # is the named function in the report text? is the gold one?
    print("\n3. THE LEXICAL FUNCTION RANKER (BM25 of function body vs report), same instances")
    for name, sub in [("all", rows), ("agent's file right", fr), ("file right, function wrong", miss)]:
        k1 = k3 = k5 = infile1 = infile3 = 0
        for d in sub:
            lr = lex[d["r"]["id"]]
            pairs = [(p, s) for p, s, _ in lr]
            k1 += bool(pairs[:1]) and pairs[0] in d["gpairs"]
            k3 += any(x in d["gpairs"] for x in pairs[:3])
            k5 += any(x in d["gpairs"] for x in pairs[:5])
            # the same ranking restricted to the agent's top file
            inf = [x for x in pairs if x[0] == d["top"][0]]
            infile1 += bool(inf[:1]) and inf[0] in d["gpairs"]
            infile3 += any(x in d["gpairs"] for x in inf[:3])
        m = len(sub)
        print(f"  {name:28s} n={m:6d}  lexical acc@1 {pct(k1, m)} @3 {pct(k3, m)} @5 {pct(k5, m)}"
              f"  | within the agent's top file: @1 {pct(infile1, m)} @3 {pct(infile3, m)}")

    if dig:
        print("\n4. WAS THE GOLD FUNCTION EVER ON SCREEN? (file right, function wrong)")
        seen = named = total = 0
        nwin = []
        for d in miss:
            t = dig.get(d["r"]["id"])
            if not t:
                continue
            total += 1
            gl = [(g[1], g[2]) for g in d["g"] if g[0] == d["top"][0]]
            hit = byname = False
            w = 0
            for turn in t["turns"]:
                for c in turn["calls"]:
                    if c["tool"] != "read_code" or c["arg"].get("path") != d["top"][0]:
                        continue
                    w += 1
                    a = c.get("from")
                    if a is None:
                        continue
                    b = a + min(max(int(c.get("n") or 50), 10), 80) - 1
                    if any(a <= line <= b for _nm, line in gl):
                        hit = True
                    if bare(c.get("sym", "")) in {nm for nm, _l in gl}:
                        byname = True
            seen += hit
            named += byname
            nwin.append(w)
        print(f"  n={total}; the START of a gold function was inside a window the model read: "
              f"{pct(seen, total)}; it asked for a gold function BY NAME: {pct(named, total)}; "
              f"windows read of that file: median {S.median(nwin)}")
        print("\n5. SAME QUESTION when the function was right")
        ok = [d for d in fr if d["fn1"]]
        seen = total = 0
        for d in ok:
            t = dig.get(d["r"]["id"])
            if not t:
                continue
            total += 1
            gl = [(g[1], g[2]) for g in d["g"] if g[0] == d["top"][0]]
            for turn in t["turns"]:
                for c in turn["calls"]:
                    if c["tool"] == "read_code" and c["arg"].get("path") == d["top"][0] \
                            and c.get("from") is not None:
                        a = c["from"]
                        b = a + min(max(int(c.get("n") or 50), 10), 80) - 1
                        if any(a <= line <= b for _nm, line in gl):
                            seen += 1
                            break
                else:
                    continue
                break
        print(f"  n={total}; start of a gold function was on screen: {pct(seen, total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
