"""Does build_seeds() actually deliver the recall the diagnostic promised?

The seed change is the one architectural fix the data supports, and its
whole justification is a recall number. That number must come from the
FUNCTION THE RUNNER CALLS, not from a scratch script that re-implements
the same idea slightly differently -- otherwise the paper's reasoning and
the code's behaviour can drift apart without anything failing.

Offline: no model, no GPU. Run before spending a run on it.

Usage:
    python industry-c7/scripts/seed_source_check.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(HERE))
from run_agent import build_seeds  # noqa: E402

RES, AG, LLM = ROOT / "data/results", ROOT / "data/agent", ROOT / "data/llm"


from localize import agent_run_rows  # noqa: E402
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
_ALL_PROJECTS_SORTED = tuple(sorted(_ALL_PROJECTS))

def main() -> int:
    agent = {}
    for r in agent_run_rows(AG):
        agent[r["id"]] = r

    rows = {}
    for p in _ALL_PROJECTS_SORTED:
        f = RES / f"{p}-instances.jsonl"
        if not f.exists():
            continue
        for line in f.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            k = f"{p}:{r['issue_key']}"
            if k in agent:
                rows[k] = r

    tree_rank = {}
    f = LLM / "scored-a2.jsonl"
    if f.exists():
        for line in f.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            tree_rank[f"{r['project']}:{r['issue_key']}"] = r.get("ranking") or []

    ids = sorted(set(rows) & set(agent))
    hard = [i for i in ids if agent[i].get("hard")]
    print(f"n = {len(ids)}  (hard {len(hard)})\n")

    out = {"n": len(ids), "n_hard": len(hard), "sources": {}}
    for src in ("cond_ours", "fused"):
        seeds = {i: build_seeds(rows[i], i, src, tree_rank) for i in ids}
        cov = sum(bool(set(agent[i]["gold_files"]) & set(seeds[i]))
                  for i in ids) / len(ids)
        covh = sum(bool(set(agent[i]["gold_files"]) & set(seeds[i]))
                   for i in hard) / len(hard)
        # recall at the depth the agent is actually shown in phase 0
        cov12 = sum(bool(set(agent[i]["gold_files"]) & set(seeds[i][:12]))
                    for i in ids) / len(ids)
        size = sum(len(seeds[i]) for i in ids) / len(ids)
        out["sources"][src] = {"gold_in_seed": round(cov, 4),
                               "gold_in_seed_hard": round(covh, 4),
                               "gold_in_top12_shown": round(cov12, 4),
                               "mean_size": round(size, 1)}
        print(f"  {src:12s} gold in seed {cov:.3f}   hard {covh:.3f}   "
              f"in the 12 shown {cov12:.3f}   size {size:.1f}")

    a, b = out["sources"]["cond_ours"], out["sources"]["fused"]
    out["delta"] = {k: round(b[k] - a[k], 4) for k in a}
    print(f"\n  delta: seed {out['delta']['gold_in_seed']:+.3f}   "
          f"hard {out['delta']['gold_in_seed_hard']:+.3f}   "
          f"shown {out['delta']['gold_in_top12_shown']:+.3f}")

    # The agent currently reaches 0.903 top-10 from a 0.801 seed, so it
    # adds recall rather than only reordering. State the headroom plainly
    # instead of predicting a final accuracy we have not measured.
    cur = sum(bool(set(agent[i]["gold_files"]) & set(agent[i]["ranking"][:10]))
              for i in ids) / len(ids)
    out["current_agent_top10"] = round(cur, 4)
    print(f"\n  the agent reaches {cur:.3f} top-10 from a "
          f"{a['gold_in_seed']:.3f} seed today.")
    print("  a better seed is necessary, not sufficient: only a run shows")
    print("  how much of it converts.")

    (RES / "seed-source-check.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {RES / 'seed-source-check.json'}")

    ok = (b["gold_in_seed"] > a["gold_in_seed"] + 0.10
          and b["gold_in_seed_hard"] > a["gold_in_seed_hard"] + 0.15)
    print("PASS: fused seed delivers the measured lift" if ok
          else "FAIL: fused seed does not deliver the expected lift")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
