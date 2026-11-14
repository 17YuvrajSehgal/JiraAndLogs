"""Seed variation of the staged agent on the 1,000-instance sample.

    python scripts/score_seeds.py --seed42 <wf-seed42 rows> --vm data/agent/vm [--out data/results/seed-variation.json]

Reads agent-wf-seed<k>-p*.jsonl from --vm for every seed found, restricts the
seed-42 rows to the sample, scores every seed with c7_coverage.summarise on the
instances ALL seeds answered, and writes per-seed numbers, the mean and the
spread, plus the paired difference of each new seed against seed 42.
"""
import argparse
import glob
import json
import os
import re
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import c7_coverage as CC  # noqa: E402

ROOT = HERE.parent
METRICS = ["file_acc@1", "file_acc@5", "file_mrr", "module_agent_acc@1", "region_acc@1", "region_acc@5", "steps_citing_log"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed42", required=True)
    ap.add_argument("--vm", default=str(ROOT / "data/agent/vm"))
    ap.add_argument("--out", default=str(ROOT / "data/results/seed-variation.json"))
    a = ap.parse_args()
    sample = set(json.load(open(ROOT / "data/results/baseline-sample.json", encoding="utf-8"))["ids"])

    rows = {}
    for f in sorted(glob.glob(os.path.join(a.vm, "agent-wf-seed*-p*.jsonl"))):
        seed = int(re.search(r"seed(\d+)-p", os.path.basename(f)).group(1))
        rows.setdefault(seed, {}).update(CC.load_rows(Path(f)))
    rows[42] = {i: r for i, r in CC.load_rows(Path(a.seed42)).items() if i in sample}
    for s in rows:
        rows[s] = {i: r for i, r in rows[s].items() if i in sample}
        print(f"seed {s}: {len(rows[s])} sample rows")
    common = set.intersection(*(set(r) for r in rows.values()))
    print(f"instances answered by every seed: {len(common)} of {len(sample)}")

    scored = {s: {i: CC.score_row(r[i]) for i in common} for s, r in rows.items()}
    per_seed = {s: CC.summarise(sc)["all"] for s, sc in scored.items()}
    out = {"n_common": len(common), "n_sample": len(sample), "seeds": sorted(rows), "per_seed": per_seed, "spread": {}, "paired_vs_42": {}}
    print(f"\n{'metric':22}" + "".join(f"{'seed ' + str(s):>11}" for s in sorted(rows)) + f"{'mean':>9}{'min-max':>12}")
    for m in METRICS:
        vals = [per_seed[s][m] for s in sorted(rows)]
        out["spread"][m] = {"mean": st.fmean(vals), "min": min(vals), "max": max(vals), "range_points": 100 * (max(vals) - min(vals))}
        print(f"{m:22}" + "".join(f"{100 * v:11.1f}" for v in vals) + f"{100 * st.fmean(vals):9.1f}{100 * (max(vals) - min(vals)):12.1f}")
    for s in sorted(rows):
        if s == 42:
            continue
        d = {}
        for grp, m in (("file", "acc@1"), ("file", "acc@5"), ("region", "acc@1"), ("region", "acc@5")):
            ok = [i for i in common if grp in scored[s][i] and grp in scored[42][i]]
            diffs = [scored[s][i][grp][m] - scored[42][i][grp][m] for i in ok]
            d[f"{grp}_{m}"] = {"delta": st.fmean(diffs), "n": len(ok), "flips": sum(1 for x in diffs if x != 0)}
        out["paired_vs_42"][s] = d
        print(f"\nseed {s} minus seed 42, paired: " + ", ".join(f"{k} {100 * v['delta']:+.1f} ({v['flips']} flips)" for k, v in d.items()))
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("->", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
