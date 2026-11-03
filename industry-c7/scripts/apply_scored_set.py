"""Apply the scored set to result files already on disk.

Every analysis script reads a per-instance jsonl and slices the eval set as
`rows[n_dev:]`, taking n_dev from the matching summary. So removing the
excluded rows from the jsonl and lowering n_dev by however many of them sat
in dev leaves the original dev/eval boundary exactly where the run put it,
and every downstream script picks up the reduced set with no change.

Re-tuning is deliberately NOT done. The weights in each summary were fit on
the original dev set; refitting on the reduced dev set would change the
system being measured, and the point here is to change the population, not
the system.

Reversible: removed rows go to data/results/removed-test-only-gold/, and
each summary keeps its pre-drop blocks under `pre_scored_set`. Idempotent:
a file that has already been processed is skipped.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scored_set import load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES, LLM = ROOT / "data" / "results", ROOT / "data" / "llm"
KEEPOUT = RES / "removed-test-only-gold"
PROJECTS = ("kafka", "mariadb", "mongodb", "qt")
EXCL = load(ROOT / "data" / "benchmark")


def agg(subset, key="metrics"):
    if not subset:
        return {}
    probe = subset[0][key]
    if not isinstance(next(iter(probe.values())), dict):
        return {m: round(sum(r[key][m] for r in subset) / len(subset), 4)
                for m in probe}
    return {s: {m: round(sum(r[key][s][m] for r in subset) / len(subset), 4)
                for m in probe[s]} for s in probe}


def strip(path: Path, project: str | None) -> tuple[list, int]:
    """Returns (surviving rows, number dropped). Writes the dropped ones out."""
    KEEPOUT.mkdir(exist_ok=True)
    out = KEEPOUT / path.name
    if out.exists():
        print(f"  {path.name}: already applied, skipping")
        return [json.loads(l) for l in path.open(encoding="utf-8")], 0
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    pid = lambda r: f"{project or r['project']}:{r['issue_key']}"
    keep = [r for r in rows if pid(r) not in EXCL]
    drop = [r for r in rows if pid(r) in EXCL]
    with out.open("w", encoding="utf-8") as f:
        for r in drop:
            f.write(json.dumps(r) + "\n")
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r) + "\n")
    shutil.move(str(tmp), str(path))
    return keep, len(drop)


def fix_summary(sp: Path, rows: list, n_dropped_dev: int, n_dropped_eval: int,
                blocks: dict):
    s = json.loads(sp.read_text(encoding="utf-8"))
    if "pre_scored_set" in s:
        print(f"  {sp.name}: already applied, skipping")
        return
    s["pre_scored_set"] = {k: s[k] for k in s
                           if k in ("n_total", "n_dev", "n_eval",
                                    "n_rows", "n_eval_eligible") or
                           k.startswith("eval") or k in ("dev", "overall_all_rows")}
    for k, delta in (("n_total", n_dropped_dev + n_dropped_eval),
                     ("n_rows", n_dropped_dev + n_dropped_eval),
                     ("n_dev", n_dropped_dev), ("n_eval", n_dropped_eval)):
        if k in s:
            s[k] -= delta
    s.update(blocks)
    s["scored_set"] = {"rule": "test-only gold dropped (scored_set.py)",
                       "n_dropped_dev": n_dropped_dev,
                       "n_dropped_eval": n_dropped_eval}
    sp.write_text(json.dumps(s, indent=2), encoding="utf-8")


def do_project(p: str):
    print(p)
    summ = json.loads((RES / f"{p}-summary.json").read_text(encoding="utf-8"))
    n_dev_old = summ.get("pre_scored_set", {}).get("n_dev", summ["n_dev"])

    def dev_eval_drops(path):
        rows = [json.loads(l) for l in path.open(encoding="utf-8")]
        if len(rows) <= n_dev_old:          # already stripped
            return 0, 0
        ids = [f"{p}:{r['issue_key']}" for r in rows]
        return (sum(1 for i in ids[:n_dev_old] if i in EXCL),
                sum(1 for i in ids[n_dev_old:] if i in EXCL))

    # ---- main pipeline
    d_dev, d_ev = dev_eval_drops(RES / f"{p}-instances.jsonl")
    rows, n = strip(RES / f"{p}-instances.jsonl", p)
    ev = rows[n_dev_old - d_dev:]
    fix_summary(RES / f"{p}-summary.json", rows, d_dev, d_ev, {
        "eval": agg(ev),
        "eval_easy": agg([r for r in ev if r["strata"]["easy"]]),
        "eval_hard": agg([r for r in ev if not r["strata"]["easy"]]),
        "eval_trace_present": agg([r for r in ev if r["strata"]["trace"]]),
        "eval_trace_absent": agg([r for r in ev if not r["strata"]["trace"]]),
        "dev": agg(rows[:n_dev_old - d_dev]),
        "overall_all_rows": agg(rows)})
    print(f"  pipeline  -{n}  eval now {len(ev)}")

    # ---- IRBL baselines
    rows, n = strip(RES / f"{p}-irbl-instances.jsonl", p)
    ev = rows[n_dev_old - d_dev:]
    fix_summary(RES / f"{p}-irbl-summary.json", rows, d_dev, d_ev, {
        "eval": agg(ev),
        "eval_hard": agg([r for r in ev if not r["strata"]["easy"]]),
        "eval_easy": agg([r for r in ev if r["strata"]["easy"]])})
    print(f"  irbl      -{n}  eval now {len(ev)}")

    # ---- function stage
    rows, n = strip(RES / f"{p}-functions.jsonl", p)
    ev = [r for r in rows[n_dev_old - d_dev:] if r["eligible"]]
    fix_summary(RES / f"{p}-functions-summary.json", rows, d_dev, d_ev, {
        "n_eval_eligible": len(ev),
        "eval_eligible": agg(ev),
        "eval_eligible_hard": agg([r for r in ev if not r["strata"]["easy"]]),
        "eval_eligible_easy": agg([r for r in ev if r["strata"]["easy"]])})
    print(f"  functions -{n}  eval now {len(ev)}")


if __name__ == "__main__":
    for p in PROJECTS:
        do_project(p)
    print("llm")
    for tag in ("a2", "cp", "rr"):
        f = LLM / f"scored-{tag}.jsonl"
        if f.exists():
            _, n = strip(f, None)
            print(f"  scored-{tag} -{n}")
    print("\nagent files are left alone: the 790-instance study set already "
          "excluded test-only gold before the run (data/agent/"
          "excluded-test-only-gold.json), and the generalised rule drops "
          "nothing further from it.")
