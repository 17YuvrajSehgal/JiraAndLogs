"""Post-fix content in issue descriptions, and what dropping it costs.

Supervisor comment 2. The query text is the Jira summary and description
as they stood in a dump taken long after these bugs were fixed. Jira
descriptions are mutable, so an engineer who edited one after the fix --
pasting the patch, linking the commit, writing "fixed by" -- put the
answer inside the question. Nothing in the mining pipeline removed that.

This script is the single home for the rule, the way scored_set.py is for
test-only gold. It classifies every instance, then re-scores every system
with the contaminated instances dropped. Nothing is re-run: every system
already stored per-instance rankings.

STRICT markers are unambiguous post-fix artifacts. A bare commit SHA is
deliberately NOT one of them: bug reports routinely name the commit that
INTRODUCED a regression, which is legitimate report content and is the
majority of SHA mentions here. It is counted separately as ambiguous so
the number can be reported honestly either way.

Usage:
    python industry-c7/scripts/description_leak.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize import OUT, evaluate, load_bench  # noqa: E402
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402

ROOT = HERE.parents[0]
BENCH = ROOT / "data" / "benchmark"
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
KS = ("acc@1", "acc@5", "mrr")

STRICT = {
    "diff_block": re.compile(r"(?m)^(?:diff --git |--- a/|\+\+\+ b/|@@ -\d)"),
    "commit_link": re.compile(
        r"github\.com/[\w./-]+/(?:commit|pull)/|/commit/[0-9a-f]{7,}", re.I),
    "fix_phrase": re.compile(
        r"\b(?:fixed (?:in|by)|the fix (?:is|was)|resolved by|"
        r"patch attached|proposed patch)\b", re.I),
    "review_link": re.compile(
        r"reviews?\.apache\.org|reviewboard|codereview|gerrit", re.I),
}
AMBIGUOUS = {
    "sha_mention": re.compile(
        r"\b[0-9a-f]{40}\b|\bcommit\s+[0-9a-f]{7,12}\b", re.I),
}


def markers(text: str) -> list[str]:
    return [k for k, r in STRICT.items() if r.search(text)]


def contaminated(inst: dict) -> bool:
    return bool(markers(inst["query_text"]))


def classify() -> dict:
    per, ids, amb_ids = {}, [], []
    counts = {k: 0 for k in STRICT} | {k: 0 for k in AMBIGUOUS}
    for p in P:
        n = s = sg = 0
        for b in load_bench(p):
            n += 1
            t = b["query_text"]
            hits = markers(t)
            for k in hits:
                counts[k] += 1
            for k, r in AMBIGUOUS.items():
                if r.search(t):
                    counts[k] += 1
                    if not hits:
                        amb_ids.append(f"{p}:{b['issue_key']}")
            if hits:
                s += 1
                ids.append(f"{p}:{b['issue_key']}")
                sg += bool(b["gold_named_in_text"])
        per[p] = {"n": n, "strict": s, "strict_and_names_gold": sg,
                  "share": round(s / n, 4)}
    tot = sum(v["n"] for v in per.values())
    return {"rule": "unambiguous post-fix artifact in summary+description",
            "strict_patterns": {k: r.pattern for k, r in STRICT.items()},
            "ambiguous_patterns": {k: r.pattern for k, r in AMBIGUOUS.items()},
            "n_total": tot, "n_contaminated": len(ids),
            "share": round(len(ids) / tot, 4),
            "n_ambiguous_only": len(amb_ids),
            "marker_counts": counts, "per_project": per,
            "contaminated_ids": sorted(ids),
            "ambiguous_only_ids": sorted(amb_ids)}


def score(rk: dict, gold: dict, ids: list, drop: set) -> dict:
    keep = [i for i in ids if i not in drop]
    out = {}
    for name, per_id in rk.items():
        usable = [i for i in ids if i in per_id]
        kept = [i for i in keep if i in per_id]
        if not usable or not kept:
            continue
        gone = [i for i in usable if i in drop]
        a = {m: sum(evaluate(per_id[i], gold[i])[m] for i in usable) / len(usable)
             for m in KS}
        c = {m: sum(evaluate(per_id[i], gold[i])[m] for i in kept) / len(kept)
             for m in KS}
        # The direct test of the leakage worry: if a post-fix artifact were
        # acting as an answer key, the contaminated instances would be
        # EASIER than the rest. Reported rather than assumed.
        d = ({m: sum(evaluate(per_id[i], gold[i])[m] for i in gone) / len(gone)
              for m in KS} if gone else {m: None for m in KS})
        out[name] = {"n_all": len(usable), "n_clean": len(kept),
                     "n_dropped": len(gone),
                     "all": {m: round(a[m], 4) for m in KS},
                     "clean": {m: round(c[m], 4) for m in KS},
                     "contaminated_only": {
                         m: (round(d[m], 4) if d[m] is not None else None)
                         for m in KS},
                     "delta": {m: round(c[m] - a[m], 4) for m in KS}}
    return out


def eval_split_tables(drop: set) -> dict:
    """Retrieval-layer systems on the full evaluation split."""
    gold, rk, ids = {}, {}, []
    for p in P:
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        bench = {b["issue_key"]: b for b in load_bench(p)}
        for r in rows[n_dev:]:
            b = bench.get(r["issue_key"])
            if b is None:
                continue
            i = f"{p}:{r['issue_key']}"
            ids.append(i)
            gold[i] = b["gold_files"]
            for s, ranking in r["rankings"].items():
                rk.setdefault(s, {})[i] = ranking
    return {"population": "evaluation split", "systems": score(rk, gold, ids, drop)}


def study_table(drop: set) -> dict:
    """Every system, including REMEMBER, on the instances it ran."""
    from score_causal_gold import DOC_ORDER, rankings
    ag = [json.loads(l) for l in
          (OUT.parent / "agent/agent-v2.jsonl").open(encoding="utf-8")]
    ag = [r for r in ag if not r.get("error")]
    gold = {f"{r['project']}:{r['issue_key']}": r["gold_files"] for r in ag}
    rk = rankings(set(gold))
    names = [n for n, _ in DOC_ORDER if n in rk and not set(gold) - set(rk[n])]
    ids = sorted(set(gold))
    return {"population": "the 790 REMEMBER ran",
            "labels": {n: lab for n, lab in DOC_ORDER},
            "systems": score({n: rk[n] for n in names}, gold, ids, drop)}


def main() -> int:
    cls = classify()
    (BENCH / "description-leak.json").write_text(
        json.dumps(cls, indent=1), encoding="utf-8")
    drop = set(cls["contaminated_ids"])

    print(f"unambiguous post-fix artifact: {cls['n_contaminated']} of "
          f"{cls['n_total']}  ({cls['share']*100:.1f}%)")
    print(f"bare commit SHA only (ambiguous, kept): "
          f"{cls['n_ambiguous_only']}")
    for k, v in sorted(cls["marker_counts"].items(), key=lambda x: -x[1]):
        print(f"   {k:14}{v:6}")

    out = {"classification": {k: v for k, v in cls.items()
                              if not k.endswith("_ids")},
           "tables": {"eval_split": eval_split_tables(drop),
                      "study_790": study_table(drop)}}
    (OUT / "description-leak-rescore.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")

    for tname, tbl in out["tables"].items():
        print(f"\n=== {tbl['population']} ===")
        print(f"{'system':<24}{'n_all':>7}{'n_clean':>8}"
              f"{'acc@5 all':>11}{'clean':>8}{'dirty':>8}{'delta':>8}")
        for s, d in tbl["systems"].items():
            dirty = d["contaminated_only"]["acc@5"]
            print(f"{s:<24}{d['n_all']:>7}{d['n_clean']:>8}"
                  f"{d['all']['acc@5']:>11.4f}{d['clean']['acc@5']:>8.4f}"
                  f"{(f'{dirty:.4f}' if dirty is not None else '-'):>8}"
                  f"{d['delta']['acc@5']:>+8.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
