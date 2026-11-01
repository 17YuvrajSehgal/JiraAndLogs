"""Frequency-prior file baseline: the null model for the contamination
probe.

The probe asks the model which files a fix touched, given only the issue
key. Some hits are expected without any memorisation at all, because a
few files absorb a large share of every project's fixes: naming
`LogManager.scala` for any Kafka bug is a decent bet. This script
measures that bet.

For each project we rank files by how often they appear in the gold of
DEVELOPMENT-split instances, and score that single fixed ranking against
every evaluation instance. Probe accuracy above this line is evidence of
recall; probe accuracy at or below it is prior knowledge of the
project's hot spots, not memory of the specific fix.

Usage:
    python industry-c7/scripts/file_prior_baseline.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import BENCH, KS, OUT, evaluate  # noqa: E402

P = ("kafka", "mariadb", "mongodb", "qt")


def main() -> int:
    out = {}
    for p in P:
        bench = {b["issue_key"]: b for b in
                 (json.loads(l) for l in
                  (BENCH / f"{p}.jsonl").open(encoding="utf-8"))}
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        dev, ev = rows[:n_dev], rows[n_dev:]

        freq = Counter()
        for r in dev:
            for f in bench[r["issue_key"]]["gold_files"]:
                freq[f] += 1
        ranking = [f for f, _ in freq.most_common(10)]

        ms = [evaluate(ranking, bench[r["issue_key"]]["gold_files"]) for r in ev]
        agg = {m: round(sum(x[m] for x in ms) / len(ms), 4) for m in ms[0]}
        out[p] = {"n_eval": len(ev), "n_distinct_dev_files": len(freq),
                  "top10": ranking, "metrics": agg}
        print(f"{p:<9} n={len(ev):<5} prior acc@1={agg['acc@1']:.3f} "
              f"acc@5={agg['acc@5']:.3f} acc@10={agg['acc@10']:.3f} "
              f"mrr={agg['mrr']:.3f}")
    (OUT / "file-prior-baseline.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
