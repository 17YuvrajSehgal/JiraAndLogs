"""Choose the EXAMINE file view on the DEVELOPMENT split. CPU only.

When a file does not fit the budget, EXAMINE shows whole functions in
relevance order. The pilot lost 3 of 26 gold-file cards because the gold
function was never on screen (10 of 213 functions shown, 14 of 38, 18 of
360). This measures, on dev instances only, how often a gold function is
on screen under each setting, and what the setting costs in characters.

Evidence-named functions (printing sites, report symbols) are not
available here without the evidence pass, so every rate is a lower bound.

Usage:
    python industry-c7/scripts/view_tuning.py [--per-project 30] [--procs 12]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as S
import sys
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))

# (file_chars, func_chars, name_boost, full_first)
CONFIGS = [(24000, 6000, False, 0), (24000, 6000, True, 0), (24000, 3000, True, 0),
           (24000, 1500, True, 0), (24000, 1500, True, 2), (24000, 1500, True, 4),
           (24000, 1500, True, 6), (36000, 3000, True, 0), (16000, 3000, True, 0)]


def one_project(job):
    project, n = job
    import tools as T
    import workflow as WF
    from localize import OUT, load_bench
    bench = sorted(load_bench(project), key=lambda b: b["fix_time"])
    n_dev = json.load((OUT / f"{project}-summary.json").open())["n_dev"]
    dev = {b["issue_key"]: b for b in bench[:n_dev]}
    gold = {}
    f = OUT / f"{project}-functions.jsonl"
    if not f.exists():
        return []
    for line in f.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("eligible") and r["issue_key"] in dev:
            gold[r["issue_key"]] = r["gold_functions"]
    keys = sorted(gold)
    random.Random(42).shuffle(keys)
    out, fc = [], {}
    for k in keys[:n]:
        b = dev[k]
        by_file = {}
        for g in gold[k]:
            path, rest = g.split("::", 1)
            by_file.setdefault(path, set()).add(int(rest.rpartition("@")[2]))
        try:
            ws = T.Workspace(project, b["snapshot_sha"], b["query_text"], {}, {}, 0,
                             k, set(), fc, [])
            for path, starts in list(by_file.items())[:2]:
                funcs = ws._funcs_of(path)
                if not funcs:
                    continue
                row = {"id": f"{project}:{k}", "n_funcs": len(funcs), "n_gold": len(starts)}
                for cfg in CONFIGS:
                    view, shown = WF.file_view(ws, path, {}, *cfg)
                    if shown["mode"] == "whole":
                        on = set(starts)
                    else:
                        on = {f[1] for f in funcs
                              if f[1] in starts and f"--- {f[0]} (lines {f[1]}-" in view}
                    row[str(cfg)] = {"mode": shown["mode"], "any": bool(on),
                                     "all": on == set(starts), "chars": len(view),
                                     "shown": shown["functions_shown"]}
                out.append(row)
        except Exception as e:  # noqa: BLE001
            out.append({"id": f"{project}:{k}", "error": f"{type(e).__name__}: {e}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-project", type=int, default=30)
    ap.add_argument("--procs", type=int, default=12)
    args = ap.parse_args()
    from localize import PROJECTS
    with Pool(args.procs) as pool:
        rows = [r for rs in pool.imap_unordered(
            one_project, [(p, args.per_project) for p in sorted(PROJECTS)]) for r in rs]
    bad = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    print(f"dev gold files: {len(rows)} ({len(bad)} errors {[b['error'][:50] for b in bad[:2]]})")
    print(f"{'file_chars':>10s} {'func_chars':>10s} {'boost':>6s} {'full':>4s} | {'fits whole':>10s} | "
          f"{'gold on screen (all files)':>26s} | {'when NOT whole: any / all':>26s} | "
          f"{'chars':>7s} {'funcs shown':>11s}")
    for cfg in CONFIGS:
        k = str(cfg)
        whole = [r for r in rows if r[k]["mode"] == "whole"]
        part = [r for r in rows if r[k]["mode"] != "whole"]
        anyall = sum(r[k]["any"] for r in rows) / len(rows)
        print(f"{cfg[0]:>10d} {cfg[1]:>10d} {str(cfg[2]):>6s} {cfg[3]:>4d} | {len(whole) / len(rows):>10.3f} | "
              f"{anyall:>26.3f} | "
              f"{sum(r[k]['any'] for r in part) / max(1, len(part)):>12.3f} / "
              f"{sum(r[k]['all'] for r in part) / max(1, len(part)):<11.3f} | "
              f"{S.mean(r[k]['chars'] for r in rows):>7.0f} "
              f"{S.median(r[k]['shown'] for r in part) if part else 0:>11.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
