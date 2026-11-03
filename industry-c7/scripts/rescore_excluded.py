"""Re-score every system on the scored set (benchmark minus test-only gold).

Nothing is re-run. Every result file already stores per-instance metrics, so
dropping the excluded instances and re-aggregating reproduces exactly what
the original scripts would have written had the instances never been scored.

The dev/eval boundary is NOT recomputed. It stays where the original run put
it (first DEV_FRACTION of rows by fix_time); excluded rows are removed from
whichever side they fall on. Re-splitting would move instances across the
boundary and invalidate the tuned weights, which were fit on the original dev
set.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import DEV_FRACTION  # noqa: E402
from scored_set import load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES, PROJECTS = ROOT / "data" / "results", ("kafka", "mariadb", "mongodb", "qt")
EXCL = load(ROOT / "data" / "benchmark")


def agg(subset, key="metrics"):
    if not subset:
        return {}
    probe = subset[0][key]
    # function_stage writes a flat {mrr: ..., acc@1: ...}; everything else
    # nests metrics under a system name
    if not isinstance(next(iter(probe.values())), dict):
        return {m: round(sum(r[key][m] for r in subset) / len(subset), 4)
                for m in probe}
    systems = list(probe)
    metrics = list(probe[systems[0]])
    return {s: {m: round(sum(r[key][s][m] for r in subset) / len(subset), 4)
                for m in metrics} for s in systems}


def split(rows, project):
    """Original time split, then drop excluded rows from each side."""
    rows = sorted(rows, key=lambda r: r["fix_time"])
    n_dev = int(len(rows) * DEV_FRACTION)
    keep = lambda rs: [r for r in rs
                       if f"{project}:{r['issue_key']}" not in EXCL]
    return rows[:n_dev], rows[n_dev:], keep(rows[:n_dev]), keep(rows[n_dev:])


def blocks(ev, key="metrics"):
    return {
        "all": agg(ev, key),
        "hard": agg([r for r in ev if not r["strata"]["easy"]], key),
        "easy": agg([r for r in ev if r["strata"]["easy"]], key),
    }


def family(suffix, key="metrics", only_eligible=False):
    out = {}
    for p in PROJECTS:
        f = RES / f"{p}-{suffix}.jsonl"
        if not f.exists():
            continue
        rows = [json.loads(l) for l in f.open(encoding="utf-8")]
        _, ev, _, ev_k = split(rows, p)
        if only_eligible:
            ev = [r for r in ev if r["eligible"]]
            ev_k = [r for r in ev_k if r["eligible"]]
        out[p] = {"n_eval_before": len(ev), "n_eval_after": len(ev_k),
                  "before": blocks(ev, key), "after": blocks(ev_k, key)}
    return out


def flat_file(path, key="metrics", eval_only=True):
    """llm / agent records: one file, project on the row."""
    rows = [json.loads(l) for l in Path(path).open(encoding="utf-8")]
    if eval_only and "is_eval" in rows[0]:
        rows = [r for r in rows if r["is_eval"]]
    rows = [r for r in rows if r.get(key)]
    kept = [r for r in rows if f"{r['project']}:{r['issue_key']}" not in EXCL]
    hard = lambda rs: [r for r in rs if (r["hard"] if "hard" in r
                                         else not r["strata"]["easy"])]
    return {"n_before": len(rows), "n_after": len(kept),
            "before": {"all": agg(rows, key), "hard": agg(hard(rows), key)},
            "after": {"all": agg(kept, key), "hard": agg(hard(kept), key)}}


if __name__ == "__main__":
    report = {
        "excluded_rule": "all gold files are test code (scored_set.py)",
        "n_excluded_in_benchmark": len(EXCL),
        "pipeline": family("instances"),
        "irbl": family("irbl-instances"),
        "functions": family("functions", key="metrics", only_eligible=True),
    }
    for tag, path in (("llm_a2", "data/llm/scored-a2.jsonl"),
                      ("llm_cp", "data/llm/scored-cp.jsonl"),
                      ("llm_rr", "data/llm/scored-rr.jsonl"),
                      ("agent_790", "data/agent/agent-v2.jsonl"),
                      ("agent_168", "data/agent/agent-main.jsonl")):
        p = ROOT / path
        if p.exists():
            report[tag] = flat_file(p)
    (RES / "rescored-test-only-gold.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8")

    for fam in ("pipeline", "irbl", "functions"):
        tot_b = sum(v["n_eval_before"] for v in report[fam].values())
        tot_a = sum(v["n_eval_after"] for v in report[fam].values())
        print(f"{fam:10s} eval {tot_b} -> {tot_a}  (-{tot_b - tot_a})")
    for tag in ("llm_a2", "llm_cp", "llm_rr", "agent_790", "agent_168"):
        if tag in report:
            r = report[tag]
            print(f"{tag:10s}      {r['n_before']} -> {r['n_after']}  "
                  f"(-{r['n_before'] - r['n_after']})")
