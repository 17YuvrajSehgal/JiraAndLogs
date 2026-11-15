"""Module-level Acc@K / MRR (challenge output (i): "the affected module").

Module = first D path components of a file (D per project -- a single
top-level dir is meaningless where everything lives under src/):
  kafka 1 (clients, core, streams...), mariadb 2 (sql, storage/innobase...),
  mongodb 3 (src/mongo/db, src/mongo/s...), qt 2 (src/corelib, src/network...).

A system's module ranking is its file ranking collapsed by first occurrence.
Gold modules are recomputed from gold_files with the same rule. Eval split
replicated from each summary's n_dev (as in stats.py). Uses the stored
top-20 file rankings -- ample for Acc@{1,3,5}.

Usage:
    python scripts/c7/module_metrics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "data/c7-results"
DEPTH = {"kafka": 1, "mariadb": 2, "mongodb": 3, "qt": 2}
SYSTEMS = ("trace_grep", "path_bm25", "content_bm25", "memory_bm25",
           "fused_no_memory", "fused_ours", "cond_no_memory", "cond_ours")
KS = (1, 3, 5)


def module_of(path: str, depth: int) -> str:
    parts = path.split("/")
    return "/".join(parts[:max(1, min(depth, len(parts) - 1))])


def main() -> int:
    out = {}
    for proj, depth in DEPTH.items():
        rows = [json.loads(l) for l in
                (RES / f"{proj}-instances.jsonl").open(encoding="utf-8")]
        n_dev = json.load((RES / f"{proj}-summary.json").open())["n_dev"]
        rows.sort(key=lambda r: r["fix_time"])
        ev = rows[n_dev:]
        # instances carry file rankings for the five SIGNALS; fused systems
        # were persisted in metrics only, so rebuild them the same way the
        # localizer did is NOT possible from top-20 alone -- instead collapse
        # every stored ranking (signals) and the fused top-20s if present.
        agg = {}
        for sys_name in SYSTEMS:
            ms = {f"acc@{k}": 0.0 for k in KS}
            ms["mrr"] = 0.0
            n = 0
            for r in ev:
                files = r["rankings"].get(sys_name)
                if files is None:
                    n = 0
                    break
                gold = {module_of(f, depth) for f in r["gold_files"]}
                mods = list(dict.fromkeys(module_of(f, depth) for f in files))
                hit = next((i for i, m in enumerate(mods) if m in gold), None)
                ms["mrr"] += 1.0 / (hit + 1) if hit is not None else 0.0
                for k in KS:
                    ms[f"acc@{k}"] += float(any(m in gold for m in mods[:k]))
                n += 1
            if n:
                agg[sys_name] = {m: round(v / n, 4) for m, v in ms.items()}
        out[proj] = {"n_eval": len(ev), "module_depth": depth, "systems": agg}

    (RES / "module-metrics.json").write_text(json.dumps(out, indent=2),
                                             encoding="utf-8")
    for proj, res in out.items():
        print(f"\n--- {proj} (module depth {res['module_depth']}, "
              f"n={res['n_eval']}) ---")
        print(f"{'system':<17}{'acc@1':>8}{'acc@3':>8}{'acc@5':>8}{'mrr':>8}")
        for s, m in res["systems"].items():
            print(f"{s:<17}{m['acc@1']:>8.3f}{m['acc@3']:>8.3f}"
                  f"{m['acc@5']:>8.3f}{m['mrr']:>8.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
