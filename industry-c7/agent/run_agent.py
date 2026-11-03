"""Batch runner for the localization agent.

Restart-safe: ids already in the output file are skipped, so a killed run
resumes without repeating work.Each instance writes one result row and one
full transcript, so every reported number can be traced to the exact
conversation that produced it.

Cost is recorded per instance (LLM calls, prompt/completion tokens, wall
seconds, tool calls), because the paper's industrial argument is about
what accuracy costs, not accuracy alone.

Scoring population: the evaluation split loaded through
localize.load_bench, so the agent runs on exactly the scored set every
baseline is scored on (scripts/scored_set.py owns the rule). Default is
the seeded 200/project sample used by the dense and noise experiments;
--full runs the whole split.

Instances whose gold is only test files are already gone by then. They are
dropped because a hit there means retrieving the test file the fix edited,
not localizing a defect -- NOT because they are unanswerable. They sit in
the ranking universe and are in fact easier than average, so removing them
moves our own numbers down.

Usage:
    python industry-c7/agent/run_agent.py --workers 14
    python industry-c7/agent/run_agent.py --workers 20 --full
    python industry-c7/agent/run_agent.py --project kafka --limit 20
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent as A  # noqa: E402
import tools as T  # noqa: E402
from localize import (BENCH, OUT, PROJECTS, evaluate,  # noqa: E402
                      load_bench, load_support, parse_iso_epoch)

P = ("kafka", "mariadb", "mongodb", "qt")
AGENT_OUT = Path(__file__).resolve().parents[1] / "data/agent"
SEED_SAMPLE, SAMPLE_N = 42, 200

_lock = threading.Lock()
_done = 0


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _sample_keys(project, rng):
    """The seeded 200/project draw, reproduced exactly as first run.

    The draw predates the scored set, so it is taken on the unfiltered
    benchmark at the original dev boundary and only then intersected with
    the scored set. Drawing on the filtered list instead would change the
    list length, hence the indices, hence the sample -- it moves 213 of the
    790 already-run instances. The sample must not shift under results that
    are already reported.
    """
    raw = sorted((json.loads(l) for l in
                  (BENCH / f"{project}.jsonl").open(encoding="utf-8")),
                 key=lambda b: b["fix_time"])
    summary = json.load((OUT / f"{project}-summary.json").open())
    n_dev = (summary.get("pre_scored_set") or summary)["n_dev"]
    ev = raw[n_dev:]
    idx = sorted(rng.sample(range(len(ev)), min(SAMPLE_N, len(ev))))
    return {ev[i]["issue_key"] for i in idx}


def build_population(projects, limit=0, full=False):
    """The evaluation split, drawn from the scored set.

    Rows come from localize.load_bench, so the exclusion rule and the
    dev/eval boundary are the ones every other system uses. Slicing the
    UNFILTERED benchmark with the adjusted n_dev walks the boundary
    backwards and pulls dev instances into eval -- 24 of them on mongodb.
    """
    rng = random.Random(SEED_SAMPLE)
    pop = []
    for p in projects:
        bench = {b["issue_key"]: b for b in load_bench(p)}
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        ev_bench = sorted(bench.values(), key=lambda b: b["fix_time"])[n_dev:]
        if full:
            keys = {b["issue_key"] for b in ev_bench}
        else:
            keys = _sample_keys(p, rng) & {b["issue_key"] for b in ev_bench}
        by_key = {r["issue_key"]: r for r in rows}
        for k in sorted(keys):
            b, r = bench[k], by_key.get(k)
            if r is None:
                continue
            pop.append((p, b, r))
    rng2 = random.Random(7)
    rng2.shuffle(pop)          # interleave projects for even partial coverage
    return pop[:limit] if limit else pop


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", action="append", choices=list(P))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--full", action="store_true",
                    help="run the whole evaluation split instead of the "
                         "seeded %d/project sample" % SAMPLE_N)
    ap.add_argument("--version", type=int, default=2, choices=(2, 3),
                    help="3 requires a causal_chain in the submission and "
                         "walks the backward hop in phase 0 (T10/T11). "
                         "Default stays 2 so an unflagged re-run cannot "
                         "silently change what the reported numbers mean.")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tag", default="main")
    ap.add_argument("--shuffle-seeds", action="store_true",
                    help="validity check: randomise the lexical seed order "
                         "handed to the agent (LLM4FL report up to 22%% Top-1 "
                         "sensitivity to initial ordering)")
    args = ap.parse_args()
    projects = args.project or list(P)
    AGENT_OUT.mkdir(parents=True, exist_ok=True)
    (AGENT_OUT / "transcripts").mkdir(exist_ok=True)
    out_path = AGENT_OUT / f"agent-{args.tag}.jsonl"

    pop = build_population(projects, args.limit, args.full)

    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001
                pass
    todo = [x for x in pop if f"{x[0]}:{x[1]['issue_key']}" not in done]
    print(f"population={len(pop)} full={args.full} v{args.version} "
          f"done={len(done)} todo={len(todo)} workers={args.workers} "
          f"seed={args.seed} shuffle_seeds={args.shuffle_seeds}", flush=True)

    support = {p: load_support(p, PROJECTS[p]["key_prefix"]) for p in projects}
    fcaches = {p: {} for p in projects}
    commit = git_commit()
    fh = out_path.open("a", encoding="utf-8")
    t0 = time.time()
    agg = {"calls": 0, "in": 0, "out": 0}

    def work(item):
        global _done
        proj, b, row = item
        rid = f"{proj}:{b['issue_key']}"
        mem, dup, created, _preds = support[proj]
        started = time.time()
        try:
            seeds = list(row["rankings"]["cond_ours"][:20])
            if args.shuffle_seeds:
                random.Random(hash(rid) & 0xffff).shuffle(seeds)
            ws = T.Workspace(
                proj, b["snapshot_sha"], b["query_text"], mem, dup,
                parse_iso_epoch(b.get("created")) or created.get(b["issue_key"])
                or b["fix_time"], b["issue_key"], set(b["fix_shas"]),
                fcaches[proj], seeds)
            res = A.run_instance(ws, seed=args.seed, version=args.version)
            err = None
        except Exception as e:  # noqa: BLE001 - one bad instance must not stop the run
            res, err = None, f"{type(e).__name__}: {e}"
        wall = round(time.time() - started, 1)
        gold = b["gold_files"]
        if res is None:
            rowout = {"id": rid, "project": proj, "issue_key": b["issue_key"],
                      "error": err, "wall_s": wall}
        else:
            rowout = {
                "id": rid, "project": proj, "issue_key": b["issue_key"],
                "hard": not b["gold_named_in_text"], "gold_files": gold,
                "ranking": res["ranking"], "agent_ranking": res["agent_ranking"],
                "lexical_seed": res["lexical_seed"],
                "metrics": evaluate(res["ranking"], gold),
                "metrics_agent_only": evaluate(res["agent_ranking"], gold),
                "metrics_lexical": evaluate(res["lexical_seed"], gold),
                "stop_reason": res["stop_reason"], "rationale": res["rationale"],
                "n_notes": len(res["notes"]), "n_tool_calls": len(res["tool_calls"]),
                "tools_used": [c["tool"] for c in res["tool_calls"]],
                "cost": {"llm_calls": res["usage"]["calls"],
                         "prompt_tokens": res["usage"]["in"],
                         "completion_tokens": res["usage"]["out"],
                         "wall_s": wall},
                "resolver": res.get("resolver", {}),
                "version": res.get("version", 2),
                "causal_chain": res.get("causal_chain", []),
                "prewalk_symbols": res.get("prewalk_symbols", []),
                "seed": args.seed, "shuffled_seeds": args.shuffle_seeds,
                "git_commit": commit, "model": A.MODEL, "error": None}
            (AGENT_OUT / "transcripts" /
             f"{args.tag}-{rid.replace(':', '_')}.json").write_text(
                json.dumps({"id": rid, "gold_files": gold,
                            "events": res["events"], "notes": res["notes"],
                            "tool_calls": [{"tool": c["tool"], "args": c["args"]}
                                           for c in res["tool_calls"]]},
                           indent=1, default=str), encoding="utf-8")
        with _lock:
            fh.write(json.dumps(rowout, default=str) + "\n")
            fh.flush()
            _done += 1
            if res:
                agg["calls"] += res["usage"]["calls"]
                agg["in"] += res["usage"]["in"]
                agg["out"] += res["usage"]["out"]
            if _done % 10 == 0 or _done == len(todo):
                el = time.time() - t0
                rate = _done / el * 60
                print(f"  {_done}/{len(todo)}  {el / 60:.1f}min  "
                      f"{rate:.1f}/min  eta={(len(todo) - _done) / max(rate, .01):.0f}min"
                      f"  tok_in={agg['in'] / 1e6:.1f}M", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    el = time.time() - t0
    print(f"finished {_done} in {el / 60:.1f} min; "
          f"calls={agg['calls']} in={agg['in'] / 1e6:.2f}M out={agg['out'] / 1e6:.2f}M",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
