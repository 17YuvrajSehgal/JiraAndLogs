"""Rolling-origin evaluation (reviewer: '"conservative" is claimed, not
shown'). The main protocol tunes once on the earliest 30% and never
retunes. A deployed system would retune as history grows. Here we retune
the conditioned weights at every quarter boundary of the evaluation
period, each time on ALL instances resolved before that boundary, and
evaluate each quarter with the weights available at its start. If the
rolling scheme beats the frozen scheme, the main results understate what
a maintained deployment would get.

Pure re-tuning over persisted rankings: no git, no BM25 recompute.

Usage:
    python industry-c7/scripts/rolling_origin.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import OUT, SIGNALS, rrf, tune_weights  # noqa: E402

P = ("kafka", "mariadb", "mongodb", "qt")
N_FOLDS = 4


def acc5(rows, w_by_regime):
    hits = 0
    for r in rows:
        fused = rrf(r["rankings"], w_by_regime[r["regime"]])
        hits += any(f in set(r["gold_files"]) for f in fused[:5])
    return hits / len(rows)


def cond_tune(rows):
    return {reg: (tune_weights([r for r in rows if r["regime"] == reg], SIGNALS)
                  if any(r["regime"] == reg for r in rows)
                  else {s: 1.0 for s in SIGNALS})
            for reg in ("mention", "no_mention")}


def main() -> int:
    out = {}
    for p in P:
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        # persisted rankings hold all systems; tuning needs the raw signals only
        for r in rows:
            r["rankings"] = {s: r["rankings"][s] for s in SIGNALS}
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        dev, ev = rows[:n_dev], rows[n_dev:]
        frozen = cond_tune(dev)

        folds = [ev[i * len(ev) // N_FOLDS:(i + 1) * len(ev) // N_FOLDS]
                 for i in range(N_FOLDS)]
        frozen_acc, rolling_acc, fold_detail = [], [], []
        seen = list(dev)
        for k, fold in enumerate(folds):
            w_roll = cond_tune(seen) if k else frozen  # Q1 history == dev split
            fa, ra = acc5(fold, frozen), acc5(fold, w_roll)
            frozen_acc.append(fa)
            rolling_acc.append(ra)
            fold_detail.append({"fold": k + 1, "n": len(fold),
                                "frozen": round(fa, 4), "rolling": round(ra, 4)})
            seen.extend(fold)
        n = sum(len(f) for f in folds)
        fo = sum(a * len(f) for a, f in zip(frozen_acc, folds)) / n
        ro = sum(a * len(f) for a, f in zip(rolling_acc, folds)) / n
        out[p] = {"folds": fold_detail, "frozen_overall": round(fo, 4),
                  "rolling_overall": round(ro, 4), "delta": round(ro - fo, 4)}
        print(f"{p:<9} frozen {fo:.4f}  rolling {ro:.4f}  delta {ro - fo:+.4f}")
    (OUT / "rolling-origin.json").write_text(json.dumps(out, indent=2),
                                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
