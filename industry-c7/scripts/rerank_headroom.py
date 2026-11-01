"""How much of the available headroom does the LLM reranker capture?

Our fused ranking puts a gold file somewhere in its top 20 for a known
fraction of instances. That fraction is the ceiling for ANY reranker
working from those candidates. This script reports, per project:

    ours@5   what our own ranking converts to a top-5 hit
    llm@5    what the LLM reranker converts from the same candidates
    oracle   gold present anywhere in our top 20 (the ceiling)
    used     (llm - ours) / (oracle - ours), the share of the gap closed

A high `used` with a small remaining gap means ranking is no longer the
bottleneck and further gains must come from candidate generation.

Usage:
    python industry-c7/scripts/rerank_headroom.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import OUT  # noqa: E402

P = ("kafka", "mariadb", "mongodb", "qt")


def main() -> int:
    summ = json.loads((OUT / "llm-rr-summary.json").read_text(encoding="utf-8"))
    out = {}
    print(f"{'project':<9}{'ours@5':>8}{'llm@5':>8}{'oracle@20':>11}"
          f"{'gap_closed':>12}{'remaining':>11}")
    for p in P:
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        ev = rows[n_dev:]
        oracle = sum(any(f in set(r["gold_files"])
                         for f in r["rankings"]["cond_ours"][:20])
                     for r in ev) / len(ev)
        ours = sum(r["metrics"]["cond_ours"]["acc@5"] for r in ev) / len(ev)
        llm = summ["by_project"][p]["all"]["acc@5"]
        used = (llm - ours) / (oracle - ours) if oracle > ours else None
        out[p] = {"n_eval": len(ev), "ours_acc5": round(ours, 4),
                  "llm_rerank_acc5": round(llm, 4),
                  "oracle_top20": round(oracle, 4),
                  "gap_closed": round(used, 4) if used is not None else None,
                  "remaining_to_oracle": round(oracle - llm, 4)}
        print(f"{p:<9}{ours:>8.3f}{llm:>8.3f}{oracle:>11.3f}"
              f"{used:>11.1%}{oracle - llm:>11.3f}")
    (OUT / "rerank-headroom.json").write_text(json.dumps(out, indent=2),
                                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
